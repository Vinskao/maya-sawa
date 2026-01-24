import os
import asyncio
import shutil
import uuid
import logging
from pathlib import Path
from typing import List

from fastapi import APIRouter, UploadFile, File, Form, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse

logger = logging.getLogger(__name__)

router = APIRouter()

# Use environment variable if set, otherwise fallback to local temp directory
TEMP_DIR = Path(os.getenv("TEMP_DIR", "./temp_videos"))

# Limit concurrent FFmpeg processes to 2 to avoid OOM
FFMPEG_SEMAPHORE = asyncio.Semaphore(2)

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
    v1: UploadFile = File(...),
    v2: UploadFile = File(...),
    v3: UploadFile = File(...),
    v4: UploadFile = File(...),
    background_tasks: BackgroundTasks = None,
    mode: str = Form("windows"), # Default to windows
    bg_removal_0: str = Form("none"),
    bg_removal_1: str = Form("none"),
    bg_removal_2: str = Form("none"),
    bg_removal_3: str = Form("none")
):
    """
    Merge 4 videos into a 1x4 horizontal layout and generate MP4 + GIF.
    """
    # Ensure temp dir exists
    try:
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        pass

    request_id = str(uuid.uuid4())
    job_dir = TEMP_DIR / request_id
    job_dir.mkdir(parents=True, exist_ok=True)

    input_files = [v1, v2, v3, v4]
    saved_paths = []

    try:
        # Save uploaded files
        for i, upload_file in enumerate(input_files):
            file_path = job_dir / f"input_{i}.mp4"
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(upload_file.file, buffer)
            saved_paths.append(file_path)

        output_mp4 = job_dir / "merged.mp4"
        output_gif = job_dir / "merged.gif"

        # Construct filter complex
        filter_complex = ""
        processed_inputs = []
        
        for i in range(4):
            filter_complex += f"[{i}:v]format=rgba[v{i}];"
            processed_inputs.append(f"[v{i}]")
        
        hstack_inputs = "".join(processed_inputs)
        # Main output: 1920x1080 padded
        filter_complex += f"{hstack_inputs}hstack=inputs=4,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black[outv];"
        
        # Split for GIF: scale down to 480px width for size, generate palette for quality
        filter_complex += "[outv]split[mv][gv];"
        filter_complex += "[gv]scale=480:-1,split[g1][g2];"
        filter_complex += "[g1]palettegen[pal];"
        filter_complex += "[g2][pal]paletteuse[gifv]"

        cmd = [
            "ffmpeg",
            "-i", str(saved_paths[0]),
            "-i", str(saved_paths[1]),
            "-i", str(saved_paths[2]),
            "-i", str(saved_paths[3]),
            "-filter_complex", filter_complex,
            "-map", "[mv]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-pix_fmt", "yuv420p",
            str(output_mp4),
            "-map", "[gifv]",
            str(output_gif),
            "-y"
        ]

        logger.info(f"Starting dual video merge for job {request_id}")
        
        async with FFMPEG_SEMAPHORE:
            loop = asyncio.get_running_loop()
            def run_ffmpeg():
                import subprocess
                return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
            
            completed_process = await loop.run_in_executor(None, run_ffmpeg)
            
        if returncode != 0:
            error_msg = stderr.decode('utf-8', errors='replace')
            logger.error(f"FFmpeg failed for job {request_id}: {error_msg}")
            raise HTTPException(status_code=500, detail=f"Video processing failed: {error_msg}")

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
