from pydantic_settings import BaseSettings
from pydantic import ConfigDict
from typing import List


class Settings(BaseSettings):
    model_config = ConfigDict(extra='allow', env_file='.env', case_sensitive=True)
    
    # Supabase
    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""

    # API
    API_VERSION: str = "v1"
    DEBUG_MODE: bool = True
    ALLOWED_ORIGINS: List[str] = ["http://localhost:3000"]

    # Scraper
    SCRAPE_DELAY_SECONDS: int = 3
    MAX_RETRIES: int = 3
    USER_AGENT: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    SCRAPER_API_KEY: str = ""


settings = Settings()
