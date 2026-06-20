@echo off
setlocal
cd /d "%~dp0"
title audio2pdf local server
python web_app.py
if errorlevel 1 (
  echo.
  echo audio2pdf could not start. Check the message above.
  pause
)
endlocal
