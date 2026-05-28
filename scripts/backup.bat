@echo off
REM Think4U HRMS - Windows 雙擊備份
REM 透過 git bash 呼叫 scripts/backup.sh
setlocal

set "BASH=C:\Program Files\Git\bin\bash.exe"
if not exist "%BASH%" set "BASH=C:\Program Files (x86)\Git\bin\bash.exe"
if not exist "%BASH%" (
  echo [錯誤] 找不到 git bash，請安裝 Git for Windows
  pause
  exit /b 1
)

cd /d "%~dp0\.."
"%BASH%" -lc "bash scripts/backup.sh"

echo.
pause
