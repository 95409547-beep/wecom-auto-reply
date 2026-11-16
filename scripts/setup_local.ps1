$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path $PSScriptRoot -Parent)

if (Test-Path -LiteralPath '.\runtime\python.exe') {
    $setupPython = (Resolve-Path -LiteralPath '.\runtime\python.exe').Path
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $setupPython = & py -3.12 -c 'import sys; print(sys.executable)'
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 is required.' }
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $setupPython = (Get-Command python).Source
} else {
    throw 'Install Python 3.12 with Tcl/Tk support, then run this script again.'
}

& $setupPython -c 'import sys, tkinter; assert sys.version_info[:2] == (3, 12), "Python 3.12 is required"'
if ($LASTEXITCODE -ne 0) { throw 'Python version or Tcl/Tk check failed.' }

if (-not (Test-Path -LiteralPath '.\.venv\Scripts\python.exe')) {
    & $setupPython -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the local Python environment.' }
}

$venvPython = (Resolve-Path -LiteralPath '.\.venv\Scripts\python.exe').Path
& $venvPython -m pip install 'torch==2.14.0' --index-url https://download.pytorch.org/whl/cpu --no-deps
if ($LASTEXITCODE -ne 0) { throw 'CPU PyTorch installation failed.' }
& $venvPython -m pip install -r requirements-local.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& $venvPython scripts/prepare_model.py
if ($LASTEXITCODE -ne 0) { throw 'Local embedding model preparation failed.' }
& $venvPython -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Dependency validation failed.' }

if (-not (Test-Path -LiteralPath '.env')) {
    Copy-Item -LiteralPath '.env.example' -Destination '.env'
}
Write-Host 'Ready. Open the local launcher and configure the model API in Settings.'
