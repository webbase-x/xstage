@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>nul
cd /d "%~dp0"
title X-Stage Song Studio PC - First Run Setup
echo.
echo  ==============================================
echo    X-STAGE SONG STUDIO - PC SOURCE LAUNCHER
echo  ==============================================
echo.
echo [1/3] Checking bundled source and runtime...
if not exist "%~dp0engine.py" (
  echo ERROR: engine.py not found. Extract ALL files from ZIP first.
  pause
  exit /b 1
)
if not exist "%~dp0studio\index.html" (
  echo ERROR: studio UI not found. Extract ALL files from ZIP first.
  pause
  exit /b 1
)
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-Song-Studio.ps1"
if errorlevel 1 (
  echo.
  echo Startup failed. Check the error above or setup.log.
  pause
  exit /b 1
)
exit /b 0
