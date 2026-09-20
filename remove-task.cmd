@echo off
powershell.exe -NoProfile -File "%~dp0remove-task.ps1"
exit /b %errorlevel%
