@echo off
setlocal
set "PY=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if exist "%PY%" goto run
where python >nul 2>nul
if errorlevel 1 (
 echo Python 3.12 with tkinter is required.
 pause
 exit /b 1
)
set "PY=python"
:run
"%PY%" "%~dp0desktop.py"
if errorlevel 1 pause
