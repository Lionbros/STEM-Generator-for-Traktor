@echo off
echo ===========================================
echo      StemGen Windows Setup
echo ===========================================

echo.
echo [1/3] Setting up Python Environment...
if not exist venv (
    python -m venv venv
)
call venv\Scripts\activate
pip install -r requirements.txt

echo.
echo [2/3] Setting up Frontend...
cd frontend
if not exist node_modules (
    call npm install
    call npm install -D tailwindcss@3.4.17 postcss autoprefixer
)

echo.
echo [3/3] Done!
pause
