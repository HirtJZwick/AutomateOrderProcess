<#
.SYNOPSIS
    Wrapper to run a Python script inside the Eric Orchestrator venv.

.DESCRIPTION
    Invoked from Power Automate Desktop's "Run application" action.
    - Activates (implicitly) the project venv by calling its python.exe directly
    - Forwards all arguments to the target script
    - Captures and surfaces non-zero exit codes
    - Forces UTF-8 stdout so German characters / customer names survive

.PARAMETER ScriptPath
    Full path to the Python script to execute.

.PARAMETER ScriptArgs
    Any remaining arguments are forwarded to the Python script.

.EXAMPLE
    .\run_python.ps1 -ScriptPath .\extract.py -ScriptArgs "C:\Temp\input.json"
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$ScriptPath,

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ScriptArgs
)

# --- Configuration ---------------------------------------------------------
$ProjectRoot   = "C:\Users\Hirtj\Projects\EricAutomateExcelSheet"
$VenvPython    = Join-Path $ProjectRoot "zwick_venv_ericproject\Scripts\python.exe"
$LogFile       = Join-Path $ProjectRoot "logs\run_python.log"

# --- Ensure log folder exists ---------------------------------------------
$LogDir = Split-Path $LogFile -Parent
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

function Write-Log {
    param([string]$Message)
    $timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    Add-Content -Path $LogFile -Value "[$timestamp] $Message"
}

# --- Force UTF-8 everywhere -----------------------------------------------
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING     = "utf-8"
$env:PYTHONUTF8           = "1"

# --- Sanity checks ---------------------------------------------------------
if (-not (Test-Path $VenvPython)) {
    $msg = "ERROR: venv python not found at $VenvPython"
    Write-Log $msg
    Write-Error $msg
    exit 2
}

if (-not (Test-Path $ScriptPath)) {
    $msg = "ERROR: script not found at $ScriptPath"
    Write-Log $msg
    Write-Error $msg
    exit 3
}

# --- Execute ---------------------------------------------------------------
Write-Log "Running: $VenvPython $ScriptPath $($ScriptArgs -join ' ')"

# Use the call operator (&) so paths with spaces work cleanly
& $VenvPython $ScriptPath @ScriptArgs
$exitCode = $LASTEXITCODE

Write-Log "Python exit code: $exitCode"

# Surface Python's exit code back to PAD
exit $exitCode