from fastapi import FastAPI, UploadFile, File, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from supabase import create_client, Client
from pydantic import BaseModel
from typing import List
import os
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from celery.result import AsyncResult

from tasks import process_video_with_broll
from db_operations import create_reel_entry

# Load environment variables at the start of your application
load_dotenv()

# Verify the environment variables are loaded
print("SUPABASE_URL:", os.getenv("SUPABASE_URL"))
print("SUPABASE_KEY:", os.getenv("SUPABASE_KEY"))

# Initialize FastAPI
app = FastAPI()

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Models
class VideoClip(BaseModel):
    id: str
    url: str
    duration: float
    order: int

class ReelRequest(BaseModel):
    prompt: str
    clips: List[VideoClip]
    user_id: str

class ReelStatus(BaseModel):
    id: str
    status: str
    created_at: datetime
    updated_at: datetime
    output_url: str = None

class VideoProcessingRequest(BaseModel):
    video_url: str
    user_id: str
    style: str = "default"  # Can be used to control b-roll style/frequency

# Initialize Supabase client
supabase_client: Client = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY")
)

# Routes
@app.post("/api/upload")
async def upload_video(file: UploadFile = File(...)):
    try:
        # Read file content
        content = await file.read()
        file_path = f"videos/{datetime.utcnow().isoformat()}-{file.filename}"
        
        # Upload to Supabase Storage
        supabase_client.storage.from_('videos').upload(
            file_path,
            content
        )
        
        # Get public URL
        file_url = supabase_client.storage.from_('videos').get_public_url(file_path)
        
        return {"url": file_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/create-reel")
async def create_reel(request: ReelRequest):
    try:
        # Create entry in reels table
        reel_id = await create_reel_entry(request.user_id, request.prompt)
        
        # Queue the video processing task
        print(f"Queueing task for reel_id: {reel_id}")  # Debug log
        task = process_video_with_broll.delay(request.dict(), reel_id)
        print(f"Task queued with id: {task.id}")  # Debug log
        
        return {"reel_id": reel_id, "task_id": task.id}
    except Exception as e:
        print(f"Error queueing task: {str(e)}")  # Debug log
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/status/{reel_id}")
async def get_status(reel_id: str):
    try:
        result = supabase_client.table('reels').select("*").eq('id', reel_id).execute()
        if not result.data:
            raise HTTPException(status_code=404, detail="Reel not found")
            
        return ReelStatus(**result.data[0])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/process-video")
def process_video(request: VideoProcessingRequest):
    try:
        # Create entry in reels table
        reel_id = create_reel_entry(request.user_id, "B-roll generation")
        
        # Queue the video processing task
        print(f"Queueing task for reel_id: {reel_id}")  # Debug log
        task = process_video_with_broll.delay(request.dict(), reel_id)
        print(f"Task queued with id: {task.id}")  # Debug log
        
        return {"reel_id": reel_id, "task_id": task.id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/task-status/{task_id}")
async def get_task_status(task_id: str):
    try:
        # Get Celery task status
        task_result = AsyncResult(task_id)
        
        task_status = {
            "task_id": task_id,
            "status": task_result.status,  # PENDING, STARTED, SUCCESS, FAILURE, etc.
            "done": task_result.ready(),   # True if the task has completed (success or failure)
        }
        
        # If task is done and successful, include the result
        if task_result.ready() and task_result.successful():
            task_status["result"] = task_result.get()
        elif task_result.failed():
            task_status["error"] = str(task_result.result)
            
        return task_status
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))