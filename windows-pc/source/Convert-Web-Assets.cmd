@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "XSTAGE_PY=python"
if exist ".build-venv\Scripts\python.exe" set "XSTAGE_PY=.build-venv\Scripts\python.exe"
echo X-Stage Karaoke v0.9.46 - Offline Web Asset Generator
echo Convert NCN/MIDI to AAC M4A and Lyrics JSON locally.
echo No Google credentials required, no files are uploaded.
echo.
set /p "XSTAGE_INPUT=Folder containing MID/LYR/CUR: "
set /p "XSTAGE_SF2=SoundFont SF2 file: "
set /p "XSTAGE_OUTPUT=Destination folder [public]: "
if not defined XSTAGE_OUTPUT set "XSTAGE_OUTPUT=public"
if not defined XSTAGE_INPUT goto :incomplete
if not defined XSTAGE_SF2 goto :incomplete
"%XSTAGE_PY%" tools\web_asset_generator.py --input "%XSTAGE_INPUT%" --soundfont "%XSTAGE_SF2%" --output "%XSTAGE_OUTPUT%" --workers auto
set "XSTAGE_RESULT=%errorlevel%"
echo.
if "%XSTAGE_RESULT%"=="0" (echo Conversion complete.) else (echo Conversion returned error code %XSTAGE_RESULT%. Read xstage-web-errors.log.)
pause
exit /b %XSTAGE_RESULT%
:incomplete
echo Required input is missing.
pause
exit /b 2
