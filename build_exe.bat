@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] 未找到 .venv，请先阅读 README 第 1 节。
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo [1/3] 安装 PyInstaller ...
    ".venv\Scripts\python.exe" -m pip install pyinstaller -i https://pypi.tuna.tsinghua.edu.cn/simple
    if errorlevel 1 goto :fail
)

echo [2/3] 打包 GuanLanQuant ...
".venv\Scripts\python.exe" -m PyInstaller ^
    --noconfirm --clean --windowed ^
    --name GuanLanQuant ^
    --icon "assets\guanlan.ico" ^
    --add-data "plugins;plugins" ^
    --add-data "assets;assets" ^
    --collect-submodules app ^
    --collect-all pyqtgraph ^
    run.py
if errorlevel 1 goto :fail

echo [3/3] 完成：dist\GuanLanQuant\GuanLanQuant.exe
echo 首次启动会在 exe 同级创建 data\、logs\、reports\，请保持联网。
pause
exit /b 0

:fail
echo.
echo [FAILED] 打包失败，请查看上方日志。
pause
exit /b 1
