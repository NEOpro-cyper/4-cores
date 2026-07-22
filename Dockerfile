FROM python:3.12-slim

RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Coolify will override the port via PORT env var
EXPOSE 8000

# Gunicorn: 4 workers (4 cores) × 2 threads = 8 concurrent requests
# Env vars WORKERS, THREADS, TIMEOUT can be overridden in Coolify UI
CMD ["sh", "-c", "gunicorn \
     --bind 0.0.0.0:${PORT:-8000} \
     --workers ${WORKERS:-4} \
     --threads ${THREADS:-2} \
     --timeout ${TIMEOUT:-300} \
     --graceful-timeout ${TIMEOUT:-300} \
     --preload-app \
     --max-requests 1000 \
     --max-requests-jitter 50 \
     --access-logfile - \
     --loglevel ${LOG_LEVEL:-info} \
     api.index:app"]
