# 第三方组件与许可声明

本项目的 `FGOCapture.exe` 把以下开源组件打包进了单文件里。分发时保留本文件即可满足各组件
的署名/声明要求。各组件的完整许可原文见其官方仓库或 PyPI 页面。

## 运行核心

| 组件 | 许可 | 说明 |
|---|---|---|
| [mitmproxy](https://github.com/mitmproxy/mitmproxy) | MIT | 抓包引擎（本工具以插件形式挂在其 `mitmdump` 上） |
| mitmproxy_rs / mitmproxy_windows | MIT | mitmproxy 的 Rust/Windows 支撑库 |
| [Python](https://www.python.org/) 3.15 | PSF-2.0 | 解释器 |
| [OpenSSL](https://www.openssl.org/) | Apache-2.0 | TLS 实现 |
| [cryptography](https://github.com/pyca/cryptography) | Apache-2.0 OR BSD-3-Clause | 证书生成/解析 |
| [aioquic](https://github.com/aiortc/aioquic) · pylsqpack | BSD-3-Clause / MIT | QUIC 支持 |
| h11 · h2 · hpack · hyperframe · wsproto | MIT | HTTP/1.1、HTTP/2、WebSocket |
| Brotli | MIT | 压缩解码 |
| [tornado](https://www.tornadoweb.org/) | Apache-2.0 | 网络栈 |
| Flask · Werkzeug · Jinja2 · itsdangerous · blinker · asgiref · MarkupSafe · click | BSD-3-Clause | mitmproxy 的 web 接口（未启用） |
| urwid · wcwidth | LGPL-2.1+ / MIT | mitmproxy 控制台界面（本工具用 mitmdump，不加载） |
| ldap3 | LGPL-3.0 | mitmproxy 的 LDAP 认证（未启用） |
| pydivert | LGPL-3.0 | mitmproxy 的 Windows 透明代理（本工具不用） |
| publicsuffix2 | MIT and MPL-2.0 | 域名处理 |
| certifi | MPL-2.0 | CA 证书列表 |
| pyOpenSSL · sortedcontainers | Apache-2.0 | |
| bcrypt · argon2-cffi | Apache-2.0 / MIT | mitmproxy 的密码保护功能 |
| kaitaistruct · ruamel.yaml · service-identity · attrs · cffi · pycparser · pyasn1 · pyperclip · typing_extensions | MIT / BSD / PSF-2.0 | 其他依赖 |

## 打包工具（不会进入 exe 的运行时，但其引导程序在 exe 里）

| 组件 | 许可 | 说明 |
|---|---|---|
| [PyInstaller](https://pyinstaller.org/) | GPL-2.0-or-later **WITH bootloader exception** | 打包工具；该例外明确允许把打包产物按任意许可分发 |
| pefile · altgraph · pywin32-ctypes | MIT / BSD-3-Clause | PyInstaller 的依赖 |

## 关于 LGPL 组件

urwid、ldap3、pydivert 是 LGPL。它们随 mitmproxy 一起被打了进去，但本工具并不使用它们的功能
（用的是 mitmdump，不是交互式控制台 / LDAP / 透明代理）。LGPL 要求的"可替换"在本项目里是满足的：

- 这些组件都是 PyPI 上公开发布的纯 Python 包（或在 exe 内以独立文件存在）；
- 任何人都能按 README 第二节从源码重新构建（`build_exe.bat`），或替换 `tools/stage` 里的对应
  文件后重新打包。

## 本项目的许可

本项目自身代码（`capture.py`、`fgo_addon.py`、`make_import.py`、`tools/`、文档）采用
**MIT License**，见仓库根目录 `LICENSE`。

`FGOCapture.exe` 里的 FGO 抓包逻辑、区间判定、Chaldea 导入文件的提取规则均为本项目原创；
mitmproxy 仅作为通用抓包引擎被调用，本项目未修改其源码。

## 声明

- 本项目不包含任何 FGO 的游戏资源、账号数据或服务器端内容。
- 本项目在 AI 辅助下开发（代码由 AI 生成，经人工设计流程、真机验证与反复修正）。
  MIT 许可覆盖本仓库中由作者整理和编辑的部分；如对 AI 生成内容的著作权归属有疑问，
  可以把它当作"无担保、可自由使用"的代码看待。
