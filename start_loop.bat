@echo off
rem Start resident monitoring in a minimized window (checks every N minutes)
cd /d "%~dp0"
start "VIX Monitor" /min python main.py loop
echo Resident monitor started (minimized window). Close that window to stop.
timeout /t 3 >nul
