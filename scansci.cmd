@echo off
call "%~dp0python.cmd" -m scansci_pdf.main %*
exit /b %errorlevel%
