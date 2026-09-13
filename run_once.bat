@echo off
rem Run one check now (push only if VIX above threshold)
cd /d "%~dp0"
python main.py run
pause
