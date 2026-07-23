"""
Entry point for Dulo.tv Stream API.
Tries waitress (production), falls back to Flask dev server.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api.index import app

PORT = int(os.environ.get("PORT", "8000"))
HOST = "0.0.0.0"

try:
    from waitress import serve
    print(f"[run.py] Starting with waitress on {HOST}:{PORT}")
    serve(app, host=HOST, port=PORT, threads=8)
except ImportError:
    print(f"[run.py] waitress not available, using Flask dev server on {HOST}:{PORT}")
    app.run(host=HOST, port=PORT, threaded=True)
