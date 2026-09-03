@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [Trading AI] Creating Python environment...
  py -3.12 -m venv .venv
  if errorlevel 1 goto :error
)
call ".venv\Scripts\activate.bat"
python -c "import fastapi,uvicorn,httpx" >nul 2>nul
if errorlevel 1 (
  echo [Trading AI] Installing backend dependencies...
  python -m pip install -r backend\requirements.txt
  if errorlevel 1 goto :error
)
if not exist "frontend\dist\index.html" (
  echo [Trading AI] Building frontend...
  pushd frontend
  call npm install
  if errorlevel 1 goto :error
  call npm run build
  if errorlevel 1 goto :error
  popd
)
echo [Trading AI] Opening http://127.0.0.1:8000
start "" http://127.0.0.1:8000
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
goto :eof
:error
echo [Trading AI] Startup failed. Review the message above.
pause
exit /b 1

