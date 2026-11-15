@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul
echo X-Stage Karaoke PC - full source regression tests
if not exist ".venv\Scripts\python.exe" (
  echo First run "Run-X-Stage-Karaoke-PC.cmd" to set up Python.
  pause
  exit /b 2
)
".venv\Scripts\python.exe" "tools\run_build_tests.py"
set "EXITCODE=%ERRORLEVEL%"
echo.
if "%EXITCODE%"=="0" (echo ALL TESTS PASSED) else (echo TESTS FAILED: %EXITCODE%)
echo Results: build-tests-summary.json and build-tests.log
pause
exit /b %EXITCODE%
