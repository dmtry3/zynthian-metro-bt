# Подключение к Mi Band 10 по Bluetooth Classic (RFCOMM) и авторизация.
# Работает только на Linux с Bluetooth (на Pi). В WSL2 Bluetooth нет.
import logging
import socket
import threading
import time

from . import protocol as p

log = logging.getLogger("band")


class BandError(Exception):
    pass


class BandClient:
    def __init__(self, mac, secret, channel=None, timeout=10.0):
        self.mac = mac
        self.secret = secret
        self.channel = channel
        self.timeout = timeout
        self.sock = None
        self.auth = None
        self._buf = bytearray()
        self._seq = 0
        self._send_lock = threading.Lock()
        self._ready = threading.Event()
        self._error = None
        self._reader = None
        self._closed = False
        self.on_command = None  # необязательный обработчик команд от браслета: f(fields)

    # ---------- подключение ----------

    def connect(self):
        channels = [self.channel] if self.channel else list(range(1, 31))
        last = None
        for ch in channels:
            s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
            s.settimeout(self.timeout)
            try:
                s.connect((self.mac, ch))
            except OSError as e:
                s.close()
                last = e
                log.debug("канал %d: %s", ch, e)
                continue
            self.sock, self.channel = s, ch
            log.info("подключено к %s, RFCOMM канал %d", self.mac, ch)
            break
        if self.sock is None:
            raise BandError("не удалось подключиться к %s: %s" % (self.mac, last))
        self.sock.settimeout(None)
        self._handshake()

    def _handshake(self):
        self.sock.sendall(p.v1_version_request())
        version = self._read_v1_version()
        log.info("версия протокола SPP: %s", version.hex())
        if not version or version[0] < 2:
            raise BandError("браслет ответил протоколом V1 (%s), поддерживается только V2" % version.hex())
        self.sock.sendall(p.v2_frame(p.V2_SESSION, 0, p.SESSION_CONFIG))
        self._reader = threading.Thread(target=self._read_loop, name="band-rx", daemon=True)
        self._reader.start()
        if not self._ready.wait(self.timeout):
            raise BandError("авторизация не завершилась за %.0f с" % self.timeout)
        if self._error:
            raise BandError(self._error)
        log.info("авторизация пройдена")

    def _read_v1_version(self):
        self.sock.settimeout(self.timeout)
        try:
            while True:
                r = p.v1_try_decode(self._buf) if self._buf else None
                if r:
                    ch, payload, ln = r
                    del self._buf[:ln]
                    if ch == 0:
                        return payload
                    log.warning("до версии пришёл кадр V1 на канале %d, пропускаю", ch)
                    continue
                data = self.sock.recv(4096)
                if not data:
                    raise BandError("браслет закрыл соединение")
                self._buf += data
        except socket.timeout:
            raise BandError("браслет не ответил на запрос версии")
        finally:
            self.sock.settimeout(None)

    def close(self):
        self._closed = True
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass

    # ---------- приём ----------

    def _read_loop(self):
        try:
            while True:
                # в буфере могли остаться байты после ответа на запрос версии: сначала разбираем их
                while True:
                    start = self._buf.find(p.V2_PREAMBLE)
                    if start < 0:
                        self._buf.clear()
                        break
                    if start:
                        del self._buf[:start]
                    try:
                        r = p.v2_try_decode(self._buf)
                    except ValueError as e:
                        log.warning("%s, пропускаю байт", e)
                        del self._buf[:1]
                        continue
                    if r is None:
                        break
                    ptype, seq, payload, ln = r
                    del self._buf[:ln]
                    self._on_frame(ptype, seq, payload)
                data = self.sock.recv(4096)
                if not data:
                    raise BandError("браслет закрыл соединение")
                self._buf += data
        except Exception as e:
            if not self._closed:
                log.error("приём остановлен: %s", e)
                self._error = self._error or str(e)
            self._ready.set()

    def _on_frame(self, ptype, seq, payload):
        if ptype == p.V2_SESSION:
            log.debug("session config, opcode %d", payload[0] if payload else -1)
            self.auth = p.AuthSession(self.secret)
            self._send_data(self.auth.nonce_command(), encrypted=False)
        elif ptype == p.V2_DATA:
            self._send_raw(p.v2_frame(p.V2_ACK, seq, b""))
            if len(payload) < 2:
                return
            channel, opcode, body = payload[0] & 0x0F, payload[1], payload[2:]
            if opcode == p.OP_ENCRYPTED:
                body = self.auth.decrypt(body)
            if channel == p.CH_PROTOBUF:
                self._on_command(body)
            else:
                log.debug("данные на канале %d (%d байт), пропускаю", channel, len(body))
        elif ptype == p.V2_ACK:
            log.debug("ack %d", seq)
        elif ptype == p.V2_NACK:
            log.warning("nack: браслет ждёт пакет %d", seq)

    def _on_command(self, body):
        f = p.pb_decode(body)
        type_, sub = p.pb_get(f, 1), p.pb_get(f, 2)
        log.debug("команда от браслета: тип %s, подтип %s", type_, sub)
        if type_ == p.AUTH_TYPE and sub == p.AUTH_CMD_NONCE:
            try:
                self._send_data(self.auth.handle_watch_nonce(p.pb_get(f, 3, b"")), encrypted=False)
            except ValueError as e:
                self._error = str(e)
                self._ready.set()
        elif type_ == p.AUTH_TYPE and sub == p.AUTH_CMD_AUTH:
            self._ready.set()
        elif type_ == p.AUTH_TYPE:
            self._error = "браслет отклонил авторизацию (подтип %s, статус %s)" % (sub, p.pb_get(f, 100))
            self._ready.set()
        elif self.on_command:
            self.on_command(f)

    # ---------- отправка ----------

    def _send_raw(self, frame):
        with self._send_lock:
            self.sock.sendall(frame)

    def _send_data(self, cmd, encrypted=True):
        body = self.auth.encrypt(cmd) if encrypted else cmd
        opcode = p.OP_ENCRYPTED if encrypted else p.OP_PLAIN
        with self._send_lock:
            frame = p.v2_frame(p.V2_DATA, self._seq, bytes([p.CH_PROTOBUF, opcode]) + body)
            self._seq = (self._seq + 1) & 0xFF
            self.sock.sendall(frame)

    def send_command(self, cmd):
        if not self._ready.is_set() or self._error:
            raise BandError("браслет не авторизован")
        self._send_data(cmd, encrypted=True)

    def find_watch(self, start):
        self.send_command(p.find_watch_command(start))

    def buzz(self, duration=0.08):
        """Короткая вибрация через «найти браслет»: старт, пауза, стоп."""
        t = time.monotonic()
        self.find_watch(True)
        time.sleep(duration)
        self.find_watch(False)
        return t
