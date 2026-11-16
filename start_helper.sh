#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/helper"

PY=${PYTHON:-python3}
command -v "$PY" >/dev/null || { echo "python3 not found"; exit 1; }

"$PY" -c "import flask" 2>/dev/null || "$PY" -m pip install -r requirements.txt
"$PY" -c "import yt_dlp" 2>/dev/null || "$PY" -m pip install -U yt-dlp

exec "$PY" server.py
