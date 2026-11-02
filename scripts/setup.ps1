param([switch]$SkipModels)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$env:PYTHONUTF8 = '1'

function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed: $Program (exit $LASTEXITCODE)" }
}

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw 'Install Python 3.12 and 3.11 with the Windows Python launcher first.'
}
if (-not (Test-Path -LiteralPath '.venv/Scripts/python.exe')) {
    Invoke-Checked 'py' @('-3.12', '-m', 'venv', '.venv')
}
if (-not (Test-Path -LiteralPath '.tts-venv/Scripts/python.exe')) {
    Invoke-Checked 'py' @('-3.11', '-m', 'venv', '.tts-venv')
}
Invoke-Checked '.venv/Scripts/python.exe' @('-m', 'pip', 'install', '-r', 'requirements.txt', '-r', 'requirements-desktop.txt')
Invoke-Checked '.tts-venv/Scripts/python.exe' @('-m', 'pip', 'install', '-r', 'requirements-engine.txt')
Invoke-Checked '.venv/Scripts/python.exe' @('scripts/prepare_install.py', '--presets-only')
if (-not $SkipModels) {
    Invoke-Checked '.tts-venv/Scripts/python.exe' @('scripts/prepare_install.py', '--models-only')
}
Write-Host 'Setup complete. Run .venv/Scripts/pythonw.exe desktop.py to start.'
