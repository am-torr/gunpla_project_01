"""
RAG INGESTION PIPELINE v1.0 - Gestalt-Spatial Edition
=====================================================
CONTAINER: DOC → EMBEDDING → SUPABASE → RETRIEVAL
PATTERN: 1. Chunk → 2. Embed → 3. Store → 4. Query
VISUAL: See architecture map above ^

Arvin Profile: 2-3d hands-on, patterns first, advance 50% time
"""

import os  # OS = Operating System module
import torch  # PyTorch = tensor math library (GPU/CPU acceleration)
from transformers import pipeline  # HF Transformers = 100k+ ML models
from supabase import create_client, Client  # Supabase Python client
from langchain_text_splitters import RecursiveCharacterTextSplitter  # Smart doc chunker

# =============================================================================
# 🏗️ CONFIG CONTAINER (Change these 5 vars only)
# =============================================================================
HF_HOME = r'D:\PROJECT\doc-ingest\models\hf-cache'  # HF Hub cache location
SUPABASE_URL = os.getenv('SUPABASE_URL')  # Your Supabase project URL
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')  # Admin API key (not anon)
MODEL_NAME = 'sentence-transformers/all-MiniLM-L6-v2'  # 384-dim embedder
CHUNK_SIZE = 500  # Chars per chunk (optimal for retrieval)

os.environ['HF_HOME'] = HF_HOME
os.environ['TRANSFORMERS_OFFLINE'] = '0'  # 0=online, 1=offline

# =============================================================================
# 🔧 EMBEDDER FACTORY (Reusable pattern)
# =============================================================================
def get_embedder():
    """
    PATTERN: Factory = Create once, reuse forever
    MiniLM-L6-v2: 22M params, 80MB disk, 384-dim output
    """
    embedder = pipeline('feature-extraction', model=MODEL_NAME)
    return embedder

# =============================================================================
# ✂️ CHUNKER (LangChain pattern: Recursive split w/ overlap)
# =============================================================================
def get_chunker():
    """
    RecursiveCharacterTextSplitter:
    - Splits on \n\n, \n, ., ?, ! 
    - Keeps 50-char overlap (context preservation)
    - Gestalt: Maintains doc structure
    """
    return RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=50,
        separators=["\n\n", "\n", " ", ""]
    )

# =============================================================================
# 🔢 SENTENCE EMBEDDING (Mean pooling = Official method)
# =============================================================================
def pool_to_sentence_embedding(embedder, text_chunks):
    """
    FIXED POOLING: Handles [1,1,384], [1,22,384], batching
    Mean pooling = Official sentence-transformers method
    """
    embeddings = []
    for chunk in text_chunks:
        result = embedder(chunk)  # List → [1, seq_len, 384]
        tokens = torch.tensor(result)  # Shape: [1, seq_len, 384]
        
        # SIMPLIFIED: No mask needed for feature-extraction
        sentence_emb = torch.mean(tokens, dim=1).squeeze().tolist()
        embeddings.append(sentence_emb)  # Always [384]
    
    return embeddings



""" def pool_to_sentence_embedding(embedder, text_chunks):
    """
"""     WHY POOLING? Raw tokens=[1,N,384] → sentence=[384]
    Mean Pooling: Average all token vectors (CLS+content+SEP)
    OUTPUT: list[float] for Supabase vector(384) """
"""     """ """
    embeddings = []
    for chunk in text_chunks:
        result = embedder(chunk)  # [1, seq_len, 384]
        tokens = torch.tensor(result)  # PyTorch tensor
        # MASKING PATTERN: Ignore padding (future-proof)
        attention_mask = torch.ones(tokens.shape[:-1], dtype=torch.float)
        pooled = (tokens * attention_mask.unsqueeze(-1)).sum(1)
        pooled /= attention_mask.sum(1, keepdim=True).unsqueeze(-1)
        embeddings.append(pooled.squeeze().tolist())  # [384]
    return embeddings """


# =============================================================================
# 🗄️ SUPABASE CLIENT + INGEST (Batch upsert pattern)
# =============================================================================
def get_supabase_client():
    """Supabase = Postgres + pgvector + auth"""
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def ingest_document(supabase_client, filename, raw_text):
    """
    FULL PIPELINE:
    1. Chunk raw_text → list[str]
    2. Embed chunks → list[list[float]]
    3. Batch insert → Supabase RPC/transaction
    """
    embedder = get_embedder()
    chunker = get_chunker()
    
    # 1. CHUNK
    chunks = chunker.split_text(raw_text)
    print(f"📄 {filename}: {len(chunks)} chunks")
    
    # 2. EMBED
    embeddings = pool_to_sentence_embedding(embedder, chunks)
    
    # 3. PREP ROWS (Supabase format)
    rows = []
    for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
        rows.append({
            "filename": filename,
            "chunk_index": i,
            "content": chunk,
            "metadata": {"source": filename, "chunk": i},
            "embedding": emb  # vector(384) ready!
        })
    
    # 4. BATCH UPSERT (Efficient: 1000+ rows/sec)
    response = (supabase_client
                .table("documents")
                .insert(rows)
                .execute())
    
    print(f"✅ Ingested {len(rows)} chunks → Supabase")
    return response

# =============================================================================
# 🔍 RETRIEVER (Query → Top-K matches)
# =============================================================================
def retrieve(supabase_client, query, top_k=5, threshold=0.7):
    """
    pgvector RPC: match_documents(query_emb, threshold, top_k)
    Cosine similarity: 1 - distance (higher = more similar)
    """
    embedder = get_embedder()
    query_emb = pool_to_sentence_embedding(embedder, [query])[0]
    
    result = (supabase_client
              .rpc("match_documents", {
                  "query_embedding": query_emb,
                  "match_threshold": threshold,
                  "match_count": top_k
              })
              .execute())
    
    return result.data  # [{"content": "...", "similarity": 0.85}, ...]

# =============================================================================
# 🚀 USAGE PATTERNS (Copy-paste blocks)
# =============================================================================
if __name__ == "__main__":
    # TEST EMBEDDING ONLY
    embedder = get_embedder()
    emb = pool_to_sentence_embedding(embedder, ["hello world"])[0]
    print(f"✅ Embedding: {len(emb)} dims")
    
    # FULL INGEST
    # supabase = get_supabase_client()
    # ingest_document(supabase, "test.txt", "Your document text here...")
    
    # QUERY
    # docs = retrieve(supabase, "hello world")
    # print(docs)






""" from transformers import pipeline
import os
os.environ['HF_HOME'] = r'D:\PROJECT\doc-ingest\models\hf-cache'


model_name = 'sentence-transformers/all-MiniLM-L6-v2'
embedder = pipeline('feature-extraction',model=model_name)

result = embedder('hello world')

print(result) """