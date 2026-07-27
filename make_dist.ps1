# make_dist.ps1
# Run from the project root to produce OrderTracker.zip
# Usage: .\make_dist.ps1

$ErrorActionPreference = "Stop"
$root   = Split-Path -Parent $MyInvocation.MyCommand.Path
$outZip = Join-Path $root "OrderTracker.zip"

# ── Remove old zip ────────────────────────────────────────────────────────────
if (Test-Path $outZip) {
    Remove-Item $outZip -Force
    Write-Host "Removed old OrderTracker.zip"
}

# ── Build a temporary staging folder ─────────────────────────────────────────
$staging = Join-Path $env:TEMP "OrderTracker_staging"
if (Test-Path $staging) { Remove-Item $staging -Recurse -Force }
New-Item -ItemType Directory -Path $staging | Out-Null

# ── Helper: copy a single file preserving relative path ──────────────────────
function Stage-File($src, $rel) {
    $dest = Join-Path $staging $rel
    $dir  = Split-Path $dest -Parent
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
    Copy-Item $src $dest -Force
}

# ── Root-level Python source files ───────────────────────────────────────────
foreach ($f in Get-ChildItem $root -File -Filter "*.py") {
    Stage-File $f.FullName $f.Name
}

# ── Batch/config/readme files ────────────────────────────────────────────────
foreach ($name in @("install.bat", "start.bat", "README_ERIC.txt")) {
    $src = Join-Path $root $name
    if (Test-Path $src) { Stage-File $src $name }
}

# ── webapp/backend ────────────────────────────────────────────────────────────
$backendSrc = Join-Path $root "webapp\backend"
$backendDst = Join-Path $staging "webapp\backend"
Copy-Item $backendSrc $backendDst -Recurse -Force
# Remove __pycache__ from backend
Get-ChildItem $backendDst -Recurse -Filter "__pycache__" -Directory | Remove-Item -Recurse -Force

# ── webapp/__init__.py ────────────────────────────────────────────────────────
$webappInit = Join-Path $root "webapp\__init__.py"
if (Test-Path $webappInit) { Stage-File $webappInit "webapp\__init__.py" }

# ── webapp/frontend/dist (pre-built React app) ────────────────────────────────
$distSrc = Join-Path $root "webapp\frontend\dist"
if (-not (Test-Path $distSrc)) {
    Write-Error "webapp/frontend/dist not found. Run 'npm run build' in webapp/frontend first."
}
$distDst = Join-Path $staging "webapp\frontend\dist"
Copy-Item $distSrc $distDst -Recurse -Force

# ── config.json / eric_orders.db — intentionally NOT bundled ─────────────────
# This zip is a code-only update package. It must never include config.json or
# eric_orders.db: on a machine that already has an install, extracting this
# zip with overwrite must never touch the receiving machine's own root_folder
# setting or live order data. The app's storage layer auto-migrates the schema
# (adds any new columns) the first time the updated code runs against an
# existing database, so an existing eric_orders.db does not need to be replaced.
# (A brand-new install still works: app.py creates a blank config.json/db on
# first run if they don't exist.)

# ── Zip the staging folder ────────────────────────────────────────────────────
Write-Host "Creating OrderTracker.zip..."
Compress-Archive -Path (Join-Path $staging "*") -DestinationPath $outZip -CompressionLevel Optimal
Remove-Item $staging -Recurse -Force

$size = (Get-Item $outZip).Length / 1MB
Write-Host ""
Write-Host "Done! OrderTracker.zip created ($([math]::Round($size,1)) MB)"
Write-Host ""
Write-Host "Contents to send to Eric:"
Write-Host "  install.bat   <- run once to set up Python + packages"
Write-Host "  start.bat     <- run daily to launch the app"
Write-Host "  README_ERIC.txt"
