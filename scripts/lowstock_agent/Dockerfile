# Low-stock Agent SDK pipeline — runner (scheduler) + review UI share this image.
# Build context is the repo root: docker build -f scripts/lowstock_agent/Dockerfile .
FROM python:3.12-slim

# Node + the Claude Code CLI: the Python Agent SDK drives the CLI as a subprocess.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates gnupg \
 && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && npm install -g @anthropic-ai/claude-code \
 && apt-get purge -y curl gnupg \
 && apt-get autoremove -y \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY scripts/lowstock_agent/requirements.txt ./scripts/lowstock_agent/requirements.txt
RUN pip install --no-cache-dir -r scripts/lowstock_agent/requirements.txt

COPY scripts/lowstock_agent ./scripts/lowstock_agent

ENV PYTHONUNBUFFERED=1

# Default: the scheduled runner. The review UI overrides this in docker-compose.
CMD ["python", "-m", "scripts.lowstock_agent.scheduler"]
