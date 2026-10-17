@echo off
setlocal
cd /d "%~dp0"
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
