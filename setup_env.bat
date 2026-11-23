@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo ============================================
echo  FGO 抓包脚本 - 安装依赖
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo [!] 没找到 python，请先安装 Python 3.9+ 并勾选 Add to PATH
  echo     下载：https://www.python.org/downloads/windows/
  pause
  exit /b 1
)

for /f "tokens=2" %%v in ('python --version 2^>^&1') do echo [i] Python %%v

if not exist ".venv\Scripts\python.exe" (
  echo [i] 创建虚拟环境 .venv ...
  python -m venv .venv
)

if not exist ".venv\Scripts\python.exe" (
  echo [!] 虚拟环境创建失败
  pause
  exit /b 1
)

echo [i] 安装 mitmproxy（第一次要下载几十 MB，请耐心等）...
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install mitmproxy

if not exist ".venv\Scripts\mitmdump.exe" (
  echo.
  echo [i] 上面这种方式失败的话，改用 --python 方式再试一次...
  python -m pip --python .venv\Scripts\python.exe install mitmproxy
)

if not exist ".venv\Scripts\mitmdump.exe" (
  echo.
  echo [!] 依赖安装失败。常见原因：
  echo     1. 网络问题： pip install mitmproxy -i https://pypi.tuna.tsinghua.edu.cn/simple
  echo     2. Python 版本太新/太旧：建议 3.10 - 3.13
  echo     3. 没有虚拟环境权限：用「管理员身份运行」再试
  pause
  exit /b 1
)

echo.
echo [i] 版本：
.venv\Scripts\mitmdump.exe --version
echo.
echo [OK] 安装完成，双击 run.bat 开始抓包。
pause
