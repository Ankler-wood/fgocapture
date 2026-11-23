# 给 FGOCapture.exe 加 Authenticode 签名（自签名证书）
# 用法：右键 -> 使用 PowerShell 运行；或  powershell -ExecutionPolicy Bypass -File tools\sign_exe.ps1
#
# 作用与局限（务必看 README）：
#   * 签名后，任何人改动 exe 都会让签名失效，配合 FGOCapture.exe.sha256 可以查出被改过；
#   * 证书是自签的，Windows 仍会提示「未知发布者」，不会变成受信任的商用签名；
#   * 把证书指纹（Thumbprint）发出去，对方可以用 verify.bat 核对是不是你签的那份。

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path $root)) { $root = (Get-Location).Path }
$exe = Join-Path $root 'FGOCapture.exe'
if (-not (Test-Path $exe)) { throw "找不到 $exe，先运行 build_exe.bat" }

$cerPath = Join-Path $root 'FGOCapture.cer'
$thumbFile = Join-Path $root 'FGOCapture.signature.txt'

# 复用已有证书（按 Subject 找），没有就新建一个仅用于代码签名的自签名证书
$subject = 'CN=FGOCapture Self-Signed (integrity only)'
$cert = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert |
        Where-Object { $_.Subject -eq $subject } |
        Sort-Object NotAfter -Descending | Select-Object -First 1

if (-not $cert) {
    Write-Host '[i] 创建自签名代码签名证书（仅本机 CurrentUser，可随时删除）...'
    $cert = New-SelfSignedCertificate `
        -Type CodeSigningCert `
        -Subject $subject `
        -KeyUsage DigitalSignature `
        -CertStoreLocation 'Cert:\CurrentUser\My' `
        -NotAfter (Get-Date).AddYears(5) `
        -TextExtension @('2.5.29.37={text}1.3.6.1.5.5.7.3.3')
}

Write-Host "[i] 使用证书：$($cert.Subject)"
Write-Host "    指纹：$($cert.Thumbprint)"

$sig = Set-AuthenticodeSignature -FilePath $exe -Certificate $cert -HashAlgorithm SHA256
Write-Host "[i] 签名状态：$($sig.Status)  $($sig.StatusMessage)"

# 导出公钥证书，方便别人导入后把发布者变成「受信任」
Export-Certificate -Cert $cert -FilePath $cerPath -Force | Out-Null

$hash = (Get-FileHash $exe -Algorithm SHA256).Hash.ToLower()
Set-Content (Join-Path $root 'FGOCapture.exe.sha256') ($hash + '  FGOCapture.exe') -Encoding ASCII

@(
    'FGOCapture.exe 签名信息'
    ''
    "证书主题 : $($cert.Subject)"
    "证书指纹 : $($cert.Thumbprint)"
    "有效期至 : $($cert.NotAfter.ToString('yyyy-MM-dd'))"
    "签名状态 : $($sig.Status)"
    "文件SHA256: $hash"
    ''
    '任何人拿到 exe 后可以运行 verify.bat 核对上面的指纹和哈希；'
    '对不上就说明文件被改动过，不要运行。'
) | Set-Content $thumbFile -Encoding UTF8

Write-Host ''
Write-Host "[OK] 已签名，并写出："
Write-Host "     $cerPath"
Write-Host "     $thumbFile"
Write-Host "     $(Join-Path $root 'FGOCapture.exe.sha256')"
