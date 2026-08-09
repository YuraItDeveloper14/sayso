# Build SaySo into a Windows application that needs no Python installed.
#
#   powershell -ExecutionPolicy Bypass -File tools\build_exe.ps1
#
# Produces dist\SaySo\SaySo.exe. One folder rather than one file on purpose:
# a single-file build re-extracts a few hundred megabytes of model runtime to a
# temp directory on every launch, which turns a two-second start into a minute.
#
# data\ and models\ are created next to the executable on first run, so notes,
# keys and downloaded voices survive an upgrade.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"

& $python tools\make_ico.py

& $python -m PyInstaller `
    --noconfirm --clean `
    --onedir `
    --name SaySo `
    --icon "static\sayso.ico" `
    --add-data "templates;templates" `
    --add-data "static;static" `
    --collect-all faster_whisper `
    --collect-all ctranslate2 `
    --collect-all onnxruntime `
    --collect-all piper `
    --collect-all tokenizers `
    --hidden-import win32com.client `
    --hidden-import pyttsx3.drivers `
    --hidden-import pyttsx3.drivers.sapi5 `
    run.py

$exe = Join-Path $root "dist\SaySo\SaySo.exe"
if (Test-Path $exe) {
    $size = (Get-ChildItem (Join-Path $root "dist\SaySo") -Recurse -File |
             Measure-Object Length -Sum).Sum / 1MB
    "built: $exe"
    "folder size: {0:N0} MB" -f $size
} else {
    "build failed - no executable produced"
    exit 1
}
