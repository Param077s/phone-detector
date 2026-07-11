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
if not exist "venv\" (
  echo   First-time setup. This downloads ~2 GB and takes 5-15 minutes.
  echo   It happens ONCE. Please keep this window open.
  echo.
  python -m venv venv
  venv\Scripts\python -m pip install --upgrade pip >nul 2>nul
  echo   Installing components...
  venv\Scripts\pip install -r requirements.txt
  if errorlevel 1 (
    echo   Setup failed. Check your internet and try again.
    pause
    exit /b 1
  )
  echo   Preparing the detector...
  venv\Scripts\python -c "from ultralytics import YOLO; YOLO('yolo11m.pt')" >nul 2>nul
  echo   Setup complete!
  echo.
)

REM --- 3) Launch + open browser ---
echo   Vigil is starting at http://localhost:8000
echo   Keep this window open while using Vigil. Close it to stop.
echo.
start "" http://localhost:8000
venv\Scripts\python -m uvicorn app:app --host 127.0.0.1 --port 8000
pause
