import os
import asyncio
import shutil
import uuid
import logging
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, UploadFile, File, Form, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse

logger = logging.getLogger(__name__)

router = APIRouter()

# Use environment variable if set, otherwise fallback to local temp directory
TEMP_DIR = Path(os.getenv("TEMP_DIR", "./temp_videos"))

# Limit concurrent FFmpeg processes to 2 to avoid OOM
FFMPEG_SEMAPHORE = asyncio.Semaphore(2)

# Upload guard (bytes). Must stay <= nginx ingress proxy-body-size.
MAX_TOTAL_UPLOAD_BYTES = int(os.getenv("MAX_TOTAL_UPLOAD_BYTES", str(1024 * 1024 * 1024)))


def _run(cmd: List[str]):
    """Run a command synchronously and return the CompletedProcess."""
    import subprocess
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)


def _probe_duration(path: Path) -> float:
    """Return the duration of a video file in seconds (0.0 if unknown)."""
    result = _run([
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ])
    try:
        return float(result.stdout.decode().strip())
    except (ValueError, AttributeError):
        return 0.0

async def delayed_cleanup(dir_path: Path, delay_seconds: int = 600):
    """Background task to remove temporary directory after a delay (default 10 mins)."""
    await asyncio.sleep(delay_seconds)
    try:
        if dir_path.exists():
            shutil.rmtree(dir_path, ignore_errors=True)
            logger.info(f"Cleaned up job directory: {dir_path}")
    except Exception as e:
        logger.error(f"Error deleting directory {dir_path}: {e}")

@router.get("/download/{job_id}/{ext}")
async def download_video(job_id: str, ext: str):
    """Download a processed video by job ID and extension."""
    filename = f"merged.{ext}"
    file_path = TEMP_DIR / job_id / filename
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found or expired")
    
    media_type = "video/mp4" if ext == "mp4" else "image/gif"
    return FileResponse(file_path, media_type=media_type, filename=filename)

@router.post("/merge-videos")
async def merge_videos(
    v1: Optional[UploadFile] = File(None),
    v2: Optional[UploadFile] = File(None),
    v3: Optional[UploadFile] = File(None),
    v4: Optional[UploadFile] = File(None),
    background_tasks: BackgroundTasks = None,
    mode: str = Form("windows"), # Default to windows
    bg_removal_0: str = Form("none"),
    bg_removal_1: str = Form("none"),
    bg_removal_2: str = Form("none"),
    bg_removal_3: str = Form("none")
):
    """
    Merge 4 videos into a 1x4 horizontal layout and generate MP4 + GIF.
    Supports variable number of inputs (1-4). Missing slots are filled with black.
    """
    # Ensure temp dir exists
    try:
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        pass

    request_id = str(uuid.uuid4())
    job_dir = TEMP_DIR / request_id
    job_dir.mkdir(parents=True, exist_ok=True)

    # Map slot index (0-3) to uploaded file (or None)
    slot_files = [v1, v2, v3, v4]
    
    # Check if at least one file is provided
    if not any(slot_files):
        raise HTTPException(status_code=400, detail="At least one video file is required")

    input_paths = []
    # Map slot index to logical ffmpeg input index (e.g., slot 0 -> input 0, slot 2 -> input 1 if slot 1 is empty)
    slot_to_input_idx = {}
    
    current_input_idx = 0
    
    try:
        # Save uploaded files
        valid_inputs = [] # items: (slot_index, file_path)
        
        total_bytes = 0
        for i, upload_file in enumerate(slot_files):
            if upload_file:
                file_path = job_dir / f"input_{i}.mp4"
                with open(file_path, "wb") as buffer:
                    shutil.copyfileobj(upload_file.file, buffer)
                total_bytes += file_path.stat().st_size
                valid_inputs.append((i, file_path))

        if total_bytes > MAX_TOTAL_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"Total upload size {total_bytes / 1048576:.1f} MB exceeds the "
                    f"limit of {MAX_TOTAL_UPLOAD_BYTES / 1048576:.0f} MB."
                ),
            )

        output_mp4 = job_dir / "merged.mp4"
        output_gif = job_dir / "merged.gif"

        loop = asyncio.get_running_loop()

        # ------------------------------------------------------------------
        # Pass 1: normalise each clip to height 1080 and apply the boomerang
        # (forward + reverse) effect, writing an intermediate file.
        #
        # Doing this as a separate pass keeps the `reverse` filter's memory
        # use bounded to one clip, and gives us a concrete file we can loop
        # with `-stream_loop` in pass 2 at O(1) memory.
        # ------------------------------------------------------------------
        boomerang_paths = []
        async with FFMPEG_SEMAPHORE:
            for idx, (slot_idx, path) in enumerate(valid_inputs):
                boom_path = job_dir / f"boom_{idx}.mp4"
                boom_filter = (
                    "[0:v]scale=-2:1080,setsar=1,fps=30,split[fwd][revpre];"
                    "[revpre]reverse[rev];"
                    "[fwd][rev]concat=n=2:v=1:a=0[out]"
                )
                boom_cmd = [
                    "ffmpeg", "-i", str(path),
                    "-filter_complex", boom_filter,
                    "-map", "[out]", "-an",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                    "-pix_fmt", "yuv420p",
                    str(boom_path), "-y",
                ]
                result = await loop.run_in_executor(None, _run, boom_cmd)
                if result.returncode != 0:
                    error_msg = result.stderr.decode("utf-8", errors="replace")
                    logger.error(f"FFmpeg boomerang pass failed for job {request_id}: {error_msg}")
                    raise HTTPException(
                        status_code=500,
                        detail=f"Video processing failed: {error_msg}",
                    )
                boomerang_paths.append(boom_path)

        # Longest clip decides the output duration; every other clip is
        # replayed (looped) until it reaches the same length.
        durations = [_probe_duration(p) for p in boomerang_paths]
        target_duration = max(durations) if durations else 0.0
        if target_duration <= 0:
            raise HTTPException(status_code=400, detail="Could not determine video duration")

        logger.info(
            f"Job {request_id}: clip durations {['%.2f' % d for d in durations]}, "
            f"looping all to {target_duration:.2f}s"
        )

        # ------------------------------------------------------------------
        # Pass 2: loop each clip to the target duration and stack them.
        # ------------------------------------------------------------------
        cmd = ["ffmpeg"]
        for p in boomerang_paths:
            # -stream_loop -1 repeats the file indefinitely; -t caps the read
            # at the target duration, so short clips replay to fill the gap.
            cmd.extend(["-stream_loop", "-1", "-t", f"{target_duration:.3f}", "-i", str(p)])

        filter_complex = ""
        processed_labels = []
        for idx in range(len(boomerang_paths)):
            filter_complex += f"[{idx}:v]setpts=PTS-STARTPTS[v{idx}];"
            processed_labels.append(f"[v{idx}]")

        if len(processed_labels) > 1:
            hstack_inputs = "".join(processed_labels)
            filter_complex += f"{hstack_inputs}hstack=inputs={len(processed_labels)}:shortest=1[outv];"
        else:
            filter_complex += f"{processed_labels[0]}null[outv];"

        # Split for GIF: scale height to 480px (maintaining ratio), generate palette.
        # fps is capped so the GIF stays a reasonable size for long outputs.
        filter_complex += "[outv]split[mv][gv];"
        filter_complex += "[gv]fps=12,scale=-2:480:flags=lanczos,split[g1][g2];"
        filter_complex += "[g1]palettegen[pal];"
        filter_complex += "[g2][pal]paletteuse[gifv]"

        cmd.extend([
            "-filter_complex", filter_complex,
            "-map", "[mv]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-pix_fmt", "yuv420p",
            str(output_mp4),
            "-map", "[gifv]",
            str(output_gif),
            "-y"
        ])

        logger.info(f"Starting video merge for job {request_id} with {len(valid_inputs)} inputs")

        async with FFMPEG_SEMAPHORE:
            completed_process = await loop.run_in_executor(None, _run, cmd)

        if completed_process.returncode != 0:
            error_msg = completed_process.stderr.decode('utf-8', errors='replace')
            logger.error(f"FFmpeg failed for job {request_id}: {error_msg}")
            raise HTTPException(status_code=500, detail=f"Video processing failed: {error_msg}")

        # Intermediate files are no longer needed
        for p in boomerang_paths:
            p.unlink(missing_ok=True)
        for _, p in valid_inputs:
            p.unlink(missing_ok=True)

        logger.info(f"Video merge successful for job {request_id}")

        if background_tasks:
            # Leave files for 10 minutes for user to download both formats
            background_tasks.add_task(delayed_cleanup, job_dir, 600)

        return {
            "success": True,
            "job_id": request_id,
            "mp4_url": f"/videos/download/{request_id}/mp4",
            "gif_url": f"/videos/download/{request_id}/gif"
        }

    except Exception as e:
        logger.error(f"Unexpected error in merge_videos: {e}")
        shutil.rmtree(job_dir, ignore_errors=True)
        raise e
