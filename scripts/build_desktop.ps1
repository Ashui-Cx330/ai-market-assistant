$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$productName = 'AI' + [char]0x884C + [char]0x60C5 + [char]0x52A9 + [char]0x624B
$serviceName = $productName + [char]0x670D + [char]0x52A1
Set-Location $root

# GitHub release asset CDN can be unreachable on some mainland networks even
# while the GitHub API works.  electron-builder verifies every tool archive
# against its built-in SHA256, so this mirror changes transport only and a
# tampered file is rejected before execution.  An explicit environment value
# always takes precedence.
if (-not $env:ELECTRON_BUILDER_BINARIES_MIRROR) {
  $env:ELECTRON_BUILDER_BINARIES_MIRROR = 'https://npmmirror.com/mirrors/electron-builder-binaries/'
}

# electron-builder only emits fresh latest.yml when a publish provider exists.
# Resolve it automatically so direct builds cannot accidentally leave metadata
# from an older release in the output directory.
if (-not $env:GH_OWNER -or -not $env:GH_REPO) {
  $gh = Get-Command gh -ErrorAction SilentlyContinue
  $remote = (& git remote get-url origin 2>$null)
  if ($gh -and $remote -match 'github\.com[/:]([^/]+)/([^/]+?)(?:\.git)?$') {
    $env:GH_OWNER = $Matches[1]
    $env:GH_REPO = $Matches[2]
  } else {
    throw 'Cannot determine GH_OWNER/GH_REPO; refusing to generate potentially stale update metadata.'
  }
}

Write-Output '[1/5] Building Vue production assets'
npm --prefix frontend run build
if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }

Write-Output '[2/5] Installing backend build dependencies'
& "$root\.venv\Scripts\python.exe" -m pip install -r backend\requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw 'Backend build dependency installation failed' }

Write-Output '[3/5] Freezing hidden backend service'
& "$root\.venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --noconsole --name $serviceName `
  --distpath "$root\backend-dist" --workpath "$root\work\pyinstaller" --specpath "$root\work" `
  --collect-binaries xgboost --collect-data xgboost --hidden-import xgboost.sklearn `
  --collect-binaries lightgbm --collect-data lightgbm --hidden-import lightgbm.sklearn `
  --add-data "$root\version.json;." `
  "$root\backend\desktop_server.py"
if ($LASTEXITCODE -ne 0) { throw 'Backend executable build failed' }

Write-Output '[4/5] Installing desktop build dependencies'
Push-Location "$root\desktop"
npm install
if ($LASTEXITCODE -ne 0) { Pop-Location; throw 'Desktop dependency installation failed' }

Write-Output '[5/5] Building NSIS installer and update metadata'
npm run dist
if ($LASTEXITCODE -ne 0) { Pop-Location; throw 'Desktop installer build failed' }
Pop-Location
Write-Output "Installer created under $root\outputs\desktop"
