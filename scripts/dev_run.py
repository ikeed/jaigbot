#!/usr/bin/env python3
import os
import sys
import shlex
import subprocess
import time

# Simple local dev runner that launches both the FastAPI backend (uvicorn)
# and the Chainlit frontend. This mirrors the Dockerfile behavior.
#
# - Backend (uvicorn) runs on BACKEND_PORT (default 8000)
# - Chainlit runs on PORT (default 8080)
# - Chainlit is pointed at the backend via BACKEND_URL env var
#
# Usage: run this script from your PyCharm Run Configuration or manually:
#   python scripts/dev_run.py
#
# Stop both processes with Ctrl+C.

BACKEND_PORT = int(os.getenv("BACKEND_PORT", "8000"))
PORT = int(os.getenv("PORT", "8080"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "info")

# Ensure BACKEND_URL for Chainlit points to backend
env = os.environ.copy()
env.setdefault("BACKEND_URL", f"http://localhost:{BACKEND_PORT}/chat")
# Force Chainlit UI language to English by default (can be overridden)
env.setdefault("CHAINLIT_LOCALE", "en")

uvicorn_cmd = f"uvicorn app.main:app --host 0.0.0.0 --port {BACKEND_PORT} --reload --log-level {shlex.quote(LOG_LEVEL)}"
chainlit_cmd = f"chainlit run chainlit_app.py --host 0.0.0.0 --port {PORT}"

print("[dev_run.py] Starting backend:", uvicorn_cmd, flush=True)
backend = subprocess.Popen(shlex.split(uvicorn_cmd), env=env)

# Tiny delay so backend starts up before Chainlit tries to talk to it
time.sleep(0.8)

print("[dev_run.py] Starting Chainlit:", chainlit_cmd, flush=True)
frontend = subprocess.Popen(shlex.split(chainlit_cmd), env=env)

try:
    # Wait for either process to exit, then terminate the other
    while True:
        ret_backend = backend.poll()
        ret_frontend = frontend.poll()
        if ret_backend is not None:
            print(f"[dev_run.py] Backend exited with code {ret_backend}. Stopping Chainlit...")
            try:
                frontend.terminate()
                frontend.wait(timeout=5)
            except Exception:
                pass
            sys.exit(ret_backend)
        if ret_frontend is not None:
            print(f"[dev_run.py] Chainlit exited with code {ret_frontend}. Stopping backend...")
            try:
                backend.terminate()
                backend.wait(timeout=5)
            except Exception:
                pass
            sys.exit(ret_frontend)
        time.sleep(0.5)
except KeyboardInterrupt:
    print("[dev_run.py] KeyboardInterrupt: terminating children...")
    try:
        backend.terminate()
    except Exception:
        pass
    try:
        frontend.terminate()
    except Exception:
        pass
    try:
        backend.wait(timeout=5)
    except Exception:
        pass
    try:
        frontend.wait(timeout=5)
    except Exception:
        pass
    sys.exit(130)
