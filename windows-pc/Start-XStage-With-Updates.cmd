@echo off
setlocal
cd /d "%~dp0"
rem Open the existing installed X-Stage application, then check verified updates.
rem Adjust -AppPath when your installed executable is elsewhere.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-XStage-With-Updates.ps1" %*
if errorlevel 1 (
  echo.
  echo X-Stage startup failed. Check the executable path above.
  pause
  exit /b 1
)
exit /b 0
