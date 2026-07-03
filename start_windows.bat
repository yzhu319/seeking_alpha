@echo off
REM Double-click this file to start AI Infra Watch.
cd /d %~dp0

where python >nul 2>nul
if errorlevel 1 (
  echo Python isn't installed on this PC.
  echo Get it from https://www.python.org/downloads/ then run this again.
  echo IMPORTANT: on the installer's first screen, check "Add python.exe to PATH".
  pause
  exit /b 1
)

if not exist ".venv" (
  echo First-time setup — this takes a minute...
  python -m venv .venv
)

call .venv\Scripts\activate.bat
pip install -q -r requirements.txt
echo Starting AI Infra Watch — your browser will open automatically.
streamlit run app.py
pause
