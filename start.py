"""
Launcher — Trello-like scheduling app (FastAPI + PostgreSQL).
Run:  python start.py
Then open http://127.0.0.1:8000
"""

import subprocess, sys, os

# Make sure backend is on path
BACKEND = os.path.join(os.path.dirname(__file__), "backend")
os.chdir(os.path.dirname(__file__))

# Launch
cmd = [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000"]
env = os.environ.copy()
env["PYTHONPATH"] = BACKEND

print("Starting Trello Like on http://127.0.0.1:8000")
subprocess.run(cmd, env=env, cwd=BACKEND)
