@echo off
setlocal
chcp 65001 >nul
call "%~dp0python.cmd" "%~dp0checkin.py" --import-session %*
exit /b %errorlevel%
