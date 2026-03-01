import os
from dotenv import load_dotenv
from supabase import create_client
import time
import json
import traceback

load_dotenv()

class TrackerLogger:
    def __init__(self):
        url = os.getenv("SUPABASE_URL")
        key = os.getenv("SUPABASE_ANON_KEY")
        if not url or not key:
            raise ValueError("Missing SUPABASE_URL/ANON_KEY in .env")
        self.supabase = create_client(url, key)
    
    def log_run(self, run_type, status="success", metrics=None, error=None, raw_data=None, duration_ms=0):
        log_entry = {
            "run_type": run_type, "status": status,
            "metrics": metrics or {}, "error_msg": error,
            "raw_data": raw_data or {}, "duration_ms": duration_ms,
            "traceback": traceback.format_exc() if error else None
        }
        try:
            res = self.supabase.table("tracker_logs").insert(log_entry).execute()
            print("🗄️ LIVE LOG ID: " + str(res.data[0]["id"]))
            return res.data[0]["id"]
        except Exception as e:
            print("❌ DB LOG FAIL: " + str(e))
            return None

logger = TrackerLogger()
