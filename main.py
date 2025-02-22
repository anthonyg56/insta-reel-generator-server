from fastapi import FastAPI, UploadFile, File, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from celery import Celery
from supabase import create_client, Client
from pydantic import BaseModel
from typing import List
import os
import asyncio
from datetime import datetime

from tasks import process_video_with_broll

# Initialize FastAPI and Celery
app = FastAPI()
celery = Celery('tasks', broker='redis://localhost:6379/0')

# Initialize Supabase
supabase: Client = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY")
)

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

# Database functions
async def create_reel_entry(user_id: str, prompt: str) -> str:
    data = {
        'user_id': user_id,
        'prompt': prompt,
        'status': 'pending',
        'created_at': datetime.utcnow().isoformat(),
        'updated_at': datetime.utcnow().isoformat()
    }
    
    result = supabase.table('reels').insert(data).execute()
    return result.data[0]['id']

async def update_reel_status(reel_id: str, status: str, output_url: str = None):
    data = {
        'status': status,
        'updated_at': datetime.utcnow().isoformat(),
        'output_url': output_url
    }
    
    supabase.table('reels').update(data).eq('id', reel_id).execute()

# Routes
@app.post("/api/upload")
async def upload_video(file: UploadFile = File(...)):
    try:
        # Read file content
        content = await file.read()
        file_path = f"videos/{datetime.utcnow().isoformat()}-{file.filename}"
        
        # Upload to Supabase Storage
        result = supabase.storage.from_('videos').upload(
            file_path,
            content
        )
        
        # Get public URL
        file_url = supabase.storage.from_('videos').get_public_url(file_path)
        
        return {"url": file_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/create-reel")
async def create_reel(request: ReelRequest):
    try:
        # Create entry in reels table
        reel_id = await create_reel_entry(request.user_id, request.prompt)
        
        # Queue the video processing task
        task = process_video_with_broll.delay(request.dict(), reel_id)
        
        return {"reel_id": reel_id, "task_id": task.id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/status/{reel_id}")
async def get_status(reel_id: str):
    try:
        result = supabase.table('reels').select("*").eq('id', reel_id).execute()
        if not result.data:
            raise HTTPException(status_code=404, detail="Reel not found")
            
        return ReelStatus(**result.data[0])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/process-video")
async def process_video(request: VideoProcessingRequest):
    try:
        # Create entry in reels table
        reel_id = await create_reel_entry(request.user_id, "B-roll generation")
        
        # Queue the video processing task
        task = process_video_with_broll.delay(request.dict(), reel_id)
        
        return {"reel_id": reel_id, "task_id": task.id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))