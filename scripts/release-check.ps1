param(
  [string]$Version,
  [switch]$RequireTag,
  [switch]$RequirePublished
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$productName = 'AI' + [char]0x884C + [char]0x60C5 + [char]0x52A9 + [char]0x624B
function Read-Utf8Json([string]$Path) { return [IO.File]::ReadAllText($Path, [Text.Encoding]::UTF8) | ConvertFrom-Json }
function Read-LockVersion([string]$Path) {
  $text = [IO.File]::ReadAllText($Path, [Text.Encoding]::UTF8)
  $match = [Text.RegularExpressions.Regex]::Match($text, '"version"\s*:\s*"([^"]+)"')
  if (-not $match.Success) { throw "No version in lockfile: $Path" }
  return $match.Groups[1].Value
}
if (-not $Version) { $Version = (Read-Utf8Json (Join-Path $root 'version.json')).version }
$tag = "v$Version"
$owner = $env:GH_OWNER
$repo = $env:GH_REPO
if (-not $owner -or -not $repo) { throw 'GH_OWNER and GH_REPO are required.' }

$versions = @(
  (Read-Utf8Json (Join-Path $root 'version.json')).version,
  (Read-Utf8Json (Join-Path $root 'desktop\package.json')).version,
  (Read-Utf8Json (Join-Path $root 'frontend\package.json')).version,
  (Read-LockVersion (Join-Path $root 'desktop\package-lock.json')),
  (Read-LockVersion (Join-Path $root 'frontend\package-lock.json'))
)
if (@($versions | Where-Object { $_ -ne $Version }).Count -gt 0) { throw "Version mismatch: $($versions -join ', ')" }

$out = Join-Path $root 'outputs\desktop'
$installer = Join-Path $out "AI-Market-Assistant-Setup-v$Version.exe"
$blockmap = "$installer.blockmap"
$latest = Join-Path $out 'latest.yml'
foreach ($file in @($installer, $blockmap, $latest)) { if (-not (Test-Path -LiteralPath $file)) { throw "Missing release file: $file" } }
$yaml = [IO.File]::ReadAllText($latest, [Text.Encoding]::UTF8)
foreach ($required in @("version: $Version", 'files:', 'path:', 'sha512:', 'releaseDate:')) { if (-not $yaml.Contains($required)) { throw "latest.yml mismatch: $required" } }
$expectedPath = "AI-Market-Assistant-Setup-v$Version.exe"
if (-not $yaml.Contains($expectedPath)) { throw "latest.yml installer path mismatch: $expectedPath" }
$shaAlgorithm = [Security.Cryptography.SHA512]::Create()
$stream = [IO.File]::OpenRead($installer)
try { $sha512 = [Convert]::ToBase64String($shaAlgorithm.ComputeHash($stream)) }
finally { $stream.Dispose(); $shaAlgorithm.Dispose() }
if (-not $yaml.Contains($sha512)) { throw 'latest.yml SHA512 does not match the installer.' }
$installerSize = (Get-Item -LiteralPath $installer).Length
if (-not $yaml.Contains("size: $installerSize")) { throw 'latest.yml size does not match the installer.' }
$blockmapStream = [IO.File]::OpenRead($blockmap)
$gzip = New-Object IO.Compression.GZipStream($blockmapStream, [IO.Compression.CompressionMode]::Decompress)
$reader = New-Object IO.StreamReader($gzip, [Text.Encoding]::UTF8)
try { $blockmapJson = $reader.ReadToEnd() | ConvertFrom-Json }
finally { $reader.Dispose(); $gzip.Dispose(); $blockmapStream.Dispose() }
$mappedSize = 0
foreach ($file in $blockmapJson.files) { foreach ($size in $file.sizes) { $mappedSize += [long]$size } }
if ($blockmapJson.version -ne '2' -or $mappedSize -ne $installerSize) { throw 'Blockmap content does not match the installer size.' }
$appUpdate = Join-Path $out 'win-unpacked\resources\app-update.yml'
if (-not (Test-Path -LiteralPath $appUpdate)) { throw 'Packaged app-update.yml is missing.' }
$appUpdateText = [IO.File]::ReadAllText($appUpdate, [Text.Encoding]::UTF8)
if (-not $appUpdateText.Contains("owner: $owner") -or -not $appUpdateText.Contains("repo: $repo")) { throw 'Packaged updater repository does not match GH_OWNER/GH_REPO.' }

$shortcutPath = Join-Path ([Environment]::GetFolderPath('Desktop')) "$productName.lnk"
if (-not (Test-Path -LiteralPath $shortcutPath)) { Write-Warning 'Desktop shortcut is absent; first install will create it.' }
$userData = Join-Path $env:APPDATA $productName
$installRoot = Join-Path $env:LOCALAPPDATA 'Programs'
if (-not [IO.Path]::GetFullPath($userData).StartsWith([IO.Path]::GetFullPath($env:APPDATA))) { throw 'User data path is invalid.' }
if ([IO.Path]::GetFullPath($userData).StartsWith([IO.Path]::GetFullPath($installRoot))) { throw 'User data path must be outside the install directory.' }

if ($RequireTag) {
  & git rev-parse --verify "refs/tags/$tag" | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "Git tag $tag is missing." }
}
if ($RequirePublished) {
  if (-not (Get-Command gh -ErrorAction SilentlyContinue)) { throw 'GitHub CLI is not installed.' }
  $release = & gh release view $tag --repo "$owner/$repo" --json tagName,assets | ConvertFrom-Json
  if ($LASTEXITCODE -ne 0 -or $release.tagName -ne $tag) { throw "GitHub Release $tag is missing." }
  $names = @($release.assets | ForEach-Object { $_.name })
  foreach ($name in @("AI-Market-Assistant-Setup-v$Version.exe", "AI-Market-Assistant-Setup-v$Version.exe.blockmap", 'latest.yml')) {
    if ($names -notcontains $name) { throw "GitHub Release asset is missing: $name" }
  }
}
Write-Output "Release check passed: $owner/$repo $tag"
Write-Output "  installer: $installer"
Write-Output "  latest:    $latest"
Write-Output "  blockmap:  $blockmap"
Write-Output "  SHA512:    $sha512"
