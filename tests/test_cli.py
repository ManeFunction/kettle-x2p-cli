import json
import unittest
from unittest import mock

from helpers import DID, TOKEN, DeviceCase, FakeDevice, cli, config


class HeatingCommandTests(DeviceCase):
    def test_boil_writes_the_spec_batch(self):
        self.assertEqual(self.cli("boil", "--yes")[0], 0)
        self.assertEqual(self.dev.writes, [[(2, 4, 99), (2, 5, False), (2, 6, 40), (3, 1, 1440),
                                            (3, 11, 1), (3, 13, "99,0,40,1440")]])

    def test_boil_keep(self):
        self.cli("boil", "--keep", "60", "2", "--yes")
        self.assertEqual(self.dev.writes, [[(2, 4, 99), (2, 5, True), (2, 6, 60), (3, 1, 120),
                                            (3, 11, 1), (3, 13, "99,1,60,120")]])

    def test_warm(self):
        self.cli("warm", "70", "--yes")
        self.assertEqual(self.dev.writes, [[(2, 4, 70), (2, 5, False), (2, 6, 40), (3, 1, 1440),
                                            (3, 11, 0), (3, 12, "70,0,40,1440")]])

    def test_warm_keep(self):
        self.cli("warm", "80", "-k", "80", "2", "--yes")
        self.assertEqual(self.dev.writes, [[(2, 4, 80), (2, 5, True), (2, 6, 80), (3, 1, 120),
                                            (3, 11, 0), (3, 12, "80,1,80,120")]])

    def test_keep_temp_may_differ_from_target(self):
        self.cli("warm", "90", "--keep", "55", "1", "--yes")
        self.assertEqual(self.dev.writes[0][-1], (3, 12, "90,1,55,60"))

    def test_bare_keep_on_boil_uses_99_and_one_hour(self):
        self.cli("boil", "--keep", "--yes")
        self.assertEqual(self.dev.writes, [[(2, 4, 99), (2, 5, True), (2, 6, 99), (3, 1, 60),
                                            (3, 11, 1), (3, 13, "99,1,99,60")]])

    def test_bare_keep_on_warm_uses_the_target_and_one_hour(self):
        self.cli("warm", "60", "-k", "--yes")
        self.assertEqual(self.dev.writes, [[(2, 4, 60), (2, 5, True), (2, 6, 60), (3, 1, 60),
                                            (3, 11, 0), (3, 12, "60,1,60,60")]])

    def test_a_single_keep_value_is_the_time(self):
        self.cli("warm", "90", "-k", "2", "--yes")
        self.assertEqual(self.dev.writes[0][-1], (3, 12, "90,1,90,120"))

    def test_keep_time_takes_fractions_of_an_hour(self):
        self.cli("boil", "-k", "1.5", "--yes")
        self.assertEqual(self.dev.writes[0][-1], (3, 13, "99,1,99,90"))

    def test_a_single_keep_value_outside_1_24_hours_is_rejected(self):
        for argv in (["boil", "-k", "0.5"], ["warm", "90", "-k", "25"], ["boil", "-k", "55"], ["boil", "-k", "0"]):
            with self.subTest(argv=argv):
                self.assertEqual(self.cli(*argv, "--yes")[0], 1)
        self.assertEqual(self.dev.writes, [])

    def test_a_single_keep_value_on_boil_keeps_99(self):
        self.cli("boil", "-k", "3", "--yes")
        self.assertEqual(self.dev.writes[0][-1], (3, 13, "99,1,99,180"))

    def test_keep_takes_at_most_two_values(self):
        self.assertEqual(self.cli("boil", "-k", "60", "60", "60", "--yes")[0], 1)
        self.assertEqual(self.dev.writes, [])

    def test_keep_before_the_command_points_to_the_right_place(self):
        code, _, err = self.cli("--keep", "boil")
        self.assertEqual(code, 2)
        self.assertIn("goes after the command", err)

    def test_help_lists_commands_in_the_documented_order(self):
        _, out, _ = self.cli("--help")
        names = ["hello", "setup", "info", "boil", "warm", "cancel", "status", "find", "shell", "provision"]
        positions = [out.index(f"\n    {n} ") for n in names]
        self.assertEqual(positions, sorted(positions))
        flags = [out.index(f"\n  {f}") for f in ("-h, --help", "-v, --version", "--ip", "--token", "--force-model",
                                                 "-k, --keep", "--yes", "--dry-run", "--timeout", "--debug")]
        self.assertEqual(flags, sorted(flags))
        self.assertLess(out.index("\ncall options"), out.index("\n  --ip"))
        self.assertLess(out.index("\n  --force-model"), out.index("\ncommand options"))
        self.assertLess(out.index("\ncommand options"), out.index("\n  --timeout"))

    def test_command_help_lists_its_options_in_the_command_block(self):
        _, out, _ = self.cli("warm", "--help")
        block = out[out.index("command options"):]
        for flag in ("-k, --keep", "--yes", "--dry-run", "--timeout", "--debug", "--set-on"):
            self.assertIn(flag, block)
        self.assertNotIn("--ip", out)

    def test_usage_shows_command_options_behind_the_command(self):
        _, out, _ = self.cli("--help")
        usage = " ".join(out.split("\n\n")[0].split())
        self.assertIn("command [--keep [[TEMP] TIME]] [--yes] [--dry-run] [--timeout TIMEOUT] [--debug] ...", usage)
        self.assertNotIn("[--yes] [--dry-run] [--timeout TIMEOUT] [--debug] [--force-model]", usage)
        _, out, _ = self.cli("warm", "--help")
        usage = " ".join(out.split("\n\n")[0].split())
        self.assertIn("warm [--help] temp [--keep [[TEMP] TIME]] [--yes] [--dry-run] [--timeout TIMEOUT] [--debug] [--set-on]", usage)

    def test_usage_on_error_uses_long_options(self):
        for argv in (["bogus"], ["warm"], ["--yes", "boil"]):
            with self.subTest(argv=argv):
                _, _, err = self.cli(*argv)
                usage = err.split("\n\n")[0]
                self.assertIn("[--help]", usage)
                self.assertNotRegex(usage, r"\[-[a-zA-Z]\b")

    def test_command_options_before_the_command_point_to_the_right_place(self):
        for argv in (["--yes", "boil"], ["--dry-run", "boil"], ["--debug", "status"], ["--timeout", "5", "status"]):
            with self.subTest(argv=argv):
                code, _, err = self.cli(*argv)
                self.assertEqual(code, 2)
                self.assertIn("goes after the command", err)

    def test_timeout_and_debug_go_after_the_command(self):
        code, out, _ = self.cli("status", "--timeout", "2", "--debug")
        self.assertEqual(code, 0)
        self.assertIn("[miio] request", out)  # --debug took effect
        self.assertIn("temperature  : 25 C", out)

    def test_old_warm_commands_are_gone(self):
        for argv in (["warm-to", "70"], ["warm-keep", "80", "120"]):
            with self.subTest(argv=argv):
                self.assertEqual(self.cli(*argv, "--yes")[0], 2)  # argparse: invalid choice
        self.assertEqual(self.dev.writes, [])

    def test_validation_rejects_without_sending(self):
        for argv in (["warm", "39"], ["warm", "100"], ["warm", "80", "--keep", "80", "0.9"],
                     ["warm", "80", "--keep", "80", "24.1"], ["warm", "80", "--keep", "20", "2"],
                     ["boil", "--keep", "80", "0.5"], ["boil", "--keep", "100", "2"],
                     ["boil", "--keep", "55.5", "2"]):
            with self.subTest(argv=argv):
                self.assertEqual(self.cli(*argv, "--yes")[0], 1)
        self.assertEqual(self.dev.writes, [])

    def test_safety_refusals(self):
        for props in ({(2, 2): 2}, {(3, 7): True}, {(2, 1): 1}):  # fault, lifted, not idle
            with self.subTest(props=props):
                self.dev.props.update(props)
                self.assertEqual(self.cli("boil", "--yes")[0], 1)
        self.assertEqual(self.dev.writes, [])

    def test_wrong_model_is_refused(self):
        self.dev.model = "something.else"
        self.assertEqual(self.cli("boil", "--yes")[0], 1)
        self.assertEqual(self.dev.writes, [])

    def test_needs_yes_without_a_terminal(self):
        with mock.patch.object(cli.sys.stdin, "isatty", return_value=False):
            self.assertEqual(self.cli("boil")[0], 1)
        self.assertEqual(self.dev.writes, [])

    def test_dry_run_sends_nothing(self):
        code, out, _ = self.cli("warm", "80", "--keep", "80", "2", "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("(3,12) = '80,1,80,120'", out)
        self.assertEqual((self.dev.writes, self.dev.seen), ([], []))

    def test_cancel_and_stop_send_stop_work(self):
        for name in ("cancel", "stop"):
            with self.subTest(name=name):
                self.dev.actions.clear()
                self.cli(name)
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
        for flag in ("--version", "-v"):
            with self.subTest(flag=flag), self.assertRaises(SystemExit) as cm, mock.patch("sys.stdout") as out:
                cli.main([flag])
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
        lines = iter(["status", "warm 20", "bogus", "warm 65", "stop", "quit"])
        with mock.patch("builtins.input", lambda prompt="": next(lines)):
            code, out, _ = self.cli("shell", "--yes")
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
