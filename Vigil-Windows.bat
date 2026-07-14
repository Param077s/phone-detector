@echo off
REM ==========================================================================
REM   V I G I L  -  double-click to start.  (Windows)
REM   First run sets everything up. Every run after: it just opens.
REM ==========================================================================
cd /d "%~dp0"
echo ==========================================
echo             Vigil  -  starting
echo ==========================================
echo.

REM --- 1) Python 3 required ---
where python >nul 2>nul
if errorlevel 1 (
  echo   Vigil needs Python 3 - a free, one-time install.
  echo   Opening the download page...
  start "" https://www.python.org/downloads/
  echo.
  echo   During install, TICK "Add Python to PATH". Then run Vigil again.
  echo.
  pause
  exit /b 1
)

REM --- 2) First-time setup ---
REM The ".vigil-installed" marker is written only after a SUCCESSFUL install,
REM so an interrupted setup (window closed early) resumes cleanly next time
REM instead of leaving a half-built venv that reinstalls or fails to run.
if not exist ".vigil-installed" (
  echo   First-time setup. This downloads ~2 GB and takes 5-15 minutes.
  echo   It happens ONCE. Keep this window open until you see "Setup complete".
  echo.
  if exist "venv\" rmdir /s /q venv
  python -m venv venv
  venv\Scripts\python -m pip install --upgrade pip >nul 2>nul
  echo   Installing components...
  venv\Scripts\pip install -r requirements.txt
  if errorlevel 1 (
    echo   Setup didn't finish ^(connection interrupted?^). Just run Vigil again to resume.
    if exist "venv\" rmdir /s /q venv
    pause
    exit /b 1
  )
  echo   Preparing the detector...
  venv\Scripts\python -c "from ultralytics import YOLO; YOLO('yolo11m.pt')" >nul 2>nul
  echo done> ".vigil-installed"
  echo   Setup complete!
  echo.
)

REM --- 3) Launch + open browser ---
echo   Vigil is starting at http://localhost:8000
echo   On a phone (same WiFi): use this PC's IP, e.g. http://YOUR-PC-IP:8000 (run "ipconfig" to find it)
echo   Keep this window open while using Vigil. Close it to stop.
echo.
start "" http://localhost:8000
venv\Scripts\python -m uvicorn app:app --host 0.0.0.0 --port 8000
pause
