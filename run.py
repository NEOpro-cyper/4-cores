"""
Entry point for Dulo.tv Stream API.
Uses gunicorn with 4 workers (4 cores) for maximum throughput.
Falls back to waitress (multi-threaded) if gunicorn is unavailable.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

WORKERS = int(os.environ.get("WORKERS", "4"))
THREADS_PER_WORKER = int(os.environ.get("THREADS", "2"))
PORT = int(os.environ.get("PORT", "8000"))
HOST = "0.0.0.0"
TIMEOUT = int(os.environ.get("TIMEOUT", "300"))

try:
    # ── Gunicorn: 4 workers × 2 threads = handles 8 concurrent requests across 4 cores ──
    from gunicorn.app.base import BaseApplication

    class StandaloneApplication(BaseApplication):
        """Custom gunicorn application for programmatic launch."""

        def __init__(self, app, options=None):
            self.options = options or {}
            self.application = app
            super().__init__()

        def load_config(self):
            for key, value in self.options.items():
                if key in self.cfg.settings and value is not None:
                    self.cfg.set(key.lower(), value)

        def load(self):
            return self.application

    from api.index import app

    options = {
        "bind": f"{HOST}:{PORT}",
        "workers": WORKERS,
        "threads": THREADS_PER_WORKER,
        "timeout": TIMEOUT,
        "graceful_timeout": TIMEOUT,
        "preload_app": True,
        "max_requests": 1000,        # Restart workers after 1000 requests to prevent memory leaks
        "max_requests_jitter": 50,    # Add jitter so workers don't all restart at the same time
        "accesslog": "-",
        "loglevel": os.environ.get("LOG_LEVEL", "info").lower(),
    }

    print(f"[run.py] Starting gunicorn: {WORKERS} workers × {THREADS_PER_WORKER} threads on {HOST}:{PORT}")
    StandaloneApplication(app, options).run()

except ImportError:
    print("[run.py] gunicorn not available, falling back to waitress")
    from api.index import app

    try:
        from waitress import serve
        print(f"[run.py] Starting with waitress on {HOST}:{PORT} (threads=8, single-core)")
        serve(app, host=HOST, port=PORT, threads=8)
    except ImportError:
        print(f"[run.py] waitress also unavailable, using Flask dev server on {HOST}:{PORT}")
        app.run(host=HOST, port=PORT, threaded=True)
