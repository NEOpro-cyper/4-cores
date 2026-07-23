"""
Dulo.tv Stream URL API — Production Grade v3.2
================================================
Optimized with:
- Session cookie caching (30 min) — saves ~2-3s per request
- Connection pooling (requests.Session) — saves TLS handshake time
- Pre-warmed cookie on startup
- 5-minute source result cache

Vercel:  deployed as @vercel/python serverless function
VPS:     waitress / gunicorn (bash start.sh)
"""

import copy
import json
import logging
import os
import re
import subprocess
import threading
import time
import traceback
import warnings
from typing import Optional

import requests as req_lib
from flask import Flask, request, jsonify
from flask_cors import CORS

warnings.filterwarnings("ignore", message="Unverified HTTPS request")

# ── Config (override via env vars) ──────────────────────────────────────────
PROXY_URL = os.environ.get(
    "PROXY_URL",
    "http://qijlkvsz-rotate:viryx2zv5njj@p.webshare.io:80",
)
PROXIES = {"http": PROXY_URL, "https": PROXY_URL} if PROXY_URL else {}
DULO_BASE = "https://dulo.tv"
SESSION_URL = f"{DULO_BASE}/api/session"
SOURCE_URL = f"{DULO_BASE}/api/source"
SSE_TIMEOUT = int(os.environ.get("SSE_TIMEOUT", "60"))
FETCH_MODE = os.environ.get("FETCH_MODE", "requests")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
CACHE_TTL = int(os.environ.get("CACHE_TTL", "300"))  # 5 min source cache
COOKIE_TTL = int(os.environ.get("COOKIE_TTL", "1800"))  # 30 min cookie cache
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# ── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("dulo-api")


# ── Connection Pool ────────────────────────────────────────────────────────
# Reuse TCP + TLS connections across requests (saves ~0.5-1s per request)
_http_session = req_lib.Session()
_http_session.verify = False
_http_session.proxies = PROXIES
_http_session.headers.update({
    "Origin": DULO_BASE,
    "Referer": f"{DULO_BASE}/",
    "User-Agent": UA,
})


# ── Caches ─────────────────────────────────────────────────────────────────

class _TTLCache:
    """Thread-safe in-memory cache with TTL."""
    def __init__(self, ttl: int):
        self.ttl = ttl
        self._store = {}
        self._lock = threading.Lock()

    def get(self, key: str):
        with self._lock:
            entry = self._store.get(key)
            if entry and (time.time() - entry["time"]) < self.ttl:
                return entry["data"]
            if entry:
                del self._store[key]
        return None

    def set(self, key: str, data):
        with self._lock:
            self._store[key] = {"data": data, "time": time.time()}

    def clear(self):
        with self._lock:
            self._store.clear()

    def stats(self):
        with self._lock:
            now = time.time()
            active = sum(1 for e in self._store.values() if (now - e["time"]) < self.ttl)
            return {"entries": len(self._store), "active": active, "ttl_seconds": self.ttl}


class SourceCache:
    """Cache keyed by content type + tmdbId + season + episode."""
    def __init__(self, ttl: int):
        self._cache = _TTLCache(ttl)

    def _key(self, tmdb_id, content_type, season, episode):
        if content_type == "tv":
            return f"{content_type}:{tmdb_id}:s{season}:e{episode}"
        return f"{content_type}:{tmdb_id}"

    def get(self, tmdb_id, content_type, season, episode):
        return self._cache.get(self._key(tmdb_id, content_type, season, episode))

    def set(self, tmdb_id, content_type, season, episode, data):
        self._cache.set(self._key(tmdb_id, content_type, season, episode), data)

    def clear(self):
        self._cache.clear()

    def stats(self):
        return self._cache.stats()


# Source result cache (5 min)
source_cache = SourceCache(ttl=CACHE_TTL)
# Session cookie cache (30 min) — saves ~2-3s per request
cookie_cache = _TTLCache(ttl=COOKIE_TTL)

# ── App ────────────────────────────────────────────────────────────────────
app = Flask(__name__)
CORS(app)


# ═══════════════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════════════

def score_source(source: dict) -> int:
    """Score source by quality (reverse-engineered from dulo.tv's vn())."""
    score = 0
    src_type = source.get("type", "").lower()
    url = source.get("url", "").lower()
    if src_type == "mp4":
        score += 50
    elif src_type == "hls":
        score += 45
    if "storrrrrrm.site" in url or "vidrock" in url:
        score += 60
    if "vixsrc" in url:
        score += 18
    return score


# ── Session cookie (cached!) ───────────────────────────────────────────────

def _get_session_cookie_requests() -> str:
    """GET /api/session via requests lib — uses persistent Session for connection reuse."""
    resp = _http_session.get(
        SESSION_URL,
        timeout=15,
        allow_redirects=True,
    )
    cookies = resp.cookies.get_dict()
    if "amri_session" in cookies:
        return cookies["amri_session"]
    # Try Set-Cookie header
    for hdr in resp.headers.get_list("Set-Cookie") if hasattr(resp.headers, "get_list") else []:
        m = re.search(r"amri_session=([^;\s]+)", hdr)
        if m:
            return m.group(1)
    # Try raw headers
    for hdr_val in resp.headers.values():
        if "amri_session" in str(hdr_val):
            m = re.search(r"amri_session=([^;\s]+)", str(hdr_val))
            if m:
                return m.group(1)
    raise RuntimeError(
        f"Failed to obtain amri_session cookie (status={resp.status_code})"
    )


def _get_session_cookie_curl() -> str:
    """GET /api/session via subprocess curl."""
    cmd = [
        "curl", "-s", "-D", "-",
        "--max-time", "15",
        "-H", f"Origin: {DULO_BASE}",
        "-H", f"Referer: {DULO_BASE}/",
        "-H", f"User-Agent: {UA}",
    ]
    if PROXY_URL:
        cmd += ["--proxy", PROXY_URL]
    cmd.append(SESSION_URL)

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)

    if result.returncode != 0 and not result.stdout:
        raise RuntimeError(f"Session curl failed: {result.stderr[:300]}")

    for line in result.stdout.split("\n"):
        if "amri_session" in line:
            m = re.search(r"amri_session=([^;\s]+)", line)
            if m:
                return m.group(1)

    raise RuntimeError("Failed to obtain amri_session cookie from curl")


def get_session_cookie() -> str:
    """
    Get session cookie — CHECKS CACHE FIRST.
    Cookie is cached for COOKIE_TTL seconds (default 30 min).
    Only fetches from dulo.tv if cache miss or expired.
    """
    cached = cookie_cache.get("amri_session")
    if cached:
        logger.info("Session cookie: CACHED")
        return cached

    logger.info("Session cookie: fetching fresh...")
    if FETCH_MODE == "curl":
        try:
            val = _get_session_cookie_curl()
        except FileNotFoundError:
            logger.warning("curl not found, falling back to requests")
            val = _get_session_cookie_requests()
    else:
        try:
            val = _get_session_cookie_requests()
        except Exception as e:
            logger.warning(f"requests session failed ({e}), trying curl")
            try:
                val = _get_session_cookie_curl()
            except FileNotFoundError:
                raise

    # Cache the cookie
    cookie_cache.set("amri_session", val)
    logger.info(f"Session cookie: fresh → {val[:8]}... cached for {COOKIE_TTL}s")
    return val


def refresh_cookie():
    """Force refresh the session cookie (used on startup + periodic refresh)."""
    try:
        val = get_session_cookie()  # This will use cache if valid, or fetch fresh
        logger.info(f"Cookie pre-warmed: {val[:8]}...")
    except Exception as e:
        logger.warning(f"Cookie pre-warm failed: {e} (will retry on first request)")


# ── SSE source fetch ───────────────────────────────────────────────────────

def _fetch_sse_requests(cookie_val: str, body: dict) -> str:
    """
    POST /api/source via requests Session — NON-STREAMING.
    Uses persistent Session for connection reuse (saves TLS handshake).
    """
    resp = _http_session.post(
        SOURCE_URL,
        json=body,
        headers={
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
            "Cookie": f"amri_session={cookie_val}",
        },
        timeout=SSE_TIMEOUT,
        allow_redirects=True,
    )
    resp.raise_for_status()
    return resp.text


def _fetch_sse_curl(cookie_val: str, body_json: str) -> str:
    """POST /api/source via subprocess curl — returns raw SSE text."""
    cmd = [
        "curl", "-s", "-N",
        "--max-time", str(SSE_TIMEOUT),
        "-X", "POST",
        "-H", f"Origin: {DULO_BASE}",
        "-H", f"Referer: {DULO_BASE}/",
        "-H", "Accept: text/event-stream",
        "-H", "Content-Type: application/json",
        "-H", f"Cookie: amri_session={cookie_val}",
        "-H", f"User-Agent: {UA}",
    ]
    if PROXY_URL:
        cmd += ["--proxy", PROXY_URL]
    cmd += ["-d", body_json]
    cmd.append(SOURCE_URL)

    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=SSE_TIMEOUT + 10
    )

    if result.returncode != 0 and not result.stdout:
        raise RuntimeError(
            f"Source curl failed (exit {result.returncode}): {result.stderr[:300]}"
        )

    return result.stdout


def fetch_sse(cookie_val: str, body: dict) -> str:
    """Fetch SSE text, trying primary then fallback mode."""
    if FETCH_MODE == "curl":
        try:
            return _fetch_sse_curl(cookie_val, json.dumps(body))
        except FileNotFoundError:
            logger.warning("curl not found, falling back to requests for SSE")
            return _fetch_sse_requests(cookie_val, body)
    else:
        try:
            return _fetch_sse_requests(cookie_val, body)
        except Exception as e:
            # If SSE fetch fails, invalidate the cookie — it might be stale
            logger.warning(f"SSE fetch failed ({e}), invalidating cookie cache")
            cookie_cache.clear()
            try:
                return _fetch_sse_curl(cookie_val, json.dumps(body))
            except FileNotFoundError:
                raise


# ── SSE parsing ────────────────────────────────────────────────────────────

def parse_sse(sse_text: str) -> list:
    """Parse SSE event text into a list of source dicts."""
    all_sources = []
    event_type = None
    data_lines = []

    for line in sse_text.split("\n"):
        if line.startswith("event:"):
            event_type = line[len("event:"):].strip()
        elif line.startswith("data:"):
            data_lines.append(line[len("data:"):].strip())
        elif line == "":
            if event_type and data_lines:
                data_str = " ".join(data_lines)
                try:
                    data = json.loads(data_str)
                    if event_type == "sources":
                        all_sources.extend(data.get("sources", []))
                    elif event_type == "error":
                        error_msg = data.get("message", data.get("error", "Unknown"))
                        raise RuntimeError(f"Dulo source error: {error_msg}")
                except json.JSONDecodeError:
                    pass
            event_type = None
            data_lines = []

    # Handle last event if no trailing newline
    if event_type and data_lines:
        data_str = " ".join(data_lines)
        try:
            data = json.loads(data_str)
            if event_type == "sources":
                all_sources.extend(data.get("sources", []))
        except json.JSONDecodeError:
            pass

    return all_sources


# ── Main fetch ─────────────────────────────────────────────────────────────

def fetch_sources(
    tmdb_id: int,
    content_type: str,
    season: Optional[int] = None,
    episode: Optional[int] = None,
) -> tuple:
    """
    Fetch stream sources from dulo.tv.
    Returns (list_of_sources, elapsed_seconds, from_cache).
    Results cached for CACHE_TTL seconds. Cookie cached for COOKIE_TTL seconds.
    """
    # Check source cache first
    cached = source_cache.get(tmdb_id, content_type, season, episode)
    if cached is not None:
        logger.info(f"Source cache HIT: tmdb={tmdb_id} type={content_type} s={season} e={episode}")
        return cached["sources"], cached["elapsed"], True

    logger.info(
        f"Source cache MISS — fetching: tmdb={tmdb_id} type={content_type} "
        f"s={season} e={episode} mode={FETCH_MODE}"
    )
    start_time = time.time()

    # Step 1: Session cookie (cached for 30 min — saves ~2-3s)
    cookie_val = get_session_cookie()
    cookie_elapsed = round(time.time() - start_time, 2)
    logger.info(f"Cookie step took {cookie_elapsed}s")

    # Step 2: SSE source fetch
    body = {"type": content_type, "tmdbId": tmdb_id}
    if content_type == "tv":
        body["season"] = season
        body["episode"] = episode

    sse_text = fetch_sse(cookie_val, body)
    logger.info(f"SSE response length: {len(sse_text)} chars")

    # Step 3: Parse
    all_sources = parse_sse(sse_text)
    elapsed = round(time.time() - start_time, 2)
    logger.info(f"Found {len(all_sources)} sources in {elapsed}s (cookie={cookie_elapsed}s)")

    # Store in cache
    source_cache.set(tmdb_id, content_type, season, episode, {
        "sources": all_sources,
        "elapsed": elapsed,
    })

    return all_sources, elapsed, False


def tv_extra(season, episode):
    if season is not None and episode is not None:
        return {"season": season, "episode": episode}
    return {}


def _build_response(raw_sources, tmdb_id, content_type, season, episode, elapsed, server=None, from_cache=False):
    """Build JSON response. If server=N, return only that server."""
    if not raw_sources:
        return jsonify({
            "error": "No sources found",
            "tmdbId": tmdb_id,
            "type": content_type,
            **tv_extra(season, episode),
            "elapsed_seconds": elapsed,
            "cached": from_cache,
        }), 404

    sources = copy.deepcopy(raw_sources)

    for src in sources:
        src["score"] = score_source(src)
    sources.sort(key=lambda s: s["score"], reverse=True)

    for i, src in enumerate(sources):
        src["server_number"] = i + 1

    if server is not None:
        matching = [s for s in sources if s["server_number"] == server]
        if not matching:
            return jsonify({
                "error": f"Server {server} not found",
                "available_servers": len(sources),
                "elapsed_seconds": elapsed,
                "cached": from_cache,
            }), 404
        return jsonify({
            "tmdbId": tmdb_id,
            "type": content_type,
            **tv_extra(season, episode),
            "server": server,
            "source": matching[0],
            "elapsed_seconds": elapsed,
            "cached": from_cache,
        })

    return jsonify({
        "tmdbId": tmdb_id,
        "type": content_type,
        **tv_extra(season, episode),
        "total_servers": len(sources),
        "sources": sources,
        "elapsed_seconds": elapsed,
        "cached": from_cache,
    })


# ═══════════════════════════════════════════════════════════════════════════
#  Endpoints
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/")
def root():
    return jsonify({
        "name": "Dulo.tv Stream API",
        "version": "3.2.0",
        "status": "running",
        "fetch_mode": FETCH_MODE,
        "cache_ttl_source": CACHE_TTL,
        "cache_ttl_cookie": COOKIE_TTL,
        "endpoints": {
            "movie": "/api/movie/<tmdbId>?server=<n>",
            "tv": "/api/tv/<tmdbId>/<season>/<episode>?server=<n>",
            "legacy_stream": "/api/stream?id=<tmdbId>&type=movie|tv&season=<n>&episode=<n>&server=<n>",
            "list_servers": "/api/stream/list?id=<tmdbId>&type=movie|tv&season=<n>&episode=<n>",
            "health": "/health",
        },
        "examples": [
            "/api/movie/550",
            "/api/movie/550?server=1",
            "/api/tv/1396/1/1",
            "/api/tv/1396/1/1?server=2",
        ],
    })


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "version": "3.2.0",
        "fetch_mode": FETCH_MODE,
        "proxy_configured": bool(PROXY_URL),
        "source_cache": source_cache.stats(),
        "cookie_cache": cookie_cache.stats(),
    })


@app.route("/api/movie/<int:tmdb_id>")
def get_movie(tmdb_id):
    server = request.args.get("server", type=int)
    if server is not None and server < 1:
        return jsonify({"error": "server must be >= 1"}), 400

    try:
        raw_sources, elapsed, from_cache = fetch_sources(tmdb_id, "movie")
    except Exception as e:
        logger.error(f"Movie fetch failed: {e}\n{traceback.format_exc()}")
        return jsonify({"error": str(e)}), 502

    return _build_response(raw_sources, tmdb_id, "movie", None, None, elapsed, server, from_cache)


@app.route("/api/tv/<int:tmdb_id>/<int:season>/<int:episode>")
def get_tv(tmdb_id, season, episode):
    server = request.args.get("server", type=int)
    if server is not None and server < 1:
        return jsonify({"error": "server must be >= 1"}), 400

    try:
        raw_sources, elapsed, from_cache = fetch_sources(tmdb_id, "tv", season, episode)
    except Exception as e:
        logger.error(f"TV fetch failed: {e}\n{traceback.format_exc()}")
        return jsonify({"error": str(e)}), 502

    return _build_response(raw_sources, tmdb_id, "tv", season, episode, elapsed, server, from_cache)


@app.route("/api/stream")
def get_stream():
    tmdb_id = request.args.get("id", type=int)
    content_type = request.args.get("type", "movie")
    season = request.args.get("season", type=int)
    episode = request.args.get("episode", type=int)
    server = request.args.get("server", type=int)

    if tmdb_id is None:
        return jsonify({"error": "id parameter is required"}), 400
    if content_type not in ("movie", "tv"):
        return jsonify({"error": "type must be 'movie' or 'tv'"}), 400
    if content_type == "tv" and (season is None or episode is None):
        return jsonify({"error": "season and episode are required for TV"}), 400
    if server is not None and server < 1:
        return jsonify({"error": "server must be >= 1"}), 400

    try:
        raw_sources, elapsed, from_cache = fetch_sources(tmdb_id, content_type, season, episode)
    except Exception as e:
        logger.error(f"Stream fetch failed: {e}\n{traceback.format_exc()}")
        return jsonify({"error": str(e)}), 502

    return _build_response(raw_sources, tmdb_id, content_type, season, episode, elapsed, server, from_cache)


@app.route("/api/stream/list")
def list_sources():
    tmdb_id = request.args.get("id", type=int)
    content_type = request.args.get("type", "movie")
    season = request.args.get("season", type=int)
    episode = request.args.get("episode", type=int)

    if tmdb_id is None:
        return jsonify({"error": "id parameter is required"}), 400
    if content_type not in ("movie", "tv"):
        return jsonify({"error": "type must be 'movie' or 'tv'"}), 400
    if content_type == "tv" and (season is None or episode is None):
        return jsonify({"error": "season and episode required for TV"}), 400

    try:
        raw_sources, elapsed, from_cache = fetch_sources(tmdb_id, content_type, season, episode)
    except Exception as e:
        return jsonify({"error": str(e)}), 502

    sources = copy.deepcopy(raw_sources)
    for src in sources:
        src["score"] = score_source(src)
    sources.sort(key=lambda s: s["score"], reverse=True)

    servers = []
    for i, src in enumerate(sources):
        servers.append({
            "server": i + 1,
            "title": src.get("title", "Unknown"),
            "quality": src.get("quality", "Unknown"),
            "type": src.get("type", "Unknown"),
            "score": src.get("score", 0),
        })

    return jsonify({
        "tmdbId": tmdb_id,
        "type": content_type,
        **tv_extra(season, episode),
        "total_servers": len(servers),
        "servers": servers,
        "elapsed_seconds": elapsed,
        "cached": from_cache,
    })


# ── Pre-warm cookie on startup ─────────────────────────────────────────────

# Warm up the session cookie + TLS connection before first user request
logger.info("Pre-warming session cookie and TLS connection...")
refresh_cookie()
logger.info("Pre-warm complete. Server ready.")


# ── Entry point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        threaded=True,
    )
