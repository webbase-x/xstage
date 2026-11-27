@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>&1
if errorlevel 1 goto python
py -3 -m karaoke.compact_verified_index_gui
if errorlevel 1 pause
goto end
:python
python -m karaoke.compact_verified_index_gui
if errorlevel 1 pause
:end
