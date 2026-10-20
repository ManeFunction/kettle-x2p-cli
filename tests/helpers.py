import os
import socket
import struct
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kettle import miio  # noqa: E402

TOKEN = bytes.fromhex("f1860468b2c9f6d86fda299bba63ee0b")
DID = 0x3A22C275


class FakeDevice(threading.Thread):
    """A miio device on 127.0.0.1 speaking the real wire format, with a MIoT kettle model.

    leak_token: put the token in the hello reply (setup-mode behaviour).
    drop_first: ignore the first N datagrams (simulates packet loss).
    """

    def __init__(self, leak_token=False, drop_first=0, token=TOKEN, model="xiaomi.kettle.v20", props=None):
        super().__init__(daemon=True)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.leak, self.drop, self.token, self.model = leak_token, drop_first, token, model
        self.props = {(2, 1): 0, (2, 2): 0, (2, 3): 25, (2, 4): 40, (2, 5): False, (2, 6): 40,
                      (2, 7): False, (3, 1): 1440, (3, 7): False, (3, 10): 0, (3, 11): 0}
        self.props.update(props or {})
        self.seen, self.writes, self.actions = [], [], []
        self.start()

    def run(self):
        while True:
            data, addr = self.sock.recvfrom(4096)
            if self.drop:
                self.drop -= 1
                continue
            if data == miio.HELLO:
                head = struct.pack(">HHIII", miio.MAGIC, 32, 0, DID, 5000)
                self.sock.sendto(head + (self.token if self.leak else b"\xff" * 16), addr)
                continue
            try:
                req = miio.decode_response(self.token, data)
            except miio.MiioError:
                continue  # a real device silently drops what it cannot decrypt
            self.seen.append(req)
            method, params = req["method"], req["params"]
            if method == "miIO.info":
                res = {"model": self.model, "token": "ff" * 16, "fw_ver": "2.2.7_0016",
                       "mac": "E4:FE:43:6B:FE:0C"}
            elif method == "get_properties":
                res = [{"siid": i["siid"], "piid": i["piid"], "code": 0,
                        "value": self.props[(i["siid"], i["piid"])]} for i in params]
            elif method == "set_properties":
                self.writes.append([(i["siid"], i["piid"], i["value"]) for i in params])
                for i in params:
                    self.props[(i["siid"], i["piid"])] = i["value"]
                self.props[(2, 1)] = 1  # starts heating
                res = [{"siid": i["siid"], "piid": i["piid"], "code": 0} for i in params]
            elif method == "action":
                self.actions.append((params["siid"], params["aiid"]))
                self.props[(2, 1)] = 0
                res = {"code": 0, "out": []}
            else:
                res = [method]
            reply = miio.build_packet(self.token, DID, 5000, {"id": req["id"], "result": res})
            self.sock.sendto(reply, addr)


import contextlib  # noqa: E402
import io  # noqa: E402
import pathlib  # noqa: E402
import tempfile  # noqa: E402
import unittest  # noqa: E402
from unittest import mock  # noqa: E402

from kettle import cli, config  # noqa: E402


class DeviceCase(unittest.TestCase):
    """Isolated config dir, no sleeping, and every MiioClient talks to self.dev's port."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.config_path = pathlib.Path(tmp.name) / "config.json"
        self.dev = FakeDevice()
        orig = miio.MiioClient.__init__
        dev = self.dev

        def init(client, ip, token=None, timeout=3.0, retries=3, port=miio.PORT, debug=False):
            orig(client, ip, token, timeout, retries, dev.port, debug)

        for patcher in (mock.patch.object(config, "CONFIG_PATH", self.config_path),
                        mock.patch.object(cli.time, "sleep", lambda s: None),
                        mock.patch.object(cli, "DEFAULT_TIMEOUT", 1.0),
                        mock.patch.object(miio.MiioClient, "__init__", init)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def cli(self, *argv):
        """Run the CLI; returns (exit_code, stdout, stderr). Exit code 0 when main() returns."""
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                cli.main(["--ip", "127.0.0.1", "--token", TOKEN.hex(), *argv])
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 1
        return code, out.getvalue(), err.getvalue()
