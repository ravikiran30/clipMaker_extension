@echo off
setlocal enabledelayedexpansion
title ClipMaker - install on-demand launcher

set "HELPER=%~dp0helper"
set "HOSTBAT=%HELPER%\clipmaker_host.bat"
set "HOSTJSON=%HELPER%\com.clipmaker.launcher.json"

echo.
echo  Letting Chrome start the ClipMaker helper on demand.
echo.

rem --- locate python -------------------------------------------------------
set "PY="
for /f "delims=" %%i in ('where python.exe 2^>nul') do if not defined PY set "PY=%%i"
if not defined PY (
  echo  ERROR: python.exe not found on PATH.
  pause
  exit /b 1
)
echo  Python: %PY%

rem --- the host Chrome actually launches -----------------------------------
> "%HOSTBAT%" echo @echo off
>> "%HOSTBAT%" echo "%PY%" "%HELPER%\launcher.py"

rem --- extension ids allowed to talk to it ---------------------------------
rem  Unpacked ids are derived from the folder path, so both install locations
rem  are listed. Add your own with: install_ondemand.bat <your-extension-id>
set "EXTRA="
if not "%~1"=="" set "EXTRA=    \"chrome-extension://%~1/\",";

> "%HOSTJSON%" echo {
>> "%HOSTJSON%" echo   "name": "com.clipmaker.launcher",
>> "%HOSTJSON%" echo   "description": "Starts the ClipMaker helper server on demand",
>> "%HOSTJSON%" echo   "path": "%HOSTBAT:\=\\%",
>> "%HOSTJSON%" echo   "type": "stdio",
>> "%HOSTJSON%" echo   "allowed_origins": [
if defined EXTRA >> "%HOSTJSON%" echo %EXTRA%
>> "%HOSTJSON%" echo     "chrome-extension://ehpfggkgfcnapppfbbnbacggfcnioalg/",
>> "%HOSTJSON%" echo     "chrome-extension://icfoeonoljcblehokpmidddfblnnocfk/",
>> "%HOSTJSON%" echo     "chrome-extension://klcejjkajgiconcmccdbnncbefkcclok/",
>> "%HOSTJSON%" echo     "chrome-extension://lnelakgapnbhihengndhafgjcibjbkhf/"
>> "%HOSTJSON%" echo   ]
>> "%HOSTJSON%" echo }

rem --- register for Chrome and Edge (per-user, no admin needed) ------------
reg add "HKCU\Software\Google\Chrome\NativeMessagingHosts\com.clipmaker.launcher" /ve /t REG_SZ /d "%HOSTJSON%" /f >nul
reg add "HKCU\Software\Microsoft\Edge\NativeMessagingHosts\com.clipmaker.launcher" /ve /t REG_SZ /d "%HOSTJSON%" /f >nul

echo  Registered: com.clipmaker.launcher
echo  Host json : %HOSTJSON%
echo.
echo  Now reload the extension in chrome://extensions and open ClipMaker.
echo  If the helper is down, it will start itself within a few seconds.
echo.
echo  NOTE: if it still says the helper is not running, copy your extension ID
echo        from chrome://extensions and run:
echo            install_ondemand.bat YOUR_EXTENSION_ID
echo.
pause
