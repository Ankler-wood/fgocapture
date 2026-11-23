import base64
import json
import sys
from pathlib import Path
from urllib.parse import unquote

for path in sys.argv[1:]:
    p = Path(path)
    data = p.read_bytes()
    text = data.decode("utf-8", "ignore").strip()
    print("==", p.name, "len", len(text))
    print("   percent-encoded?", "%" in text)
    fixed = unquote(text) if "%" in text else text
    print("   after unquote len", len(fixed), "mod4", len(fixed) % 4)
    try:
        payload = base64.b64decode(fixed + "=" * (-len(fixed) % 4))
        print("   decoded", len(payload), "head", payload[:60])
        obj = json.loads(payload)
        cache = obj.get("cache") or {}
        rep = cache.get("replaced") or {}
        print("   top keys:", list(obj.keys()))
        print("   replaced keys:", len(rep))
        for key in ("userSvt", "userItem", "userServantList"):
            if key in rep:
                print("   %s -> %d" % (key, len(rep[key])))
    except Exception as exc:
        print("   FAILED:", type(exc).__name__, str(exc)[:150])
