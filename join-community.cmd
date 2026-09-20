@echo off
setlocal
set "COMMUNITY_URL=https://skill.createsci.com/community"
echo %COMMUNITY_URL%
if /I "%~1"=="--url" exit /b 0
start "" "%COMMUNITY_URL%"
if errorlevel 1 (
  echo Could not open the browser. Open the link above manually.
  exit /b 1
)
exit /b 0
