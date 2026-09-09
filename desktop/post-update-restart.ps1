param([Parameter(Mandatory=$true)][string]$Executable)
$ErrorActionPreference = 'SilentlyContinue'
Start-Sleep -Seconds 3
if (Test-Path -LiteralPath $Executable) {
  Start-Process -FilePath $Executable -ArgumentList '--post-update-restart'
}
