import os
import requests

class NAMSManager:
    def __init__(self):
        self.url = os.getenv("SUPABASE_URL")
        self.key = os.getenv("SUPABASE_SERVICE_ROLE")
        self.headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json"
        }

    def seed_knowledge(self, category, content):
        data = {"category": category, "content": content}
        response = requests.post(f"{self.url}/rest/v1/frameworkknowledge", headers=self.headers, json=data)
        return response.status_code

    def log_execution(self, workflow_id, node_name, error_msg, success):
        data = {
            "workflow_id": workflow_id,
            "node_name": node_name,
            "error_message": error_msg,
            "success_status": success
        }
        response = requests.post(f"{self.url}/rest/v1/n8nexecutions", headers=self.headers, json=data)
        return response.status_code

if __name__ == "__main__":
    print("NAMS Framework CLI Initialized")