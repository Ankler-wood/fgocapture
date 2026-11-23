@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [!] 还没装依赖，先双击 setup_env.bat
  pause
  exit /b 1
)

.venv\Scripts\python.exe capture.py %*
echo.
echo [i] 窗口保留，方便看报错。按任意键关闭。
pause >nul
