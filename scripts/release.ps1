param([ValidatePattern('^\d+\.\d+\.\d+$')][string]$Version)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$productName = 'AI' + [char]0x884C + [char]0x60C5 + [char]0x52A9 + [char]0x624B
if (-not $env:GH_OWNER -or -not $env:GH_REPO) { throw 'Set GH_OWNER and GH_REPO first.' }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'Git is not installed.' }
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { throw 'Install GitHub CLI and run gh auth login.' }
& gh auth status
if ($LASTEXITCODE -ne 0) { throw 'GitHub CLI is not authenticated.' }
Set-Location $root
& git rev-parse --is-inside-work-tree | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'The current directory is not a Git repository.' }
$remoteText = & git remote get-url origin
$remote = if ($remoteText) { ([string]$remoteText).Trim() } else { '' }
if ($LASTEXITCODE -ne 0 -or -not $remote) { throw 'The Git repository has no origin remote.' }
if ($remote -notmatch [Regex]::Escape("$($env:GH_OWNER)/$($env:GH_REPO)")) { throw "origin does not match GH_OWNER/GH_REPO: $remote" }
if (& git status --porcelain) { throw 'The worktree must be clean before release.' }

$current = ([IO.File]::ReadAllText((Join-Path $root 'version.json'), [Text.Encoding]::UTF8) | ConvertFrom-Json).version
if (-not $Version) {
  $parts = $current.Split('.')
  $Version = "$($parts[0]).$($parts[1]).$([int]$parts[2] + 1)"
}
& (Join-Path $PSScriptRoot 'set-version.ps1') -Version $Version
& git add version.json frontend/package.json desktop/package.json desktop/package-lock.json
& git commit -m "release: v$Version"
if ($LASTEXITCODE -ne 0) { throw 'Version commit failed.' }
& (Join-Path $PSScriptRoot 'build_desktop.ps1')
& (Join-Path $PSScriptRoot 'release-check.ps1') -Version $Version
& git tag -a "v$Version" -m "$productName v$Version"
& (Join-Path $PSScriptRoot 'release-check.ps1') -Version $Version -RequireTag
& git push origin HEAD
& git push origin "v$Version"
$out = Join-Path $root 'outputs\desktop'
& gh release create "v$Version" --repo "$($env:GH_OWNER)/$($env:GH_REPO)" --title "$productName v$Version" --generate-notes `
  (Join-Path $out "AI-Market-Assistant-Setup-v$Version.exe") (Join-Path $out "AI-Market-Assistant-Setup-v$Version.exe.blockmap") (Join-Path $out 'latest.yml')
if ($LASTEXITCODE -ne 0) { throw 'GitHub Release publishing failed.' }
& (Join-Path $PSScriptRoot 'release-check.ps1') -Version $Version -RequirePublished
