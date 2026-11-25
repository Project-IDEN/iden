@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0local.ps1" %*
exit /b %ERRORLEVEL%
