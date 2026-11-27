@echo off
setlocal
cd /d "%~dp0"
title Govee Pixel Hub - Installation

echo ============================================================
echo        Govee H6630 Pixel Hub - 1-Click Setup
echo ============================================================
echo.

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [FEHLER] Python wurde nicht gefunden!
    echo Bitte installiere Python 3.10 oder neuer von https://www.python.org/
    echo und setze das Haekchen bei "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

echo [1/3] Erstelle Python Virtual Environment (.venv-pixel)...
if not exist ".venv-pixel" (
    python -m venv .venv-pixel
)

echo [2/3] Installiere Abhaengigkeiten (bleak, Pillow, winrt, psutil)...
".venv-pixel\Scripts\python.exe" -m pip install --upgrade pip --quiet
".venv-pixel\Scripts\python.exe" -m pip install -r requirements.txt --quiet

echo [3/3] Pruefe Konfiguration...
if not exist "display_hub.json" (
    copy display_hub.example.json display_hub.json >nul
    echo       Standard-Konfiguration erstellt (display_hub.json).
)

echo.
echo ============================================================
echo    Installation erfolgreich abgeschlossen!
echo    Starte den Hub mit einem Doppelklick auf:
echo    Start-PixelHub.bat
echo ============================================================
echo.
pause
