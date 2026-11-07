#!/usr/bin/env python3
"""Достаёт ключ Mi Band 10 из zip с логами Mi Fitness и пишет config/band.json.

    python3 scripts/extract_key.py путь/к/логам.zip

Ключ — поле encryptKey в XiaomiFit.main.log. Целиком не печатается.
"""
import json
import os
import re
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "config", "band.json")

# В логе устройство записано одной JSON-строкой: detail {..., encryptKey, ..., mac, ...}, потом model и name
DEVICE_RE = re.compile(rb'"encryptKey": "([0-9a-f]{32})".{0,400}?"mac": "([0-9A-F:]*)".{0,400}?'
                       rb'"did": "(\d+)".{0,200}?"model": "([^"]+)", "name": "([^"]*)"', re.S)


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    found = {}
    with zipfile.ZipFile(sys.argv[1]) as z:
        for name in z.namelist():
            if os.path.basename(name).startswith("XiaomiFit") and not name.endswith("/"):
                for m in DEVICE_RE.finditer(z.read(name)):
                    key, mac, did, model, dev = (g.decode(errors="replace") for g in m.groups())
                    found[key] = {"mac_hint": mac, "did": did, "model": model, "name": dev.strip()}
    if not found:
        print("Ключ не найден. Нужен zip с XiaomiFit.main.log из Mi Fitness.")
        return 1
    if len(found) > 1:
        print("Нашлось %d разных ключей (несколько привязок). Беру последний в логе." % len(found))
    key, info = list(found.items())[-1]

    cfg = {}
    if os.path.exists(CONFIG):
        with open(CONFIG) as f:
            cfg = json.load(f)
    cfg.update({"authkey": key, "name": info["name"], "model": info["model"], "mac_hint": info["mac_hint"]})
    cfg.setdefault("mac", "")
    cfg.setdefault("rfcomm_channel", None)
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    with open(CONFIG, "w") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    os.chmod(CONFIG, 0o600)
    print("Браслет: %s (%s)" % (info["name"], info["model"]))
    print("Ключ:    %s…%s (16 байт)" % (key[:4], key[-4:]))
    print("MAC:     в логе только хвост «%s». Полный MAC найдём на Pi: scripts/band_test.py scan" % info["mac_hint"])
    print("Записано в %s" % CONFIG)
    return 0


if __name__ == "__main__":
    sys.exit(main())
