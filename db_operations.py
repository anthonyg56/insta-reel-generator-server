from supabase import create_client, Client
import os
from datetime import datetime
import logging
from dotenv import load_dotenv

load_dotenv()

# Initialize Supabase client
supabase_client: Client = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_KEY")
)

logger = logging.getLogger(__name__)

def create_reel_entry(user_id: str, prompt: str) -> str:
    result = supabase_client.from_('reels').insert({
        'user_id': user_id,
        'prompt': prompt,
        'status': 'pending'
    }).execute()
    
    return result.data[0]['id']

def update_reel_status(reel_id: str, status: str, output_url: str = None):
    """Update the status and output URL of a reel in the database."""
    try:
        data = {"status": status}
        if output_url:
            data["output_url"] = output_url

        result = supabase_client.from_("reels").update(data).eq("id", reel_id).execute()
        
        if not result.data:
            logger.error(f"Failed to update reel status for reel_id: {reel_id}")
            return False
            
        logger.info(f"Successfully updated reel status to {status} for reel_id: {reel_id}")
        return True
        
    except Exception as e:
        logger.error(f"Error updating reel status: {str(e)}", exc_info=True)
        raise 