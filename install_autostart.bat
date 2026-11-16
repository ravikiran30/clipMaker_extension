@echo off
setlocal
title ClipMaker - install autostart

set "HELPER=%~dp0helper"
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "VBS=%STARTUP%\ClipMaker Helper.vbs"

echo.
echo  Installing the ClipMaker helper as a silent startup task.
echo  Helper folder: %HELPER%
echo.

rem --- find pythonw.exe (python without a console window) -------------------
set "PYW="
for /f "delims=" %%i in ('where pythonw.exe 2^>nul') do if not defined PYW set "PYW=%%i"
if not defined PYW (
  for /f "delims=" %%i in ('where python.exe 2^>nul') do if not defined PYW set "PYW=%%~dpipythonw.exe"
)
if not defined PYW (
  echo  ERROR: could not find pythonw.exe. Is Python installed and on PATH?
  pause
  exit /b 1
)
echo  Using: %PYW%

rem --- make sure dependencies exist before we hide the window ---------------
"%PYW:pythonw.exe=python.exe%" -c "import flask" >nul 2>&1
if errorlevel 1 (
  echo  Installing Python dependencies...
  "%PYW:pythonw.exe=python.exe%" -m pip install -r "%HELPER%\requirements.txt"
)

rem --- write the launcher into the Startup folder ---------------------------
> "%VBS%" echo ' ClipMaker - starts the local helper with no console window.
>> "%VBS%" echo Set sh = CreateObject("WScript.Shell")
>> "%VBS%" echo sh.CurrentDirectory = "%HELPER%"
>> "%VBS%" echo sh.Run """%PYW%"" ""%HELPER%\server.py""", 0, False

if exist "%VBS%" (
  echo  Installed: %VBS%
) else (
  echo  ERROR: could not write to the Startup folder.
  pause
  exit /b 1
)

rem --- start it now so you don't have to reboot -----------------------------
echo  Starting the helper now...
cscript //nologo "%VBS%" >nul 2>&1

echo.
echo  Done. The helper now starts automatically when you log in,
echo  with no terminal window. Log: %HELPER%\helper.log
echo.
echo  To undo: run uninstall_autostart.bat
echo.
pause
