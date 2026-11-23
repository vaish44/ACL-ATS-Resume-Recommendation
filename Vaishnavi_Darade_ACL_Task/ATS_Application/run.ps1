$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot
$Port = 1114
$Url = "http://127.0.0.1:$Port"

function Find-Python {
    foreach ($cmd in @("py", "python", "python3")) {
        if (Get-Command $cmd -ErrorAction SilentlyContinue) {
            $extra = @()
            if ($cmd -eq "py") { $extra = @("-3") }
            & $cmd @extra -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" 2>$null
            if ($LASTEXITCODE -eq 0) { return @($cmd) + $extra }
        }
    }
    return $null
}

$python = Find-Python
if (-not $python) {
    Write-Host "Python 3.9+ was not found. Install it from https://www.python.org/downloads/ (tick 'Add to PATH')." -ForegroundColor Red
    exit 1
}

if (-not (Test-Path "venv\Scripts\python.exe")) {
    Write-Host "Creating virtual environment..." -ForegroundColor Cyan
    $exe = $python[0]; $rest = @($python | Select-Object -Skip 1)
    & $exe @rest -m venv venv
    if ($LASTEXITCODE -ne 0) { Write-Host "Could not create the virtual environment." -ForegroundColor Red; exit 1 }
}
$venvPython = Join-Path $PSScriptRoot "venv\Scripts\python.exe"

$coreImports = "import flask, flask_sqlalchemy, google.genai, openai, bs4, docx, olefile, PIL, pypdf, pytesseract"
$pipFlags = @("--prefer-binary", "--only-binary=PyMuPDF", "--disable-pip-version-check")
$marker = "venv\.installed"

& $venvPython -c $coreImports 2>$null
$needInstall = ($LASTEXITCODE -ne 0) -or -not (Test-Path $marker) -or ((Get-Item "requirements.txt").LastWriteTime -gt (Get-Item $marker -ErrorAction SilentlyContinue).LastWriteTime)
if ($needInstall) {
    Write-Host "Installing required libraries..." -ForegroundColor Cyan
    & $venvPython -m pip install --upgrade pip --quiet --disable-pip-version-check
    & $venvPython -m pip install @pipFlags -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Full install failed. Installing packages one by one..." -ForegroundColor Yellow
        foreach ($pkg in Get-Content "requirements.txt") {
            $pkg = $pkg.Trim()
            if (-not $pkg) { continue }
            & $venvPython -m pip install @pipFlags --quiet $pkg
            if ($LASTEXITCODE -ne 0) { Write-Host "WARNING: could not install $pkg" -ForegroundColor Yellow }
        }
    }
    New-Item -ItemType File -Path $marker -Force | Out-Null
}

& $venvPython -c $coreImports 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Some required libraries could not be installed. Details:" -ForegroundColor Red
    & $venvPython -c $coreImports
    Write-Host "Check your internet connection, then delete the 'venv' folder and run run.bat again." -ForegroundColor Red
    exit 1
}
& $venvPython -c "import fitz" 2>$null
if ($LASTEXITCODE -ne 0) { Write-Host "Note: PyMuPDF is not available. PDFs are read with pypdf; scanned PDFs need an AI key." -ForegroundColor Yellow }

if (-not (Select-String -Path "env_app.py" -Pattern '(GEMINI|OPENAI)_API_KEY\s*=\s*"[^"]+"' -Quiet -ErrorAction SilentlyContinue)) {
    Write-Host "Tip: set GEMINI_API_KEY or OPENAI_API_KEY in env_app.py to enable AI evaluation." -ForegroundColor Yellow
}

$busy = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($busy) {
    Write-Host "Port $Port is already in use. Opening $Url" -ForegroundColor Yellow
    Start-Process $Url
    exit 0
}

Start-Job -ScriptBlock {
    param($u)
    for ($i = 0; $i -lt 30; $i++) {
        try { Invoke-WebRequest -Uri "$u/login" -UseBasicParsing -TimeoutSec 2 | Out-Null; Start-Process $u; break } catch { Start-Sleep -Seconds 1 }
    }
} -ArgumentList $Url | Out-Null

Write-Host "Starting RR - Resume Recommendation on $Url  (Ctrl+C to stop)" -ForegroundColor Green
& $venvPython app.py
