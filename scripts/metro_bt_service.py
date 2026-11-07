#!/usr/bin/env python3
"""Сервис metro_bt: доли от плагина «Metro BT» → вибрация Mi Band 10.
Запускается systemd (scripts/install.sh). Вручную: sudo python3 scripts/metro_bt_service.py [-v]"""
import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from band.service import MetroService  # noqa: E402

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG if "-v" in sys.argv else logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    MetroService(os.path.join(ROOT, "config", "band.json")).run()
