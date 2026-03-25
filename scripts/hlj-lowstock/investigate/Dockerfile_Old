FROM python:3.12-slim
RUN pip install --upgrade pip --timeout=600 --retries=5 --no-cache-dir
RUN pip install --no-cache-dir --timeout=600 --retries=5 fastapi uvicorn playwright beautifulsoup4
RUN playwright install --with-deps chromium
WORKDIR /app
COPY . /app
EXPOSE 8001
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
