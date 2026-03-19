FROM python:3.12-slim

# PH-net proof: retries + SSL
RUN apt-get update -qq && \
    apt-get install -y curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Pip upgrade first
RUN pip install --upgrade pip --timeout=600 --retries=5 --no-cache-dir

# Exact script deps — no more crashes
RUN pip install --no-cache-dir --timeout=600 --retries=5 \
    fastapi==0.115.0 \
    uvicorn[standard]==0.30.6 \
    playwright==1.48.0 \
    beautifulsoup4==4.12.3 \
    lxml==4.9.4 \
    requests==2.32.3 \
    python-dotenv==1.0.1

# Install Chromium (headless)
RUN playwright install --with-deps chromium

WORKDIR /app
COPY . /app
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
