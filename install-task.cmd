@echo off
powershell.exe -NoProfile -File "%~dp0install-task.ps1" %*
exit /b %errorlevel%
