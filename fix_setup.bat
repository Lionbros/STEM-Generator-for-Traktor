@echo off
echo ===========================================
echo      Fixing StemGen Installation
echo ===========================================

call venv\Scripts\activate

echo.
echo [1/2] Re-installing PyTorch with CUDA support...
echo This ensures we get the GPU-accelerated version.
pip uninstall -y torch torchaudio
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124
:: Using cu124 (CUDA 12.4) as it is current stable for many. Or cu121. Let's stick to cu121 to be safe or check user driver? 
:: Safest is cu121 for broader compatibility.
pip install torch torchaudio --force-reinstall --index-url https://download.pytorch.org/whl/cu121

echo.
echo [2/2] Checking Dependencies...
where sox >nul 2>nul
if %errorlevel% neq 0 (
    echo [WARNING] SoX is NOT found in your PATH!
    echo StemGen requires SoX to function.
    echo.
    echo Please download SoX from: https://sourceforge.net/projects/sox/files/sox/
    echo And add its folder to your System PATH.
    echo.
) else (
    echo [OK] SoX is found.
)

echo.
echo Done. Please restart run.bat.
pause
