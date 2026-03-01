cd D:\PROJECT\gunpla-tracker-verified
docker-compose up -d
docker ps  # fastapi:8000, n8n:5678, postgres
curl localhost:8000/health  # API check
localhost:5678  # n8n workflows → cron scrape
