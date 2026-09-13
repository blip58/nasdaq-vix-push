@echo off
rem Remove the scheduled task created by install_task.bat
schtasks /delete /tn "NasdaqVIXPush" /f
pause
