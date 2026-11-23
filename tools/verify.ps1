# 核对 FGOCapture.exe 是否被篡改（供拿到文件的人在 PowerShell 里跑）
# 由 verify.bat 调用，也可以直接：
#   powershell -ExecutionPolicy Bypass -File tools\verify.ps1
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
$exe = Join-Path $root 'FGOCapture.exe'

Write-Host '============================================'
Write-Host '  FGOCapture.exe 完整性校验'
Write-Host '============================================'
Write-Host ''

if (-not (Test-Path $exe)) {
    Write-Host '[!] 当前目录没有 FGOCapture.exe' -ForegroundColor Red
    exit 1
}

$bad = $false

# 1) 文件哈希 vs 清单
Write-Host '[1/3] 文件 SHA-256 对比 FGOCapture.exe.sha256'
$list = Join-Path $root 'FGOCapture.exe.sha256'
if (Test-Path $list) {
    $want = (Get-Content $list -Raw).Split(' ')[0].Trim().ToLower()
    $got = (Get-FileHash $exe -Algorithm SHA256).Hash.ToLower()
    Write-Host "    期望 $want"
    Write-Host "    实际 $got"
    if ($want -eq $got) {
        Write-Host '    >>> 一致，文件没有被改过' -ForegroundColor Green
    } else {
        Write-Host '    >>> 不一致！文件可能被替换或植入，请不要运行' -ForegroundColor Red
        $bad = $true
    }
} else {
    Write-Host '    [!] 没有 .sha256 清单，跳过这一项'
}

# 2) exe 内置载荷自校验
Write-Host ''
Write-Host '[2/3] exe 内置载荷自校验'
& $exe --verify
if ($LASTEXITCODE -ne 0) { $bad = $true }

# 3) Authenticode 签名
Write-Host ''
Write-Host '[3/3] Authenticode 签名'
$sig = Get-AuthenticodeSignature $exe
Write-Host "    状态: $($sig.Status)"
if ($sig.SignerCertificate) {
    Write-Host "    签名者: $($sig.SignerCertificate.Subject)"
    Write-Host "    指纹  : $($sig.SignerCertificate.Thumbprint)"
    $info = Join-Path $root 'FGOCapture.signature.txt'
    if (Test-Path $info) { Write-Host '    （和 FGOCapture.signature.txt 里的指纹对比一下）' }
} else {
    Write-Host '    未签名（不影响使用，但只能靠上面的哈希判断是否被改过）'
}

Write-Host ''
if ($bad) {
    Write-Host '[!] 校验失败：不要运行这个 exe，去找发给你的人重新要一份。' -ForegroundColor Red
    exit 1
}
Write-Host '校验通过。' -ForegroundColor Green
exit 0
