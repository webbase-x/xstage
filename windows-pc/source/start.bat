@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0XStageKaraoke.exe" (
    start "" "%~dp0XStageKaraoke.exe"
    exit /b
)
where py >nul 2>nul
if not errorlevel 1 (
    py -3 "%~dp0main.py" %*
) else (
    python "%~dp0main.py" %*
)
if errorlevel 1 (
    echo.
    echo Cannot start newKaraoke. Install Python 3.10+ with Tcl/Tk.
    echo If Python is installed, see data\newKaraoke.log.
    pause
)
