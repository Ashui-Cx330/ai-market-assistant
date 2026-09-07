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
$restartAfter = (Get-Date).AddSeconds(15)
$restartAttempted = $false
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
  # NSIS --force-run is normally sufficient, but on some Windows profiles the
  # installer exits without launching the new executable.  The independent
  # guard provides a second, bounded restart path after the installed file is
  # confirmed to be the pending version.
  if (-not $SkipRestart -and -not $restartAttempted -and (Get-Date) -ge $restartAfter -and $state.updateStatus -eq 'pending-health-check') {
    try {
      $candidateInstallDir = [IO.Path]::GetFullPath([string]$state.installDir).TrimEnd('\')
      $expectedInstallDir = if ($AllowedInstallDir) { [IO.Path]::GetFullPath($AllowedInstallDir).TrimEnd('\') } else { $candidateInstallDir }
      $candidateExecutable = Join-Path $candidateInstallDir ([string]$state.executableName)
      if ($candidateInstallDir -eq $expectedInstallDir -and (Test-Path -LiteralPath $candidateExecutable)) {
        $installedVersion = (Get-Item -LiteralPath $candidateExecutable).VersionInfo.ProductVersion
        if ($installedVersion -eq $state.pendingVersion -or $installedVersion.StartsWith(([string]$state.pendingVersion) + '.')) {
          Start-Process -FilePath $candidateExecutable
          $restartAttempted = $true
          Write-UpdateLog ('rollback guard launched pending version ' + $state.pendingVersion)
        }
      }
    } catch {
      Write-UpdateLog ('pending version restart deferred: ' + $_.Exception.Message)
    }
  }
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
if (-not $SkipProcessKill) {
  # A launch failure may mean there is no remaining process. taskkill reports
  # that normal condition on stderr; it must not abort the rollback.
  $savedErrorAction = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  & taskkill.exe /IM ([string]$state.executableName) /T /F 2>$null | Out-Null
  if ($state.backendExecutableName) {
    & taskkill.exe /IM ([string]$state.backendExecutableName) /T /F 2>$null | Out-Null
  }
  $ErrorActionPreference = $savedErrorAction
}
Start-Sleep -Seconds 2
& robocopy.exe $backupDir $installDir /MIR /IS /IT /R:2 /W:1 /NFL /NDL /NJH /NJS | Out-Null
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
