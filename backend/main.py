import os
import shutil
import threading
import uuid
import logging
from typing import List, Optional
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import subprocess
from datetime import datetime
import time

# Imports for metadata
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, APIC
from mutagen.mp4 import MP4, MP4Cover

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("StemGenAPI")

app = FastAPI(title="StemGen Local")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.path.join(BASE_DIR, "..", "input")
OUTPUT_DIR = os.path.join(BASE_DIR, "..", "output")
ORIGINALS_DIR = os.path.join(INPUT_DIR, "Original mp3s")
os.makedirs(INPUT_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(ORIGINALS_DIR, exist_ok=True)

# Queue System
class QueueItem(BaseModel):
    id: str
    filename: str
    status: str  # queued, processing, completed, failed, skipped
    progress: int
    error: Optional[str] = None
    output_path: Optional[str] = None

QUEUE: List[QueueItem] = []
CURRENT_TASK_ID: Optional[str] = None
STOP_EVENT = threading.Event()
PAUSE_EVENT = threading.Event()

def copy_metadata_mutagen(src_path, dst_path):
    """
    Robustly copy ID3 tags and Cover Art from MP3 to M4A using Mutagen.
    """
    try:
        # Load Source (MP3)
        try:
            source = MP3(src_path, ID3=ID3)
        except Exception:
            logger.warning(f"Could not read ID3 tags from {src_path}")
            return

        if not source.tags:
            return

        # Load Destination (M4A)
        dest = MP4(dst_path)

        # Map common tags
        # Title
        if 'TIT2' in source.tags:
            dest['\xa9nam'] = str(source.tags['TIT2'])
        # Artist
        if 'TPE1' in source.tags:
            dest['\xa9ART'] = str(source.tags['TPE1'])
        # Album
        if 'TALB' in source.tags:
            dest['\xa9alb'] = str(source.tags['TALB'])
        # Year
        if 'TDRC' in source.tags:
            dest['\xa9day'] = str(source.tags['TDRC'])
        
        # Cover Art (APIC)
        for tag_key in source.tags.keys():
            if tag_key.startswith('APIC'):
                pic = source.tags[tag_key]
                # Detect format
                fmt = MP4Cover.FORMAT_JPEG if pic.mime == 'image/jpeg' else MP4Cover.FORMAT_PNG
                dest['covr'] = [MP4Cover(pic.data, imageformat=fmt)]
                break # Only one cover needed

        dest.save()
        logger.info("Metadata and Cover Art copied successfully via Mutagen.")

    except Exception as e:
        logger.error(f"Mutagen Metadata Copy Failed: {e}")

def archive_original(filename):
    """
    Move the source file to 'Original mp3s' folder, handling duplicates.
    """
    src = os.path.join(INPUT_DIR, filename)
    if not os.path.exists(src):
        return
        
    basename = os.path.basename(filename)
    try:
        clean_name = basename.split('_', 1)[1]
    except:
        clean_name = basename
        
    dest = os.path.join(ORIGINALS_DIR, clean_name)
    
    # If exists, append timestamp
    if os.path.exists(dest):
        base, ext = os.path.splitext(clean_name)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = os.path.join(ORIGINALS_DIR, f"{base}_{ts}{ext}")
        
    try:
        shutil.move(src, dest)
        logger.info(f"Archived original file to {dest}")
    except Exception as e:
        logger.error(f"Failed to archive original: {e}")

def process_queue_worker():
    global CURRENT_TASK_ID
    while True:
        # Check pause
        while PAUSE_EVENT.is_set() and not STOP_EVENT.is_set():
            time.sleep(0.5)

        # Find next queued item
        item = next((i for i in QUEUE if i.status == "queued"), None)
        if not item:
            time.sleep(1)
            continue

        # Start Processing
        CURRENT_TASK_ID = item.id
        item.status = "processing"
        item.progress = 5 
        
        job_temp_dir = None
        
        try:
            # Create a dedicated temp folder for this job to isolate filenames
            job_temp_dir = os.path.join(INPUT_DIR, f"temp_{item.id}")
            os.makedirs(job_temp_dir, exist_ok=True)

            original_name_no_ext = os.path.splitext(item.filename.split('_', 1)[1])[0] 
            target_input_wav = os.path.join(job_temp_dir, f"{original_name_no_ext}.wav")
            source_file = os.path.join(INPUT_DIR, item.filename)
            
            # Convert to WAV
            logger.info(f"Preparing input file: {target_input_wav}")
            try:
                subprocess.run(
                    ["ffmpeg", "-i", source_file, "-y", target_input_wav], 
                    check=True, 
                    stdout=subprocess.DEVNULL, 
                    stderr=subprocess.DEVNULL
                )
            except subprocess.CalledProcessError as e:
                logger.error("FFmpeg conversion failed.")
                item.status = "failed"
                shutil.rmtree(job_temp_dir, ignore_errors=True)
                CURRENT_TASK_ID = None
                continue

            logger.info(f"Starting processing for {original_name_no_ext}")
            
            # Output handling
            def get_date_suffix(d):
                return 'th' if 11<=d<=13 else {1:'st',2:'nd',3:'rd'}.get(d%10, 'th')
            now = datetime.now()
            day = now.day
            date_str = now.strftime("%b. ") + f"{day}{get_date_suffix(day)} " + now.strftime("%Y")
            batch_folder_name = f"STEMS {date_str}"
            output_folder = os.path.join(OUTPUT_DIR, batch_folder_name)
            os.makedirs(output_folder, exist_ok=True)

            cmd = [
                "stemgen", 
                target_input_wav, 
                "--output", output_folder,
                "--format", "aac", 
                "--device", "cuda"
            ]
            
            process = subprocess.Popen(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT, 
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            for line in process.stdout:
                if STOP_EVENT.is_set():
                    process.terminate()
                    break
                
                line_stripped = line.strip().lower()
                print(f"[Worker] {line_stripped}")
                
                if "demucs" in line_stripped and "processing" in line_stripped:
                    item.progress = max(item.progress, 15)
                elif "%" in line_stripped:
                    try:
                        import re
                        match = re.search(r"(\d+)%", line_stripped)
                        if match:
                            item.progress = int(match.group(1))
                    except:
                        pass
                elif "saving" in line_stripped:
                        item.progress = 85

            process.wait()

            # Cleanup temp dir
            shutil.rmtree(job_temp_dir, ignore_errors=True)

            if process.returncode == 0 and not STOP_EVENT.is_set():
                item.status = "completed"
                item.progress = 100
                
                expected_filename = f"{original_name_no_ext}.stem.m4a"
                full_output_path = os.path.join(output_folder, expected_filename)
                
                # POST-PROCESSING: Copy Metadata
                if os.path.exists(full_output_path) and os.path.exists(source_file):
                    copy_metadata_mutagen(source_file, full_output_path)
                
                # Archive original file
                archive_original(item.filename)
                
                if os.path.exists(full_output_path):
                    item.output_path = os.path.join(batch_folder_name, expected_filename)
                else:
                    found = False
                    for f in os.listdir(output_folder):
                        if f.startswith(original_name_no_ext) and f.endswith(".stem.m4a"):
                            item.output_path = os.path.join(batch_folder_name, f)
                            found = True
                            break
                    if not found:
                        item.status = "failed"
                        item.error = "File not found after processing"
            else:
                if STOP_EVENT.is_set():
                    item.status = "skipped"
                    STOP_EVENT.clear() 
                else:
                    item.status = "failed"
                    item.error = "Process failed"
                
        except Exception as e:
            logger.error(f"Error processing {item.filename}: {e}")
            item.status = "failed"
            item.error = str(e)
        
        CURRENT_TASK_ID = None

# Start worker thread
worker_thread = threading.Thread(target=process_queue_worker, daemon=True)
worker_thread.start()

@app.get("/queue")
def get_queue():
    return QUEUE

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    # 1. Check Archive (Exact filename match)
    if os.path.exists(os.path.join(ORIGINALS_DIR, file.filename)):
         raise HTTPException(status_code=409, detail="Duplicate: File already in Archive")

    # 2. Check Output (Stem filename match)
    # stemgen output is [filename].stem.m4a
    # We need to handle potential extensions in original filename if they were stripped differently?
    # Our logic: original_name_no_ext = os.path.splitext(item.filename.split('_', 1)[1])[0]
    # So if file.filename is "Song.mp3", stem is "Song.stem.m4a"
    stem_basename = os.path.splitext(file.filename)[0] + ".stem.m4a"
    
    # Recursive search in OUTPUT_DIR
    for root, dirs, files in os.walk(OUTPUT_DIR):
        if stem_basename in files:
            raise HTTPException(status_code=409, detail="Duplicate: Stem already exists")

    file_id = str(uuid.uuid4())
    filename = f"{file_id}_{file.filename}"
    file_path = os.path.join(INPUT_DIR, filename)
    
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    item = QueueItem(
        id=file_id,
        filename=filename,
        status="queued",
        progress=0
    )
    QUEUE.append(item)
    return item

@app.get("/download/{item_id}")
def download_result(item_id: str):
    item = next((i for i in QUEUE if i.id == item_id), None)
    if not item or item.status != "completed" or not item.output_path:
        raise HTTPException(status_code=404, detail="File not ready or found")
    
    # Path is now relative to OUTPUT_DIR (e.g. "STEMS Dec. 10th 2025/Song.stem.m4a")
    full_path = os.path.join(OUTPUT_DIR, item.output_path)
    filename = os.path.basename(full_path)
    return FileResponse(full_path, filename=filename)

@app.get("/state")
def get_state():
    return {
        "paused": PAUSE_EVENT.is_set(),
        "processing_id": CURRENT_TASK_ID
    }

@app.post("/control/pause")
def pause_queue():
    PAUSE_EVENT.set()
    return {"status": "paused"}

@app.post("/control/resume")
def resume_queue():
    PAUSE_EVENT.clear()
    return {"status": "running"}

@app.post("/control/skip/{item_id}")
def skip_item(item_id: str):
    global CURRENT_TASK_ID
    # Check running
    if CURRENT_TASK_ID == item_id:
        STOP_EVENT.set()
        return {"status": "skipped_running"}
    
    # Check queued
    for i in QUEUE:
        if i.id == item_id and i.status == "queued":
            i.status = "skipped"
            return {"status": "skipped_queued"}
            
    return {"error": "Item not found or already done"}
