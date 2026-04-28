cd D:\Projects\Slide_show_automation\slideshow_v4

@"
@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist venv\Scripts\activate.bat (
    echo [Loi] Venv chua co. Chay: uv venv ^&^& uv pip install -r requirements.txt
    pause
    exit /b 1
)
call venv\Scripts\activate.bat
python main.py
if errorlevel 1 pause
"@ | Out-File -Encoding ASCII run.bat