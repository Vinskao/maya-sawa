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
        
        for i, upload_file in enumerate(slot_files):
            if upload_file:
                file_path = job_dir / f"input_{i}.mp4"
                with open(file_path, "wb") as buffer:
                    shutil.copyfileobj(upload_file.file, buffer)
                valid_inputs.append((i, file_path))

        output_mp4 = job_dir / "merged.mp4"
        output_gif = job_dir / "merged.gif"

        # Construct filter complex
        filter_complex = ""
        processed_labels = []
        
        for idx, (slot_idx, path) in enumerate(valid_inputs):
            # Create boomerang effect: play forward, then reverse
            # Input mapping: idx corresponds to the order in cmd inputs
            
            # 1. Split input into forward key and reverse source
            filter_complex += f"[{idx}:v]split[fwd{idx}][revpre{idx}];"
            # 2. Reverse the second copy
            filter_complex += f"[revpre{idx}]reverse[rev{idx}];"
            # 3. Concatenate forward and reverse
            filter_complex += f"[fwd{idx}][rev{idx}]concat=n=2:v=1:a=0[loop{idx}];"
            
            # Scale to height 1080, width dynamic (divisible by 2)
            # Remove padding to allow dynamic width
            filter_complex += f"[loop{idx}]scale=-2:1080,format=rgba[v{idx}];"
            processed_labels.append(f"[v{idx}]")
        
        if not processed_labels:
             raise HTTPException(status_code=400, detail="No video inputs processed")

        if len(valid_inputs) > 1:
            hstack_inputs = "".join(processed_labels)
            # Main output: hstack all valid inputs. 
            filter_complex += f"{hstack_inputs}hstack=inputs={len(valid_inputs)}:shortest=1[outv];"
        else:
            # Single input case: just pass it through
            filter_complex += f"{processed_labels[0]}null[outv];"
        
        # Split for GIF: scale height to 480px (maintaining ratio), generate palette
        filter_complex += "[outv]split[mv][gv];"
        filter_complex += "[gv]scale=-2:480:flags=lanczos,split[g1][g2];"
        filter_complex += "[g1]palettegen[pal];"
        filter_complex += "[g2][pal]paletteuse[gifv]"

        cmd = ["ffmpeg"]
        for _, p in valid_inputs:
            cmd.extend(["-i", str(p)])
            
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
            loop = asyncio.get_running_loop()
            def run_ffmpeg():
                import subprocess
                return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
            
            completed_process = await loop.run_in_executor(None, run_ffmpeg)
            
        if completed_process.returncode != 0:
            error_msg = completed_process.stderr.decode('utf-8', errors='replace')
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
