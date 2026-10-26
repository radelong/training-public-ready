@echo off
setlocal
set "PACKAGE_ROOT=%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%PACKAGE_ROOT%00_Click_To_Install_GDP\Start-GDP-Install.ps1"
if errorlevel 1 (
  echo.
  echo Installation stopped. Read the message above before trying again.
  pause
  exit /b 1
)
echo.
echo Installation finished. Read the acceptance steps in START_HERE_GDP_FRESH_INSTALL.md.
pause
