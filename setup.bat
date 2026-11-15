@echo off
cd /d "%~dp0"
py -3 -m venv .venv
if errorlevel 1 goto :failed
".venv\Scripts\python.exe" -m pip install -r requirements-lock.txt
if errorlevel 1 goto :failed
".venv\Scripts\python.exe" scripts\bundle_plotly.py
if errorlevel 1 goto :failed
echo Setup complete. Run start.bat to open the dashboard.
pause
exit /b 0
:failed
echo Setup failed. Read the error above, then try again.
pause
exit /b 1
