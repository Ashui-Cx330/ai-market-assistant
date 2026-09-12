param(
  [ValidatePattern('^\d+\.\d+\.\d+$')][string]$Version,
  [switch]$RequireTag,
  [switch]$RequirePublished
)
$ErrorActionPreference='Stop'
& (Join-Path $PSScriptRoot 'scripts\release-check.ps1') -Version $Version -RequireTag:$RequireTag -RequirePublished:$RequirePublished
exit $LASTEXITCODE
