param(
    [ValidateRange(1, 65535)]
    [int]$Port = 8001
)

$ErrorActionPreference = 'Stop'
$originalPath = $env:Path
Push-Location $PSScriptRoot
try {
    $python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python)) {
        throw 'Missing .venv. Run: python -m venv .venv; .\.venv\Scripts\python.exe -m pip install -r backend/requirements.lock.txt'
    }
    $listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
    if ($listener) {
        throw "Port $Port is already in use. Existing processes were not stopped. Retry with: .\start-local.ps1 -Port 8002"
    }
    $node = Get-Command node.exe -ErrorAction SilentlyContinue
    $candidates = @()
    if ($node) { $candidates += $node.Source }
    if ($env:NVM_HOME -and (Test-Path -LiteralPath $env:NVM_HOME)) {
        $candidates += Get-ChildItem -LiteralPath $env:NVM_HOME -Directory -Filter 'v22.*' | Sort-Object { [version]$_.Name.Substring(1) } -Descending | ForEach-Object { Join-Path $_.FullName 'node.exe' }
    }
    $selected = $null
    foreach ($candidate in $candidates) {
        if (-not (Test-Path -LiteralPath $candidate)) { continue }
        $version = [version]((& $candidate --version).Trim().TrimStart('v'))
        if ($version.Major -eq 22 -and $version.Minor -ge 12) { $selected = $candidate; break }
    }
    if (-not $selected) { throw 'Node 22.12+ (22.x) is required. Install it with nvm before running this script.' }
    $env:Path = "$(Split-Path -Parent $selected);$originalPath"
    Write-Host "Using $(& $selected --version). Global nvm selection is unchanged."
    Push-Location (Join-Path $PSScriptRoot 'frontend')
    try {
        if (-not (Test-Path -LiteralPath 'node_modules')) {
            & npm.cmd ci
            if ($LASTEXITCODE -ne 0) { throw 'npm ci failed.' }
        }
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
    } finally { Pop-Location }
    Write-Host "Open http://127.0.0.1:$Port - no login or database required. Press Ctrl+C to stop."
    & $python -B -X utf8 server.py --local --port $Port
    if ($LASTEXITCODE -ne 0) { throw 'Local backend stopped with an error.' }
} finally {
    $env:Path = $originalPath
    Pop-Location
}
