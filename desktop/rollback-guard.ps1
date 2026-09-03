param(
  [Parameter(Mandatory=$true)][string]$StateFile,
  [Parameter(Mandatory=$true)][string]$LogFile,
  [int]$TimeoutSeconds = 300,
  [string]$AllowedInstallDir,
  [string]$AllowedBackupRoot,
  [switch]$SkipProcessKill,
  [switch]$SkipRestart
)

$ErrorActionPreference = 'Stop'
function Write-UpdateLog([string]$Message) {
  Add-Content -LiteralPath $LogFile -Value ((Get-Date).ToUniversalTime().ToString('o') + ' ' + $Message) -Encoding UTF8
}

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline) {
  Start-Sleep -Seconds 2
  if (-not (Test-Path -LiteralPath $StateFile)) { continue }
  try { $state = [IO.File]::ReadAllText($StateFile, [Text.Encoding]::UTF8) | ConvertFrom-Json } catch { continue }
  if ($state.updateStatus -eq 'stable' -and $state.healthCheck -eq 'passed') {
    if ($state.backupPath -and (Test-Path -LiteralPath $state.backupPath)) {
      Remove-Item -LiteralPath $state.backupPath -Recurse -Force
    }
    Write-UpdateLog 'update confirmed healthy; rollback guard finished'
    exit 0
  }
  if ($state.updateStatus -eq 'rolled-back') { exit 0 }
}

$state = [IO.File]::ReadAllText($StateFile, [Text.Encoding]::UTF8) | ConvertFrom-Json
$installDir = [IO.Path]::GetFullPath([string]$state.installDir).TrimEnd('\')
$backupDir = [IO.Path]::GetFullPath([string]$state.backupPath).TrimEnd('\')
$allowedInstallRoot = [IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'Programs')).TrimEnd('\')
$allowedInstall = if ($AllowedInstallDir) { [IO.Path]::GetFullPath($AllowedInstallDir).TrimEnd('\') } else { $installDir }
$allowedBackupRoot = if ($AllowedBackupRoot) { [IO.Path]::GetFullPath($AllowedBackupRoot).TrimEnd('\') } else { [IO.Path]::GetFullPath((Join-Path (Split-Path -Parent $StateFile) 'update-backups')).TrimEnd('\') }
if ($installDir -ne $allowedInstall -or (-not $AllowedInstallDir -and -not $installDir.StartsWith($allowedInstallRoot, [StringComparison]::OrdinalIgnoreCase)) -or -not $backupDir.StartsWith($allowedBackupRoot, [StringComparison]::OrdinalIgnoreCase) -or -not (Test-Path -LiteralPath $backupDir)) {
  Write-UpdateLog 'rollback refused: validated install or backup path mismatch'
  exit 2
}

Write-UpdateLog ('health check timed out; rolling back ' + $state.pendingVersion + ' to ' + $state.previousVersion)
if (-not $SkipProcessKill) { & taskkill.exe /IM ([string]$state.executableName) /T /F 2>$null | Out-Null }
Start-Sleep -Seconds 2
& robocopy.exe $backupDir $installDir /MIR /R:2 /W:1 /NFL /NDL /NJH /NJS | Out-Null
if ($LASTEXITCODE -ge 8) { Write-UpdateLog ('rollback copy failed with code ' + $LASTEXITCODE); exit 3 }

$bad = @($state.badVersions)
if ($state.pendingVersion -and $bad -notcontains $state.pendingVersion) { $bad += $state.pendingVersion }
$failedVersion = $state.pendingVersion
$stableVersion = $state.previousVersion
$state.currentVersion = $stableVersion
$state.previousVersion = $null
$state.pendingVersion = $null
$state.updateStatus = 'rolled-back'
$state.healthCheck = 'failed'
$state | Add-Member -NotePropertyName installResult -NotePropertyValue 'failed-and-rolled-back' -Force
$state.launchAttempts = 0
$state | Add-Member -NotePropertyName rollbackCount -NotePropertyValue ([int]$state.rollbackCount + 1) -Force
$state.badVersions = $bad
$state | Add-Member -NotePropertyName rollbackMessage -NotePropertyValue 'startup-health-check-failed' -Force
$state | Add-Member -NotePropertyName lastUpdateTime -NotePropertyValue ((Get-Date).ToUniversalTime().ToString('o')) -Force
[IO.File]::WriteAllText($StateFile, ($state | ConvertTo-Json -Depth 8), (New-Object Text.UTF8Encoding($false)))
Write-UpdateLog ('rollback succeeded: bad=' + $failedVersion + ', stable=' + $stableVersion)
$oldExecutable = Join-Path $installDir ([string]$state.executableName)
if (-not $SkipRestart -and (Test-Path -LiteralPath $oldExecutable)) { Start-Process -FilePath $oldExecutable }
