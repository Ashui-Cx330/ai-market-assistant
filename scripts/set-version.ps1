param([Parameter(Mandatory=$true)][ValidatePattern('^\d+\.\d+\.\d+$')][string]$Version)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

function Set-JsonVersion([string]$Path, [int]$Count = 1) {
  $content = [IO.File]::ReadAllText($Path, [Text.Encoding]::UTF8)
  $pattern = '("version"\s*:\s*")[^"]+("\s*[,}])'
  $matches = [Text.RegularExpressions.Regex]::Matches($content, $pattern)
  if ($matches.Count -lt $Count) { throw "Expected $Count version fields in $Path" }
  $updated = $content
  for ($index = $Count - 1; $index -ge 0; $index--) {
    $match = $matches[$index]
    $replacement = $match.Groups[1].Value + $Version + $match.Groups[2].Value
    $updated = $updated.Substring(0, $match.Index) + $replacement + $updated.Substring($match.Index + $match.Length)
  }
  [IO.File]::WriteAllText($Path, $updated, (New-Object Text.UTF8Encoding($false)))
}

Set-JsonVersion (Join-Path $root 'version.json')
Set-JsonVersion (Join-Path $root 'frontend\package.json')
Set-JsonVersion (Join-Path $root 'desktop\package.json')
Set-JsonVersion (Join-Path $root 'desktop\package-lock.json') 2
Write-Output "Versions synchronized to $Version"
