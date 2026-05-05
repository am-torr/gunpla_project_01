import os, requests
from supabase import create_client
load_dotenv()

class NAMSFramework:
    def __init__(self):
        self.supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE"))
    
    def embed_text(self, text):
        resp = requests.post("http://localhost:5001/embed", json={"inputs": text})
        return resp.json()[0]  # 384-dim vector
    
    def store_knowledge(self, partition, title, content, source_type, metadata):
        embedding = self.embed_text(content)
        self.supabase.table("framework_knowledge").insert({
            "partition": partition, "source_type": source_type, "title": title,
            "content": content, "metadata": metadata, "embedding": embedding
        }).execute()
    
    def query_knowledge(self, query, partition=None, top_k=5):
        query_emb = self.embed_text(query)
        resp = self.supabase.rpc("match_documents", {
            "query_embedding": query_emb, "match_threshold": 0.78, "match_count": top_k, "partition": partition
        }).execute()
        return resp.data