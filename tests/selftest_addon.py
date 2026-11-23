"""离线自测：用 mitmproxy.test 造几条 flow，验证落盘/分类/凭据/Chaldea 导入文件。"""
import base64
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out" / "_selftest"
if OUT.exists():
    shutil.rmtree(OUT)
os.environ.update({
    "FGO_OUTDIR": str(OUT), "FGO_LABEL": "bilibili", "FGO_DISPLAY": "简中B服",
    "FGO_DEVICE": "emulator-5556", "FGO_PKG": "com.bilibili.fatego", "FGO_PORT": "8082",
})

sys.path.insert(0, str(ROOT))
import fgo_addon  # noqa: E402
from mitmproxy.test import tflow  # noqa: E402


class FakeLoader:
    def add_option(self, *a, **k):
        pass


addon = fgo_addon.FgoCapture()
addon.load(FakeLoader())


def make_flow(host, path, method="POST", req_body=b"", resp_body=b"", ctype="application/json"):
    flow = tflow.tflow(resp=True)
    flow.request.host = host
    flow.request.path = path
    flow.request.method = method
    flow.request.content = req_body
    flow.response.status_code = 200
    flow.response.headers["content-type"] = ctype
    flow.response.content = resp_body
    return flow


# 简中服登录响应：base64（ey 开头），解码后含 userServantList
login_payload = json.dumps({
    "response": [{"resCode": "00", "success": {
        "sguid": "100000000001", "userGame": {"lv": 188},
        "userServantList": [{"id": i, "lv": 90, "skill": [10, 10, 10],
                              "name": "servant-%d" % i} for i in range(600)]
    }}]
}, ensure_ascii=False).encode("utf-8")
assert len(login_payload) > 20000, len(login_payload)
login_b64 = base64.b64encode(login_payload) + b"\n"

cases = [
    # 1. 简中服 topLogin.php —— 应生成 Chaldea 导入文件
    make_flow("le1-bili-fate.biligame.net",
              "/rongame_beta/rgfate/60_1001/topLogin.php",
              req_body=b"deviceid=abc&rguid=1",
              resp_body=login_b64),
    # 2. login.php —— 只有账号信息（无 userServantList），不该被当成导入文件
    make_flow("le1-bili-fate.biligame.net",
              "/rongame_beta/rgfate/60_1001/login.php",
              resp_body=base64.b64encode(b'{"response":[{"resCode":"00","success":{"sguid":"1"}}]}')),
    # 3. 带 authkey 的游戏接口
    make_flow("game.fate-go.jp", "/gacha/history",
              req_body=b"authkey=SECRET123&user_id=100200300",
              resp_body=b'{"gachaHistory":[]}'),
    # 4. 噪音域名：跳过
    make_flow("app-measurement.com", "/a", resp_body=b"{}"),
    # 5. 资源图：记为 asset
    make_flow("cdn.example.com", "/assets/servant/1.png", method="GET",
              ctype="image/png", resp_body=b"\x89PNG"),
    # 6. 普通请求
    make_flow("api.bilibili.com", "/x/y", method="GET", resp_body=b'{"code":0}'),
]

for flow in cases:
    addon.request(flow)
    addon.response(flow)
addon.done()

print("== 目录 ==")
for path in sorted(OUT.rglob("*")):
    if path.is_file():
        print("  ", path.relative_to(OUT), path.stat().st_size, "B")

print("\n== index.csv ==")
print((OUT / "index.csv").read_text(encoding="utf-8"))

chaldea = sorted((OUT / "chaldea").glob("toplogin_*.json"))
chaldea = [p for p in chaldea if not p.name.endswith(".decoded.json")]
print("== chaldea 导入文件 ==", [p.name for p in chaldea])

print("== summary.md ==")
print((OUT / "summary.md").read_text(encoding="utf-8"))

print("\n== 断言 ==")
game_files = list((OUT / "game").glob("*.json"))
assert len(game_files) == 3, ("游戏接口应 3 条", len(game_files))
assert len(list((OUT / "flows").glob("*.json"))) == 2, "资源 1 条 + 其他 1 条（噪音被跳过）"
assert len(chaldea) == 1, ("只应生成 1 个导入文件", len(chaldea))
assert chaldea[0].read_bytes() == login_b64, "导入文件必须与响应体逐字节一致"
decoded = json.loads(chaldea[0].read_bytes().decode().strip() and
                     base64.b64decode(chaldea[0].read_bytes()))
assert decoded["response"][0]["success"]["sguid"] == "100000000001"
status = json.loads((OUT / "status.json").read_text(encoding="utf-8"))
assert status["has_chaldea"] is True, status
print("全部通过 ✓")
