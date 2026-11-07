# Протокол Xiaomi SPP (Mi Band 10) без сокетов: кадры, protobuf, шифрование.
# Портировано из Gadgetbridge (AGPL-3.0): XiaomiSppPacketV1/V2, XiaomiAuthService.
import hashlib
import hmac
import os
import struct

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESCCM

# ---------- protobuf (вручную, нужно всего несколько полей) ----------

def _varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def pb_uint(field, value):
    return _varint(field << 3 | 0) + _varint(value)


def pb_bytes(field, data):
    if isinstance(data, str):
        data = data.encode()
    return _varint(field << 3 | 2) + _varint(len(data)) + data


def pb_float(field, value):
    return _varint(field << 3 | 5) + struct.pack("<f", value)


def pb_decode(data):
    """Разбор сообщения в {номер поля: [значения]}. Вложенные сообщения остаются bytes."""
    fields = {}
    i = 0
    while i < len(data):
        key, i = _read_varint(data, i)
        field, wtype = key >> 3, key & 7
        if wtype == 0:
            value, i = _read_varint(data, i)
        elif wtype == 2:
            ln, i = _read_varint(data, i)
            value = data[i:i + ln]
            i += ln
        elif wtype == 5:
            value = data[i:i + 4]
            i += 4
        elif wtype == 1:
            value = data[i:i + 8]
            i += 8
        else:
            raise ValueError("неизвестный wire type %d" % wtype)
        fields.setdefault(field, []).append(value)
    return fields


def _read_varint(data, i):
    n = shift = 0
    while True:
        b = data[i]
        i += 1
        n |= (b & 0x7F) << shift
        if not b & 0x80:
            return n, i
        shift += 7


def pb_get(fields, field, default=None):
    vals = fields.get(field)
    return vals[0] if vals else default


# Command: type=1, subtype=2, auth=3, system=4, notification=9, status=100
def command(type_, subtype, auth=None, system=None):
    msg = pb_uint(1, type_) + pb_uint(2, subtype)
    if auth is not None:
        msg += pb_bytes(3, auth)
    if system is not None:
        msg += pb_bytes(4, system)
    return msg


AUTH_TYPE = 1
AUTH_CMD_NONCE = 26
AUTH_CMD_AUTH = 27
SYSTEM_TYPE = 2
SYSTEM_CMD_FIND_WATCH = 18


def find_watch_command(start):
    # System.findDevice = 5: 0 = начать, 1 = остановить
    return command(SYSTEM_TYPE, SYSTEM_CMD_FIND_WATCH, system=pb_uint(5, 0 if start else 1))


# ---------- кадры V1 (нужны только для запроса версии) ----------

V1_PREAMBLE = b"\xba\xdc\xfe"
V1_EPILOGUE = b"\xef"


def v1_version_request():
    # channel 0 (version), flag=1, needsResponse=1, opcode READ=0, serial 0, plain
    payload = b""
    return (V1_PREAMBLE + bytes([0, 0x80 | 0x40]) + struct.pack("<H", len(payload) + 3)
            + bytes([0, 0, 0]) + payload + V1_EPILOGUE)


def v1_try_decode(buf):
    """Вернуть (channel, payload, длина кадра) или None, если кадр ещё не весь."""
    if len(buf) < 11:
        return None
    if buf[:3] != V1_PREAMBLE:
        raise ValueError("не кадр V1: %s" % buf[:8].hex())
    ln = struct.unpack_from("<H", buf, 5)[0] - 3
    total = 11 + ln
    if len(buf) < total:
        return None
    if buf[total - 1:total] != V1_EPILOGUE:
        raise ValueError("кадр V1 без эпилога")
    return buf[3] & 0x0F, bytes(buf[10:10 + ln]), total


# ---------- кадры V2 ----------

V2_PREAMBLE = b"\xa5\xa5"
V2_NACK, V2_ACK, V2_SESSION, V2_DATA = 0, 1, 2, 3
CH_PROTOBUF = 1  # и авторизация, и команды
OP_PLAIN, OP_ENCRYPTED = 1, 2

SESSION_START_REQUEST = 1
SESSION_START_RESPONSE = 2

# Параметры сессии из дампа официального приложения: версия 1.0.0, кадр 64512, окно 32, таймаут 10 с
SESSION_CONFIG = bytes([
    SESSION_START_REQUEST,
    1, 3, 0, 1, 0, 0,
    2, 2, 0, 0x00, 0xFC,
    3, 2, 0, 0x20, 0x00,
    4, 2, 0, 0x10, 0x27,
])


def crc16_arc(data):
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def v2_frame(ptype, seq, payload):
    return (V2_PREAMBLE + bytes([ptype & 0x0F, seq & 0xFF])
            + struct.pack("<HH", len(payload), crc16_arc(payload)) + payload)


def v2_try_decode(buf):
    """Вернуть (тип, seq, payload, длина кадра) или None, если кадр ещё не весь."""
    if len(buf) < 8:
        return None
    if buf[:2] != V2_PREAMBLE:
        raise ValueError("не кадр V2: %s" % buf[:8].hex())
    ln, crc = struct.unpack_from("<HH", buf, 4)
    if len(buf) < 8 + ln:
        return None
    payload = bytes(buf[8:8 + ln])
    if crc16_arc(payload) != crc:
        raise ValueError("кадр V2: неверная контрольная сумма")
    return buf[2] & 0x0F, buf[3], payload, 8 + ln


# ---------- авторизация и шифрование ----------

def derive_keys(secret, phone_nonce, watch_nonce):
    """64 байта: ключ расшифровки, ключ шифрования, nonce расшифровки, nonce шифрования."""
    key = hmac.new(phone_nonce + watch_nonce, secret, hashlib.sha256).digest()
    out = b""
    tmp = b""
    counter = 1
    while len(out) < 64:
        tmp = hmac.new(key, tmp + b"miwear-auth" + bytes([counter]), hashlib.sha256).digest()
        out += tmp
        counter += 1
    return out[:64]


def _ctr(key, data):
    # Xiaomi SPP V2: AES-CTR, где IV равен ключу, и счётчик заново для каждого сообщения
    c = Cipher(algorithms.AES(key), modes.CTR(key)).encryptor()
    return c.update(data) + c.finalize()


class AuthSession:
    def __init__(self, secret, phone_nonce=None):
        if len(secret) != 16:
            raise ValueError("ключ должен быть 16 байт")
        self.secret = secret
        self.phone_nonce = phone_nonce or os.urandom(16)
        self.enc_key = self.dec_key = None
        self.enc_nonce = self.dec_nonce = None

    def nonce_command(self):
        # Account.appVerify = 30 { nonce = 1 }
        return command(AUTH_TYPE, AUTH_CMD_NONCE, auth=pb_bytes(30, pb_bytes(1, self.phone_nonce)))

    def handle_watch_nonce(self, auth_bytes, phone_name="Zynthian", region="RU"):
        """Ответ браслета (Account) → команда подтверждения. ValueError, если ключ не тот."""
        verify = pb_get(pb_decode(auth_bytes), 31)  # Account.deviceVerify
        if verify is None:
            raise ValueError("в ответе нет deviceVerify")
        v = pb_decode(verify)
        watch_nonce, watch_hmac = pb_get(v, 1), pb_get(v, 2)
        k = derive_keys(self.secret, self.phone_nonce, watch_nonce)
        self.dec_key, self.enc_key = k[0:16], k[16:32]
        self.dec_nonce, self.enc_nonce = k[32:36], k[36:40]
        expected = hmac.new(self.dec_key, watch_nonce + self.phone_nonce, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, watch_hmac):
            raise ValueError("браслет не принял ключ (hmac не совпал): проверь authkey")
        enc_nonces = hmac.new(self.enc_key, self.phone_nonce + watch_nonce, hashlib.sha256).digest()
        device_info = (pb_uint(1, 0) + pb_float(2, 34.0) + pb_bytes(3, phone_name)
                       + pb_uint(4, 224) + pb_bytes(5, region))
        ccm_nonce = self.enc_nonce + struct.pack("<II", 0, 0)
        enc_info = AESCCM(self.enc_key, tag_length=4).encrypt(ccm_nonce, device_info, None)
        confirm = pb_bytes(1, enc_nonces) + pb_bytes(2, enc_info)
        return command(AUTH_TYPE, AUTH_CMD_AUTH, auth=pb_bytes(32, confirm))

    def encrypt(self, data):
        return _ctr(self.enc_key, data)

    def decrypt(self, data):
        return _ctr(self.dec_key, data)
