import os
import unittest

from helpers import miio  # noqa: F401  (sets up sys.path)
from kettle import aes


class AesTests(unittest.TestCase):
    def test_fips197_block(self):
        rk = aes._expand_key(bytes(range(16)))
        ct = aes.encrypt_block(rk, bytes.fromhex("00112233445566778899aabbccddeeff"))
        self.assertEqual(ct.hex(), "69c4e0d86a7b0430d8cdb78070b4c55a")
        self.assertEqual(aes.decrypt_block(rk, ct).hex(), "00112233445566778899aabbccddeeff")

    def test_sp800_38a_cbc_vectors(self):
        key = bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c")
        iv = bytes(range(16))
        plain = bytes.fromhex("6bc1bee22e409f96e93d7e117393172a" "ae2d8a571e03ac9c9eb76fac45af8e51"
                              "30c81c46a35ce411e5fbc1191a0a52ef" "f69f2445df4f9b17ad2b417be66c3710")
        expected = bytes.fromhex("7649abac8119b246cee98e9b12e9197d" "5086cb9b507219ee95db113a917678b2"
                                 "73bed6b8e3c1743b7116e69e22229516" "3ff1caa1681fac09120eca307586e1a7")
        ct = aes.cbc_encrypt(key, iv, plain)
        self.assertEqual(ct[:64], expected)  # the 5th block is padding only
        self.assertEqual(aes.cbc_decrypt(key, iv, ct), plain)

    def test_roundtrip_all_padding_lengths(self):
        key, iv = os.urandom(16), os.urandom(16)
        for n in (0, 1, 15, 16, 17, 31, 32, 250):
            data = os.urandom(n)
            self.assertEqual(aes.cbc_decrypt(key, iv, aes.cbc_encrypt(key, iv, data)), data, n)

    def test_matches_cryptography_when_installed(self):
        try:
            from cryptography.hazmat.primitives import padding
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        except ImportError:
            self.skipTest("cryptography not installed")
        key, iv, data = os.urandom(16), os.urandom(16), os.urandom(100)
        padder = padding.PKCS7(128).padder()
        enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
        ref = enc.update(padder.update(data) + padder.finalize()) + enc.finalize()
        self.assertEqual(aes.cbc_encrypt(key, iv, data), ref)

    def test_rejects_bad_input(self):
        key, iv = bytes(16), bytes(16)
        with self.assertRaises(ValueError):
            aes._expand_key(b"short")
        with self.assertRaises(ValueError):
            aes.cbc_decrypt(key, iv, b"")
        with self.assertRaises(ValueError):
            aes.cbc_decrypt(key, iv, bytes(15))
        with self.assertRaises(ValueError):  # valid length, garbage padding
            aes.cbc_decrypt(key, iv, bytes(16))


if __name__ == "__main__":
    unittest.main()
