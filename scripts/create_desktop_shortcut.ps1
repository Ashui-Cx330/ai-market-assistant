$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$electron = Join-Path $projectRoot 'desktop\node_modules\electron\dist\electron.exe'
$desktopFolder = [Environment]::GetFolderPath('Desktop')
$appName = -join (@(0x0041, 0x0049, 0x884C, 0x60C5, 0x52A9, 0x624B) | ForEach-Object { [char]$_ })
$shortcutPath = Join-Path $desktopFolder ($appName + '.lnk')
$icon = Join-Path $projectRoot 'desktop\assets\app-icon.ico'

if (-not (Test-Path -LiteralPath $electron)) { throw 'Electron is not installed. Run npm install in the desktop directory first.' }

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $electron
$shortcut.Arguments = [char]34 + (Join-Path $projectRoot 'desktop') + [char]34
$shortcut.WorkingDirectory = $projectRoot
$shortcut.IconLocation = $icon + ',0'
$shortcut.Description = 'AI market analysis desktop application'
$shortcut.Save()
Write-Output $shortcutPath
