@echo off
title ClipMaker helper
cd /d "%~dp0helper"

where python >nul 2>&1
if errorlevel 1 (
  echo Python was not found on PATH. Install Python 3.9+ and try again.
  pause
  exit /b 1
)

python -c "import flask" >nul 2>&1
if errorlevel 1 (
  echo Installing Python dependencies...
  python -m pip install -r requirements.txt
)

python -c "import yt_dlp" >nul 2>&1
if errorlevel 1 (
  python -m pip install -U yt-dlp
)

python server.py
echo.
echo Helper stopped.
pause
