"""Configuration for the low-stock agent.

Reuses the same `.env` as the rest of the project (the `ANTHROPIC_API_KEY`
currently provisioned for RAG, and the Supabase service-role credentials).
Mirrors the `pydantic-settings` pattern in app/config.py.
"""
import os

from dotenv import load_dotenv
from pydantic import ConfigDict
from pydantic_settings import BaseSettings

# Populate os.environ from .env so the Agent SDK's CLI subprocess inherits
# ANTHROPIC_API_KEY (the SDK reads it from the environment).
load_dotenv()


class Settings(BaseSettings):
    model_config = ConfigDict(extra="allow", env_file=".env", case_sensitive=True)

    # Anthropic (reuse the RAG key)
    ANTHROPIC_API_KEY: str = ""

    # Supabase (service role — backend writes)
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""

    # Input source
    HLJ_LOWSTOCK_URL: str = "http://localhost:8001"
    HLJ_FETCH_TIMEOUT: float = 600.0   # /low-stock does a full Playwright scrape; be patient

    # Dedup: posted low-stock items live in post_queue with source_type='hlj'.
    # 30-day "posted recently" cooldown mirrors import_post_queue_stg.sql (staging
    # dedup). NB: the candidate workflow (02) also dedups on active-row uniqueness
    # via import_post_queue's ON CONFLICT (source_type, source_id).
    DEDUP_SOURCE_TYPE: str = "hlj"
    REPOST_COOLDOWN_DAYS: int = 30

    # Deal signal
    STOCK_URGENCY_THRESHOLD: int = 5      # matches 02's stock_threshold; qualify when stock_count <= this
    DEAL_DROP_PCT: float = 10.0           # V2: price drop (%) that counts as a real deal
    USE_PRICE_DELTA_GATE: bool = False    # V2 switch: also require is_real_deal to qualify

    # Models — classification uses cheap/fast Haiku (per gunpla-classifier skill);
    # the optional suggested caption uses Sonnet (per caption-generator skill).
    CLASSIFIER_MODEL: str = "haiku"
    CAPTION_MODEL: str = "sonnet"
    CLASSIFIER_BATCH_SIZE: int = 20       # batch ambiguous items, never one-by-one

    # Post copy / caption
    ENABLE_SUGGESTED_CAPTION: bool = True  # also produce an LLM caption for the reviewer

    # Link shortening (mirrors 02: Bitly -> TinyURL -> raw affiliate fallback)
    ENABLE_SHORTENER: bool = True
    BITLY_ACCESS_TOKEN: str = ""

    # Orchestration
    MAX_CONCURRENCY: int = 4
    AGENT_SOURCE_SYSTEM: str = "hlj-lowstock-agent"

    # Scheduled runner (scheduler.py)
    RUN_INTERVAL_HOURS: float = 6.0    # how often the containerized runner fires
    RUN_THRESHOLD: int = 5             # /low-stock threshold per scheduled run
    RUN_LIMIT: int = 20                # cap items processed per scheduled run
    RUN_ON_START: bool = False         # also run once immediately on boot

    # Review UI (review_app.py)
    REVIEW_PORT: int = 8011


settings = Settings()

# Belt-and-suspenders: ensure the key is exported for the SDK subprocess.
if settings.ANTHROPIC_API_KEY and not os.environ.get("ANTHROPIC_API_KEY"):
    os.environ["ANTHROPIC_API_KEY"] = settings.ANTHROPIC_API_KEY


def get_supabase():
    """Create a Supabase client using the service-role key."""
    from supabase import create_client

    if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError(
            "SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing in .env — "
            "the agent needs the service-role credentials to read/write Supabase."
        )
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
