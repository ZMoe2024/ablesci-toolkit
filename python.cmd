@echo off
if exist "%~dp0.venv\Scripts\python.exe" goto venv
where py >nul 2>&1
if not errorlevel 1 goto launcher
python.exe %*
exit /b %errorlevel%
:launcher
py -3 %*
exit /b %errorlevel%
:venv
"%~dp0.venv\Scripts\python.exe" %*
exit /b %errorlevel%
