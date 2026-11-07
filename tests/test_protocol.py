"""Офлайн-тесты протокола. Запуск: python3 -m unittest discover -s tests"""
import hashlib
import hmac
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cryptography.hazmat.primitives.ciphers.aead import AESCCM  # noqa: E402

from band import protocol as p  # noqa: E402


def crc_gadgetbridge(payload):
    """Дословный перенос calculatePayloadChecksum из XiaomiSppPacketV2.java."""
    crc = 0
    for b in payload:
        sb = b - 256 if b > 127 else b  # byte в Java знаковый
        for j in range(8):
            crc = (crc << 1) & 0xFFFFFFFF
            if ((crc >> 16) & 1) ^ ((sb >> j) & 1):
                crc ^= 0x8005
    rev = int("{:032b}".format(crc)[::-1], 2)
    return rev >> 16


class TestFrames(unittest.TestCase):
    def test_crc_matches_gadgetbridge(self):
        self.assertEqual(p.crc16_arc(b"123456789"), 0xBB3D)  # контрольное значение CRC-16/ARC
        for data in (b"", b"\x00", b"\xff\x80\x7f", os.urandom(300), p.SESSION_CONFIG):
            self.assertEqual(p.crc16_arc(data), crc_gadgetbridge(data))

    def test_v2_roundtrip(self):
        frame = p.v2_frame(p.V2_DATA, 7, b"\x01\x02hello")
        self.assertEqual(p.v2_try_decode(frame), (p.V2_DATA, 7, b"\x01\x02hello", len(frame)))
        self.assertIsNone(p.v2_try_decode(frame[:-1]))
        bad = bytearray(frame)
        bad[-1] ^= 1
        with self.assertRaises(ValueError):
            p.v2_try_decode(bad)

    def test_v1_version_request(self):
        # как в Gadgetbridge: ba dc fe, канал 0, флаги c0, длина 3, opcode 0, serial 0, plain, ef
        self.assertEqual(p.v1_version_request().hex(), "badcfe00c00300000000ef")
        reply = p.V1_PREAMBLE + bytes([0, 0]) + struct.pack("<H", 5) + b"\x00\x00\x00" + b"\x02\x00" + p.V1_EPILOGUE
        self.assertEqual(p.v1_try_decode(reply), (0, b"\x02\x00", len(reply)))

    def test_protobuf(self):
        f = p.pb_decode(p.find_watch_command(True))
        self.assertEqual((p.pb_get(f, 1), p.pb_get(f, 2)), (2, 18))
        self.assertEqual(p.pb_get(p.pb_decode(p.pb_get(f, 4)), 5), 0)
        f = p.pb_decode(p.find_watch_command(False))
        self.assertEqual(p.pb_get(p.pb_decode(p.pb_get(f, 4)), 5), 1)
        self.assertEqual(p.pb_decode(p.pb_uint(1, 300)), {1: [300]})


class FakeBand:
    """Сторона браслета для проверки авторизации, по тем же формулам."""

    def __init__(self, secret):
        self.secret = secret
        self.nonce = os.urandom(16)

    def reply_to_nonce(self, cmd):
        f = p.pb_decode(cmd)
        assert (p.pb_get(f, 1), p.pb_get(f, 2)) == (1, 26)
        self.phone_nonce = p.pb_get(p.pb_decode(p.pb_get(p.pb_decode(p.pb_get(f, 3)), 30)), 1)
        k = p.derive_keys(self.secret, self.phone_nonce, self.nonce)
        self.phone_enc_key, self.phone_dec_key = k[16:32], k[0:16]
        self.phone_enc_nonce = k[36:40]
        mac = hmac.new(self.phone_dec_key, self.nonce + self.phone_nonce, hashlib.sha256).digest()
        verify = p.pb_bytes(1, self.nonce) + p.pb_bytes(2, mac)
        return p.pb_bytes(31, verify)

    def check_confirm(self, cmd):
        f = p.pb_decode(cmd)
        assert (p.pb_get(f, 1), p.pb_get(f, 2)) == (1, 27)
        conf = p.pb_decode(p.pb_get(p.pb_decode(p.pb_get(f, 3)), 32))
        exp = hmac.new(self.phone_enc_key, self.phone_nonce + self.nonce, hashlib.sha256).digest()
        assert p.pb_get(conf, 1) == exp
        info = AESCCM(self.phone_enc_key, tag_length=4).decrypt(
            self.phone_enc_nonce + b"\0" * 8, p.pb_get(conf, 2), None)
        return p.pb_decode(info)


class TestAuth(unittest.TestCase):
    def test_handshake(self):
        secret = os.urandom(16)
        band = FakeBand(secret)
        s = p.AuthSession(secret)
        info = band.check_confirm(s.handle_watch_nonce(band.reply_to_nonce(s.nonce_command())))
        self.assertEqual(p.pb_get(info, 3), b"Zynthian")
        self.assertEqual(p.pb_get(info, 4), 224)
        # шифрование: что зашифровал телефон, браслет расшифровывает своим ключом
        msg = p.find_watch_command(True)
        self.assertEqual(p._ctr(band.phone_enc_key, s.encrypt(msg)), msg)

    def test_wrong_key(self):
        band = FakeBand(os.urandom(16))
        s = p.AuthSession(os.urandom(16))
        with self.assertRaises(ValueError):
            s.handle_watch_nonce(band.reply_to_nonce(s.nonce_command()))

    def test_derive_keys_reference(self):
        # Эталон посчитан по алгоритму computeAuthStep3Hmac (HKDF-Expand на HMAC-SHA256, info "miwear-auth")
        secret, pn, wn = bytes(range(16)), bytes(16), bytes([1]) * 16
        prk = hmac.new(pn + wn, secret, hashlib.sha256).digest()
        t1 = hmac.new(prk, b"miwear-auth\x01", hashlib.sha256).digest()
        t2 = hmac.new(prk, t1 + b"miwear-auth\x02", hashlib.sha256).digest()
        self.assertEqual(p.derive_keys(secret, pn, wn), t1 + t2)


if __name__ == "__main__":
    unittest.main()
