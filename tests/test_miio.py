import hashlib
import unittest

from helpers import DID, TOKEN, FakeDevice, miio


class PacketTests(unittest.TestCase):
    def test_hello_packet(self):
        self.assertEqual(miio.HELLO, bytes.fromhex("21310020") + b"\xff" * 28)

    def test_key_derivation(self):
        key = hashlib.md5(TOKEN).digest()
        self.assertEqual(miio._keys(TOKEN), (key, hashlib.md5(key + TOKEN).digest()))

    def test_build_and_decode_roundtrip(self):
        pkt = miio.build_packet(TOKEN, DID, 1234, {"id": 1, "result": ["ok"]})
        self.assertEqual(miio.decode_response(TOKEN, pkt)["result"], ["ok"])

    def test_wrong_token_is_rejected(self):
        pkt = miio.build_packet(TOKEN, DID, 1234, {"id": 1, "result": []})
        with self.assertRaises(miio.MiioError):
            miio.decode_response(b"\x01" * 16, pkt)

    def test_malformed_packets(self):
        with self.assertRaises(miio.MiioError):
            miio.parse_packet(b"\x21\x31")
        with self.assertRaises(miio.MiioError):
            miio.parse_packet(b"\x00" * 40)


class ClientTests(unittest.TestCase):
    def client(self, dev, token=TOKEN, timeout=1.0):
        return miio.MiioClient("127.0.0.1", token, port=dev.port, timeout=timeout)

    def test_handshake_and_ids_increase(self):
        dev = FakeDevice()
        with self.client(dev) as c:
            h = c.handshake()
            self.assertEqual((h.did, h.stamp, h.token), (DID, 5000, None))
            c.call("one")
            c.call("two")
        self.assertEqual([r["id"] for r in dev.seen], [1, 2])

    def test_leaked_token_is_picked_up(self):
        dev = FakeDevice(leak_token=True)
        with self.client(dev, token=None) as c:
            self.assertEqual(c.handshake().token, TOKEN)
            self.assertEqual(c.token, TOKEN)

    def test_leaked_token_beats_a_stale_saved_one(self):
        dev = FakeDevice(leak_token=True)
        with self.client(dev, token=b"\x11" * 16) as c:
            self.assertEqual(c.call("miIO.info")["model"], "xiaomi.kettle.v20")

    def test_retries_after_a_dropped_packet(self):
        dev = FakeDevice(drop_first=1)
        with self.client(dev, timeout=0.3) as c:
            self.assertEqual(c.call("miIO.info")["model"], "xiaomi.kettle.v20")

    def test_no_token_is_an_error(self):
        with miio.MiioClient("127.0.0.1", None, port=1, timeout=0.2) as c:
            with self.assertRaises(miio.MiioError):
                c.call("miIO.info")

    def test_miot_param_shapes(self):
        dev = FakeDevice()
        with self.client(dev) as c:
            c.get_properties([(2, 1)])
            c.set_properties([(2, 4, 99)])
            c.action(3, 1)
        get, set_, act = dev.seen
        self.assertEqual(get["params"], [{"did": "2-1", "siid": 2, "piid": 1}])
        self.assertEqual(set_["params"], [{"did": "2-4", "siid": 2, "piid": 4, "value": 99}])
        self.assertEqual(act["params"], {"did": "action-3-1", "siid": 3, "aiid": 1, "in": []})


class DiscoverTests(unittest.TestCase):
    def test_finds_a_responding_device(self):
        dev = FakeDevice()
        self.assertEqual(miio.discover("127.0.0", wait=0.5, port=dev.port), [("127.0.0.1", DID)])


if __name__ == "__main__":
    unittest.main()
