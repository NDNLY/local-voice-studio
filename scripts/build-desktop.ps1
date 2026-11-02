$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$env:PYTHONUTF8 = '1'
& '.venv/Scripts/python.exe' -m PyInstaller --noconfirm --onefile --windowed --name '声匣' --icon 'assets/shengxia-rabbit.ico' --distpath 'dist' --workpath 'build/pyinstaller' --specpath 'build' --exclude-module PyQt5 --exclude-module PyQt6 --exclude-module PySide2 --exclude-module PySide6 'desktop.py'
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }
Write-Host 'Built dist/声匣.exe. Close the app, then copy it to the project root to run.'
