import os
from supabase import create_client

# Load from .env
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# Ping
data = supabase.table('store_prices').select('count').execute()
print("✅ Supabase connected:", data)
