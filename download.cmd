@echo off
setlocal
chcp 65001 >nul
if "%~1"=="" (
  echo Usage: download.cmd REQUEST_ID
  exit /b 2
)
call "%~dp0python.cmd" "%~dp0assist_download.py" --assist-id "%~1" --wait-seconds 3600
exit /b %errorlevel%
