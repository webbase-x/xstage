@echo off
setlocal
cd /d "%~dp0"
echo ======================================
echo   X-Stage Android TV/Tablet Debug APK
echo   Verified Gradle 8.11.1
echo ======================================
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Build-Debug-APK.ps1"
if errorlevel 1 (
  echo.
  echo BUILD FAILED - check the error printed above.
  pause
  exit /b 1
)
echo.
echo APK created successfully in app\build\outputs\apk\debug
pause
