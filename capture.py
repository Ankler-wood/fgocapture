#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""capture.py —— FGO 三服多模拟器抓包编排器（Windows + 雷电/MuMu/夜神/BlueStacks）。

它做四件事：
  1. 找到 adb，枚举所有已连上的模拟器，读出各自装了哪个 FGO 包，自动判定是
     华为渠道服 / 简中B服 / 日服；
  2. 给每个模拟器把 mitmproxy 的根证书装进「系统证书」目录（bind mount 覆盖
     /system/etc/security/cacerts，不需要可写 /system，重启后重跑即可）；
  3. 每个模拟器分配一个独立代理端口，用 `adb reverse` 把流量导到本机对应
     mitmdump 进程，因此三台模拟器的包互不混淆；
  4. 按服务器分目录落盘（flows/、game/、index.csv、auth.json），Ctrl+C 退出时
     自动还原代理设置并卸载证书。

用法见 README.md，最常用：
    run.bat                     # 打开三个模拟器后直接跑，开始抓包
    run.bat --list              # 只看设备识别结果，不动任何设置
    run.bat --duration 60       # 抓 60 秒后自动停
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

FROZEN = bool(getattr(sys, "frozen", False))
if FROZEN:
    # 打包成 exe 后：程序本体在解包目录，可写的 conf/out 放回「exe 所在目录」
    HERE = Path(os.environ.get("FGO_APP_BASE") or Path(sys.executable).resolve().parent)
    RES_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
else:
    HERE = Path(__file__).resolve().parent
    RES_DIR = HERE
ADDON = RES_DIR / "fgo_addon.py"
CONFDIR = HERE / "conf"
CA_DIR_REMOTE = "/data/local/tmp/fgo_cacerts"

# 已知的客户端 → (key, 显示名)。注意顺序：华为服包名里同时含 bilibili 和 huawei。
PACKAGE_RULES = [
    ("huawei", "华为渠道服", ("com.bilibili.fgo.huawei", "com.huawei.fgo")),
    ("jp", "日服", ("com.aniplex.fategrandorder",)),
    ("bilibili", "简中B服", ("com.bilibili.fatego",)),
]

# 简中服各渠道的包名后缀 -> 显示名（com.bilibili.fgo.<后缀>）
CN_CHANNELS = {
    "huawei": "华为渠道服", "honor": "荣耀渠道服",
    "bilibili": "简中B服", "xiaomi": "小米渠道服", "mi": "小米渠道服",
    "oppo": "OPPO渠道服", "vivo": "vivo渠道服",
    "yyb": "应用宝渠道服", "tencent": "应用宝渠道服", "tx": "应用宝渠道服",
    "4399": "4399渠道服", "9game": "九游渠道服", "uc": "UC渠道服",
    "meizu": "魅族渠道服", "samsung": "三星渠道服", "lenovo": "联想渠道服",
    "baidu": "百度渠道服", "360": "360渠道服", "sogou": "搜狗渠道服",
    "mumu": "MuMu渠道服", "bili": "简中B服",
}

# 兜底：按包名关键字猜（顺序有意义）
NAME_RULES = [
    ("us", "美服", "fategrandorder.en"),
    ("kr", "韩服", "fategrandorderkr"),
    ("kr", "韩服", "fategrandorder.kr"),
    ("tw", "繁中服", "fategrandch"),
    ("tw", "繁中服", "fgetw"),
    ("tw", "繁中服", "komoe"),
    ("huawei", "华为渠道服", "huawei"),
    ("jp", "日服", "fategrandorder"),
    ("jp", "日服", "aniplex"),
    ("bilibili", "简中B服", "fatego"),
    ("bilibili", "简中B服", "biligame"),
]

ADB_CANDIDATES = [
    r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe",
    r"%ANDROID_HOME%\platform-tools\adb.exe",
    r"%ANDROID_SDK_ROOT%\platform-tools\adb.exe",
    r"C:\leidian\LDPlayer9\adb.exe",
    r"D:\leidian\LDPlayer9\adb.exe",
    r"D:\LDPlayer\LDPlayer9\adb.exe",
    r"C:\LDPlayer\LDPlayer9\adb.exe",
    r"C:\Program Files\Netease\MuMuPlayer-12.0\shell\adb.exe",
    r"C:\Program Files\Netease\MuMuPlayerGlobal-12.0\shell\adb.exe",
    r"D:\Program Files\Netease\MuMuPlayer-12.0\shell\adb.exe",
    r"C:\Program Files\Nox\bin\adb.exe",
    r"C:\Program Files (x86)\Nox\bin\adb.exe",
    r"C:\Program Files\BlueStacks_nxt\HD-Adb.exe",
]
LDPLAYER_DIRS = [r"C:\leidian\LDPlayer9", r"D:\leidian\LDPlayer9",
                 r"D:\LDPlayer\LDPlayer9", r"C:\LDPlayer\LDPlayer9"]

# 各模拟器的 adb 端口（找不到设备时逐个握手）
ADB_PORT_HINTS = [
    5555, 5557, 5559,            # 雷电 / BlueStacks 常规
    16384, 16416, 16448, 16480,  # MuMu 12（每实例 +32）
    7555,                        # MuMu 6
    62001, 62025,                # 夜神
    21503,                       # MEmu
]

# 这些域名不做中间人，直接盲转发（CONNECT 隧道）。
# 原因：华为 HMS / bilibili SDK / bugly 等是 Java 实现且大多带证书绑定，
# 强行解密只会让它们握手失败；而我们要的是 FGO 本体（Unity/libcurl）的接口。
# 用 --ignore 可以覆盖。
IGNORE_HOSTS = [
    # 华为 / HMS 全家桶：登录靠它们，必须原样放过
    r".*\.huawei\.com", r".*\.huawei\.net", r".*\.huawei\.cn",
    r".*\.hicloud\.com", r".*\.hisdatav\.com", r".*\.dbankcdn\.com",
    r".*\.dbankcloud\.cn", r".*\.dbankcloud\.com", r".*\.hianswer\.net",
    r".*\.hispace\.com", r".*\.hiviewdfx\.com", r".*\.hwccpc\.com",
    r".*\.hihonor\.com", r".*\.honor\.com", r".*\.hwcdn\.net",
    # 渠道 / 门户 / 第三方 SDK
    r".*\.biligame\.com",
    r".*-sdk-app-api\.biligame\.net",
    r".*-sdkcenter-login.*",
    r".*-log\.biligame\.net",
    r".*\.biliapi\.com",
    r"bugly\.qq\.com",
    r".*\.umeng\.com",
    r"middledata\.ldmnq\.com",
    # 资源 CDN：动辄几 MB~几百 MB，解密没意义还拖慢游戏
    r"cdn\.data\.fate-go\.jp",
    r"masterdata-update\.fate-go\.jp",
    r"view\.fate-go\.jp",
    r".*-patch-fate\.biligame\.net",
]


# ----------------------------------------------------------------- 小工具

def run(cmd: List[str], timeout: int = 30, env: Optional[dict] = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout, env=env)
    except FileNotFoundError:
        return subprocess.CompletedProcess(cmd, 127, "", "not found")
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or ""
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        return subprocess.CompletedProcess(cmd, 124, out, "timeout")


def free_port(start: int) -> int:
    for port in range(start, start + 200):
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
        return port
    raise RuntimeError("找不到空闲端口")


def open_ports(ports: List[int], timeout: float = 0.35) -> List[int]:
    """并行探测哪些本机端口在监听（比逐个 adb connect 快得多）。"""
    def probe(port: int) -> bool:
        with socket.socket() as sock:
            sock.settimeout(timeout)
            return sock.connect_ex(("127.0.0.1", port)) == 0

    alive: List[int] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(16, len(ports) or 1)) as pool:
        for port, ok in zip(ports, pool.map(probe, ports)):
            if ok:
                alive.append(port)
    return alive


KNOWN_DISPLAY = {k: d for k, d, _ in PACKAGE_RULES}
for _suffix, _disp in CN_CHANNELS.items():
    KNOWN_DISPLAY.setdefault(_suffix, _disp)
KNOWN_DISPLAY.update({"cn_channel": "简中渠道服", "unknown": "未识别FGO",
                      "us": "美服", "tw": "繁中服", "kr": "韩服"})


def display_for(key: str) -> str:
    return KNOWN_DISPLAY.get(key, key)


def find_adb(explicit: Optional[str] = None) -> Optional[str]:
    if explicit:
        return explicit if Path(explicit).exists() else None
    which = shutil.which("adb")
    if which:
        return which
    for raw in ADB_CANDIDATES:
        path = Path(os.path.expandvars(raw))
        if path.is_file():
            return str(path)
    for base in LDPLAYER_DIRS:
        for name in ("adb.exe",):
            path = Path(base) / name
            if path.is_file():
                return str(path)
    return None


# ----------------------------------------------------------------- 设备对象

@dataclass
class Device:
    serial: str
    model: str = ""
    android: str = ""
    root: bool = False
    packages: List[str] = field(default_factory=list)
    key: str = ""
    display: str = ""
    pkg: str = ""
    port: int = 0
    proxy_mode: str = ""
    outdir: Path = Path(".")
    engine: Optional[subprocess.Popen] = None

    @property
    def title(self) -> str:
        return "%s / %s" % (self.display or "未识别", self.serial)


class Adb:
    def __init__(self, path: str):
        self.path = path

    def __call__(self, *args, timeout: int = 30) -> subprocess.CompletedProcess:
        return run([self.path, *[str(a) for a in args]], timeout=timeout)

    def devices(self) -> List[str]:
        proc = self("devices")
        serials = []
        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("List of devices"):
                continue
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                serials.append(parts[0])
        # emulator-5554 与 127.0.0.1:5555 是同一台，优先用 emulator-XXXX
        keep = list(serials)
        for serial in serials:
            if re.fullmatch(r"127\.0\.0\.1:(\d+)", serial):
                port = int(serial.split(":")[1])
                alias = "emulator-%d" % (port - 1)
                if alias in serials:
                    keep.remove(serial)
        return keep

    def connect(self, port: int) -> None:
        self("connect", "127.0.0.1:%d" % port, timeout=4)

    def shell(self, serial: str, command: str, timeout: int = 30) -> str:
        proc = self("-s", serial, "shell", command, timeout=timeout)
        return (proc.stdout or "") + (proc.stderr or "")

    def root(self, serial: str) -> bool:
        out = self.shell(serial, "id -u", timeout=10).strip()
        if out.splitlines() and out.splitlines()[0].strip() == "0":
            return True
        self("-s", serial, "root", timeout=15)
        time.sleep(2.0)
        for _ in range(6):
            out = self.shell(serial, "id -u", timeout=10)
            for line in out.splitlines():
                if line.strip() == "0":
                    return True
            if "not found" in out:
                return False
            time.sleep(1.0)
        return False


# ----------------------------------------------------------------- 主流程

class Capture:
    def __init__(self, args):
        self.args = args
        self.adb = None
        self.devices: List[Device] = []
        self.procs: List[subprocess.Popen] = []
        self.flags: Dict[str, dict] = {}
        self._mitmdump: Optional[str] = None
        self.exported: set = set()
        self.ignore_patterns: List[str] = (
            [p.strip() for p in args.ignore.split(",") if p.strip()]
            if getattr(args, "ignore", None) else list(IGNORE_HOSTS)
        )

    # ------------------------------------------------------------- 环境
    @property
    def mitmdump(self) -> str:
        if self._mitmdump is None:
            self._mitmdump = self._find_mitmdump()
        return self._mitmdump

    def _find_mitmdump(self) -> str:
        local = HERE / ".venv" / "Scripts" / "mitmdump.exe"
        if local.is_file():
            return str(local)
        which = shutil.which("mitmdump")
        if which:
            return which
        print("[!] 没找到 mitmdump，请先运行 setup_env.bat 安装依赖。")
        sys.exit(2)

    def engine_base(self) -> List[str]:
        """抓包引擎的启动命令。

        打包成 exe 后没有独立的 mitmdump.exe，就用自己再启动一个 `--mitmdump` 角色；
        源码运行时才去调 .venv 里的 mitmdump。
        """
        if FROZEN:
            return [sys.executable, "--mitmdump"]
        return [self.mitmdump]

    def _adb(self) -> Adb:
        path = find_adb(self.args.adb)
        if not path:
            print("[!] 没找到 adb。请用 --adb 指定，或先开一次模拟器。")
            sys.exit(2)
        return Adb(path)

    # ------------------------------------------------------------- 发现
    def discover(self) -> None:
        adb = self.adb
        if self.args.launch:
            self._launch_instances()

        # 各家模拟器的 adb 端口不一样：先并行探一下哪些在监听，再逐个握手
        for port in open_ports(ADB_PORT_HINTS):
            adb.connect(port)
        time.sleep(0.8)
        serials = adb.devices()

        if not serials:
            print("[!] 没有连接上的模拟器。检查：")
            print("    1) 模拟器已启动；2) 已开启 root/adb 调试；")
            print("    3) 端口不在默认列表时，用 --adb 指定模拟器自带的 adb.exe，")
            print("       或先手动 `adb connect 127.0.0.1:<端口>` 再运行。")
            return

        for serial in serials:
            device = Device(serial=serial)
            props = adb.shell(
                serial,
                "getprop ro.product.model; getprop ro.build.version.release", timeout=10)
            lines = [ln.strip() for ln in props.splitlines() if ln.strip()]
            device.model = lines[0] if lines else "?"
            device.android = lines[1] if len(lines) > 1 else "?"
            pkgs = adb.shell(serial, "pm list packages", timeout=25)
            device.packages = sorted({p.split(":", 1)[1] for p in pkgs.splitlines() if p.startswith("package:")})
            device.root = adb.shell(serial, "id -u", timeout=10).strip().splitlines()[:1] == ["0"]
            self._classify(device)
            self.devices.append(device)

        override = self._parse_map(self.args.map)
        for device in self.devices:
            if device.serial in override:
                key = override[device.serial]
                display = display_for(key)
                device.key, device.display = key, display
                if not device.pkg:
                    device.pkg = next((n for k, _, names in PACKAGE_RULES if k == key
                                       for n in names), "")
        # 手动映射也可能指定没装游戏的设备
        for serial, key in override.items():
            if not any(d.serial == serial for d in self.devices):
                display = display_for(key)
                self.devices.append(Device(serial=serial, key=key, display=display, model="手动映射"))

    def _classify(self, device: Device) -> None:
        # 1) 已知包名
        for key, display, names in PACKAGE_RULES:
            for name in names:
                if name in device.packages:
                    device.key, device.display, device.pkg = key, display, name
                    return
        # 2) 简中服渠道包：com.bilibili.fgo.<渠道后缀>
        for pkg in device.packages:
            if pkg.startswith("com.bilibili.fgo."):
                suffix = pkg.rsplit(".", 1)[-1].lower()
                display = CN_CHANNELS.get(suffix)
                if display:
                    device.key = "huawei" if suffix == "huawei" else suffix
                    device.display, device.pkg = display, pkg
                    return
                # 认不出具体渠道，但至少知道是简中渠道服
                device.key, device.display, device.pkg = "cn_channel", "简中渠道服", pkg
                return
        # 3) 关键字兜底
        for key, display, token in NAME_RULES:
            for pkg in device.packages:
                if token in pkg and any(t in pkg for t in ("fgo", "fate", "fateg", "fgetw")):
                    device.key, device.display, device.pkg = key, display, pkg
                    return
        # 4) 装了 FGO 但完全认不出（繁中服/美服/未知渠道）：仍然抓，名字叫「未识别FGO」
        for pkg in device.packages:
            if any(t in pkg for t in ("fgo", "fate", "fateg", "fgetw")) and pkg.count(".") >= 2:
                device.key, device.display, device.pkg = "unknown", "未识别FGO", pkg
                return

    def _parse_map(self, spec: Optional[str]) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for chunk in (spec or "").split(","):
            chunk = chunk.strip()
            if not chunk or "=" not in chunk:
                continue
            serial, key = chunk.split("=", 1)
            out[serial.strip()] = key.strip()
        return out

    def _launch_instances(self) -> None:
        ldconsole = None
        for base in LDPLAYER_DIRS:
            path = Path(base) / "ldconsole.exe"
            if path.is_file():
                ldconsole = str(path)
                break
        if not ldconsole:
            print("[i] 没找到 ldconsole.exe，跳过自动启动。")
            return
        proc = run([ldconsole, "list2"], timeout=20)
        indexes = []
        for line in proc.stdout.splitlines():
            parts = line.split(",")
            if parts and parts[0].strip().isdigit():
                indexes.append(int(parts[0].strip()))
        for index in indexes:
            run([ldconsole, "launch", "--index", str(index)], timeout=20)
        if indexes:
            print("[i] 已请求启动 %d 个雷电实例，等待起来……" % len(indexes))
            time.sleep(8)

    # ------------------------------------------------------------- 计划
    def assign(self) -> None:
        base = Path(self.args.out) if self.args.out else HERE / "out"
        if not self.args.out:
            base = base / datetime.now().strftime("%Y%m%d-%H%M%S")
        self.run_dir = base

        chosen = [d for d in self.devices if d.key and (not self.args.only or d.key in self.args.only.split(","))]
        chosen.sort(key=lambda d: ("huawei", "bilibili", "jp").index(d.key) if d.key in ("huawei", "bilibili", "jp") else 9)
        self.devices = chosen
        port = self.args.port_base
        for device in chosen:
            # 上一次运行残留的监听会让新引擎 bind 失败，直接跳过被占用的端口
            device.port = free_port(port)
            port = device.port + 1
            device.outdir = base / device.display

    # ------------------------------------------------------------- 打印
    def show_devices(self) -> None:
        if not self.devices:
            print("（没有设备）")
            return
        print("\n%-18s %-10s %-7s %-6s %-12s %s" % ("序列号", "机型", "安卓", "root", "识别为", "游戏包名"))
        print("-" * 96)
        for device in self.devices:
            print("%-18s %-10s %-7s %-6s %-12s %s" % (
                device.serial, device.model[:10], device.android or "?",
                "已是" if device.root else "需提权", device.display or "未识别",
                device.pkg or "-"))
        unknown = [d for d in self.devices if not d.key]
        if unknown:
            print("\n[i] %d 台没识别到 FGO，可用 --map %s=jp|bilibili|huawei 手动指定"
                  % (len(unknown), unknown[0].serial))
        print()

    # ------------------------------------------------------------- 证书
    def ensure_ca(self) -> Path:
        CONFDIR.mkdir(parents=True, exist_ok=True)
        cert = CONFDIR / "mitmproxy-ca-cert.pem"
        if cert.exists():
            return cert
        port = free_port(8899)
        proc = subprocess.Popen(
            self.engine_base() + ["-q", "--set", "confdir=%s" % CONFDIR, "-p", str(port)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=self._env(FGO_OUTDIR=str(HERE / "conf" / "_init"), FGO_LABEL="_init"),
        )
        try:
            for _ in range(80):
                if cert.exists():
                    return cert
                if proc.poll() is not None:
                    break
                time.sleep(0.25)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        if not cert.exists():
            print("[!] mitmproxy 没生成根证书，检查 %s" % CONFDIR)
            sys.exit(2)
        return cert

    def cert_hash(self, cert: Path) -> str:
        try:
            from cryptography import x509  # mitmproxy 依赖，装了就有
            parsed = x509.load_pem_x509_certificate(cert.read_bytes())
            digest = hashlib.md5(parsed.subject.public_bytes()).hexdigest()
            return digest[:8]
        except Exception:
            print("[i] 未装 cryptography，使用 mitmproxy 默认证书哈希 c8750f0d")
            return "c8750f0d"

    def _ca_mounted(self, device: Device) -> bool:
        """bind mount 的源路径在 /proc/mounts 里看不到，只能看 mountinfo 的第 4 字段。"""
        out = self.adb.shell(device.serial,
                             "grep -c '%s' /proc/self/mountinfo" % CA_DIR_REMOTE.strip("/"))
        return out.strip().splitlines()[:1] == ["1"] or (out.strip().isdigit() and int(out.strip()) > 0)

    def install_ca(self, device: Device, cert: Path, cert_hash: str) -> bool:
        remote = "%s/%s.0" % (CA_DIR_REMOTE, cert_hash)
        mounted = self._ca_mounted(device)
        already = bool(mounted)
        seeded = self.adb.shell(device.serial, "ls %s/.seeded 2>/dev/null" % CA_DIR_REMOTE).strip()
        # 只在「还没挂载、也没播过种」时复制一次原厂证书，避免把挂载点复制进它自己
        if not already and not seeded:
            self.adb.shell(
                device.serial,
                "mkdir -p %s && cp -a /system/etc/security/cacerts/. %s/ && touch %s/.seeded"
                % (CA_DIR_REMOTE, CA_DIR_REMOTE, CA_DIR_REMOTE), timeout=60)
        push = self.adb("-s", device.serial, "push", str(cert), remote, timeout=30)
        if push.returncode != 0 and "No such file" in (push.stderr or ""):
            self.adb.shell(device.serial, "mkdir -p %s" % CA_DIR_REMOTE)
            push = self.adb("-s", device.serial, "push", str(cert), remote, timeout=30)
        if push.returncode != 0:
            print("[!] %s 推送证书失败：%s" % (device.serial, push.stderr.strip()[:120]))
            return False
        self.adb.shell(device.serial, "chmod 755 %s; chmod 644 %s/*" % (CA_DIR_REMOTE, CA_DIR_REMOTE))
        self.adb.shell(device.serial,
                       "chcon u:object_r:system_security_cacerts_file:s0 %s 2>/dev/null; true" % remote)
        if not already:
            self.adb.shell(device.serial,
                           "mount -o bind %s /system/etc/security/cacerts" % CA_DIR_REMOTE)
        check = self.adb.shell(device.serial,
                               "ls /system/etc/security/cacerts/%s.0 2>/dev/null" % cert_hash).strip()
        return bool(check)

    # ------------------------------------------------------------- 代理
    def setup_proxy(self, device: Device) -> bool:
        port = device.port
        reverse = self.adb("-s", device.serial, "reverse", "tcp:%d" % port, "tcp:%d" % port, timeout=20)
        if reverse.returncode == 0:
            device.proxy_mode = "reverse"
            host = "127.0.0.1"
        else:
            device.proxy_mode = "gateway"
            route = self.adb.shell(device.serial, "ip route 2>/dev/null | grep default", timeout=10)
            match = re.search(r"via (\d+\.\d+\.\d+\.\d+)", route)
            host = match.group(1) if match else "10.0.2.2"
        self.adb.shell(device.serial, "settings put global http_proxy %s:%d" % (host, port))
        self.flags[device.serial] = {"proxy": "%s:%d" % (host, port), "port": port}
        return True

    def restore(self, device: Device, unmount_ca: bool = True) -> None:
        try:
            self.adb.shell(device.serial, "settings put global http_proxy :0", timeout=15)
        except Exception:
            pass
        try:
            self.adb("-s", device.serial, "reverse", "--remove", "tcp:%d" % device.port, timeout=10)
        except Exception:
            pass
        if unmount_ca:
            try:
                # 历史运行可能叠了多层 bind mount，逐个卸干净
                for _ in range(10):
                    if not self._ca_mounted(device):
                        break
                    self.adb.shell(device.serial,
                                   "umount /system/etc/security/cacerts", timeout=20)
                if self._ca_mounted(device):  # 还有就懒卸载
                    self.adb.shell(device.serial,
                                   "umount -l /system/etc/security/cacerts 2>/dev/null", timeout=20)
                if self._ca_mounted(device):
                    print("    [!] %s 的系统证书还挂着，重启模拟器或跑 --clean 再卸"
                          % device.serial)
            except Exception:
                pass

    # ------------------------------------------------------------- 引擎
    def stop_game(self, device: Device) -> None:
        """先杀掉还在跑的 FGO 进程。

        游戏进程在启动时就把「系统证书列表」读进内存了；抓包前如果它已经在跑，
        它不认我们新装的证书，所有请求都会 TLS 失败（画面表现为连接断开/登录失败）。
        """
        if not device.pkg or self.args.no_kill:
            return
        pid = self.adb.shell(device.serial, "pidof %s" % device.pkg, timeout=10).strip()
        if not pid:
            return
        self.adb.shell(device.serial, "am force-stop %s" % device.pkg, timeout=15)
        print("    %s 发现游戏还在运行（pid %s），已结束旧进程——请重新打开游戏"
              % (device.display, pid.split()[0]))

    def _env(self, **extra) -> dict:
        env = os.environ.copy()
        env.update({k: str(v) for k, v in extra.items()})
        return env

    def start_engine(self, device: Device) -> None:
        device.outdir.mkdir(parents=True, exist_ok=True)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        log = (self.run_dir / "_engines.log").open("a", encoding="utf-8")
        env = self._env(
            FGO_OUTDIR=str(device.outdir), FGO_LABEL=device.key,
            FGO_DISPLAY=device.display, FGO_DEVICE=device.serial,
            FGO_PKG=device.pkg, FGO_PORT=device.port,
            FGO_DUMP_FLOW="1" if self.args.flow_dump else "0",
        )
        cmd = self.engine_base() + ["-q",
               "--set", "confdir=%s" % CONFDIR,
               # 账号全量数据响应很大（简中服 ac.php 10MB、日服 login/top 5.6MB）。
               # 注意 0 在 mitmproxy 里等于「全都 stream」，那样插件拿不到 body，
               # 所以这里给一个远大于账号数据、又不会把资源 CDN 拖进来的阈值
               # （资源 CDN 已经在 ignore_hosts 里，根本不经过解密）。
               "--set", "stream_large_bodies=64m",
               "--set", "body_size_limit=256m",
               "--set", "flow_detail=0",
               "-p", str(device.port),
               "-s", str(ADDON)]
        proc = subprocess.Popen(cmd, stdout=log, stderr=log, env=env)
        device.engine = proc
        self.procs.append(proc)
        print("[+] %s 引擎已启动：%s -> %s" % (device.display, device.serial, device.outdir))

    # ------------------------------------------------------------- 状态
    def all_exported(self) -> bool:
        """所有目标服都已经拿到 Chaldea 导入文件。"""
        if not self.devices:
            return False
        for device in self.devices:
            status_file = device.outdir / "status.json"
            if not status_file.exists():
                return False
            try:
                data = json.loads(status_file.read_text(encoding="utf-8"))
            except Exception:
                return False
            if not data.get("has_chaldea"):
                return False
        return True

    def monitor_once(self) -> List[str]:
        lines = []
        for device in self.devices:
            status_file = device.outdir / "status.json"
            if not status_file.exists():
                lines.append("  %-10s 等待第一条流量……" % device.display)
                continue
            try:
                data = json.loads(status_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            if device.engine is not None and device.engine.poll() is not None:
                lines.append("  %-10s [!] 引擎已退出，看 %s" % (device.display, self.run_dir / "_engines.log"))
                continue
            mark = "★导入文件已生成" if data.get("has_chaldea") else (
                "authkey ✓" if data.get("has_authkey") else "尚未抓到登录")
            region = data.get("region") or ""
            uid = (" uid=%s" % data["uid"]) if data.get("uid") else ""
            lines.append("  %-10s %-10s 游戏接口 %-4d 其他 %-4d 资源 %-4d %s%s"
                         % (device.display, region, data.get("game", 0),
                            data.get("total", 0), data.get("asset", 0), mark, uid))
        return lines

    # ------------------------------------------------------------- 引擎配置
    def write_engine_config(self) -> None:
        """把「不解密的域名」写进 confdir/config.yaml。

        注意：命令行 `--set ignore_hosts=a,b,c` 只会被当成**一个**正则字符串
        （实测 mitmproxy 12 不按逗号拆分），所以必须走配置文件写成 YAML 列表。
        """
        CONFDIR.mkdir(parents=True, exist_ok=True)
        config = {"ignore_hosts": self.ignore_patterns}
        (CONFDIR / "config.yaml").write_text(
            json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # ------------------------------------------------------------- 收尾
    def export_chaldea(self) -> List[tuple]:
        """把各服最新的 topLogin 导入文件汇总到一个「导入文件」目录，方便手动导入。"""
        exports = self.run_dir / "导入文件"
        found: List[tuple] = []
        for device in self.devices:
            folder = device.outdir / "chaldea"
            if not folder.exists():
                continue
            files = [p for p in folder.glob("toplogin_*.json")
                     if not p.name.endswith(".decoded.json")]
            if not files:
                continue
            # 取最大的那份：账号数据越全文件越大，避免拿到增量/半截响应
            newest = max(files, key=lambda p: p.stat().st_size)
            region = ""
            try:
                status = json.loads((device.outdir / "status.json").read_text(encoding="utf-8"))
                region = (status.get("region") or "").strip()
            except Exception:
                pass
            exports.mkdir(parents=True, exist_ok=True)
            # 文件名里带上区服，导入 Chaldea 时不会选错（简中服 iOS 区/安卓区/渠道服）
            label = device.display if not region or region in device.display else "%s_%s" % (
                device.display, region.replace("简中服-", ""))
            dest = exports / ("%s_toplogin.json" % label)
            shutil.copyfile(newest, dest)
            self.exported.add(device.serial)
            found.append((label, dest))
        if found:
            lines = ["Chaldea 导入文件（原样导入，勿改内容）", ""]
            for display, dest in found:
                lines.append("%s -> %s" % (display, dest.name))
            lines += ["", "Chaldea → 工具箱/导入数据 → 选择对应区服 → 选上面的文件。",
                      "文件名里带「安卓区 / iOS区 / 渠道服」的，就选对应那个区服。", ""]
            (exports / "README.txt").write_text("\n".join(lines), encoding="utf-8")
        return found

    def write_run_readme(self) -> None:
        run_dir = getattr(self, "run_dir", None)
        if run_dir is None:
            return
        run_dir.mkdir(parents=True, exist_ok=True)
        lines = [
            "FGO 抓包 —— %s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "",
            "目录对应关系：",
        ]
        for device in self.devices:
            lines.append("  %-12s <- %s  %s" % (device.display or "未识别", device.serial, device.pkg or "-"))
        lines += [
            "",
            "每个目录里：",
            "  chaldea/   toplogin_*.json —— 直接导入 Chaldea 的文件（本目录「导入文件/」有汇总）",
            "  game/      FGO 业务接口（登录/抽卡/编队……）",
            "  flows/     其他请求（含 SDK、推送等）",
            "  index.csv  索引",
            "  auth.json  authkey/uid 等（勿外传）",
            "  summary.md 本次汇总",
            "",
        ]
        (run_dir / "README.txt").write_text("\n".join(lines), encoding="utf-8")

    def shutdown(self) -> None:
        print("\n[i] 收尾：还原代理 / 卸载证书 / 停止引擎")
        for device in self.devices:
            if device.serial in self.flags:
                self.restore(device, unmount_ca=not self.args.keep_ca)
                print("    %s 已还原" % device.serial)
        for device in self.devices:
            if device.engine and device.engine.poll() is None:
                device.engine.terminate()
        for proc in self.procs:
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
        self.write_run_readme()
        found = self.export_chaldea()
        if found:
            print("\n[★] Chaldea 导入文件：")
            for display, dest in found:
                print("    %-10s %s" % (display, dest))
        else:
            print("\n[!] 没抓到登录响应，没有生成导入文件。进游戏直到出现地球仪/公告页再抓一次。")

        if not self.args.keep_all:
            self.cleanup_run()

    def cleanup_run(self) -> None:
        """只留导入文件：把本次导出了的服目录整个删掉（flows/game/index/auth…全不要）。

        没抓到导入文件的服保留全部，方便排查。
        """
        removed = 0
        for device in self.devices:
            outdir = getattr(device, "outdir", None)
            if not outdir or not outdir.exists():
                continue
            if device.serial not in self.exported:
                continue
            try:
                shutil.rmtree(outdir)
                removed += 1
            except Exception:
                pass
        try:
            (self.run_dir / "_engines.log").unlink()
        except Exception:
            pass
        if removed:
            print("\n[i] 已清理中间文件，只保留「导入文件」目录（%d 个服的明细已删除）" % removed)
            print("    下次想保留明细排查，加 --keep-all")

    # ------------------------------------------------------------- 入口
    def run(self) -> int:
        self.adb = self._adb()
        print("[i] adb: %s" % self.adb.path)

        self.discover()
        self.show_devices()
        if self.args.list:
            return 0
        if not self.devices:
            return 1
        if not FROZEN:
            print("[i] mitmdump: %s" % self.mitmdump)

        # root
        for device in self.devices:
            device.root = self.adb.root(device.serial)
        for device in self.devices:
            if device.key and not device.root:
                print("[!] %s 拿不到 root，系统证书装不进去；华为/日服这类 targetSdk≥24 的包会抓不到 HTTPS。"
                      % device.serial)

        self.assign()
        targets = [d for d in self.devices if d.key and d.port]
        if not targets:
            print("[!] 没有可抓的目标设备。用 --map <序列号>=jp|bilibili|huawei 指定。")
            return 1

        print("\n抓包计划：")
        for device in targets:
            print("  %-10s %-18s 端口 %d -> %s" % (device.display, device.serial, device.port, device.outdir))
        if self.args.dry_run:
            return 0

        cert = self.ensure_ca()
        self.write_engine_config()
        cert_hash = self.cert_hash(cert)
        print("\n[i] 根证书：%s（Android 哈希 %s.0）" % (cert, cert_hash))

        ok_devices = []
        for device in targets:
            installed = self.install_ca(device, cert, cert_hash)
            print("    %-10s 系统证书 %s" % (device.display, "已挂载" if installed else "安装失败"))
            if not installed:
                print("      → 该服抓不到 HTTPS。可在模拟器设置里确认「root 权限」已开启。")
            self.setup_proxy(device)
            self.stop_game(device)
            self.start_engine(device)
            ok_devices.append(device)
        self.devices = ok_devices

        print("""
==================== 开始抓包 ====================
现在去三个模拟器里打开 FGO，**进到出现地球仪 / 公告页**（登录完成即可）。
· 登录响应会立刻存成 Chaldea 的导入文件（窗口里看到「★导入文件已生成」就成了）
· 三个服都拿到后会自动停止；也可以随时按 Ctrl+C
· 输出目录：%s
=================================================""" % self.run_dir)

        deadline = time.time() + self.args.duration if self.args.duration else None
        auto_stop = self.args.auto_stop or len(sys.argv) == 1
        last = 0.0
        try:
            while True:
                now = time.time()
                if deadline and now > deadline:
                    print("\n[i] 到达 --duration 时间，停止抓包")
                    break
                if auto_stop and now - last >= 3 and self.all_exported():
                    print("\n[i] 三个服的导入文件都拿到了，自动停止")
                    break
                if now - last >= 5:
                    print("\n--- %s ---" % datetime.now().strftime("%H:%M:%S"))
                    for line in self.monitor_once():
                        print(line)
                    last = now
                time.sleep(1.0)
        except KeyboardInterrupt:
            print("\n[i] 收到 Ctrl+C")
        finally:
            self.shutdown()

        print("\n[i] 完成。结果在：%s" % self.run_dir)
        for device in self.devices:
            summary = device.outdir / "summary.md"
            if summary.exists():
                print("    %s -> %s" % (device.display, summary))
        return 0

    def clean(self) -> int:
        self.adb = self._adb()
        self.discover()
        self.show_devices()
        for device in self.devices:
            self.adb.root(device.serial)
            self.restore(device, unmount_ca=True)
            print("[i] %s 代理/证书已清理" % device.serial)
        return 0


def _prepare_console() -> None:
    """让中文在任何代码页下都能正常显示（exe 双击运行时尤其重要）。"""
    if os.name == "nt":
        try:
            os.system("chcp 65001 >nul 2>nul")
        except Exception:
            pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace",
                               line_buffering=True)
        except Exception:
            pass


def _mitmdump_role(args: List[str]) -> int:
    """exe 自己充当抓包引擎（打包版没有独立 mitmdump.exe）。"""
    try:
        from mitmproxy.tools.main import mitmdump
    except Exception as exc:  # 依赖没打进去时给出明确提示
        print("[!] 内置 mitmproxy 加载失败：%r" % exc)
        return 2
    try:
        mitmdump(args)
    except SystemExit as exc:
        return int(exc.code or 0)
    except KeyboardInterrupt:
        return 0
    return 0


def main() -> int:
    _prepare_console()
    argv = sys.argv[1:]
    if argv[:1] == ["--mitmdump"]:
        return _mitmdump_role(argv[1:])
    if argv[:1] == ["--make-import"]:
        from make_import import main as import_main
        return import_main(argv[1:])

    parser = argparse.ArgumentParser(
        description="FGO 三服多模拟器抓包（华为渠道服 / 简中B服 / 日服）")
    parser.add_argument("--adb", help="adb.exe 路径")
    parser.add_argument("--out", help="输出根目录（默认 out/<时间戳>）")
    parser.add_argument("--port-base", type=int, default=8081, help="起始代理端口")
    parser.add_argument("--only", help="只抓这些服，逗号分隔：jp,bilibili,huawei")
    parser.add_argument("--map", help="手动映射：emulator-5554=jp,emulator-5556=bilibili")
    parser.add_argument("--list", action="store_true", help="只列出设备识别结果")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不做任何修改")
    parser.add_argument("--clean", action="store_true", help="清理代理设置与系统证书")
    parser.add_argument("--launch", action="store_true", help="先用 ldconsole 启动物理实例")
    parser.add_argument("--duration", type=int, default=0, help="抓多少秒后自动停（0=一直抓）")
    parser.add_argument("--flow-dump", action="store_true", help="额外写 traffic.flow（可用 mitmweb 打开）")
    parser.add_argument("--keep-ca", action="store_true", help="退出时不卸载系统证书")
    parser.add_argument("--ignore", help="不做解密的域名正则（逗号分隔），默认已排除 HMS/bilibili SDK 等")
    parser.add_argument("--auto-stop", action="store_true",
                        help="所有服都拿到导入文件后自动停止（不带参数双击运行时默认开启）")
    parser.add_argument("--no-kill", action="store_true",
                        help="不要自动结束正在运行的 FGO 进程（默认会结束，否则旧进程不认新证书）")
    parser.add_argument("--keep-all", action="store_true",
                        help="抓完保留全部中间文件；默认只留「导入文件」")
    args = parser.parse_args()

    capture = Capture(args)
    try:
        return capture.clean() if args.clean else capture.run()
    except KeyboardInterrupt:
        return 0
    except SystemExit:
        raise
    except Exception as exc:
        print("[!] 出错：%r" % exc)
        try:
            capture.shutdown()
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
