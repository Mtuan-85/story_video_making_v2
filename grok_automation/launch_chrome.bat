@echo off
REM Launch Chrome with CDP debug port for grok_automation
REM Adjust paths if needed:
REM   - chrome.exe path: depends on Chrome install location
REM   - user-data-dir: where to save profile (login session, cookies, etc.)

set CHROME_EXE="C:\Program Files\Google\Chrome\Application\chrome.exe"
set PROFILE_DIR="D:\chrome-grok-profile"
set DEBUG_PORT=9222

if not exist %CHROME_EXE% (
    echo [ERROR] Chrome khong tim thay tai: %CHROME_EXE%
    echo Vui long sua bien CHROME_EXE trong file nay.
    pause
    exit /b 1
)

echo Launching Chrome with debug port %DEBUG_PORT%...
echo Profile: %PROFILE_DIR%
echo.
echo Lan dau chay: login Grok manually, sau do giu Chrome mo.
echo App PyQt se connect vao port %DEBUG_PORT% de automate.
echo.

%CHROME_EXE% ^
  --remote-debugging-port=%DEBUG_PORT% ^
  --user-data-dir=%PROFILE_DIR% ^
  --no-first-run ^
  --no-default-browser-check ^
  https://grok.com/imagine
