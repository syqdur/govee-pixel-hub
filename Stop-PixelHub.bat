@echo off
title Govee Pixel Hub Beenden
cd /d "%~dp0"

echo ========================================================
echo           Govee Gaming Pixel Hub Beenden
echo ========================================================
echo.

.\.venv-pixel\Scripts\python.exe start_spotify.py --stop

ping 127.0.0.1 -n 3 >nul
