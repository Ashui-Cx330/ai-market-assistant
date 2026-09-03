param([Parameter(Mandatory=$true)][ValidatePattern('^\d+\.\d+\.\d+$')][string]$Version)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

function Set-JsonVersion([string]$Path) {
  $value = [IO.File]::ReadAllText($Path, [Text.Encoding]::UTF8) | ConvertFrom-Json
  $value.version = $Version
  [IO.File]::WriteAllText($Path, ($value | ConvertTo-Json -Depth 20), (New-Object Text.UTF8Encoding($false)))
}

Set-JsonVersion (Join-Path $root 'version.json')
Set-JsonVersion (Join-Path $root 'frontend\package.json')
Set-JsonVersion (Join-Path $root 'desktop\package.json')
Set-JsonVersion (Join-Path $root 'desktop\package-lock.json')
$lockPath = Join-Path $root 'desktop\package-lock.json'
$lock = [IO.File]::ReadAllText($lockPath, [Text.Encoding]::UTF8) | ConvertFrom-Json
$lock.packages.''.version = $Version
[IO.File]::WriteAllText($lockPath, ($lock | ConvertTo-Json -Depth 100), (New-Object Text.UTF8Encoding($false)))
Write-Output "Versions synchronized to $Version"
