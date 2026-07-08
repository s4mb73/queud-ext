# One-time setup on Windows RD session
# Run in PowerShell:  .\scripts\rd_setup.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

Write-Host "Installing Python dependencies..."
python -m pip install -r requirements.txt
python -m playwright install chrome

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example — edit credentials and Discord webhook."
}

New-Item -ItemType Directory -Force -Path "data" | Out-Null
Write-Host ""
Write-Host "Setup done. Configure .env then run:"
Write-Host "  rd_monitor.bat"
Write-Host "  or: python rd_monitor.py"
Write-Host ""
Write-Host "Optional exe build: .\scripts\build_rd_exe.ps1"