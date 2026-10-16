import json
import unittest
from unittest import mock

from helpers import DID, TOKEN, DeviceCase, FakeDevice, cli, config


class HeatingCommandTests(DeviceCase):
    def test_boil_writes_the_spec_batch(self):
        self.assertEqual(self.cli("--yes", "boil")[0], 0)
        self.assertEqual(self.dev.writes, [[(2, 4, 99), (2, 5, False), (2, 6, 40), (3, 1, 1440),
                                            (3, 11, 1), (3, 13, "99,0,40,1440")]])

    def test_warm_to(self):
        self.cli("--yes", "warm-to", "70")
        self.assertEqual(self.dev.writes, [[(2, 4, 70), (2, 5, False), (2, 6, 40), (3, 1, 1440),
                                            (3, 11, 0), (3, 12, "70,0,40,1440")]])

    def test_warm_keep(self):
        self.cli("--yes", "warm-keep", "80", "120")
        self.assertEqual(self.dev.writes, [[(2, 4, 80), (2, 5, True), (2, 6, 80), (3, 1, 120),
                                            (3, 11, 0), (3, 12, "80,1,80,120")]])

    def test_validation_rejects_without_sending(self):
        for argv in (["warm-to", "39"], ["warm-to", "100"], ["warm-keep", "80", "59"],
                     ["warm-keep", "80", "1441"], ["warm-keep", "20", "120"]):
            with self.subTest(argv=argv):
                self.assertEqual(self.cli("--yes", *argv)[0], 1)
        self.assertEqual(self.dev.writes, [])

    def test_safety_refusals(self):
        for props in ({(2, 2): 2}, {(3, 7): True}, {(2, 1): 1}):  # fault, lifted, not idle
            with self.subTest(props=props):
                self.dev.props.update(props)
                self.assertEqual(self.cli("--yes", "boil")[0], 1)
        self.assertEqual(self.dev.writes, [])

    def test_wrong_model_is_refused(self):
        self.dev.model = "something.else"
        self.assertEqual(self.cli("--yes", "boil")[0], 1)
        self.assertEqual(self.dev.writes, [])

    def test_needs_yes_without_a_terminal(self):
        with mock.patch.object(cli.sys.stdin, "isatty", return_value=False):
            self.assertEqual(self.cli("boil")[0], 1)
        self.assertEqual(self.dev.writes, [])

    def test_dry_run_sends_nothing(self):
        code, out, _ = self.cli("--dry-run", "warm-keep", "80", "120")
        self.assertEqual(code, 0)
        self.assertIn("(3,12) = '80,1,80,120'", out)
        self.assertEqual((self.dev.writes, self.dev.seen), ([], []))

    def test_cancel_sends_stop_work(self):
        self.cli("cancel")
        self.assertEqual(self.dev.actions, [(3, 1)])


class ReadCommandTests(DeviceCase):
    def test_status(self):
        _, out, _ = self.cli("status")
        for text in ("idle", "25 C", "water level"):
            self.assertIn(text, out)

    def test_info_hides_the_token_and_saves_the_config(self):
        _, out, _ = self.cli("info")
        self.assertNotIn("ff" * 16, out)
        self.assertNotIn(TOKEN.hex(), out)
        saved = json.loads(self.config_path.read_text())
        self.assertEqual(saved, {"ip": "127.0.0.1", "token": TOKEN.hex(), "did": DID,
                                 "model": "xiaomi.kettle.v20"})
        self.assertEqual(oct(self.config_path.stat().st_mode)[-3:], "600")

    def test_version(self):
        with self.assertRaises(SystemExit) as cm, mock.patch("sys.stdout") as out:
            cli.main(["--version"])
        self.assertEqual(cm.exception.code, 0)
        self.assertIn("kettle v", "".join(c.args[0] for c in out.write.call_args_list))


class FirstRunTests(DeviceCase):
    def run_plain(self, *argv):
        import contextlib, io  # noqa: E401
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit):
            cli.main(list(argv))
        return err.getvalue()

    def test_commands_point_to_setup_when_nothing_is_saved(self):
        self.assertIn("kettle setup", self.run_plain("status"))
        self.assertIn("kettle setup", self.run_plain("--ip", "127.0.0.1", "status"))  # ip but no token


class ShellTests(DeviceCase):
    def test_shell_keeps_the_session_and_survives_errors(self):
        lines = iter(["status", "warm-to 20", "bogus", "warm-to 65", "cancel", "quit"])
        with mock.patch("builtins.input", lambda prompt="": next(lines)):
            code, out, _ = self.cli("--yes", "shell")
        self.assertEqual(code, 0)
        self.assertEqual([w[0][2] for w in self.dev.writes], [65])  # 20 was rejected
        self.assertEqual(self.dev.actions, [(3, 1)])
        self.assertIn("error: temperature must be 40-99", out)

    def test_shell_blocks_setup_commands(self):
        lines = iter(["setup", "quit"])
        with mock.patch("builtins.input", lambda prompt="": next(lines)):
            _, out, _ = self.cli("shell")
        self.assertIn("not available inside the shell", out)


class FindTests(DeviceCase):
    def test_find_saves_the_ip(self):
        config.save_config({"ip": "10.0.0.9", "token": TOKEN.hex(), "did": DID, "model": "m"})
        real = cli.discover
        with mock.patch.object(cli, "discover", lambda base: real("127.0.0", wait=0.5, port=self.dev.port)):
            code, out, _ = self.cli("find", "--subnet", "127.0.0")
        self.assertEqual(code, 0)
        self.assertEqual(config.load_config()["ip"], "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
