@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy RemoteSigned -File "%~dp0payload\installer\Start-Windows.ps1"
if errorlevel 1 (
  echo.
  echo Installation stopped. Read the error above before trying again.
)
pause
