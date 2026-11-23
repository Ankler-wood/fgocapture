# 用 tools\tutorial.template.txt 生成教程文本
#   -Mode embedded : 塞进 exe 里（--tutorial 打印用），哈希占位改成"看使用说明.txt"
#   -Mode final    : 生成给用户看的 使用说明.txt（哈希由 -Sha256 传入）
param(
    [string]$Mode = 'embedded',
    [string]$Sha256 = '',
    [string]$Out = ''
)
$ErrorActionPreference = 'Stop'
$tools = $PSScriptRoot
$template = Join-Path $tools 'tutorial.template.txt'
$buildInfo = Join-Path $tools 'BuildInfo.cs'

function Get-Const([string]$name) {
    $line = Select-String -Path $buildInfo -Pattern "public const string $name = `"(.*)`";" |
            Select-Object -First 1
    if ($line) { return $line.Matches[0].Groups[1].Value } else { return '' }
}

$ver   = Get-Const 'Version'
$stamp = Get-Const 'BuildStamp'
$thumb = Get-Const 'ExpectedSignerThumbprint'

$text = [System.IO.File]::ReadAllText($template, [System.Text.Encoding]::UTF8)
$text = $text.Replace('{{VERSION}}', $ver).
              Replace('{{BUILD}}', $stamp).
              Replace('{{THUMB}}', $(if ($thumb) { $thumb } else { '（这一版没有签名）' }))

if ($Mode -eq 'final') {
    if (-not $Sha256) { throw 'final 模式需要 -Sha256' }
    $text = $text.Replace('{{SHA256}}', $Sha256)
    if (-not $Out) { $Out = Join-Path (Split-Path -Parent $tools) '使用说明.txt' }
    [System.IO.File]::WriteAllText($Out, $text, [System.Text.UTF8Encoding]::new($true))
    Write-Host "    使用说明 -> $Out"
} else {
    $text = $text.Replace('{{SHA256}}', '（见同目录的「使用说明.txt」）')
    if (-not $Out) { $Out = Join-Path $tools 'tutorial.txt' }
    [System.IO.File]::WriteAllText($Out, $text, [System.Text.UTF8Encoding]::new($false))
    Write-Host "    embedded tutorial -> $Out"
}
