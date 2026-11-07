"""Сервис без Bluetooth: поддельный браслет вместо BandClient."""
import json
import os
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from band import service  # noqa: E402


class FakeClient:
    instances = []

    def __init__(self, mac, secret, channel=None):
        self.calls = []
        self.channel = channel or 5
        self._ready = threading.Event()
        self._error = None
        self.closed = False
        FakeClient.instances.append(self)

    def connect(self):
        self._ready.set()

    def close(self):
        self.closed = True

    def find_watch(self, start):
        self.calls.append((start, time.monotonic()))


class TestService(unittest.TestCase):
    def setUp(self):
        FakeClient.instances = []
        service.BandClient = FakeClient
        service.IDLE_DISCONNECT = 0.5
        fd, self.cfg = tempfile.mkstemp(suffix=".json")
        with os.fdopen(fd, "w") as f:
            json.dump({"mac": "04:34:C3:A1:52:FF", "authkey": "00" * 16}, f)
        self.s = service.MetroService(self.cfg)
        threading.Thread(target=self.s._link_loop, daemon=True).start()
        threading.Thread(target=self.s._buzz_loop, daemon=True).start()

    def tearDown(self):
        os.unlink(self.cfg)

    def wait_connected(self):
        for _ in range(40):
            if self.s._connected():
                return
            time.sleep(0.05)
        self.fail("не подключился")

    def test_connect_on_alive_and_buzz(self):
        self.assertIsNone(self.s.client)
        self.s._on_message("alive")
        self.wait_connected()
        self.s._on_message("beat 50 0")
        time.sleep(0.2)
        calls = self.s.client.calls
        self.assertEqual([c[0] for c in calls], [True, False])
        self.assertGreaterEqual(calls[1][1] - calls[0][1], 0.045)

    def test_accent_longer_and_off_interrupts(self):
        self.s._on_message("alive")
        self.wait_connected()
        self.s._on_message("beat 100 1")  # акцент: 300 мс
        time.sleep(0.05)
        self.s._on_message("off")          # прерывает
        time.sleep(0.1)
        calls = self.s.client.calls
        self.assertEqual([c[0] for c in calls], [True, False])
        self.assertLess(calls[1][1] - calls[0][1], 0.15)

    def test_alive_with_host_state(self):
        with self.assertLogs("metro_bt", "INFO") as cm:
            self.s._on_message("alive 1 9950 12")
            self.s._on_message("alive 1 9950 13")   # то же состояние: в лог не пишем
            self.s._on_message("alive 0 9950 14")
        self.assertEqual(len(cm.output), 2)
        self.assertIn("99.50 BPM", cm.output[0])
        self.assertIn("стоит", cm.output[1])

    def test_disconnect_when_plugin_gone(self):
        self.s._on_message("alive")
        self.wait_connected()
        c = self.s.client
        self.s._on_message("bye")
        time.sleep(0.8)
        self.assertTrue(c.closed)
        self.assertIsNone(self.s.client)


if __name__ == "__main__":
    unittest.main()
