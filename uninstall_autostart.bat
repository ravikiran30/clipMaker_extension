@echo off
setlocal
title ClipMaker - remove autostart

set "VBS=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\ClipMaker Helper.vbs"

if exist "%VBS%" (
  del "%VBS%"
  echo  Removed the startup entry.
) else (
  echo  No startup entry found.
)

echo  Stopping any running helper...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:"127.0.0.1:5005 .*LISTENING"') do (
  taskkill /F /PID %%p >nul 2>&1
  echo  Stopped process %%p
)

echo.
echo  Done. ClipMaker will no longer start at login.
echo  You can still run it by hand with start_helper.bat
echo.
pause
