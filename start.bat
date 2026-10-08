@echo off
title Vibe Queue
cd /d "%~dp0"
if not exist .venv (
    echo Setting up for the first time...
    python -m venv .venv || goto :error
    .venv\Scripts\python -m pip install -q -r requirements.txt || goto :error
)
.venv\Scripts\python main.py
pause
exit /b

:error
echo Setup failed. Make sure Python 3 is installed and on your PATH.
pause
