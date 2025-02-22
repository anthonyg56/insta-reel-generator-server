from datetime import datetime
from supabase import Client

def create_reel_entry(supabase: Client, user_id: str, prompt: str) -> str:
    result = supabase.table('reels').insert({
        'user_id': user_id,
        'prompt': prompt,
        'status': 'pending'
    }).execute()
    
    return result.data[0]['id']

def update_reel_status(supabase: Client, reel_id: str, status: str, output_url: str = None):
    data = {
        'status': status,
        'updated_at': datetime.utcnow().isoformat(),
        'output_url': output_url
    }
    
    supabase.table('reels').update(data).eq('id', reel_id).execute() 