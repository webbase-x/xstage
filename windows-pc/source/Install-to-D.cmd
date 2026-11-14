@echo off
set "PS=powershell.exe"
if exist "%SystemRoot%\Sysnative\WindowsPowerShell\v1.0\powershell.exe" set "PS=%SystemRoot%\Sysnative\WindowsPowerShell\v1.0\powershell.exe"
"%PS%" -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\Install-Logged.ps1"
set "INSTALL_RESULT=%ERRORLEVEL%"
if "%INSTALL_RESULT%"=="20" (
    echo Installation paused: X-Stage Karaoke or an application file is still in use.
    echo Close X-Stage Karaoke, then run this installer again.
) else if not "%INSTALL_RESULT%"=="0" (
    echo Installation was not completed. Read the specific error above.
) else (
    echo Done. The X-Stage audio setup window will open.
)
pause
exit /b %INSTALL_RESULT%
