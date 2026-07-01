FROM python:3.11-slim

# Install lua5.3 for the bundled Prometheus obfuscator
RUN apt-get update && apt-get install -y --no-install-recommends \
    lua5.3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (better docker layer caching)
COPY requirements-render.txt ./
RUN pip install --no-cache-dir -r requirements-render.txt

# Copy the full backend (server.py, discord_bot.py, obfuscator.py, prometheus/, ...)
COPY . .

ENV PYTHONUNBUFFERED=1 \
    LUA_BIN=lua5.3

# Render provides $PORT
CMD sh -c 'uvicorn server:app --host 0.0.0.0 --port ${PORT:-8001}'
