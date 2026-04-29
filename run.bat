@echo off
REM Launch Story Video Maker via the project's .venv (no global Python).
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
".venv\Scripts\python.exe" main.py
pause
