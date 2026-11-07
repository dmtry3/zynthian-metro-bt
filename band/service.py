# Сервис metro_bt: принимает доли от плагина (UDP 127.0.0.1:47801) и вибрирует браслетом.
#
# Сообщения от плагина:
#   alive              плагин в цепочке (раз в секунду)
#   beat <мс> <акцент> доля: вибрация на <мс>, при акценте в ACCENT_FACTOR раз длиннее
#   off                метроном выключен: сразу остановить вибрацию
#   bye                плагин убрали из цепочки
#
# К браслету подключаемся, только пока плагин в цепочке. Через IDLE_DISCONNECT секунд
# без alive отключаемся, чтобы браслет снова мог подключиться к телефону.
import json
import logging
import os
import queue
import socket
import threading
import time

from .client import BandClient, BandError

log = logging.getLogger("metro_bt")

UDP_PORT = int(os.environ.get("METRO_BT_PORT", "47801"))
IDLE_DISCONNECT = 10.0
RECONNECT_DELAY = 5.0
ACCENT_FACTOR = 3  # во сколько раз сильная доля длиннее обычной


class MetroService:
    def __init__(self, config_path):
        with open(config_path) as f:
            cfg = json.load(f)
        if not cfg.get("mac") or not cfg.get("authkey"):
            raise SystemExit("В %s нет mac или authkey (scripts/extract_key.py, band_test.py scan)" % config_path)
        self.mac = cfg["mac"]
        self.secret = bytes.fromhex(cfg["authkey"])
        self.channel = cfg.get("rfcomm_channel")
        self.client = None
        self.last_alive = 0.0
        self.beats = queue.Queue(maxsize=4)

    # ---------- связь с браслетом ----------

    def _connected(self):
        c = self.client
        return c is not None and c._ready.is_set() and not c._error

    def _disconnect(self, why):
        if self.client:
            log.info("отключаюсь от браслета: %s", why)
            self.client.close()
            self.client = None

    def _link_loop(self):
        """Подключается, пока плагин в цепочке, и отключается, когда его нет."""
        next_try = 0.0
        while True:
            wanted = time.monotonic() - self.last_alive < IDLE_DISCONNECT
            if not wanted:
                self._disconnect("плагина нет в цепочке")
            elif self.client and not self._connected():
                self._disconnect("связь потеряна: %s" % self.client._error)
                next_try = time.monotonic() + RECONNECT_DELAY
            elif not self.client and time.monotonic() >= next_try:
                c = BandClient(self.mac, self.secret, channel=self.channel)
                try:
                    log.info("подключаюсь к %s", self.mac)
                    c.connect()
                    self.channel = c.channel
                    self.client = c
                except (BandError, OSError) as e:
                    c.close()
                    log.warning("не подключился: %s, повтор через %.0f с", e, RECONNECT_DELAY)
                    next_try = time.monotonic() + RECONNECT_DELAY
            time.sleep(0.5)

    # ---------- вибрация ----------

    def _buzz_loop(self):
        while True:
            ms = self.beats.get()
            c = self.client
            if not self._connected():
                continue
            try:
                if not ms:  # «off» вне вибрации: на всякий случай стоп
                    c.find_watch(False)
                    continue
                c.find_watch(True)
                # пауза, но «off» её прерывает: в очередь кладётся 0
                try:
                    nxt = self.beats.get(timeout=ms / 1000.0)
                except queue.Empty:
                    nxt = None
                c.find_watch(False)
                if nxt:
                    self.beats.put_nowait(nxt)  # следующая доля пришла во время вибрации
            except (BandError, OSError) as e:
                log.warning("вибрация не ушла: %s", e)

    def _on_message(self, msg):
        parts = msg.split()
        if not parts:
            return
        if parts[0] == "alive":
            self.last_alive = time.monotonic()
        elif parts[0] == "beat" and len(parts) >= 3:
            self.last_alive = time.monotonic()
            ms = int(parts[1]) * (ACCENT_FACTOR if parts[2] == "1" else 1)
            try:
                self.beats.put_nowait(ms)
            except queue.Full:
                log.debug("очередь вибраций полна, долю пропускаю")
        elif parts[0] == "off":
            try:
                self.beats.put_nowait(0)  # прервать текущую вибрацию
            except queue.Full:
                pass
        elif parts[0] == "bye":
            self.last_alive = 0.0

    def run(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind(("127.0.0.1", UDP_PORT))
        log.info("жду плагин на 127.0.0.1:%d, браслет %s", UDP_PORT, self.mac)
        threading.Thread(target=self._link_loop, name="link", daemon=True).start()
        threading.Thread(target=self._buzz_loop, name="buzz", daemon=True).start()
        while True:
            data, _ = s.recvfrom(256)
            self._on_message(data.decode(errors="replace"))
