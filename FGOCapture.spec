# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包脚本：把 capture.py + mitmproxy + fgo_addon 打成一个 exe。

用法（在 fgo-capture 目录下）：
    .venv\\Scripts\\pyinstaller.exe FGOCapture.spec --noconfirm
产物：dist\\FGOCapture.exe（单文件，双击即用）
"""
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas, binaries, hiddenimports = [], [], []

# mitmproxy 及其运行时要的第三方包：它们大量使用动态导入/data 文件，
# 必须整包收进去，否则运行时报 ModuleNotFoundError。
PACKAGES = [
    "mitmproxy",
    "mitmproxy_rs",
    "mitmproxy_windows",
    "aioquic",
    "publicsuffix2",
    "pydivert",
    "pylsqpack",
    "brotli",
    "ldap3",
    "kaitaistruct",
    "ruamel.yaml",
    "wsproto",
    "h2",
    "hpack",
    "hyperframe",
    "h11",
    "sortedcontainers",
    "service_identity",
    "pyopenssl",
    "OpenSSL",
    "cryptography",
    "cffi",
    "flask",
    "werkzeug",
    "argon2",
    "bcrypt",
    "click",
    "tornado",
]
for pkg in PACKAGES:
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as exc:  # 某个包没装/无数据也不要紧
        print("collect_all skipped %s: %r" % (pkg, exc))

hiddenimports += collect_submodules("mitmproxy")
hiddenimports += collect_submodules("mitmproxy.addons")
hiddenimports += collect_submodules("mitmproxy.proxy")
hiddenimports += ["make_import", "fgo_addon"]

# 抓包插件本身要以真实文件形式给 mitmproxy 的 -s 参数
datas += [("fgo_addon.py", ".")]

a = Analysis(
    ["capture.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "pandas", "PIL", "pytest", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)

# FGO_ONEDIR=1 时打「文件夹版」（启动快、便于排查），否则打单文件 exe
import os as _os

if _os.environ.get("FGO_ONEDIR") == "1":
    exe = EXE(
        pyz, a.scripts, [], exclude_binaries=True,
        name="FGOCapture", debug=False, strip=False, upx=False, console=True,
    )
    coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False,
                   name="FGOCapture")
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name="FGOCapture",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=True,
        icon=None,
    )
