#!/usr/bin/env python3
"""Проверка связи с Mi Band 10 на Pi.

    python3 scripts/band_test.py scan                найти браслет и записать его MAC в config/band.json
    python3 scripts/band_test.py connect             подключиться и пройти авторизацию
    python3 scripts/band_test.py buzz [мс]           одна короткая вибрация (по умолчанию 80 мс)
    python3 scripts/band_test.py beats [BPM] [N]     N вибраций в темпе (по умолчанию 100 BPM, 16 долей)

Флаг -v включает подробный лог. Перед запуском выключи Bluetooth на телефоне:
браслет держит только одно подключение.
"""
import json
import logging
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
CONFIG = os.path.join(ROOT, "config", "band.json")

from band.client import BandClient, BandError  # noqa: E402


def load_config():
    if not os.path.exists(CONFIG):
        sys.exit("Нет %s. Сначала: python3 scripts/extract_key.py <zip с логами>" % CONFIG)
    with open(CONFIG) as f:
        return json.load(f)


def save_config(cfg):
    with open(CONFIG, "w") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    os.chmod(CONFIG, 0o600)


def scan(cfg):
    print("Ищу «%s» 15 секунд (bluetoothctl)…" % cfg.get("name", "Xiaomi Smart Band 10"))
    out = subprocess.run(["bluetoothctl", "--timeout", "15", "scan", "on"],
                         capture_output=True, text=True).stdout
    out += subprocess.run(["bluetoothctl", "devices"], capture_output=True, text=True).stdout
    found = {}
    for mac, name in re.findall(r"Device ([0-9A-F:]{17}) (.+)", out):
        if "Band 10" in name:
            found[mac] = name.strip()
    hint = cfg.get("mac_hint", "")
    if hint:
        found = {m: n for m, n in found.items() if m.endswith(hint)} or found
    if not found:
        print("Браслет не найден. Он должен быть рядом и не подключён к телефону.")
        return 1
    for mac, name in found.items():
        print("  %s  %s" % (mac, name))
    mac = next(iter(found))
    cfg["mac"] = mac
    save_config(cfg)
    print("Записал MAC %s в %s" % (mac, CONFIG))
    return 0


def connect(cfg):
    if not cfg.get("mac"):
        sys.exit("В конфиге нет MAC. Сначала: python3 scripts/band_test.py scan")
    c = BandClient(cfg["mac"], bytes.fromhex(cfg["authkey"]), channel=cfg.get("rfcomm_channel"))
    t = time.monotonic()
    c.connect()
    print("Подключено и авторизовано за %.1f с (RFCOMM канал %d)" % (time.monotonic() - t, c.channel))
    if cfg.get("rfcomm_channel") != c.channel:
        cfg["rfcomm_channel"] = c.channel
        save_config(cfg)
    return c


def main():
    args = [a for a in sys.argv[1:] if a != "-v"]
    logging.basicConfig(level=logging.DEBUG if "-v" in sys.argv else logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    if not args or args[0] not in ("scan", "connect", "buzz", "beats"):
        print(__doc__)
        return 1
    cfg = load_config()
    if args[0] == "scan":
        return scan(cfg)
    try:
        c = connect(cfg)
        if args[0] == "buzz":
            ms = float(args[1]) if len(args) > 1 else 80
            c.buzz(ms / 1000)
            print("Отправил вибрацию на %.0f мс. Почувствовал?" % ms)
            time.sleep(1)
        elif args[0] == "beats":
            bpm = float(args[1]) if len(args) > 1 else 100
            n = int(args[2]) if len(args) > 2 else 16
            period = 60.0 / bpm
            start = time.monotonic() + 0.5
            print("%d долей в темпе %.0f BPM. Хлопай вместе с вибрацией, сравни с ощущением." % (n, bpm))
            for i in range(n):
                target = start + i * period
                time.sleep(max(0.0, target - time.monotonic()))
                late = (time.monotonic() - target) * 1000
                c.buzz(0.06 if i % 4 else 0.12)
                print("  доля %2d  отправлено с опозданием %.1f мс" % (i + 1, late))
            time.sleep(1)
        c.close()
    except BandError as e:
        print("Ошибка: %s" % e)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
