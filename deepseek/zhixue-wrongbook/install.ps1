# One-shot bootstrap: works on a machine with NO Python installed.
#
# Order (each step needs no admin rights and no installer):
#   1. python / py launcher on PATH
#   2. Python bundled with AI tools (WorkBuddy / ZCode binaries)
#   3. Nothing found -> download uv (single exe, ~12MB) into the user
#      profile, install a managed CPython, create the venv, then hand
#      over to install.py (--no-venv, deps go straight into that venv).
#
# Usage: double-click install.bat, or: install.bat --config --account ... --password ...

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

function Find-Python {
    $c = Get-Command python -ErrorAction SilentlyContinue
    if ($c -and (Test-Path $c.Source)) { return $c.Source }
    $c = Get-Command py -ErrorAction SilentlyContinue
    if ($c) { return "py" }
    $cands = @(
        (Join-Path $env:USERPROFILE ".workbuddy-ai\binaries\python\current\python.exe"),
        (Join-Path $env:USERPROFILE ".zcode\binaries\python\current\python.exe")
    )
    foreach ($base in @(
            (Join-Path $env:USERPROFILE ".workbuddy-ai\binaries\python\versions"),
            (Join-Path $env:USERPROFILE ".zcode\binaries\python\versions"))) {
        if (Test-Path $base) {
            Get-ChildItem $base -Directory | Sort-Object Name -Descending |
                ForEach-Object { $cands += (Join-Path $_.FullName "python.exe") }
        }
    }
    foreach ($c in $cands) { if (Test-Path $c) { return $c } }
    return $null
}

function Get-Uv {
    # Return uv.exe path; download from GitHub if missing (no admin needed)
    $bin = Join-Path $env:USERPROFILE ".zhixue-wrongbook\bin"
    $uv = Join-Path $bin "uv.exe"
    if (Test-Path $uv) { return $uv }
    Write-Host "==> No Python found. Downloading portable runtime manager uv (one-time, ~12MB)"
    New-Item -ItemType Directory -Force $bin | Out-Null
    $zip = Join-Path $bin "uv.zip"
    Invoke-WebRequest "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip" `
        -OutFile $zip -UseBasicParsing
    $tmp = Join-Path $bin "uv_extract"
    Expand-Archive $zip -DestinationPath $tmp -Force
    Move-Item (Join-Path $tmp "uv.exe") $uv -Force
    Remove-Item $tmp, $zip -Recurse -Force
    return $uv
}

$py = Find-Python

if (-not $py) {
    $uv = Get-Uv
    & $uv python install 3.12
    & $uv venv (Join-Path $root ".venv") --python 3.12 --seed
    $py = Join-Path $root ".venv\Scripts\python.exe"
    # venv is seeded with pip; install.py --no-venv installs deps right into it
    & $py (Join-Path $root "install.py") --no-venv @args
} else {
    Write-Host "==> Using Python: $py"
    & $py (Join-Path $root "install.py") @args
}
