$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$testRoot = Join-Path $root 'work\rollback-test'
$install = Join-Path $testRoot 'install\app'
$backupRoot = Join-Path $testRoot 'data\update-backups'
$backup = Join-Path $backupRoot 'v0.3.0'
$stateFile = Join-Path $testRoot 'data\update-state.json'
$logFile = Join-Path $testRoot 'data\update.log'
if (Test-Path -LiteralPath $testRoot) { Remove-Item -LiteralPath $testRoot -Recurse -Force }
New-Item -ItemType Directory -Path $install,$backup -Force | Out-Null
Set-Content -LiteralPath (Join-Path $install 'version.txt') -Value '0.3.1-broken' -Encoding UTF8
Set-Content -LiteralPath (Join-Path $install 'new-only.txt') -Value 'remove-on-rollback' -Encoding UTF8
Set-Content -LiteralPath (Join-Path $backup 'version.txt') -Value '0.3.0-stable' -Encoding UTF8
@{
  currentVersion='0.3.0'; previousVersion='0.3.0'; pendingVersion='0.3.1';
  updateStatus='pending-health-check'; healthCheck='waiting'; launchAttempts=1;
  backupPath=$backup; installDir=$install; executableName='app.exe'; badVersions=@()
} | ConvertTo-Json | ForEach-Object { [IO.File]::WriteAllText($stateFile, $_, (New-Object Text.UTF8Encoding($false))) }

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'rollback-guard.ps1') `
  -StateFile $stateFile -LogFile $logFile -TimeoutSeconds 2 -AllowedInstallDir $install `
  -AllowedBackupRoot $backupRoot -SkipProcessKill -SkipRestart
if ($LASTEXITCODE -ne 0) { throw "Rollback guard failed with exit code $LASTEXITCODE" }
$result = [IO.File]::ReadAllText($stateFile, [Text.Encoding]::UTF8) | ConvertFrom-Json
if ($result.updateStatus -ne 'rolled-back' -or $result.currentVersion -ne '0.3.0') { throw 'Rollback state was not persisted.' }
if ((Get-Content -Raw (Join-Path $install 'version.txt')).Trim() -ne '0.3.0-stable') { throw 'Stable files were not restored.' }
if (Test-Path -LiteralPath (Join-Path $install 'new-only.txt')) { throw 'Broken-version files were not removed.' }
if ($result.badVersions -notcontains '0.3.1') { throw 'Bad release was not blocked.' }
Remove-Item -LiteralPath $testRoot -Recurse -Force
Write-Output 'PASS health-timeout/restore-old-version/remove-broken-files/mark-bad-release/persist-state'
