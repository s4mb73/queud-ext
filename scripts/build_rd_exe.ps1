# Build QueudAIO.exe for Windows RD (onedir — copy whole dist\QueudAIO folder)
# Requires: pip install pyinstaller
# TMPT_SOLVER=headless still needs: playwright install chrome  (once per machine)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

python -m pip install pyinstaller --quiet

Write-Host "Building QueudAIO..."
python -m PyInstaller `
    --noconfirm `
    --clean `
    --onedir `
    --name QueudAIO `
    --console `
    --paths "$Root" `
    --hidden-import wreq `
    --hidden-import playwright `
    --hidden-import queud_aio.cli `
    --collect-submodules queud_aio `
    "$Root\rd_monitor.py"

$Out = Join-Path $Root "dist\QueudAIO"
Write-Host ""
Write-Host "Built: $Out\QueudAIO.exe"
Write-Host ""
Write-Host 'Deploy to RD - copy this entire folder:'
Write-Host '  dist\QueudAIO\'
Write-Host 'Plus alongside the exe:'
Write-Host '  .env'
Write-Host '  data\proxies.txt, data\discord_webhook, profiles from CSV'
Write-Host ''
Write-Host 'On the RD machine (only if TMPT_SOLVER uses headless):'
Write-Host '  playwright install chrome'