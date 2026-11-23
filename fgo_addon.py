#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fgo_addon.py —— FGO 抓包用的 mitmproxy 插件。

由 capture.py 以子进程方式调用，每个模拟器一个进程、一个输出目录：

    mitmdump -p 8081 -s fgo_addon.py

环境变量（由 capture.py 注入）：
    FGO_OUTDIR   本服务器输出目录
    FGO_LABEL    服务器标识，如 jp / bilibili / huawei
    FGO_DISPLAY  服务器中文名，如 日服
    FGO_DEVICE   adb 序列号
    FGO_PKG      游戏包名
    FGO_PORT     本服代理端口
    FGO_DUMP_FLOW  "1" 时额外写 traffic.flow（可用 mitmweb 打开回放）

输出：
    flows/   每个请求一个 json（请求头/请求体/响应头/响应体）
    game/    仅 FGO 业务接口（同上格式，便于直接看）
    index.csv 总索引
    auth.json 抓到的 authkey / uid 等凭据（填进 Chaldea 用）
    errors.log TLS 握手失败等错误（多半是证书没被信任）
    status.json 进度，供 capture.py 轮询显示
"""
from __future__ import annotations

import base64
import csv
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, unquote_plus

from mitmproxy import ctx, http

# ---------------------------------------------------------------- 规则定义

# 明确的 FGO 域名（各服都覆盖）
GAME_HOST_RE = re.compile(
    r"(fate-?go|fategrandorder|aniplex|biligame)", re.I
)
# FGO 常见接口路径前缀
GAME_PATH_RE = re.compile(
    r"^/("
    r"login|top|gacha|battle|home|friend|deck|user|item|shop|event|script|"
    r"mission|summon|card|servant|formation|storage|team|raid|war|treasure|"
    r"box|quest|tutorial|message|present|support|profile|help|banner"
    r")", re.I
)
# 纯噪音，直接跳过（这些请求仍然放行，只是不落盘）
NOISE_RE = re.compile(
    r"(mitm\.it|mitmproxy|gstatic|googleapis|google\.com|googleusercontent|"
    r"crashlytics|app-measurement|doubleclick|facebook|umeng|bugly|sentry|"
    r"appsflyer|adjust\.com|azureedge|akamai)", re.I
)
# 资源类（图片/音频/大文件），只记元信息不存正文
ASSET_RE = re.compile(
    r"\.(png|jpe?g|webp|gif|mp3|ogg|m4a|wav|mp4|zip|apk|dat|bin|assetbundle|"
    r"unity3d|bundle|bytes)(\?|$)", re.I
)
# 凭据字段（Chaldea 需要 authkey + user_id）
CRED_KEY_RE = re.compile(
    r"^(authkey|auth_key|user_?id|uid|device_?id|secret|token|session_?key)$", re.I
)

MAX_INLINE_BODY = 512 * 1024  # 超过这个大小的响应体不存正文

# 从游戏接口域名反推「区服」——同一个安卓客户端，账号在 iOS 区还是渠道服，
# 看的是它连哪组服务器（这是 Chaldea 导入时真正要选的那个区服）
REGION_RULES = [
    (re.compile(r"-ios-fate", re.I), "简中服-iOS区"),
    (re.compile(r"-bili-fate", re.I), "简中服-安卓区"),
    (re.compile(r"-uo-fate", re.I), "简中服-渠道服"),
    (re.compile(r"fate-go\.jp", re.I), "日服"),
    (re.compile(r"fate-go\.us", re.I), "美服"),
    (re.compile(r"fate-go\.com\.tw", re.I), "繁中服"),
    (re.compile(r"fate-go\.co?\.?kr", re.I), "韩服"),
]


def detect_region(host: str) -> str:
    for pattern, name in REGION_RULES:
        if pattern.search(host):
            return name
    return ""


def _log(level: str, message: str, *args) -> None:
    """ctx.log 只在 mitmproxy 运行时存在，且它只接受一个已格式化的字符串。"""
    log = getattr(ctx, "log", None)
    if log is None:
        return
    try:
        text = message % args if args else message
    except Exception:
        text = message
    getattr(log, level)(text)


def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _slug(text: str, maxlen: int = 90) -> str:
    text = text.split("?")[0]
    text = re.sub(r"[^0-9A-Za-z._/-]+", "_", text)
    text = text.strip("_/").replace("/", "-")
    return (text[:maxlen] or "root").strip("-")


def _decode_text(value, limit: int = MAX_INLINE_BODY):
    """bytes -> str / dict / list；超限或非文本返回 None。"""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        return value
    if isinstance(value, (bytes, bytearray)):
        if len(value) > limit:
            return None
        for enc in ("utf-8", "gb18030", "shift_jis"):
            try:
                return value.decode(enc)
            except UnicodeDecodeError:
                continue
        return None
    return None


def _parse_pairs(text: str) -> dict:
    """把 a=1&b=2 风格或 data={json} 风格解析成 dict。"""
    out = {}
    if not text:
        return out
    for part in text.split("&"):
        if "=" not in part:
            continue
        key, _, val = part.partition("=")
        key, val = unquote_plus(key), unquote_plus(val)
        out[key] = val
        if val[:1] in "{[":
            try:
                inner = json.loads(val)
            except Exception:
                inner = None
            if isinstance(inner, dict):
                out.update({k: v for k, v in inner.items()
                            if isinstance(v, (str, int, float))})
    return out


def _payload_from_bytes(raw: bytes):
    """从响应体里取出可读 JSON：兼容明文 / base64 / URL编码的 base64（简中服 ac.php）。"""
    text = raw.decode("utf-8", "ignore").strip()
    if text[:2] == "ey":  # base64（简中服/繁中服常常再套一层 URL 编码：%3D%3D）
        fixed = unquote(text) if "%" in text else text
        fixed = fixed.strip()
        try:
            return base64.b64decode(fixed + "=" * (-len(fixed) % 4))
        except Exception:
            return None
    if text[:1] in "{[":
        return raw
    return None


class FgoCapture:
    def __init__(self) -> None:
        self.out = Path(os.environ.get("FGO_OUTDIR", "out"))
        self.label = os.environ.get("FGO_LABEL", "unknown")
        self.display = os.environ.get("FGO_DISPLAY", self.label)
        self.device = os.environ.get("FGO_DEVICE", "")
        self.pkg = os.environ.get("FGO_PKG", "")
        self.dump_flow = os.environ.get("FGO_DUMP_FLOW", "0") == "1"

        self.seq = 0
        self.stats = {"total": 0, "game": 0, "asset": 0, "skipped": 0}
        self.auth: dict = {}
        self.chaldea_files: list = []
        self.region: str = ""
        self._index_fh = None
        self._index = None
        self._flow_fh = None
        self._flow_writer = None
        self._last_status = 0.0

    # ------------------------------------------------------------ 生命周期
    def load(self, loader) -> None:  # noqa: ARG002
        self.out.mkdir(parents=True, exist_ok=True)
        (self.out / "flows").mkdir(exist_ok=True)
        (self.out / "game").mkdir(exist_ok=True)

        index_path = self.out / "index.csv"
        new_file = not index_path.exists() or index_path.stat().st_size == 0
        self._index_fh = index_path.open("a", encoding="utf-8", newline="")
        self._index = csv.writer(self._index_fh)
        if new_file:
            self._index.writerow(
                ["seq", "time", "method", "host", "path", "status",
                 "req_bytes", "resp_bytes", "kind", "cred", "file"]
            )
            self._index_fh.flush()

        if self.dump_flow:
            from mitmproxy import io

            self._flow_fh = (self.out / "traffic.flow").open("ab")
            self._flow_writer = io.FlowWriter(self._flow_fh)

        meta = {
            "label": self.label,
            "display": self.display,
            "device": self.device,
            "package": self.pkg,
            "started_at": _ts(),
            "proxy_port": os.environ.get("FGO_PORT", ""),
        }
        (self.out / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self._write_status(force=True)
        _log("info", "[%s] 输出目录 %s（端口 %s）", self.display, self.out,
             meta["proxy_port"] or "?")

    def done(self) -> None:
        for fh in (self._index_fh, self._flow_fh):
            try:
                if fh:
                    fh.close()
            except Exception:
                pass
        self._write_summary()
        self._write_status(force=True)
        _log("info", "[%s] 结束：共 %d 条，游戏接口 %d 条，凭据 %s",
             self.display, self.stats["total"], self.stats["game"],
             "已抓到" if self.auth.get("authkey") else "未抓到")

    # ------------------------------------------------------------ 事件回调
    def request(self, flow: http.HTTPFlow) -> None:
        flow.metadata["fgo_t0"] = time.time()

    def response(self, flow: http.HTTPFlow) -> None:
        try:
            self._handle(flow)
        except Exception as exc:  # 抓包插件绝不能把流量打挂
            _log("warn", "[%s] 处理失败 %s: %r", self.display, flow.request.path, exc)
        finally:
            self._write_status()

    def error(self, flow: http.HTTPFlow) -> None:
        self._log_error("%s %s -> %s" % (flow.request.method,
                                         flow.request.pretty_url, flow.error))

    def tls_failed_client(self, data) -> None:
        # 尽量把是谁失败记下来，否则日志里全是 '?' 没法排查
        sni = ""
        for attr in ("conn", "context"):
            obj = getattr(data, attr, None)
            for name in ("sni", "servername"):
                value = getattr(obj, name, None)
                if isinstance(value, str) and value:
                    sni = value
                    break
            if sni:
                break
        client = getattr(getattr(data, "client_conn", None), "peername", None)
        if not sni:
            try:
                sni = str(getattr(data.conn, "sni", "")) or ""
            except Exception:
                sni = ""
        self._log_error("TLS 握手失败 sni=%s client=%s（该域名没被忽略，客户端又不信任我们的证书）"
                        % (sni or "?", client or "?"))

    # ------------------------------------------------------------ 主处理
    def _handle(self, flow: http.HTTPFlow) -> None:
        req, resp = flow.request, flow.response
        host = (req.pretty_host or "").lower()
        path = req.path.split("?")[0]
        is_noise = bool(NOISE_RE.search(host))

        req_text = _decode_text(req.get_content(strict=False))
        req_pairs = _parse_pairs(req_text) if isinstance(req_text, str) else {}
        if isinstance(req_text, str) and req_text.lstrip()[:1] == "{":
            try:
                body_json = json.loads(req_text)
            except Exception:
                body_json = None
            if isinstance(body_json, dict):
                req_pairs.update({k: v for k, v in body_json.items()
                                  if isinstance(v, (str, int, float))})

        cred_hit = {k: str(v) for k, v in req_pairs.items() if CRED_KEY_RE.match(k)}
        is_game = bool(GAME_HOST_RE.search(host)) or (
            bool(GAME_PATH_RE.match(path)) and bool(cred_hit)
        )
        ctype = (resp.headers.get("content-type", "") if resp else "").split(";")[0].strip().lower()
        is_asset = bool(ASSET_RE.search(path)) or ctype.startswith(
            ("image/", "video/", "audio/", "font/"))

        if cred_hit and is_game:
            self._record_auth(flow, cred_hit)
        if is_game and not self.region:
            found = detect_region(host)
            if found:
                self.region = found
                _log("info", "[%s] 识别到区服：%s（%s）", self.display, found, host)

        if is_noise and not is_game:
            self.stats["skipped"] += 1
            return

        self.seq += 1
        kind = "game" if is_game else ("asset" if is_asset else "other")
        self.stats["total"] += 1
        if is_game:
            self.stats["game"] += 1
        elif is_asset:
            self.stats["asset"] += 1

        record = self._build_record(flow, host, kind, cred_hit, is_asset)
        name = "%05d_%s_%s_%s.json" % (
            self.seq, datetime.now().strftime("%H%M%S"),
            req.method, _slug(host + path),
        )
        folder = "game" if is_game else "flows"
        target = self.out / folder / name
        target.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

        self._index.writerow([
            self.seq, record["time"], req.method, host, req.path,
            (resp.status_code if resp else ""),
            record["request"]["size"], (record["response"] or {}).get("size", 0),
            kind, ",".join(sorted(cred_hit)) if cred_hit else "",
            "%s/%s" % (folder, name),
        ])
        self._index_fh.flush()

        if self._flow_writer is not None:
            self._flow_writer.add(flow)

        self._maybe_export_chaldea(flow, path)

        if is_game:
            _log("info", "[%s] %s %s%s -> %s", self.display, req.method, host,
                 path[:70], resp.status_code if resp else "-")

    def _build_record(self, flow, host, kind, cred_hit, is_asset) -> dict:
        req, resp = flow.request, flow.response
        req_text = _decode_text(req.get_content(strict=False))
        resp_text = None
        resp_json = None
        if resp is not None:
            raw = resp.get_content(strict=False) or b""
            if not is_asset:
                resp_text = _decode_text(raw)
                if isinstance(resp_text, str) and resp_text.lstrip()[:1] in "{[":
                    try:
                        resp_json = json.loads(resp_text)
                    except Exception:
                        resp_json = None

        def headers(msg):
            if msg is None:
                return {}
            return {k: ("<redacted>" if k.lower() == "cookie" else v)
                    for k, v in msg.headers.items()}

        return {
            "time": _ts(),
            "kind": kind,
            "client": str(getattr(flow.client_conn, "peername", "")),
            "request": {
                "method": req.method,
                "scheme": req.scheme,
                "host": host,
                "path": req.path,
                "http_version": req.http_version,
                "headers": headers(req),
                "size": len(req.get_content(strict=False) or b""),
                "body": req_text,
                "credential_fields": cred_hit or None,
            },
            "response": None if resp is None else {
                "status": resp.status_code,
                "reason": resp.reason,
                "headers": headers(resp),
                "size": len(resp.get_content(strict=False) or b""),
                "body": resp_text,
                "json": resp_json,
            },
            "timing_ms": int((time.time() - flow.metadata.get("fgo_t0", time.time())) * 1000),
        }

    # ------------------------------------------------------------ 凭据
    def _record_auth(self, flow, cred: dict) -> None:
        req = flow.request
        changed = False
        for key, val in cred.items():
            lk = key.lower()
            if self.auth.get(lk) != val:
                self.auth[lk] = val
                changed = True
        self.auth["source_host"] = req.pretty_host
        self.auth["source_path"] = req.path.split("?")[0]
        self.auth["captured_at"] = _ts()
        self.auth["user_agent"] = req.headers.get("user-agent", "")
        if not changed and (self.out / "auth.json").exists():
            return
        (self.out / "auth.json").write_text(
            json.dumps(self.auth, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        full = {
            "hint": "把 authkey / user_id(uid) 填入 Chaldea 的抓包页面；本文件含账号凭据，勿外传",
            "auth": self.auth,
            "request": {
                "method": req.method,
                "url": req.pretty_url,
                "headers": dict(req.headers.items()),
                "body": _decode_text(req.get_content(strict=False)),
            },
        }
        (self.out / "auth_full.json").write_text(
            json.dumps(full, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ------------------------------------------------------------ Chaldea 导入文件
    def _maybe_export_chaldea(self, flow, path: str) -> None:
        """把「账号全量数据」的响应体原样存成 Chaldea 的 topLogin 导入文件。

        依据 Chaldea 官方文档：导入的就是登录流程里那条含 userServantList 的响应体，
        简中服/繁中服是 `ey` 开头的 base64，日服/美服是明文 json。
        不按路径判断（简中服是 topLogin.php、日服是 /login），只认内容里的
        userServantList —— 这才是 Chaldea 真正需要的东西。
        """
        resp = flow.response
        if resp is None:
            return
        raw = resp.get_content(strict=False) or b""
        if len(raw) < 20000:  # 全量账号数据至少几十 KB，小响应直接跳过
            return
        text = raw.decode("utf-8", "ignore").strip()
        payload = None
        if text[:2] == "ey":  # base64（简中服/繁中服，常再套一层 URL 编码：%3D%3D）
            payload = _payload_from_bytes(raw)
        elif text[:1] in "{[":
            payload = raw
        probe = payload or raw

        # 账号全量数据的特征字段：日服在 cache.replaced.userSvt / userItem，
        # 简中服/繁中服在 cache.replaced 里也是同一套名字（老版本用 userServantList）
        strict = any(m in probe for m in (
            b'"userSvt"', b'"userSvtStorage"', b'"userItem"', b'"userServantList"'))
        # 有些版本/区服的字段名会变，这里再兜一层：游戏 API 上 1MB 以上的
        # JSON 响应基本就是账号全量数据（login/top、ac.php?_key=toplogin）
        loose = (not strict and len(probe) >= 1024 * 1024
                 and probe.lstrip()[:1] in (b"{",) and b'"success"' in probe)
        # 再兜一层：按接口路径认（简中服 ac.php?_key=toplogin / 日服 /login/top）
        by_path = ("/login/top" in path
                   or ("ac.php" in path and "toplogin" in flow.request.path.lower()))
        if not (strict or loose or (by_path and len(raw) > 200000)):
            if len(raw) >= 2 * 1024 * 1024:  # 大响应但没命中，存一份原文方便排查
                dbg = self.out / "chaldea" / "_raw"
                dbg.mkdir(parents=True, exist_ok=True)
                stamp_dbg = datetime.now().strftime("%Y%m%d-%H%M%S")
                (dbg / ("%s_%s.raw" % (stamp_dbg, _slug(path, 30)))).write_bytes(raw)
                _log("warn", "[%s] %s%s 有 %d 字节响应但没认出账号数据，已存原文到 chaldea/_raw",
                     self.display, flow.request.pretty_host, path[:50], len(raw))
            return

        folder = self.out / "chaldea"
        folder.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = folder / ("toplogin_%s.json" % stamp)
        target.write_bytes(raw)  # 逐字节原样保存
        if payload is not raw:
            (folder / ("toplogin_%s.decoded.json" % stamp)).write_bytes(payload)
        self.chaldea_files.append(target.name)
        _log("info", "[%s] ★ Chaldea 导入文件：%s（%d 字节，来自 %s%s）",
             self.display, target, len(raw), flow.request.pretty_host, path[:40])

    # ------------------------------------------------------------ 辅助
    def _write_status(self, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._last_status < 0.5:
            return
        self._last_status = now
        payload = dict(self.stats)
        payload.update({
            "label": self.label,
            "display": self.display,
            "last_update": _ts(),
            "has_authkey": bool(self.auth.get("authkey")),
            "has_chaldea": bool(self.chaldea_files),
            "region": self.region,
            "uid": self.auth.get("user_id") or self.auth.get("uid") or "",
        })
        try:
            (self.out / "status.json").write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
        except Exception:
            pass

    def _log_error(self, message: str) -> None:
        try:
            with (self.out / "errors.log").open("a", encoding="utf-8") as fh:
                fh.write("%s %s\n" % (_ts(), message))
        except Exception:
            pass

    def _write_summary(self) -> None:
        cred = {k: v for k, v in self.auth.items()
                if k in ("authkey", "user_id", "uid", "deviceid", "device_id")}
        lines = [
            "# %s 抓包结果" % self.display,
            "",
            "- 设备：`%s`" % self.device,
            "- 包名：`%s`" % self.pkg,
            "- 区服：%s" % (self.region or "（抓包期间没看到游戏接口，无法判定）"),
            "- 结束时间：%s" % _ts(),
            "- 请求总数：%d（游戏接口 %d，资源 %d，跳过噪音 %d）"
            % (self.stats["total"], self.stats["game"],
               self.stats["asset"], self.stats["skipped"]),
            "",
        ]
        if self.chaldea_files:
            lines += ["## Chaldea 导入文件", "",
                      "把下面这个文件（原样，别改）导入 Chaldea 即可：", ""]
            lines += ["- `chaldea/%s`" % name for name in self.chaldea_files]
            lines.append("")
        else:
            lines += ["## Chaldea 导入文件", "",
                      "没抓到登录响应：抓包期间要**进游戏直到出现地球仪/公告页**。", ""]
        if self.auth.get("authkey"):
            lines += ["## 凭据（Chaldea 用）", "", "```json",
                      json.dumps(cred, ensure_ascii=False, indent=2), "```", ""]
        else:
            lines += ["## 凭据", "",
                      "未抓到 authkey：抓包期间要进过游戏（登录 / 抽卡 / 编队）。", ""]
        lines += ["## 目录", "",
                  "- `chaldea/toplogin_*.json` 直接导入 Chaldea 的文件",
                  "- `game/` 游戏接口明细", "- `flows/` 其他请求",
                  "- `index.csv` 索引", "- `auth.json` 账号凭据（勿外传）", ""]
        try:
            (self.out / "summary.md").write_text("\n".join(lines), encoding="utf-8")
        except Exception:
            pass


addons = [FgoCapture()]
