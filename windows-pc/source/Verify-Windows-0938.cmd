@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo X-Stage Karaoke v0.9.38 - Windows source regression tests
 echo This does not install the app or touch D:\newKaraoke.
echo All test media and catalogs are temporary fixtures.
echo ============================================================
py -3.13 -m unittest discover -s tests -p "test_*.py"
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" echo Some tests failed. Please save the full console output before updating the live installation.
pause
exit /b %RESULT%
