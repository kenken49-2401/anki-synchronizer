@echo off
setlocal
cd /d "%~dp0"
if "%~1"=="" goto open_web
if /i "%~1"=="--command" if /i "%~2"=="open" goto open_web
where uv >nul 2>nul
if errorlevel 1 (
  echo Install uv from https://docs.astral.sh/uv/getting-started/installation/ then run this launcher again.
  pause
  exit /b 1
)
uv run --no-project --python 3.12 python "%~dp0scripts\desktop.py" %*
set "atlas_exit=%errorlevel%"
if not "%atlas_exit%"=="0" pause
exit /b %atlas_exit%

:open_web
start "" "https://kenken49-2401.github.io/anki-synchronizer/"
if errorlevel 1 (
  echo Could not open your browser. Open this address manually:
  echo https://kenken49-2401.github.io/anki-synchronizer/
  pause
  exit /b 1
)
exit /b 0
