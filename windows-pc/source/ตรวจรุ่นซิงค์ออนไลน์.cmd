@echo off
setlocal
cd /d "%~dp0"
echo ============================================================
echo X-Stage Karaoke Online Windows Source - Recovery r2
echo ============================================================
if not exist "karaoke\web_resume.py" (
  echo FAIL: Missing web_resume.py. You opened the wrong source folder.
  pause
  exit /b 1
)
findstr /C:"Recovery r2" "karaoke\ui.py" >nul
if errorlevel 1 (
  echo FAIL: This is not the updated Online Sync source.
  pause
  exit /b 1
)
findstr /C:"เข้าสู่ระบบ Google Drive" "karaoke\ui.py" >nul
if errorlevel 1 (
  echo FAIL: Google Login first-window button missing from the source.
  pause
  exit /b 1
)
echo PASS: Source contains the first-window Google Drive Login and recovery code.
echo NOTE: This does NOT prove that your installed XStageKaraoke.exe was updated.
echo Build with Verify-Windows-0948.cmd then Build-Windows.cmd.
echo Check the new window title contains [Recovery r2] in the running EXE.
pause
exit /b 0
