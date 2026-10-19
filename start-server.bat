@echo off
echo Starting ATNI ResIST server...

:: Change to the project directory
cd /d "%~dp0"

:: Start the browser after a short delay (in background)
start "" cmd /c "timeout /t 2 /nobreak >nul && start http://localhost:8000/search"

:: Start the server
python -m uvicorn src.main:app --host 127.0.0.1 --port 8000

pause
