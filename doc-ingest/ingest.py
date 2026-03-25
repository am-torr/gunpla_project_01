#!/usr/bin/env python3
from sentence_transformers import SentenceTransformer
import os
from supabase import create_client
from dotenv import load_dotenv
load_dotenv()  # Loads .env from script dir or parent


model = SentenceTransformer('all-MiniLM-L6-v2')
supabase = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_SERVICE_ROLE_KEY'))

print("✅ Model loaded, test embed...")
test_emb = model.encode("Gunpla test").tolist()
print(f"Embedding: {len(test_emb)} dims")

# Test upsert
supabase.table('documents').insert([{
    'content': 'Gunpla RAG test',
    'embedding': test_emb
}]).execute()
print("✅ Upsert success!")
