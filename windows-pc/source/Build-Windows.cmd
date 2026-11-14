@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Build-Source.ps1"
set "BUILD_RESULT=%ERRORLEVEL%"
if not "%BUILD_RESULT%"=="0" (
  echo Build failed. Read the error above. Installation has not started.
) else (
  echo Build complete. Run dist\XStageKaraoke\Install-to-D.cmd to install.
)
pause
exit /b %BUILD_RESULT%
