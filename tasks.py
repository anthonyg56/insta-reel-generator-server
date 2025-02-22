import os
from typing import List, Dict
from moviepy.editor import VideoFileClip, concatenate_videoclips
from openai import OpenAI
import tempfile
import requests
from pexels_api import API
import json
from db_operations import update_reel_status
import logging
from logging.handlers import RotatingFileHandler
from celery_config import celery_app
import whisper
from supabase import create_client, Client
from dotenv import load_dotenv
import shutil
from subprocess import run, PIPE

load_dotenv()

PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")
pexels_api = API(PEXELS_API_KEY)

# Initialize Supabase client
supabase_client: Client = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY")
)

openai_client = OpenAI(
    api_key=os.environ.get("OPENAI_API_KEY"),  # This is the default and can be omitted
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add file handler for persistent logging
file_handler = RotatingFileHandler('video_processing.log', maxBytes=1024*1024, backupCount=5)
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
logger.addHandler(file_handler)

# Add this after the logger setup and before the task definitions
def check_ffmpeg():
    """Verify FFmpeg is installed and accessible"""
    if not shutil.which('ffmpeg'):
        logger.error("FFmpeg not found in system PATH")
        raise RuntimeError("FFmpeg is required but not found. Please install FFmpeg.")
    
    try:
        result = run(['ffmpeg', '-version'], stdout=PIPE, stderr=PIPE)
        if result.returncode != 0:
            logger.error("FFmpeg check failed")
            raise RuntimeError("FFmpeg check failed")
        logger.info("FFmpeg check passed successfully")
    except Exception as e:
        logger.error(f"Error checking FFmpeg: {str(e)}")
        raise

# Add FFmpeg check to startup
check_ffmpeg()

@celery_app.task(name='tasks.process_video_with_broll')
def process_video_with_broll(video_data: dict, job_id: str):
    logger.info(f"Starting video processing for reel_id: {job_id}")
    try:
        update_reel_status(job_id, "processing")
        logger.info(f"Updated reel status to processing for reel_id: {job_id}")
        
        main_video_path = download_clip(video_data['video_url'])
        logger.info(f"Downloaded main video to: {main_video_path}")
        
        logger.info("Extracting keywords from video")
        keywords = extract_keywords_from_video(main_video_path)
        logger.debug(f"Extracted keywords: {keywords}")
        
        logger.info("Fetching b-roll clips")
        broll_clips = fetch_broll_clips(keywords)
        logger.debug(f"Fetched {len(broll_clips)} b-roll clips")
        
        logger.info("Generating edit plan")
        edit_plan = generate_edit_plan(keywords, broll_clips)
        logger.debug(f"Generated edit plan: {edit_plan}")
        
        logger.info("Creating final video")
        output_path = create_final_video(main_video_path, broll_clips, edit_plan)
        logger.info(f"Final video created at: {output_path}")
        
        # 5. Upload to Supabase Storage
        file_path = f"output/{job_id}.mp4"
        with open(output_path, 'rb') as f:
            supabase_client.storage.from_('output').upload(file_path, f)
        
        output_url = supabase_client.storage.from_('videos').get_public_url(file_path)
        
        # Cleanup
        os.unlink(main_video_path)
        os.unlink(output_path)
        
        update_reel_status(job_id, "completed", output_url)
        logger.info(f"Successfully completed video processing for reel_id: {job_id}")
        return {"status": "completed", "url": output_url}
        
    except Exception as e:
        logger.error(f"Error processing video for reel_id: {job_id}", exc_info=True)
        update_reel_status(job_id, "failed")
        raise e

def extract_keywords_from_video(video_path: str) -> List[Dict]:
    logger.info(f"Starting keyword extraction from video: {video_path}")
    try:
        model = whisper.load_model("base")
        logger.info("Whisper model loaded successfully")
        
        result = model.transcribe(video_path)
        logger.debug(f"Transcription result: {result['text'][:100]}...")
        
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": """You are a video editing assistant. Analyze the transcript and identify 3-5 key topics, objects, or concepts that would benefit from B-roll footage. 
                Return ONLY a JSON array of objects, each with 'keyword' and 'timestamp' fields. Example format:
                [
                    {"keyword": "mountain", "timestamp": 10},
                    {"keyword": "river", "timestamp": 25}
                ]"""},
                {"role": "user", "content": result["text"]}
            ]
        )
        
        # Add debug logging
        content = response.choices[0].message.content
        logger.debug(f"OpenAI response content: {content}")
        
        try:
            keywords = json.loads(content)
            if not isinstance(keywords, list):
                raise ValueError("Response is not a JSON array")
            logger.info(f"Successfully extracted {len(keywords)} keywords")
            return keywords
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {content}")
            # Return a default set of keywords as fallback
            return [{"keyword": "general", "timestamp": 0}]
            
    except Exception as e:
        logger.error("Error during keyword extraction", exc_info=True)
        raise

def fetch_broll_clips(keywords: List[Dict]) -> List[Dict]:
    logger.info(f"Fetching b-roll clips for {len(keywords)} keywords")
    broll_clips = []
    headers = {
        'Authorization': PEXELS_API_KEY,
    }
    
    for keyword_data in keywords:
        try:
            logger.debug(f"Searching for clips with keyword: {keyword_data['keyword']}")
            response = requests.get(
                'https://api.pexels.com/videos/search',
                headers=headers,
                params={
                    'query': keyword_data['keyword'],
                    'orientation': 'landscape',
                    'size': 'medium',
                    'per_page': 1
                }
            )
            response.raise_for_status()
            search_results = response.json()
            
            if search_results['videos']:
                video = search_results['videos'][0]
                # Get the medium size video file URL
                video_file = next(
                    (file for file in video['video_files'] 
                     if file['quality'] == 'md' or file['height'] < 1080),
                    video['video_files'][0]  # fallback to first available file
                )
                
                broll_clips.append({
                    'keyword': keyword_data['keyword'],
                    'timestamp': keyword_data['timestamp'],
                    'url': video_file['link'],
                    'duration': video['duration']
                })
                logger.debug(f"Found clip for keyword: {keyword_data['keyword']}")
            else:
                logger.warning(f"No clips found for keyword: {keyword_data['keyword']}")
        except Exception as e:
            logger.error(f"Error fetching b-roll for keyword: {keyword_data['keyword']}", exc_info=True)
    
    return broll_clips

def generate_edit_plan(keywords: List[Dict], broll_clips: List[Dict]) -> List[Dict]:
    """Generate editing instructions for video composition"""
    logger.info("Generating edit plan")
    try:
        prompt = f"""
        Create a precise editing plan for integrating B-roll clips into the main video.
        Return ONLY a JSON array of objects with this exact format:
        [
            {{"action": "insert_broll", "timestamp": 5, "duration": 3, "clip_id": "keyword1"}},
            {{"action": "insert_broll", "timestamp": 15, "duration": 4, "clip_id": "keyword2"}}
        ]
        
        Available keywords and timestamps: {json.dumps(keywords)}
        Available B-roll clips: {json.dumps(broll_clips)}
        
        Rules:
        - timestamp must match the original keyword timestamps
        - clip_id must match one of the keywords
        - duration should be between 2-5 seconds
        - Return ONLY the JSON array, no additional text
        """
        
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a video editing assistant that returns only valid JSON arrays."},
                {"role": "user", "content": prompt}
            ]
        )
        
        content = response.choices[0].message.content.strip()
        logger.debug(f"OpenAI response content: {content}")
        
        try:
            edit_plan = json.loads(content)
            if not isinstance(edit_plan, list):
                raise ValueError("Response is not a JSON array")
            
            # Validate the edit plan
            for edit in edit_plan:
                required_keys = {"action", "timestamp", "duration", "clip_id"}
                if not all(key in edit for key in required_keys):
                    raise ValueError(f"Missing required keys in edit: {edit}")
                
                if not any(clip['keyword'] == edit['clip_id'] for clip in broll_clips):
                    raise ValueError(f"Invalid clip_id: {edit['clip_id']}")
            
            logger.info(f"Successfully generated edit plan with {len(edit_plan)} edits")
            return edit_plan
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {content}")
            # Fallback plan: create simple edit plan using available clips
            fallback_plan = []
            for i, clip in enumerate(broll_clips):
                fallback_plan.append({
                    "action": "insert_broll",
                    "timestamp": clip['timestamp'],
                    "duration": min(3, clip['duration']),  # Use up to 3 seconds
                    "clip_id": clip['keyword']
                })
            logger.warning("Using fallback edit plan")
            return fallback_plan
            
    except Exception as e:
        logger.error("Error generating edit plan", exc_info=True)
        raise

def create_final_video(main_video_path: str, broll_clips: List[Dict], edit_plan: List[Dict]) -> str:
    logger.info("Starting final video creation")
    try:
        main_video = VideoFileClip(main_video_path)
        logger.debug(f"Loaded main video, duration: {main_video.duration}")
        
        final_clips = []
        current_time = 0
        
        for edit in edit_plan:
            logger.debug(f"Processing edit at timestamp: {edit['timestamp']}")
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
        
        logger.info("Concatenating video clips")
        final_video = concatenate_videoclips(final_clips)
        
        output_path = tempfile.mktemp(suffix='.mp4')
        logger.info(f"Writing final video to: {output_path}")
        final_video.write_videofile(output_path)
        
        # Clean up
        final_video.close()
        for clip in final_clips:
            clip.close()
        
        logger.info("Final video creation completed successfully")
        return output_path
    except Exception as e:
        logger.error("Error during final video creation", exc_info=True)
        raise

def download_clip(url: str) -> str:
    logger.info(f"Downloading clip from: {url}")
    try:
        response = requests.get(url)
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as tmp:
            tmp.write(response.content)
            logger.debug(f"Clip downloaded to: {tmp.name}")
            return tmp.name
    except Exception as e:
        logger.error(f"Error downloading clip from: {url}", exc_info=True)
        raise