@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "TEMP=%~dp0temp"
set "TMP=%~dp0temp"
set "PYTHONPYCACHEPREFIX=%~dp0cache\pycache"
"%~dp0venv\Scripts\python.exe" -B "%~dp0tools\diagnostics.py"
pause
