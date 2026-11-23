@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

rem 打成一个 exe + 一个说明文本：
rem   PyInstaller onedir -> app.zip -> BuildInfo.cs（载荷哈希/版本/证书指纹）
rem   -> 内嵌教程 -> 编译 FGOCapture.exe -> 签名（有证书时）-> 生成 使用说明.txt

if not exist ".venv\Scripts\python.exe" (
  echo [!] Run setup_env.bat first / 先双击 setup_env.bat
  pause
  exit /b 1
)

set "CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if not exist "%CSC%" (
  echo [!] csc.exe not found / 找不到 C# 编译器
  pause
  exit /b 1
)

echo [1/7] install pyinstaller ...
.venv\Scripts\python.exe -m pip install pyinstaller >nul
if errorlevel 1 goto :fail

echo [2/7] pyinstaller (onedir) ...
set FGO_ONEDIR=1
.venv\Scripts\pyinstaller.exe FGOCapture.spec --noconfirm --clean --log-level ERROR
if errorlevel 1 goto :fail
set FGO_ONEDIR=
if not exist "dist\FGOCapture\FGOCapture.exe" goto :fail

echo [3/7] zip payload ...
if exist "tools\stage" rmdir /s /q "tools\stage"
mkdir "tools\stage"
xcopy "dist\FGOCapture\*" "tools\stage\" /e /i /q /y >nul
if errorlevel 1 goto :fail
if exist "tools\app.zip" del /q "tools\app.zip"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Add-Type -AssemblyName System.IO.Compression.FileSystem; [System.IO.Compression.ZipFile]::CreateFromDirectory('tools\stage','tools\app.zip',[System.IO.Compression.CompressionLevel]::Optimal,$false)"
if not exist "tools\app.zip" goto :fail

echo [4/7] BuildInfo.cs + embedded tutorial ...
powershell -NoProfile -ExecutionPolicy Bypass -File "tools\make_buildinfo.ps1"
if errorlevel 1 goto :fail
powershell -NoProfile -ExecutionPolicy Bypass -File "tools\make_tutorial.ps1" -Mode embedded
if errorlevel 1 goto :fail

echo [5/7] compile FGOCapture.exe ...
if exist "FGOCapture.exe" del /q "FGOCapture.exe"
"%CSC%" /nologo /target:exe /platform:anycpu /optimize+ /codepage:65001 ^
  /out:"FGOCapture.exe" ^
  /resource:"tools\app.zip",app.zip ^
  /resource:"tools\tutorial.txt",tutorial.txt ^
  /reference:System.IO.Compression.dll ^
  /reference:System.IO.Compression.FileSystem.dll ^
  "tools\launcher.cs" "tools\BuildInfo.cs"
if errorlevel 1 goto :fail
if not exist "FGOCapture.exe" goto :fail

echo [6/7] sign (only if the cert exists) ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert | Where-Object { $_.Subject -eq 'CN=FGOCapture Self-Signed (integrity only)' }) { & '.\tools\sign_exe.ps1' } else { Write-Host '    no cert, skip signing (run tools\sign_exe.ps1 once to create it)' }"

echo [7/7] write 使用说明.txt ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$h=(Get-FileHash 'FGOCapture.exe' -Algorithm SHA256).Hash.ToLower(); & '.\tools\make_tutorial.ps1' -Mode final -Sha256 $h; Set-Content 'FGOCapture.exe.sha256' ($h + '  FGOCapture.exe') -Encoding ASCII; Write-Host ('    exe sha256 = ' + $h)"

echo.
echo [OK] 交付物（发给别人只需要这两个）：
echo      FGOCapture.exe
echo      使用说明.txt
for %%f in ("FGOCapture.exe") do echo      exe 大小 %%~zf 字节
pause
exit /b 0

:fail
echo.
echo [!] build failed / 打包失败，看上面报错
pause
exit /b 1
