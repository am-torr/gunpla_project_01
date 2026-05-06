from supabase import create_client, Client
from app.config import settings
import logging

logger = logging.getLogger(__name__)


class Database:
    _instance: Client = None

    @classmethod
    def get_client(cls) -> Client:
        if cls._instance is None:
            try:
                # Try service_role first (bypasses RLS)
                service_key = getattr(settings, 'SUPABASE_SERVICE_ROLE_KEY', None)
                anon_key = settings.SUPABASE_KEY
                
                if service_key:
                    logger.info("Using SUPABASE_SERVICE_ROLE_KEY (bypasses RLS)")
                    cls._instance = create_client(settings.SUPABASE_URL, service_key)
                elif anon_key and settings.SUPABASE_URL:
                    logger.info("Using SUPABASE_KEY (anon)")
                    cls._instance = create_client(settings.SUPABASE_URL, anon_key)
                else:
                    logger.warning("Supabase credentials not set - database disabled")
                    return None
                
                logger.info("✅ Supabase client connected")
            except Exception as e:
                logger.error(f"❌ Supabase connection failed: {e}")
                return None
        return cls._instance


# Export db instance
try:
    db = Database.get_client()
except:
    db = None
