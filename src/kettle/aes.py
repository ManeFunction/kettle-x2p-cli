"""AES-128 in CBC mode with PKCS7 padding, pure Python (standard library only).

The miio protocol encrypts a few hundred bytes per request with AES-128-CBC, so speed is
irrelevant and a tiny implementation keeps the package free of compiled dependencies
(which makes it trivial to package for Homebrew). Verified against the FIPS-197 and
NIST SP 800-38A test vectors in tests/test_aes.py.
"""
from __future__ import annotations


def _build_sbox() -> list:
    sbox = [0] * 256
    p = q = 1
    while True:
        p = p ^ ((p << 1) & 0xFF) ^ (0x1B if p & 0x80 else 0)  # p *= 3 in GF(2^8)
        q ^= q << 1
        q ^= q << 2
        q ^= q << 4
        q &= 0xFF
        if q & 0x80:
            q ^= 0x09  # q /= 3
        x = q
        for shift in (1, 2, 3, 4):
            x ^= ((q << shift) | (q >> (8 - shift))) & 0xFF
        sbox[p] = (x ^ 0x63) & 0xFF
        if p == 1:
            break
    sbox[0] = 0x63
    return sbox


_SBOX = _build_sbox()
_INV_SBOX = [0] * 256
for _i, _v in enumerate(_SBOX):
    _INV_SBOX[_v] = _i


def _xtime(a: int) -> int:
    a <<= 1
    return (a ^ 0x11B) & 0xFF if a & 0x100 else a


def _mul(a: int, b: int) -> int:
    r = 0
    while b:
        if b & 1:
            r ^= a
        a = _xtime(a)
        b >>= 1
    return r


_MUL = {n: [_mul(i, n) for i in range(256)] for n in (2, 3, 9, 11, 13, 14)}


def _expand_key(key: bytes) -> list:
    if len(key) != 16:
        raise ValueError("AES-128 needs a 16-byte key")
    w = [list(key[i:i + 4]) for i in range(0, 16, 4)]
    rcon = 1
    for i in range(4, 44):
        t = list(w[i - 1])
        if i % 4 == 0:
            t = t[1:] + t[:1]
            t = [_SBOX[b] for b in t]
            t[0] ^= rcon
            rcon = _xtime(rcon)
        w.append([w[i - 4][j] ^ t[j] for j in range(4)])
    return [sum(w[4 * r:4 * r + 4], []) for r in range(11)]


def _add_key(state: list, rk: list) -> list:
    return [s ^ k for s, k in zip(state, rk)]


def _shift_rows(s: list) -> list:
    return [s[r + 4 * ((c + r) % 4)] for c in range(4) for r in range(4)]


def _inv_shift_rows(s: list) -> list:
    out = [0] * 16
    for c in range(4):
        for r in range(4):
            out[r + 4 * ((c + r) % 4)] = s[r + 4 * c]
    return out


def _mix_columns(s: list) -> list:
    m2, m3 = _MUL[2], _MUL[3]
    out = []
    for c in range(0, 16, 4):
        a0, a1, a2, a3 = s[c:c + 4]
        out += [m2[a0] ^ m3[a1] ^ a2 ^ a3,
                a0 ^ m2[a1] ^ m3[a2] ^ a3,
                a0 ^ a1 ^ m2[a2] ^ m3[a3],
                m3[a0] ^ a1 ^ a2 ^ m2[a3]]
    return out


def _inv_mix_columns(s: list) -> list:
    m9, m11, m13, m14 = _MUL[9], _MUL[11], _MUL[13], _MUL[14]
    out = []
    for c in range(0, 16, 4):
        a0, a1, a2, a3 = s[c:c + 4]
        out += [m14[a0] ^ m11[a1] ^ m13[a2] ^ m9[a3],
                m9[a0] ^ m14[a1] ^ m11[a2] ^ m13[a3],
                m13[a0] ^ m9[a1] ^ m14[a2] ^ m11[a3],
                m11[a0] ^ m13[a1] ^ m9[a2] ^ m14[a3]]
    return out


def encrypt_block(round_keys: list, block: bytes) -> bytes:
    s = _add_key(list(block), round_keys[0])
    for r in range(1, 10):
        s = _add_key(_mix_columns(_shift_rows([_SBOX[b] for b in s])), round_keys[r])
    return bytes(_add_key(_shift_rows([_SBOX[b] for b in s]), round_keys[10]))


def decrypt_block(round_keys: list, block: bytes) -> bytes:
    s = _add_key(list(block), round_keys[10])
    for r in range(9, 0, -1):
        s = _inv_mix_columns(_add_key([_INV_SBOX[b] for b in _inv_shift_rows(s)], round_keys[r]))
    return bytes(_add_key([_INV_SBOX[b] for b in _inv_shift_rows(s)], round_keys[0]))


def cbc_encrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    """AES-128-CBC with PKCS7 padding."""
    rk = _expand_key(key)
    pad = 16 - len(data) % 16
    data += bytes([pad]) * pad
    out, prev = bytearray(), iv
    for i in range(0, len(data), 16):
        prev = encrypt_block(rk, bytes(a ^ b for a, b in zip(data[i:i + 16], prev)))
        out += prev
    return bytes(out)


def cbc_decrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    """Inverse of cbc_encrypt; raises ValueError on bad length or padding."""
    if not data or len(data) % 16:
        raise ValueError("ciphertext is not a multiple of 16 bytes")
    rk = _expand_key(key)
    out, prev = bytearray(), iv
    for i in range(0, len(data), 16):
        block = data[i:i + 16]
        out += bytes(a ^ b for a, b in zip(decrypt_block(rk, block), prev))
        prev = block
    pad = out[-1]
    if not 1 <= pad <= 16 or out[-pad:] != bytes([pad]) * pad:
        raise ValueError("bad PKCS7 padding")
    return bytes(out[:-pad])
