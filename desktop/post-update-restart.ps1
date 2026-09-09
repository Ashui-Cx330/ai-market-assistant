param(
  [Parameter(Mandatory=$true)][string]$Executable,
  [int]$SourceProcessId = 0
)
$ErrorActionPreference = 'SilentlyContinue'
# app.quit() can take a few seconds to release Electron's single-instance lock.
# Starting the replacement on a fixed timer races that lock on slower machines,
# so wait for the exact parent process to disappear before relaunching.
if ($SourceProcessId -gt 0) {
  Wait-Process -Id $SourceProcessId -Timeout 30 -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 2
if (Test-Path -LiteralPath $Executable) {
  Start-Process -FilePath $Executable -ArgumentList '--post-update-restart'
}
