@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>nul
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0Create-Desktop-Shortcut.ps1"
if errorlevel 1 (
  echo Could not create a desktop shortcut. Please extract the full Ready ZIP first.
  pause
  exit /b 1
)
echo Desktop shortcut created with the new X-Stage Song Studio PC icon.
pause
