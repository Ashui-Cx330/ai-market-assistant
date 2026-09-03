@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\release.ps1" %*
if errorlevel 1 (
  echo.
  echo Release failed. Existing installed versions were not modified.
  exit /b 1
)
echo.
echo Release completed successfully.
