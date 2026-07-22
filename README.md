# Dulo.tv Stream API

Fetch stream URLs from dulo.tv by TMDB ID. Works for movies and TV shows.

## Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/stream?id=<tmdbId>&type=movie\|tv&season=<n>&episode=<n>&server=<n>` | Fetch stream URLs |
| `GET /api/stream/list?id=<tmdbId>&type=movie\|tv&season=<n>&episode=<n>` | List servers only (no URLs) |
| `GET /` | API info |

### Parameters

| Param | Required | Description |
|-------|----------|-------------|
| `id` | Yes | TMDB ID (e.g. 550 = Fight Club, 1396 = Breaking Bad) |
| `type` | No | `movie` (default) or `tv` |
| `season` | TV only | Season number |
| `episode` | TV only | Episode number |
| `server` | No | Server number (1, 2, 3...) — returns only that server |

### Response Format

**All servers:**
```json
{
  "tmdbId": 550,
  "type": "movie",
  "total_servers": 3,
  "sources": [
    {
      "url": "https://...",
      "title": "Source 1",
      "type": "hls",
      "quality": "4K",
      "score": 45,
      "server_number": 1
    }
  ],
  "elapsed_seconds": 8.2
}
```

**Specific server (`server=1`):**
```json
{
  "tmdbId": 550,
  "type": "movie",
  "server": 1,
  "source": {
    "url": "https://...",
    "title": "Source 1",
    "type": "hls",
    "quality": "4K",
    "score": 45,
    "server_number": 1
  },
  "elapsed_seconds": 7.5
}
```

Servers are sorted by quality score (server 1 = best). Scoring: MP4 +50, HLS +45, storrrrrrm.site/vidrock +60, vixsrc +18.

---

## Deploy on Vercel

1. Push this repo to GitHub
2. Go to [vercel.com](https://vercel.com) → Import project
3. Select the repo → Deploy
4. Set environment variables (optional):
   - `PROXY_URL` — your rotating proxy URL

> **Note:** Vercel Hobby plan has a 10s function timeout. The SSE fetch takes ~8-10s, so it may timeout occasionally. Vercel Pro (60s timeout) works reliably.

### Manual Vercel deploy

```bash
npm i -g vercel
vercel --prod
```

---

## Deploy on VPS

### Quick Start

```bash
# Clone the repo
git clone <your-repo-url> dulo-api
cd dulo-api

# Install dependencies
pip install -r requirements.txt

# Start (foreground)
bash start.sh

# Start (background daemon)
bash start.sh bg

# Check status
bash start.sh status

# Stop
bash start.sh stop
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PROXY_URL` | Built-in rotating proxy | HTTP proxy URL for dulo.tv requests |
| `PORT` | 8000 | Server listen port |
| `WORKERS` | 4 | Gunicorn worker processes |
| `SSE_TIMEOUT` | 50 | SSE stream timeout (seconds) |

### Systemd Service (auto-start on boot)

Create `/etc/systemd/system/dulo-api.service`:

```ini
[Unit]
Description=Dulo.tv Stream API
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/dulo-api
Environment=PROXY_URL=http://user:pass@proxy:80
Environment=PORT=8000
Environment=WORKERS=4
ExecStart=/usr/local/bin/gunicorn --bind 0.0.0.0:8000 --workers 4 --threads 2 --timeout 300 --graceful-timeout 300 --chdir /opt/dulo-api api.index:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable dulo-api
sudo systemctl start dulo-api
```

### Nginx Reverse Proxy

```nginx
server {
    listen 80;
    server_name api.yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_read_timeout 120s;
    }
}
```

---

## Docker

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "4", "--threads", "2", "--timeout", "300", "api.index:app"]
```

```bash
docker build -t dulo-api .
docker run -d -p 8000:8000 -e PROXY_URL=http://user:pass@proxy:80 dulo-api
```

---

## Examples

```bash
# Movie — all servers
curl 'http://localhost:8000/api/stream?id=550&type=movie'

# Movie — server 1 only
curl 'http://localhost:8000/api/stream?id=550&type=movie&server=1'

# Movie — server 2 only
curl 'http://localhost:8000/api/stream?id=550&type=movie&server=2'

# TV show — all servers
curl 'http://localhost:8000/api/stream?id=1396&type=tv&season=1&episode=1'

# TV show — server 1 only
curl 'http://localhost:8000/api/stream?id=1396&type=tv&season=1&episode=1&server=1'

# List servers (no URLs, just metadata)
curl 'http://localhost:8000/api/stream/list?id=550&type=movie'
```
