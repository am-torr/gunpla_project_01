FROM python:3.12-slim
RUN pip install --upgrade pip --timeout=600 --retries=5 --no-cache-dir
RUN pip install --no-cache-dir --timeout=600 --retries=5 --index-url https://download.pytorch.org/whl/cpu torch
RUN pip install --no-cache-dir --timeout=600 --retries=5 sentence-transformers supabase langchain-text-splitters python-dotenv psycopg2-binary
WORKDIR /app
COPY . /app
CMD ["python", "ingest.py"]
