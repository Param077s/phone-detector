@echo off
rem ==========================================================================
rem  Vigil - the real Windows release build.
rem
rem     icon -> PyInstaller (vigil.spec) -> dist\Vigil\Vigil.exe
rem          -> Inno Setup -> dist\Vigil-Setup-<version>.exe
rem
rem  Run this ON WINDOWS from the project folder. First run creates the
rem  Python environment and downloads the AI components (several GB, once).
rem
rem  Needs:  Python 3.11+  (python.org - check "Add to PATH")
rem          Inno Setup 6  (https://jrsoftware.org/isinfo.php) for the
rem          installer step; without it you still get the portable app.
rem ==========================================================================
setlocal
cd /d "%~dp0"

set PY=venv\Scripts\python.exe
if not exist %PY% (
  echo * Creating Python environment...
  where py >nul 2>nul
  if not errorlevel 1 ( py -3 -m venv venv ) else ( python -m venv venv )
  if not exist %PY% (
    echo Could not create venv - install Python 3.11+ from python.org first.
    pause & exit /b 1
  )
)

echo * 1/4  Components (first run downloads several GB)...
%PY% -m pip install --upgrade pip -q
%PY% -m pip install -r requirements.txt -r requirements-desktop.txt pyinstaller pillow -q
if errorlevel 1 ( echo Dependency install failed. & pause & exit /b 1 )

echo * 2/4  App icon...
%PY% make_icon.py
if errorlevel 1 ( echo Icon build failed. & pause & exit /b 1 )

echo * 3/4  Vigil.exe  (PyInstaller - takes a few minutes)...
if exist dist\Vigil rmdir /s /q dist\Vigil
%PY% -m PyInstaller vigil.spec --noconfirm --log-level WARN
if not exist dist\Vigil\Vigil.exe ( echo PyInstaller did not produce dist\Vigil\Vigil.exe & pause & exit /b 1 )

echo * 4/4  Installer...
for /f "delims=" %%v in ('%PY% print_version.py') do set VER=%%v
set ISCC=iscc
where iscc >nul 2>nul
if errorlevel 1 (
  if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
  if exist "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe" set ISCC="%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
)
%ISCC% /DAppVersion=%VER% vigil-installer.iss >nul 2>nul
if exist dist\Vigil-Setup-%VER%.exe (
  echo.
  echo   OK  dist\Vigil-Setup-%VER%.exe   ^(upload this to the website^)
  echo   OK  dist\Vigil\Vigil.exe         ^(portable, runs in place^)
) else (
  echo.
  echo   OK  dist\Vigil\Vigil.exe  ^(portable app^)
  echo   Installer skipped - install Inno Setup 6 from jrsoftware.org
  echo   and run this script again to get Vigil-Setup-%VER%.exe.
)
echo.
pause
