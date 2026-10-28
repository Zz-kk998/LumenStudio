@echo off
cd /d "%~dp0"
py -m pip install -r requirements-build.txt
if errorlevel 1 exit /b 1
py build.py
if errorlevel 1 exit /b 1
echo Build finished. Open the dist folder.
pause
