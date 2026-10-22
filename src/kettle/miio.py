"""Minimal raw miio client (UDP 54321): handshake, AES-128-CBC, JSON-RPC."""
from __future__ import annotations

import hashlib
import json
import socket
import struct
import time
from dataclasses import dataclass

from . import aes
from .style import paint

PORT = 54321
MAGIC = 0x2131
HELLO = bytes.fromhex("21310020") + b"\xff" * 28


class MiioError(Exception):
    pass


class MiioTimeout(MiioError):
    pass


class MiioRpcError(MiioError):
    def __init__(self, error: dict):
        super().__init__(f"device returned error: {error}")
        self.error = error


@dataclass
class Hello:
    did: int
    stamp: int
    checksum: bytes  # holds the token on some unprovisioned/older devices

    @property
    def token(self) -> bytes | None:
        """Token if the device leaks it in the hello reply, else None."""
        if self.checksum in (b"\x00" * 16, b"\xff" * 16):
            return None
        return self.checksum


def _keys(token: bytes) -> tuple[bytes, bytes]:
    key = hashlib.md5(token).digest()
    iv = hashlib.md5(key + token).digest()
    return key, iv


def encrypt(token: bytes, data: bytes) -> bytes:
    key, iv = _keys(token)
    return aes.cbc_encrypt(key, iv, data)


def decrypt(token: bytes, data: bytes) -> bytes:
    key, iv = _keys(token)
    return aes.cbc_decrypt(key, iv, data)


def build_packet(token: bytes, did: int, stamp: int, payload: dict) -> bytes:
    body = encrypt(token, json.dumps(payload, separators=(",", ":")).encode())
    head = struct.pack(">HHIII", MAGIC, 32 + len(body), 0, did, stamp)
    checksum = hashlib.md5(head + token + body).digest()
    return head + checksum + body


def parse_packet(data: bytes) -> tuple[int, int, int, bytes, bytes]:
    """Returns (length, did, stamp, checksum, body). Raises MiioError if malformed."""
    if len(data) < 32:
        raise MiioError(f"short packet ({len(data)} bytes)")
    magic, length, _unk, did, stamp = struct.unpack(">HHIII", data[:16])
    if magic != MAGIC or length != len(data):
        raise MiioError(f"bad header: magic={magic:#x} length={length} actual={len(data)}")
    return length, did, stamp, data[16:32], data[32:]


def decode_response(token: bytes, data: bytes) -> dict:
    _length, _did, _stamp, checksum, body = parse_packet(data)
    if hashlib.md5(data[:16] + token + body).digest() != checksum:
        raise MiioError("response checksum mismatch (wrong token?)")
    return json.loads(decrypt(token, body).rstrip(b"\x00").decode())


class MiioClient:
    def __init__(self, ip: str, token: bytes | None = None, timeout: float = 3.0,
                 retries: int = 3, port: int = PORT, debug: bool = False):
        self.ip, self.port = ip, port
        self.token = token
        self.timeout, self.retries, self.debug = timeout, retries, debug
        self.did: int | None = None
        self.persistent = False  # shell mode: `with` must not close the shared socket
        self._stamp_base = 0
        self._stamp_at = 0.0
        self._id = 0
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.settimeout(timeout)

    def close(self) -> None:
        self._sock.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        if not self.persistent:
            self.close()

    def _log(self, *a):
        if self.debug:
            print(paint("[miio]", "magenta"), paint(" ".join(map(str, a)), "dim"))

    def _roundtrip(self, packet: bytes) -> bytes:
        self._log("->", packet.hex())
        self._sock.sendto(packet, (self.ip, self.port))
        try:
            data, _ = self._sock.recvfrom(4096)
        except socket.timeout:
            raise MiioTimeout(f"no reply from {self.ip}:{self.port} in {self.timeout}s") from None
        self._log("<-", data.hex())
        return data

    def handshake(self) -> Hello:
        """Send hello, sync device id and stamp. Retries on timeout."""
        last: Exception | None = None
        for _ in range(self.retries):
            try:
                data = self._roundtrip(HELLO)
            except MiioTimeout as e:
                last = e
                continue
            _l, did, stamp, checksum, _b = parse_packet(data)
            self.did, self._stamp_base, self._stamp_at = did, stamp, time.monotonic()
            # A device that leaks its token in the hello reply is telling us its *current* one
            # (it is regenerated every time setup mode is entered), so it beats any saved token.
            if Hello(did, stamp, checksum).token:
                self.token = checksum
            return Hello(did, stamp, checksum)
        raise last or MiioTimeout("handshake failed")

    def _stamp(self) -> int:
        return self._stamp_base + int(time.monotonic() - self._stamp_at) + 1

    def call(self, method: str, params=None, retry: bool = True) -> object:
        """Send one RPC; re-handshake transparently on timeout or stale stamp.

        retry=False sends exactly once (for non-idempotent calls like config_router)."""
        if self.token is None:
            raise MiioError("no token available (the kettle hides it); run `kettle setup`")
        last: Exception | None = None
        for attempt in range(self.retries if retry else 1):
            try:
                if self.did is None or attempt > 0:
                    self.handshake()
                self._id = self._id % 9999 + 1
                req = {"id": self._id, "method": method, "params": params if params is not None else []}
                self._log("request", req)
                data = self._roundtrip(build_packet(self.token, self.did, self._stamp(), req))
                resp = decode_response(self.token, data)
                self._log("response", resp)
                if resp.get("id") != self._id:
                    raise MiioError(f"id mismatch: sent {self._id}, got {resp.get('id')}")
                if "error" in resp:
                    raise MiioRpcError(resp["error"])
                return resp.get("result")
            except MiioRpcError:
                raise
            except (MiioError, ValueError, OSError) as e:  # timeout, bad checksum, stale stamp, no route...
                last = e
                self.did = None
        raise MiioError(f"{method} failed after {self.retries} attempts: {last}")

    # --- MIoT helpers -------------------------------------------------
    def get_properties(self, props: list[tuple[int, int]]) -> list[dict]:
        req = [{"did": f"{s}-{p}", "siid": s, "piid": p} for s, p in props]
        return self.call("get_properties", req)

    def set_properties(self, items: list[tuple[int, int, object]]) -> list[dict]:
        req = [{"did": f"{s}-{p}", "siid": s, "piid": p, "value": v} for s, p, v in items]
        return self.call("set_properties", req)

    def action(self, siid: int, aiid: int, args: list | None = None) -> dict:
        return self.call("action", {"did": f"action-{siid}-{aiid}", "siid": siid,
                                    "aiid": aiid, "in": args or []})


def local_subnet() -> str:
    """First three octets of this computer's outgoing IPv4 address, e.g. "192.168.1"."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 9))  # no packet is sent; just picks the outgoing interface
        return s.getsockname()[0].rsplit(".", 1)[0]
    finally:
        s.close()


def discover(base: str, wait: float = 4.0, port: int = PORT) -> list:
    """Hello-sweep BASE.1-254; returns [(ip, did)] for every miio device that answers."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(0.3)
    found = {}
    try:
        for host in range(1, 255):
            try:
                sock.sendto(HELLO, (f"{base}.{host}", port))
            except OSError:
                continue
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            try:
                data, addr = sock.recvfrom(4096)
                found[addr[0]] = parse_packet(data)[1]
            except socket.timeout:
                continue
            except MiioError:
                continue
    finally:
        sock.close()
    return sorted(found.items(), key=lambda kv: tuple(int(p) for p in kv[0].split(".")))
