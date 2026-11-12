@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>nul
cd /d "%~dp0"
title X-Stage Song Studio PC Ready
echo.
echo ===============================================
echo    X-STAGE SONG STUDIO PC - READY TO RUN
echo    Local / Offline / No Dependency Downloads
echo ===============================================
echo.
if not exist "%~dp0.engine-ready-manifest.json" (
 echo ERROR: Ready-to-run manifest is missing.
 echo This is not the complete PC Ready ZIP. Extract the ENTIRE archive first.
 pause
 exit /b 1
)
if not exist "%~dp0.runtime\python\pythonw.exe" (
 echo ERROR: Bundled Python runtime is missing. Re-extract the Ready ZIP.
 pause
 exit /b 1
)
if not exist "%~dp0.runtime\tools\ffmpeg.exe" (
 echo ERROR: Bundled FFmpeg is missing. Re-extract the Ready ZIP.
 pause
 exit /b 1
)
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-Song-Studio-Ready.ps1"
if errorlevel 1 (
 echo.
 echo Startup failed. See start-ready.log in this folder.
 pause
 exit /b 1
)
exit /b 0
