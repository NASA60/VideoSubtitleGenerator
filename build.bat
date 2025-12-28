@echo off
cd /d "%~dp0"

echo Cleaning up...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist *.spec del *.spec

echo.
echo ========================================================
echo Step 1: Installing Dependencies...
echo ========================================================
python -m pip install -r requirements.txt
python -m pip install pyinstaller

echo.
echo ========================================================
echo Step 2: Building Executable...
echo ========================================================
rem --noconsole: Hide console window
rem --collect-all vosk: Include Vosk
pyinstaller --noconsole --onefile --name "VideoSubtitleGen_v2" --collect-all vosk --hidden-import imageio_ffmpeg --hidden-import tkinterdnd2 main.py

echo.
echo ========================================================
echo Build Complete!
echo ========================================================
pause