@echo off
rem Register a Windows scheduled task: run one check every 10 minutes.
rem Push happens only when VIX > threshold, so frequent checks are harmless.
setlocal
set TASKNAME=NasdaqVIXPush
set MINUTES=10

set PYEXE=
for /f "delims=" %%i in ('where python 2^>nul') do (
    if not defined PYEXE set PYEXE=%%i
)
if not defined PYEXE (
    echo [ERROR] python not found in PATH. Install Python first.
    pause
    exit /b 1
)

schtasks /create /f /tn "%TASKNAME%" /sc minute /mo %MINUTES% /tr "\"%PYEXE%\" \"%~dp0main.py\" run"
if %errorlevel%==0 (
    echo.
    echo [OK] Task "%TASKNAME%" created: runs every %MINUTES% minutes.
    echo      Remove it later with remove_task.bat
) else (
    echo [ERROR] Failed to create task. Try running this script as Administrator.
)
pause
