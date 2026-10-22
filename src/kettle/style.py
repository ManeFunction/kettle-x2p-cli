"""ANSI colours for the terminal output, standard library only.

Colours are on only when the stream is a terminal; NO_COLOR (https://no-color.org) turns them off, FORCE_COLOR
on, and TERM=dumb off, in that order (the rules of Python 3.14's argparse). The palette:
  (bold) blue    headings (field names)            bold magenta  the program name
  green          success, healthy readings          red           errors, faults
  yellow         warnings, things to check          cyan          commands, addresses, paths, URLs
  bold           the values that matter             dim           secondary details
"""
from __future__ import annotations

import functools
import json
import os
import re
import sys

CODES = {"bold": "1", "dim": "2", "red": "31", "green": "32", "yellow": "33", "blue": "34", "magenta": "35",
         "cyan": "36"}
RESET = "\x1b[0m"
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
CODE_RE = re.compile(r"`[^`\n]+`")
OPTION_RE = re.compile(r"(?<![\w-])--?[a-zA-Z][\w-]*")
JSON_TOKEN_RE = re.compile(r'("(?:[^"\\]|\\.)*")(\s*:)?|\b(true|false|null)\b|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)')


@functools.lru_cache(maxsize=None)
def windows_vt() -> bool:
    """Switch the Windows console to ANSI mode; False where it cannot be (old consoles)."""
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE; stderr shares the console
        mode = ctypes.c_ulong()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(mode.value & 4 or kernel32.SetConsoleMode(handle, mode.value | 4))  # VIRTUAL_TERMINAL_PROCESSING
    except Exception:
        return False


def enabled(file=None) -> bool:
    file = sys.stdout if file is None else file
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    if os.environ.get("TERM") == "dumb":
        return False
    try:
        if not file.isatty():
            return False
    except (AttributeError, ValueError):
        return False
    return sys.platform != "win32" or windows_vt()


def paint(text, *styles: str, file=None) -> str:
    """text in the given styles (names from CODES) if file (default stdout) shows colours."""
    if not styles or not enabled(file):
        return str(text)
    return f"\x1b[{';'.join(CODES[s] for s in styles)}m{text}{RESET}"


def prompt(text, *styles: str) -> str:
    """paint() for an input() prompt: with readline loaded, its line editing must not count the colour codes."""
    painted = paint(text, *styles)
    if "readline" not in sys.modules:
        return painted
    return ANSI_RE.sub(lambda m: f"\x01{m.group()}\x02", painted)


def plain(text: str) -> str:
    return ANSI_RE.sub("", text)


def code(text: str, file=None) -> str:
    """Commands quoted in backticks, like `kettle setup`, in cyan."""
    return CODE_RE.sub(lambda m: paint(m.group(), "cyan", file=file), text)


def option(name: str, file=None, bold: bool = False) -> str:
    """-s in green, --long in cyan (argparse's colours)."""
    return paint(name, *(("bold",) if bold else ()), "cyan" if name.startswith("--") else "green", file=file)


def options(text: str, file=None) -> str:
    """Every -s / --long option mentioned in a sentence, and its `commands`, coloured."""
    return OPTION_RE.sub(lambda m: option(m.group(), file), code(text, file))


def error(msg, file=None) -> str:
    """An `error: ...` line for file (default stderr)."""
    file = sys.stderr if file is None else file
    return f"{paint('error:', 'bold', 'red', file=file)} {code(str(msg), file)}"


def warning(msg, label: str = "warning:", file=None) -> str:
    return f"{paint(label, 'bold', 'yellow', file=file)} {code(str(msg), file)}"


def coded(name, number) -> str:
    """`idle (0)`: a name with the number it stands for, dimmed."""
    return f"{name} {paint(f'({number})', 'dim')}"


def field(label: str, value, width: int) -> str:
    """One `label : value` line of a report, labels padded to width."""
    return f"{paint(label.ljust(width), 'blue')} : {value}"


def json_text(data, indent=None) -> str:
    """json.dumps with keys in blue, strings in green and numbers, booleans and null in yellow."""
    text = json.dumps(data, indent=indent)
    if not enabled():
        return text

    def token(m):
        if m.group(1):
            return paint(m.group(1), "blue" if m.group(2) else "green") + (m.group(2) or "")
        return paint(m.group(), "yellow")
    return JSON_TOKEN_RE.sub(token, text)
