import os
import asyncio
import shutil
import uuid
import logging
from pathlib import Path
from typing import List

from fastapi import APIRouter, UploadFile, File, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse

logger = logging.getLogger(__name__)

router = APIRouter()

# Use environment variable if set, otherwise fallback to local temp directory
TEMP_DIR = Path(os.getenv("TEMP_DIR", "./temp_videos"))

# Limit concurrent FFmpeg processes to 2 to avoid OOM
FFMPEG_SEMAPHORE = asyncio.Semaphore(2)

def cleanup_files(file_paths: List[Path], dir_path: Path):
    """Background task to remove temporary files and directory."""
    for path in file_paths:
        try:
            if path.exists():
                path.unlink()
        except Exception as e:
            logger.error(f"Error deleting file {path}: {e}")
    
    # Try to remove the directory
    try:
        if dir_path.exists():
            shutil.rmtree(dir_path, ignore_errors=True)
    except Exception as e:
        logger.error(f"Error deleting directory {dir_path}: {e}")

@router.post("/merge-videos")
async def merge_videos(
    v1: UploadFile = File(...),
    v2: UploadFile = File(...),
    v3: UploadFile = File(...),
    v4: UploadFile = File(...),
    background_tasks: BackgroundTasks = None
):
    """
    Merge 4 videos into a 1x4 horizontal layout.
    Layout: v1 | v2 | v3 | v4
    """
    # Ensure temp dir exists
    try:
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        # Fallback for local dev if permissions issue, though /app/temp assumes container
        local_temp = Path("./temp_videos")
        local_temp.mkdir(parents=True, exist_ok=True)
        # We'll use the one we created
        # But for strictly following the plan relying on /app/temp and correct permissions in K8s
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

        output_path = job_dir / "output.mp4"

        # FFmpeg command for 1x4 horizontal layout
        # xstack layout explanation:
        # v1: 0_0 (position x=0, y=0)
        # v2: w0_0 (position x=width of v1, y=0)
        # v3: w0+w1_0 (position x=width of v1+v2, y=0)
        # v4: w0+w1+w2_0 (position x=width of v1+v2+v3, y=0)
        cmd = [
            "ffmpeg",
            "-i", str(saved_paths[0]),
            "-i", str(saved_paths[1]),
            "-i", str(saved_paths[2]),
            "-i", str(saved_paths[3]),
            "-filter_complex", "hstack=inputs=4",
            "-y", # Overwrite output if exists
            str(output_path)
        ]

        logger.info(f"Starting video merge for job {request_id}")
        
        # run ffmpeg with semaphore
        # Helper function to run ffmpeg synchronously
        def run_ffmpeg_sync(command):
            import subprocess
            return subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False  # We'll check returncode manually
            )

        # run ffmpeg in thread pool to avoid blocking async loop
        async with FFMPEG_SEMAPHORE:
            loop = asyncio.get_running_loop()
            # Use default executor (ThreadPoolExecutor)
            completed_process = await loop.run_in_executor(None, run_ffmpeg_sync, cmd)
            
            stdout = completed_process.stdout
            stderr = completed_process.stderr
            returncode = completed_process.returncode
            
        if returncode != 0:
            error_msg = stderr.decode('utf-8', errors='replace')
            logger.error(f"FFmpeg failed for job {request_id}: {error_msg}")
            raise HTTPException(status_code=500, detail=f"Video processing failed: {error_msg}")

        logger.info(f"Video merge successful for job {request_id}")

        # Schedule cleanup
        cleanup_targets = saved_paths + [output_path]
        if background_tasks:
            background_tasks.add_task(cleanup_files, cleanup_targets, job_dir)

        return FileResponse(output_path, media_type="video/mp4", filename="merged.mp4")

    except Exception as e:
        logger.error(f"Unexpected error in merge_videos: {e}")
        # Cleanup immediately on failure
        shutil.rmtree(job_dir, ignore_errors=True)
        raise e
