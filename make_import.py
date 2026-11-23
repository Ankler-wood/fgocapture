"""从已抓到的数据生成 Chaldea 导入文件。

支持两种输入：
  1. 抓包目录里的一条 flow：`out/.../<服>/game/00018_xxx_ac.php.json`
  2. 插件留下的大响应原文：`out/.../<服>/chaldea/_raw/xxx.raw`

命令行：
    python make_import.py <文件> [<文件> ...]
    FGOCapture.exe --make-import <文件>

生成（与输入同级的 chaldea/ 目录下）：
    toplogin_<时间>.json           ← 原样响应体，Chaldea 直接导入
    toplogin_<时间>.decoded.json   ← 解码后的明文 json（备用 / 方便人看）
"""
import base64
import json
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

MARKERS = (b'"userSvt"', b'"userSvtStorage"', b'"userItem"', b'"userServantList"')


def payload_from_bytes(raw: bytes):
    """明文 / base64 / URL编码的 base64 → 可读 JSON；认不出返回 None。"""
    text = raw.decode("utf-8", "ignore").strip()
    if text[:2] == "ey":  # 简中服/繁中服的 base64，常再套一层 URL 编码
        fixed = unquote(text) if "%" in text else text
        fixed = fixed.strip()
        try:
            return base64.b64decode(fixed + "=" * (-len(fixed) % 4))
        except Exception:
            return None
    if text[:1] in "{[":
        return raw
    return None


def _read_source(src: Path) -> bytes:
    if src.suffix.lower() == ".raw":
        return src.read_bytes()
    data = json.loads(src.read_text(encoding="utf-8"))
    resp = data.get("response") or {}
    body = resp.get("body")
    if body is None:
        raise ValueError("这条 flow 没存正文（可能被 stream 掉了），换 .raw 或重抓")
    return body.encode("utf-8")


def _target_dir(src: Path) -> Path:
    # flow 在 <服>/game/ 下，raw 在 <服>/chaldea/_raw/ 下
    if "game" in src.parts:
        return src.parent.parent / "chaldea"
    return src.parent


def make_import(src) -> Path:
    src = Path(src)
    raw = _read_source(src)
    payload = payload_from_bytes(raw)

    if payload:
        hit = [m.decode() for m in MARKERS if m in payload]
        print("[i] 解码出 %d 字节 JSON，命中字段：%s" % (len(payload), ", ".join(hit) or "无"))
        if hit:
            try:
                succ = json.loads(payload).get("cache", {}).get("replaced", {})
                print("[i] 从者 %d / 素材 %d"
                      % (len(succ.get("userSvt", [])), len(succ.get("userItem", []))))
            except Exception:
                pass
    else:
        print("[!] 没认出这坨数据（既不是 json 也不是 base64），仍然原样保存")

    outdir = _target_dir(src)
    outdir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = outdir / ("toplogin_%s.json" % stamp)
    target.write_bytes(raw)
    print("[OK] %s（%d 字节）" % (target, len(raw)))
    if payload and payload != raw:
        prev = outdir / ("toplogin_%s.decoded.json" % stamp)
        prev.write_bytes(payload)
        print("[OK] %s（解码版）" % prev)
    return target


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__)
        return 2
    code = 0
    for item in argv:
        try:
            make_import(item)
        except Exception as exc:
            print("[!] %s 失败：%r" % (item, exc))
            code = 1
    return code


if __name__ == "__main__":
    sys.exit(main())
