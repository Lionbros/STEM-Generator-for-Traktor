@echo off
echo ===========================================
echo      Starting StemGen Local
echo ===========================================

:: Check for venv
if not exist venv (
    echo Error: venv not found. Please run setup.bat first.
    pause
    exit /b
)

:: Start Backend
echo Starting Backend Server...
start "StemGen Backend" cmd /k "venv\Scripts\activate && uvicorn backend.main:app --reload --port 8000"

:: Start Frontend
echo Starting Frontend...
cd frontend
start "StemGen Frontend" cmd /k "npm run dev"

:: Open Browser (wait a bit for vite)
timeout /t 5 >nul
start http://localhost:5173

echo.
echo Application is running. Close the terminal windows to stop.
