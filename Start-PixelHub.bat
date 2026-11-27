@echo off
title Govee Pixel Hub
cd /d "%~dp0"

echo ========================================================
echo               Govee Gaming Pixel Hub
echo ========================================================
echo.

.\.venv-pixel\Scripts\python.exe start_spotify.py

if errorlevel 1 (
    echo.
    echo [FEHLER] Hub konnte nicht gestartet werden.
    echo Logdatei pruefen: spotify-output\worker.log
    echo.
    pause
) else (
    ping 127.0.0.1 -n 3 >nul
)
