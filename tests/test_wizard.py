import argparse
import unittest
from unittest import mock

from helpers import DID, TOKEN, DeviceCase, FakeDevice, cli, config, miio
from kettle import wizard


def make_args(**kw):
    ns = dict(ip=None, token=None, subnet=None, force_model=False)
    ns.update(kw)
    return argparse.Namespace(**ns)


class Script:
    """Scripted answers for ask()/secret(); records everything printed."""

    def __init__(self, answers=(), secrets=()):
        self.answers, self.secrets, self.printed = iter(answers), iter(secrets), []

    def ask(self, prompt=""):
        self.printed.append(prompt)
        return next(self.answers)

    def secret(self, prompt=""):
        self.printed.append(prompt)
        return next(self.secrets)

    def out(self, *a):
        self.printed.append(" ".join(str(x) for x in a))

    @property
    def text(self):
        return "\n".join(self.printed)


class CleanTokenTests(unittest.TestCase):
    def test_accepts_pasted_variants(self):
        want = "0123456789abcdef0123456789abcdef"
        for raw in (want, want.upper(), f"  {want}\n", f'"{want}"', "01234567 89abcdef 01234567 89abcdef"):
            self.assertEqual(wizard.clean_token(raw), want, raw)

    def test_rejects_wrong_input(self):
        for raw in ("", "abc", "g" * 32, "0" * 31, "0" * 33):
            self.assertEqual(wizard.clean_token(raw), "", raw)


class WizardTests(DeviceCase):
    def discover_here(self):
        real = miio.discover
        return mock.patch.object(wizard, "discover",
                                 lambda base: real("127.0.0", wait=0.5, port=self.dev.port))

    def run_wizard(self, script, **kw):
        with self.discover_here(), mock.patch.object(wizard, "local_subnet", lambda: "127.0.0"):
            wizard.run_setup(make_args(**kw), ask=script.ask, secret=script.secret, out=script.out)

    def test_happy_path_finds_the_kettle_and_saves_it(self):
        s = Script(answers=[""], secrets=[TOKEN.hex()])
        self.run_wizard(s)
        self.assertEqual(config.load_config(), {"ip": "127.0.0.1", "token": TOKEN.hex(), "did": DID,
                                                "model": "xiaomi.kettle.v20"})
        self.assertEqual(oct(self.config_path.stat().st_mode)[-3:], "600")
        for text in ("Xiaomi Home", "Xiaomi-Cloud-Tokens-Extractor", "token_extractor.py",
                     "All set", "DHCP reservation"):
            self.assertIn(text, s.text)
        self.assertNotIn(TOKEN.hex(), s.text)  # the token is never echoed back in full

    def test_bad_token_input_is_retried_then_accepted(self):
        s = Script(answers=[""], secrets=["nope", "1234", TOKEN.hex().upper()])
        self.run_wizard(s)
        self.assertEqual(config.load_config()["token"], TOKEN.hex())
        self.assertEqual(s.text.count("not a 32-character hex token"), 2)

    def test_gives_up_after_three_bad_tokens(self):
        s = Script(answers=[""], secrets=["a", "b", "c"])
        with self.assertRaises(cli.KettleError):
            self.run_wizard(s)
        self.assertEqual(config.load_config(), {})

    def test_wrong_token_saves_nothing(self):
        s = Script(answers=["", "127.0.0.1"], secrets=["00" * 16])  # Enter after step 1, then a manual IP
        with self.assertRaises(cli.KettleError) as cm:
            self.run_wizard(s)
        self.assertIn("did not accept the token", str(cm.exception))
        self.assertEqual(config.load_config(), {})

    def test_unsupported_model_is_not_saved(self):
        self.dev.model = "yunmi.kettle.v19"
        with self.assertRaises(cli.KettleError) as cm:
            self.run_wizard(Script(answers=[""], secrets=[TOKEN.hex()]))
        self.assertIn("supports", str(cm.exception))
        self.assertEqual(config.load_config(), {})

    def test_manual_ip_when_discovery_finds_nothing(self):
        s = Script(answers=["", "not-an-ip", "127.0.0.1"], secrets=[TOKEN.hex()])
        with mock.patch.object(wizard, "discover", lambda base: []), \
                mock.patch.object(wizard, "local_subnet", lambda: "127.0.0"):
            wizard.run_setup(make_args(), ask=s.ask, secret=s.secret, out=s.out)
        self.assertEqual(config.load_config()["ip"], "127.0.0.1")
        self.assertIn("Could not find the kettle automatically", s.text)
        self.assertIn("not an IPv4 address", s.text)

    def test_skipped_when_already_set_up(self):
        config.save_config({"ip": "127.0.0.1", "token": TOKEN.hex(), "did": DID, "model": "m"})
        s = Script(answers=["n"])
        self.run_wizard(s)
        self.assertIn("Nothing changed", s.text)
        self.assertEqual(config.load_config()["model"], "m")

    def test_scripted_mode_needs_no_prompts(self):
        s = Script()  # any ask()/secret() call would raise StopIteration
        self.run_wizard(s, token=TOKEN.hex(), ip="127.0.0.1")
        self.assertEqual(config.load_config()["ip"], "127.0.0.1")
        self.assertNotIn("Step 1/4", s.text)

    def test_scripted_mode_rejects_a_malformed_token(self):
        with self.assertRaises(cli.KettleError):
            self.run_wizard(Script(), token="zz", ip="127.0.0.1")


if __name__ == "__main__":
    unittest.main()
