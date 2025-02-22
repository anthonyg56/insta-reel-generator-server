import os
from typing import List, Dict
from moviepy.editor import VideoFileClip, concatenate_videoclips
import openai
from celery import Celery
import replicate
import tempfile
import requests
import supabase
import whisper
from pexels_api import API
import json

from main import update_reel_status

celery = Celery('tasks', broker='redis://localhost:6379/0')

PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")
pexels = API(PEXELS_API_KEY)

@celery.task
def process_video_with_broll(request_data: dict, reel_id: str):
    try:
        update_reel_status(reel_id, 'processing')
        
        # Download the main video
        main_video_path = download_clip(request_data['video_url'])
        
        # 1. Extract audio and transcribe
        keywords = extract_keywords_from_video(main_video_path)
        
        # 2. Fetch b-roll clips for each keyword
        broll_clips = fetch_broll_clips(keywords)
        
        # 3. Generate editing instructions
        edit_plan = generate_edit_plan(keywords, broll_clips)
        
        # 4. Create final video
        output_path = create_final_video(main_video_path, broll_clips, edit_plan)
        
        # 5. Upload to Supabase Storage
        file_path = f"output/{reel_id}.mp4"
        with open(output_path, 'rb') as f:
            supabase.storage.from_('videos').upload(file_path, f)
        
        output_url = supabase.storage.from_('videos').get_public_url(file_path)
        
        # Cleanup
        os.unlink(main_video_path)
        os.unlink(output_path)
        
        update_reel_status(reel_id, 'completed', output_url)
        return {"status": "completed", "url": output_url}
        
    except Exception as e:
        update_reel_status(reel_id, 'failed')
        return {"status": "failed", "error": str(e)}

def extract_keywords_from_video(video_path: str) -> List[Dict]:
    """Extract keywords and timestamps from video audio"""
    # Load the Whisper model
    model = whisper.load_model("base")
    
    # Extract audio and transcribe
    result = model.transcribe(video_path)
    
    # Use GPT to analyze transcript and identify key moments
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "Analyze this transcript and identify key topics, objects, or concepts that would benefit from B-roll footage. Return a JSON array of objects with 'keyword' and 'timestamp' fields."},
            {"role": "user", "content": result["text"]}
        ]
    )
    
    return json.loads(response.choices[0].message.content)

def fetch_broll_clips(keywords: List[Dict]) -> List[Dict]:
    """Fetch relevant B-roll clips for each keyword"""
    broll_clips = []
    
    for keyword_data in keywords:
        # Search for video clips on Pexels
        search_results = pexels.search_videos(
            query=keyword_data['keyword'],
            orientation='landscape',
            size='medium',
            per_page=1
        )
        
        if search_results.videos:
            video = search_results.videos[0]
            broll_clips.append({
                'keyword': keyword_data['keyword'],
                'timestamp': keyword_data['timestamp'],
                'url': video.url,
                'duration': video.duration
            })
    
    return broll_clips

def generate_edit_plan(keywords: List[Dict], broll_clips: List[Dict]) -> List[Dict]:
    """Generate editing instructions for video composition"""
    prompt = f"""
    Given these keywords and available B-roll clips, create an editing plan that 
    specifies how to integrate B-roll naturally. Consider pacing and transitions.
    
    Keywords: {json.dumps(keywords)}
    Available clips: {json.dumps(broll_clips)}
    """
    
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "Create a video editing plan. Return a JSON array of edit instructions with 'action', 'timestamp', 'duration', and 'clip_id' fields."},
            {"role": "user", "content": prompt}
        ]
    )
    
    return json.loads(response.choices[0].message.content)

def create_final_video(main_video_path: str, broll_clips: List[Dict], edit_plan: List[Dict]) -> str:
    """Create the final video with B-roll insertions"""
    main_video = VideoFileClip(main_video_path)
    final_clips = []
    current_time = 0
    
    for edit in edit_plan:
        # Add main video segment up to b-roll insertion point
        if edit['timestamp'] > current_time:
            segment = main_video.subclip(current_time, edit['timestamp'])
            final_clips.append(segment)
        
        # Add b-roll clip
        broll = next(clip for clip in broll_clips if clip['keyword'] == edit['clip_id'])
        broll_video = VideoFileClip(download_clip(broll['url']))
        broll_segment = broll_video.subclip(0, edit['duration'])
        
        # Optional: Add transition effects
        broll_segment = broll_segment.crossfadein(0.5)
        
        final_clips.append(broll_segment)
        current_time = edit['timestamp'] + edit['duration']
    
    # Add remaining main video
    if current_time < main_video.duration:
        final_clips.append(main_video.subclip(current_time))
    
    # Concatenate all clips
    final_video = concatenate_videoclips(final_clips)
    
    # Export final video
    output_path = tempfile.mktemp(suffix='.mp4')
    final_video.write_videofile(output_path)
    
    # Clean up
    final_video.close()
    for clip in final_clips:
        clip.close()
    
    return output_path

def download_clip(url: str) -> str:
    """Download clip from Supabase Storage to temp file"""
    response = requests.get(url)
    with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as tmp:
        tmp.write(response.content)
        return tmp.name