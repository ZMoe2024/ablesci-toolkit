@echo off
call "%~dp0python.cmd" -m pip install -r "%~dp0requirements-scansci.txt"
exit /b %errorlevel%
