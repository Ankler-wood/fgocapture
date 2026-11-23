# 计算 app.zip 的 SHA-256，写入 tools\BuildInfo.cs（启动器用它做自校验）
# 同时查一下本机有没有我们的签名证书，把指纹也写进去（没有就留空）
param(
    [string]$ZipPath = '',
    [string]$TemplatePath = '',
    [string]$OutPath = ''
)
$ErrorActionPreference = 'Stop'
$tools = $PSScriptRoot
if (-not $ZipPath)      { $ZipPath = Join-Path $tools 'app.zip' }
if (-not $TemplatePath) { $TemplatePath = Join-Path $tools 'BuildInfo.template.cs' }
if (-not $OutPath)      { $OutPath = Join-Path $tools 'BuildInfo.cs' }

$hash  = (Get-FileHash $ZipPath -Algorithm SHA256).Hash.ToLower()
$stamp = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
$ver   = '1.0.2-' + (Get-Date).ToString('yyyyMMdd-HHmm')

$thumb = ''
try {
    $cert = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert |
            Where-Object { $_.Subject -eq 'CN=FGOCapture Self-Signed (integrity only)' } |
            Sort-Object NotAfter -Descending | Select-Object -First 1
    if ($cert) { $thumb = $cert.Thumbprint }
} catch { }

$text = [System.IO.File]::ReadAllText($TemplatePath, [System.Text.Encoding]::UTF8)
$text = $text.Replace('__APPZIP_SHA256__', $hash).
              Replace('__BUILD_STAMP__', $stamp).
              Replace('__VERSION__', $ver).
              Replace('__SIGNER_THUMB__', $thumb)
[System.IO.File]::WriteAllText($OutPath, $text, [System.Text.UTF8Encoding]::new($false))

Write-Host "    payload sha256 = $hash"
Write-Host "    version        = $ver"
Write-Host "    signer thumb   = $(if ($thumb) { $thumb } else { '(未找到证书，构建为未签名)' })"
