@echo off
setlocal
cd /d "%~dp0"
title Zero-Cloud ERP Engine on a Laptop (Local AI + Python)

echo ===============================================================================
echo    ZERO-CLOUD ERP ENGINE ON A LAPTOP (Local AI + Python)
echo    100%% Offline - Zero Cloud Fees - Standard Laptop CPU Friendly
echo ===============================================================================
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"

if errorlevel 1 (
    echo.
    echo [ERROR] Setup encountered an issue.
    pause
)

endlocal
