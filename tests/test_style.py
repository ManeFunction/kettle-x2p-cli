import io
import os
import sys
import unittest
from unittest import mock

from helpers import DeviceCase, cli
from kettle import style


class Tty(io.StringIO):
    def isatty(self):
        return True


def env(**values):
    """os.environ without the colour variables, plus values."""
    clean = {k: v for k, v in os.environ.items() if k not in ("NO_COLOR", "FORCE_COLOR", "TERM")}
    return mock.patch.dict(os.environ, {**clean, **values}, clear=True)


class EnabledTests(unittest.TestCase):
    def test_terminals_get_colours_and_other_streams_do_not(self):
        with env(), mock.patch.object(style.sys, "platform", "linux"):
            self.assertTrue(style.enabled(Tty()))
            self.assertFalse(style.enabled(io.StringIO()))
            self.assertFalse(style.enabled(object()))

    def test_environment_overrides(self):
        with env(NO_COLOR="1", FORCE_COLOR="1"):
            self.assertFalse(style.enabled(Tty()))
        with env(FORCE_COLOR="1"):
            self.assertTrue(style.enabled(io.StringIO()))
        with env(TERM="dumb"):
            self.assertFalse(style.enabled(Tty()))

    def test_paint(self):
        with env(FORCE_COLOR="1"):
            self.assertEqual(style.paint("hot", "bold", "red"), "\x1b[1;31mhot\x1b[0m")
            self.assertEqual(style.paint(25), "25")
        with env(NO_COLOR="1"):
            self.assertEqual(style.paint("hot", "bold", "red"), "hot")

    def test_options_and_commands_in_a_sentence(self):
        with env(FORCE_COLOR="1"):
            text = style.options("pass -y/--yes, see `kettle setup`; Wi-Fi and keep-warm stay plain")
        self.assertEqual(style.plain(text), "pass -y/--yes, see `kettle setup`; Wi-Fi and keep-warm stay plain")
        for part in ("\x1b[32m-y\x1b[0m", "\x1b[36m--yes\x1b[0m", "\x1b[36m`kettle setup`\x1b[0m"):
            self.assertIn(part, text)
        self.assertNotIn("\x1b", text.split(";")[1])

    def test_json_keeps_its_text(self):
        data = {"model": "a:b", "n": -1.5, "ok": True, "none": None, "s": "true 12"}
        with env(FORCE_COLOR="1"), mock.patch.object(style.sys, "stdout", Tty()):
            text = style.json_text(data, indent=2)
        self.assertEqual(style.plain(text), style.json.dumps(data, indent=2))
        self.assertIn('\x1b[34m"model"\x1b[0m: \x1b[32m"a:b"\x1b[0m', text)
        self.assertIn('\x1b[32m"true 12"\x1b[0m', text)  # nothing coloured inside a string

    def test_prompts_hide_the_codes_from_readline(self):
        with env(FORCE_COLOR="1"), mock.patch.dict(sys.modules, readline=mock.Mock()):
            self.assertEqual(style.prompt("kettle>", "bold"), "\x01\x1b[1m\x02kettle>\x01\x1b[0m\x02")
        with env(FORCE_COLOR="1"), mock.patch.dict(sys.modules):
            sys.modules.pop("readline", None)
            self.assertEqual(style.prompt("kettle>", "bold"), "\x1b[1mkettle>\x1b[0m")


class ColouredCliTests(DeviceCase):
    def coloured(self, *argv):
        with env(FORCE_COLOR="1"):
            return self.cli(*argv)

    def test_help_is_the_plain_help_plus_colours(self):
        for argv in (["--help"], ["warm", "--help"], ["provision", "--help"], ["bogus"], ["--yes", "boil"]):
            with self.subTest(argv=argv):
                plain = self.cli(*argv)
                coloured = self.coloured(*argv)
                self.assertNotEqual(coloured, plain)
                self.assertEqual(tuple(style.plain(x) if isinstance(x, str) else x for x in coloured), plain)

    def test_help_colours(self):
        out = self.coloured("--help")[1]
        for part in ("\x1b[1;34musage:\x1b[0m \x1b[1;35mkettle\x1b[0m", "[\x1b[36m--ip\x1b[0m \x1b[33mIP\x1b[0m]",
                     "\x1b[1;34mcall options (go before the command):\x1b[0m",
                     "  \x1b[1;32m-k\x1b[0m, \x1b[1;36m--keep\x1b[0m \x1b[1;33m[[TEMP] TIME]\x1b[0m",
                     "    \x1b[1;32mcancel\x1b[0m | \x1b[1;32mstop\x1b[0m"):
            self.assertIn(part, out)

    def test_status_and_errors(self):
        self.dev.props[(2, 2)] = 7
        out = self.coloured("status")[1]
        self.assertIn("\x1b[1;32midle\x1b[0m \x1b[2m(0)\x1b[0m", out)
        self.assertIn("\x1b[1;31msomething wrong\x1b[0m", out)
        err = self.coloured("boil", "--yes")[2]
        self.assertTrue(err.startswith("\x1b[1;31merror:\x1b[0m kettle fault"))

    def test_python_314_argparse_colours_stay_off(self):
        if sys.version_info < (3, 14):
            self.skipTest("argparse colours its help itself from Python 3.14")
        self.assertFalse(cli.build_parser().color)


if __name__ == "__main__":
    unittest.main()
