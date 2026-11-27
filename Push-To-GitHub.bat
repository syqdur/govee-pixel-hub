@echo off
cd /d "%~dp0"
echo Pushing to https://github.com/syqdur/govee-pixel-hub.git ...
git branch -M main
git push origin main
echo.
pause
