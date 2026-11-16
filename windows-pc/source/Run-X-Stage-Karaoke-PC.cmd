@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul
echo ================================================
echo   X-Stage Karaoke PC - Windows Source (CMD)
echo ================================================
rem Support older releases that nest all sources in one child folder.
rem Keep using this CMD file's directory (never search unrelated user files).
if not exist "main.py" if exist "X-Stage-Karaoke-PC-Source\main.py" (
  cd /d "%~dp0X-Stage-Karaoke-PC-Source"
)
if not exist "main.py" (
  echo ERROR: main.py not found beside this launcher.
  echo.
  echo Extract the COMPLETE Windows-CMD-Source ZIP, not just this CMD file.
  echo Expected: main.py, karaoke\, requirements.txt, tools\.
  echo Open the extracted X-Stage-Karaoke-PC-Source folder and run the CMD there.
  echo.
  pause
  exit /b 2
)
if not exist "requirements.txt" (
  echo ERROR: requirements.txt is missing. Extract the complete ZIP.
  pause
  exit /b 2
)
if exist ".venv\Scripts\python.exe" goto launch
where py >nul 2>&1
if not errorlevel 1 (
  py -3.13 -c "import sys; assert sys.version_info[:2] == (3,13)" >nul 2>&1
  if not errorlevel 1 (
    py -3.13 -m venv ".venv"
    if errorlevel 1 goto setup_failed
    goto install
  )
)
where python >nul 2>&1
if errorlevel 1 goto missing_python
python -c "import sys; assert sys.version_info[:2] == (3,13)" >nul 2>&1
if errorlevel 1 goto missing_python
python -m venv ".venv"
if errorlevel 1 goto setup_failed
:install
echo Installing Python packages into local .venv ...
".venv\Scripts\python.exe" -m pip install -r "requirements.txt"
if errorlevel 1 goto setup_failed
:launch
echo Opening X-Stage Karaoke PC from source...
if not exist ".local-test-data" mkdir ".local-test-data"
".venv\Scripts\python.exe" "main.py" --data-dir "%CD%\.local-test-data" %*
set "EXITCODE=%ERRORLEVEL%"
if not "%EXITCODE%"=="0" (
  echo.
  echo Program exited with error %EXITCODE%.
  echo Check .local-test-data logs and traceback above.
  pause
)
exit /b %EXITCODE%
:missing_python
echo Python 3.13 x64 with Tkinter is required.
echo Install Python 3.13 x64 from python.org, including the py launcher.
pause
exit /b 3
:setup_failed
echo Environment setup failed. Check the error above and internet access.
pause
exit /b 4
