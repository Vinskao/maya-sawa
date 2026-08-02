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

# Output height per clip. 4 clips at 1080 produce a 7680x1080 canvas, which
# costs ~1.6GB of RAM in ffmpeg; lower this to cut memory and CPU.
OUTPUT_HEIGHT = int(os.getenv("MERGE_OUTPUT_HEIGHT", "1080"))
OUTPUT_FPS = int(os.getenv("MERGE_OUTPUT_FPS", "30"))


def _run(cmd: List[str]):
    """Run a command synchronously and return the CompletedProcess."""
    import subprocess
    try:
        return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                f"'{cmd[0]}' is not installed in this container. "
                "The image must be rebuilt with ffmpeg available."
            ),
        ) from exc


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
    bg_removal_3: str = Form("none"),
    boomerang: bool = Form(False),
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
        # Pass 1: normalise each clip to height 1080 / 30fps, writing an
        # intermediate file we can loop with `-stream_loop` in pass 2 at
        # O(1) memory.
        #
        # NOTE: the boomerang effect uses ffmpeg's `reverse` filter, which
        # buffers every decoded frame in RAM (1080p RGBA is ~8MB/frame, so a
        # 5s 30fps clip needs ~1.2GB). That will OOM-kill the pod under its
        # 1.5Gi limit, so it is opt-in and applied at a reduced resolution.
        # ------------------------------------------------------------------
        normalised_paths = []
        async with FFMPEG_SEMAPHORE:
            for idx, (slot_idx, path) in enumerate(valid_inputs):
                out_path = job_dir / f"norm_{idx}.mp4"
                if boomerang:
                    # Reverse at 540p to keep the frame buffer manageable,
                    # then scale the concatenated result back up to 1080.
                    half = max(2, (OUTPUT_HEIGHT // 2) // 2 * 2)
                    vf = (
                        f"[0:v]scale=-2:{half},setsar=1,fps={OUTPUT_FPS},split[fwd][revpre];"
                        "[revpre]reverse[rev];"
                        f"[fwd][rev]concat=n=2:v=1:a=0,scale=-2:{OUTPUT_HEIGHT}[out]"
                    )
                else:
                    vf = f"[0:v]scale=-2:{OUTPUT_HEIGHT},setsar=1,fps={OUTPUT_FPS}[out]"

                norm_cmd = [
                    "ffmpeg", "-i", str(path),
                    "-filter_complex", vf,
                    "-map", "[out]", "-an",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                    "-pix_fmt", "yuv420p",
                    str(out_path), "-y",
                ]
                result = await loop.run_in_executor(None, _run, norm_cmd)
                if result.returncode != 0:
                    error_msg = result.stderr.decode("utf-8", errors="replace")
                    logger.error(f"FFmpeg normalise pass failed for job {request_id}: {error_msg}")
                    raise HTTPException(
                        status_code=500,
                        detail=f"Video processing failed: {error_msg}",
                    )
                normalised_paths.append(out_path)

        # Longest clip decides the output duration; every other clip is
        # replayed (looped) until it reaches the same length.
        durations = [_probe_duration(p) for p in normalised_paths]
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
        for p in normalised_paths:
            # -stream_loop -1 repeats the file indefinitely; -t caps the read
            # at the target duration, so short clips replay to fill the gap.
            cmd.extend(["-stream_loop", "-1", "-t", f"{target_duration:.3f}", "-i", str(p)])

        filter_complex = ""
        processed_labels = []
        for idx in range(len(normalised_paths)):
            filter_complex += f"[{idx}:v]setpts=PTS-STARTPTS[v{idx}];"
            processed_labels.append(f"[v{idx}]")

        if len(processed_labels) > 1:
            hstack_inputs = "".join(processed_labels)
            filter_complex += f"{hstack_inputs}hstack=inputs={len(processed_labels)}:shortest=1[outv];"
        else:
            filter_complex += f"{processed_labels[0]}null[outv];"

        filter_complex = filter_complex.rstrip(";")

        cmd.extend([
            "-filter_complex", filter_complex,
            "-map", "[outv]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-pix_fmt", "yuv420p",
            "-threads", "2",
            str(output_mp4),
            "-y"
        ])

        logger.info(f"Starting video merge for job {request_id} with {len(valid_inputs)} inputs")

        async with FFMPEG_SEMAPHORE:
            completed_process = await loop.run_in_executor(None, _run, cmd)

        if completed_process.returncode != 0:
            error_msg = completed_process.stderr.decode('utf-8', errors='replace')
            logger.error(f"FFmpeg failed for job {request_id}: {error_msg}")
            raise HTTPException(status_code=500, detail=f"Video processing failed: {error_msg}")

        # ------------------------------------------------------------------
        # Pass 3: GIF, generated from the finished MP4 in two steps.
        #
        # The single-pass `split -> palettegen -> paletteuse` graph has to
        # buffer the whole stream in RAM while the palette is computed
        # (measured ~1.2GB for a 2-up 1080p clip). Writing the palette to a
        # file first keeps this pass at ~175MB.
        # ------------------------------------------------------------------
        palette_path = job_dir / "palette.png"
        gif_scale = "fps=12,scale=-2:480:flags=lanczos"

        async with FFMPEG_SEMAPHORE:
            palette_cmd = [
                "ffmpeg", "-i", str(output_mp4),
                "-vf", f"{gif_scale},palettegen",
                str(palette_path), "-y",
            ]
            palette_result = await loop.run_in_executor(None, _run, palette_cmd)

            if palette_result.returncode == 0:
                gif_cmd = [
                    "ffmpeg", "-i", str(output_mp4), "-i", str(palette_path),
                    "-lavfi", f"{gif_scale}[x];[x][1:v]paletteuse",
                    str(output_gif), "-y",
                ]
                gif_result = await loop.run_in_executor(None, _run, gif_cmd)
            else:
                gif_result = palette_result

        palette_path.unlink(missing_ok=True)

        if gif_result.returncode != 0:
            # The MP4 is the primary deliverable; a GIF failure should not
            # sink the whole job.
            logger.warning(
                f"GIF generation failed for job {request_id}: "
                f"{gif_result.stderr.decode('utf-8', errors='replace')}"
            )

        # Intermediate files are no longer needed
        for p in normalised_paths:
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
            "gif_url": (
                f"/videos/download/{request_id}/gif" if output_gif.exists() else None
            ),
            "duration": round(target_duration, 2),
        }

    except Exception as e:
        logger.error(f"Unexpected error in merge_videos: {e}")
        shutil.rmtree(job_dir, ignore_errors=True)
        raise e
