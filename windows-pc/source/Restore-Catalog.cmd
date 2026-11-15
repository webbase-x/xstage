@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
echo Close X-Stage Karaoke before restoring a catalog backup.
where py >nul 2>nul
if errorlevel 1 (
  echo Python launcher is not installed. Use CPython 3.13 from the Windows build guide.
  pause
  exit /b 1
)
if "%~1"=="" (
  py -3 tools\restore_catalog.py
) else (
  py -3 tools\restore_catalog.py --database "%~1"
)
if errorlevel 1 echo Catalog restore did not complete. Read the message above.
pause
