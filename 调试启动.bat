@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] 未找到 .venv，请先按 README 第 1 节创建环境。
    pause
    exit /b 1
)
".venv\Scripts\python.exe" "run.py"
echo.
echo [进程已退出，错误码 %ERRORLEVEL%]
pause
