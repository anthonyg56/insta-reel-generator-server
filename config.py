from pydantic import BaseSettings

class Settings(BaseSettings):
    SUPABASE_URL: str
    SUPABASE_KEY: str
    OPENAI_API_KEY: str
    REPLICATE_API_TOKEN: str
    
    class Config:
        env_file = ".env"

settings = Settings()