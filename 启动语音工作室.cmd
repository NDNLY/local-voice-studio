@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
if exist "%~dp0声匣.exe" (
    start "" "%~dp0声匣.exe"
    exit /b
)
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0desktop.py"
if errorlevel 1 pause
