<#
.SYNOPSIS
    Builds the FRIDAY OS Windows installer end-to-end: PyInstaller exe,
    then the Inno Setup installer wrapping it.

.DESCRIPTION
    Run this from the project root, inside an activated venv with
    requirements.txt installed, on Windows. It:
      1. Reads the version from app/_version.py (single source of truth
         — see that file's docstring for why).
      2. Runs PyInstaller against installer/friday_os.spec.
      3. Locates ISCC.exe (Inno Setup's compiler) and runs it against
         installer/friday_os.iss, passing the version through.
      4. Reports the final installer path.

    Each step is verified before moving to the next -- a partial/broken
    PyInstaller output will not silently get wrapped into an installer
    that looks fine but doesn't actually run.

.EXAMPLE
    .\scripts\build_installer.ps1
#>

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $ProjectRoot

function Write-Step($msg) {
    Write-Host ""
    Write-Host "==> $msg" -ForegroundColor Cyan
}

function Fail($msg) {
    Write-Host "ERROR: $msg" -ForegroundColor Red
    exit 1
}

# --- 1. Prerequisite checks -------------------------------------------------

Write-Step "Checking prerequisites"

if (-not $env:VIRTUAL_ENV) {
    Fail "No virtual environment is active. Run: .venv\Scripts\Activate.ps1"
}

try {
    python -c "import PyInstaller" 2>$null
    if ($LASTEXITCODE -ne 0) { throw }
} catch {
    Fail "PyInstaller isn't installed in this venv. Run: pip install -r requirements.txt"
}

# Inno Setup doesn't reliably put ISCC.exe on PATH -- check common
# install locations, but also allow an explicit override via
# $env:ISCC_PATH for anyone who installed it somewhere nonstandard.
$IsccCandidates = @(
    $env:ISCC_PATH,
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { $_ -and (Test-Path $_) }

if (-not $IsccCandidates) {
    Fail "Inno Setup's ISCC.exe was not found. Install Inno Setup 6.3+ from https://jrsoftware.org/isdl.php, or set `$env:ISCC_PATH to its location."
}
$Iscc = $IsccCandidates[0]
Write-Host "Found ISCC at: $Iscc"

# --- 2. Read version from the single source of truth ------------------------

Write-Step "Reading app version"

$VersionLine = Get-Content "app\_version.py" | Select-String '__version__\s*=\s*"([^"]+)"'
if (-not $VersionLine) {
    Fail "Could not parse __version__ out of app\_version.py"
}
$AppVersion = $VersionLine.Matches[0].Groups[1].Value
Write-Host "Building version: $AppVersion"

# --- 3. PyInstaller -----------------------------------------------------------

Write-Step "Running PyInstaller (this takes a few minutes)"

if (Test-Path "dist\FridayOS") { Remove-Item -Recurse -Force "dist\FridayOS" }
if (Test-Path "build") { Remove-Item -Recurse -Force "build" }

pyinstaller installer\friday_os.spec --noconfirm
if ($LASTEXITCODE -ne 0) { Fail "PyInstaller build failed (see output above)." }

$ExePath = "dist\FridayOS\FridayOS.exe"
if (-not (Test-Path $ExePath)) {
    Fail "PyInstaller reported success but $ExePath doesn't exist. Something's wrong with installer\friday_os.spec."
}
Write-Host "PyInstaller output verified: $ExePath"

# --- 4. Inno Setup -------------------------------------------------------------

Write-Step "Running Inno Setup"

if (-not (Test-Path "installer\output")) {
    New-Item -ItemType Directory -Path "installer\output" | Out-Null
}

& $Iscc "installer\friday_os.iss" "/DAppVersion=$AppVersion"
if ($LASTEXITCODE -ne 0) { Fail "Inno Setup compilation failed (see output above)." }

$InstallerPath = "installer\output\FridayOS-Setup-$AppVersion.exe"
if (-not (Test-Path $InstallerPath)) {
    Fail "Inno Setup reported success but $InstallerPath doesn't exist."
}

# --- 5. Done ---------------------------------------------------------------------

Write-Step "Build complete"
Write-Host "Installer: $(Resolve-Path $InstallerPath)" -ForegroundColor Green
Write-Host ""
Write-Host "This installer has NOT been code-signed. Running it on another" -ForegroundColor Yellow
Write-Host "machine will trigger a Windows SmartScreen warning until you" -ForegroundColor Yellow
Write-Host "obtain a code-signing certificate -- see docs/architecture/INSTALLER_GUIDE.md." -ForegroundColor Yellow
