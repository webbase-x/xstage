@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo X-Stage Karaoke v0.9.40 - Windows regression gate
 echo No installation, song deletion, or automatic shutdown.
echo All test songs and databases are temporary fixtures.
echo ============================================================
if exist ".build-venv\Scripts\python.exe" (
  set "PYTHON=.build-venv\Scripts\python.exe"
) else (
  set "PYTHON=py -3.13"
)
%PYTHON% tools\run_build_tests.py
set "RESULT=%ERRORLEVEL%"
echo.
echo Test log: %CD%\build-tests.log
echo Test exit code: %RESULT%
if not "%RESULT%"=="0" echo Do not install: tests failed. Keep the existing installed program.
pause
exit /b %RESULT%
