@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo X-Stage Karaoke v0.9.44 - Windows regression gate
echo Only tests synthetic fixtures; no Drive authentication or song deletion.
echo ============================================================
if exist ".build-venv\Scripts\python.exe" (
 set "PYTHON=.build-venv\Scripts\python.exe"
) else (
 set "PYTHON=py -3.13"
)
%PYTHON% tools\run_build_tests.py
set "RESULT=%ERRORLEVEL%"
echo Test log: %CD%\build-tests.log
echo Test summary: %CD%\build-tests-summary.json
if "%RESULT%"=="0" (echo BUILD TEST RESULT: PASS) else (echo BUILD TEST RESULT: FAIL. Do not install.)
pause
exit /b %RESULT%
