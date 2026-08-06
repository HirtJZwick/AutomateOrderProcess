# make_dist.ps1
# Builds the folder that gets handed to Eric.
#
# Run from the project root:
#     .\make_dist.ps1                   # folder + zip, empty database
#     .\make_dist.ps1 -IncludeDatabase  # ship eric_orders.db as well
#     .\make_dist.ps1 -NoZip            # folder only
#
# Output:
#     dist\OrderTracker\      <- give this folder to Eric
#     dist\OrderTracker.zip   <- the same thing, zipped for e-mail/Teams
#
# The React frontend is rebuilt automatically (needs Node + npm). Everything
# else is a straight copy, so the distributed app matches what was tested here.

[CmdletBinding()]
param(
    [switch]$IncludeDatabase,
    [switch]$NoZip,
    [switch]$SkipFrontendBuild
)

$ErrorActionPreference = "Stop"
$root    = Split-Path -Parent $MyInvocation.MyCommand.Path
$distDir = Join-Path $root "dist"
$outDir  = Join-Path $distDir "OrderTracker"
$outZip  = Join-Path $distDir "OrderTracker.zip"

function Write-Step($text) { Write-Host "==> $text" -ForegroundColor Cyan }

# -- 1. Rebuild the frontend so dist/ matches the current sources -------------
$frontend = Join-Path $root "webapp\frontend"
if ($SkipFrontendBuild) {
    Write-Step "Skipping frontend build (-SkipFrontendBuild)"
} else {
    Write-Step "Building the React frontend..."
    Push-Location $frontend
    try {
        if (-not (Test-Path (Join-Path $frontend "node_modules"))) {
            Write-Host "    node_modules missing - running 'npm install' first..."
            & npm install
            if ($LASTEXITCODE -ne 0) { throw "npm install failed." }
        }
        & npm run build
        if ($LASTEXITCODE -ne 0) { throw "npm run build failed." }
    } finally {
        Pop-Location
    }
}

$frontendDist = Join-Path $frontend "dist"
if (-not (Test-Path (Join-Path $frontendDist "index.html"))) {
    throw "webapp\frontend\dist\index.html not found - the frontend build produced no output."
}

# -- 2. Start from a clean output folder --------------------------------------
Write-Step "Preparing $outDir"
if (Test-Path $outDir) { Remove-Item $outDir -Recurse -Force }
New-Item -ItemType Directory -Path $outDir -Force | Out-Null

function Copy-Into($src, $relative) {
    $dest = Join-Path $outDir $relative
    $dir  = Split-Path $dest -Parent
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    Copy-Item $src $dest -Force
}

# -- 3. Core Python modules ---------------------------------------------------
# Only the modules the running application imports. Developer-only utilities
# (list_sharepoint_folders.py) and the test suite are deliberately excluded.
Write-Step "Copying application code"
$coreModules = @(
    "ingest.py",
    "storage.py",
    "excel_sync.py",
    "power_automate.py",
    "extract_checklist.py",
    "extract_order_pdf.py"
)
foreach ($name in $coreModules) {
    $src = Join-Path $root $name
    if (-not (Test-Path $src)) { throw "Required module '$name' is missing from the project root." }
    Copy-Into $src $name
}

# -- 4. The webapp package (backend code + built frontend) --------------------
Copy-Into (Join-Path $root "webapp\__init__.py") "webapp\__init__.py"
foreach ($name in @("__init__.py", "app.py", "derive.py", "settings.py")) {
    Copy-Into (Join-Path $root "webapp\backend\$name") "webapp\backend\$name"
}

$distDest = Join-Path $outDir "webapp\frontend\dist"
New-Item -ItemType Directory -Path $distDest -Force | Out-Null
Copy-Item (Join-Path $frontendDist "*") $distDest -Recurse -Force

# -- 5. Launcher scripts, dependency list and instructions --------------------
Write-Step "Copying launcher scripts and instructions"
foreach ($name in @("install.bat", "start.bat", "requirements.txt", "README_ERIC.txt")) {
    $src = Join-Path $root $name
    if (-not (Test-Path $src)) { throw "Required file '$name' is missing from the project root." }
    Copy-Into $src $name
}

# -- 6. config.json - ship a blank one ----------------------------------------
# Eric points the app at his own synced order folder from the in-app Settings
# panel. The flow URLs fall back to the defaults baked into power_automate.py
# when left empty, and excel_root falls back to the scan folder.
Write-Step "Writing a blank config.json"
$blankConfig = [ordered]@{
    root_folder                 = ""
    db_path                     = "eric_orders.db"
    oc_contacts_flow_url        = ""
    shipping_date_flow_url      = ""
    excel_root                  = ""
    sharepoint_site_url         = ""
    sharepoint_root_path        = ""
    flow_result_timeout_seconds = 90
}
$json = $blankConfig | ConvertTo-Json
[System.IO.File]::WriteAllText(
    (Join-Path $outDir "config.json"),
    $json,
    (New-Object System.Text.UTF8Encoding($false))
)

# -- 7. Database --------------------------------------------------------------
# Without -IncludeDatabase the app starts empty: storage.init_db() creates the
# file and tables on first run. With it, the recipient gets every order already
# ingested and only needs one "Scan new orders" pass to re-point the stored
# folder paths at their own machine.
$db = Join-Path $root "eric_orders.db"
if ($IncludeDatabase) {
    if (-not (Test-Path $db)) { throw "-IncludeDatabase was given but eric_orders.db does not exist." }
    Write-Step "Including eric_orders.db"
    Copy-Into $db "eric_orders.db"
    $py = Join-Path $root "zwick_venv_ericproject\Scripts\python.exe"
    if (Test-Path $py) {
        $orders = & $py -c "import sqlite3,sys; print(sqlite3.connect(sys.argv[1]).execute('select count(*) from orders').fetchone()[0])" $db
        Write-Host "    database contains $orders orders"
    }
} else {
    Write-Step "Shipping without a database (starts empty on first run)"
}

# -- 8. Safety net: no stray caches -------------------------------------------
Get-ChildItem $outDir -Recurse -Force -Directory -Filter "__pycache__" |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

# -- 9. Zip it up as well -----------------------------------------------------
if (-not $NoZip) {
    Write-Step "Creating OrderTracker.zip"
    if (Test-Path $outZip) { Remove-Item $outZip -Force }
    Compress-Archive -Path $outDir -DestinationPath $outZip -CompressionLevel Optimal
}

# -- 10. Summary --------------------------------------------------------------
$fileCount = (Get-ChildItem $outDir -Recurse -File).Count
$sizeMb    = [math]::Round(((Get-ChildItem $outDir -Recurse -File | Measure-Object Length -Sum).Sum / 1MB), 1)

Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host "  Folder : $outDir  ($fileCount files, $sizeMb MB)"
if (-not $NoZip) {
    Write-Host "  Zip    : $outZip  ($([math]::Round((Get-Item $outZip).Length / 1MB, 1)) MB)"
}
Write-Host ""
Write-Host "Hand over the folder (or the zip). Eric then runs:"
Write-Host "  1. install.bat   - once, sets up Python and the packages"
Write-Host "  2. start.bat     - opens the app in the browser"
Write-Host "  README_ERIC.txt explains the rest."
Write-Host ""
