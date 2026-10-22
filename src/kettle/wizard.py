"""`kettle setup`: guided first-time setup with on-screen instructions.

Steps: pair in the Xiaomi Home app, get the token with the open-source extractor, paste it,
find the kettle on the LAN (the token tells us which device is the kettle), verify and save.
"""
from __future__ import annotations

import getpass
import ipaddress
import re
import sys

from . import cli, config
from .miio import MiioClient, MiioError, discover, local_subnet
from .style import code, paint, prompt

EXTRACTOR_URL = "https://github.com/PiotrMachowski/Xiaomi-Cloud-Tokens-Extractor"
EXTRACTOR_ZIP = ("https://github.com/PiotrMachowski/Xiaomi-cloud-tokens-extractor"
                 "/releases/latest/download/token_extractor.zip")
TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")
RULE = "-" * 64


def clean_token(raw: str) -> str:
    """Lower-case a pasted token and drop spaces/quotes/colons; "" if it is not 32 hex digits."""
    token = re.sub(r"[\s'\"`:]", "", raw).lower()
    return token if TOKEN_RE.match(token) else ""


def probe(ip: str, token: bytes, timeout: float = 1.5):
    """miIO.info from ip with the token, or None if it does not answer / cannot decrypt."""
    c = MiioClient(ip, token, timeout=timeout, retries=2)
    try:
        info = c.call("miIO.info")
        return info if isinstance(info, dict) else None
    except MiioError:
        return None
    finally:
        c.close()


def ref(text) -> str:
    """Commands, addresses, paths and URLs, in cyan."""
    return paint(text, "cyan")


def run_setup(args, ask=input, secret=getpass.getpass, out=print) -> None:
    rule = paint(RULE, "dim")

    def step(n: int, title: str) -> None:
        out(f"\n{rule}\n{paint(f'Step {n}/4:', 'bold', 'blue')} {paint(title, 'bold')}\n{rule}")

    def yes_no(question: str) -> str:
        return prompt(question, "bold") + prompt(" [y/N] ", "dim")

    scripted = bool(args.token)  # token on the command line: no prompts, for scripts
    if not scripted and not sys.stdin.isatty() and ask is input:
        cli.die("setup is interactive; for scripts pass --token (and --ip) instead")

    out(f"{paint('kettle setup', 'bold', 'magenta')}: connect this computer to your Xiaomi Smart Kettle 2 Pro")
    saved = config.load_config()
    if saved.get("token") and saved.get("ip") and not scripted:
        out(f"\nAlready set up for {ref(saved['ip'])} ({paint(saved.get('model', 'unknown model'), 'bold')}).")
        if ask(yes_no("Run setup again?")).strip().lower() != "y":
            out(code("Nothing changed. Try `kettle status`."))
            return

    # ---- 1. pairing -------------------------------------------------
    if not scripted:
        step(1, "Add the kettle to the Xiaomi Home app")
        out(f"""The kettle gets onto your Wi-Fi through Xiaomi's app, and Xiaomi's cloud is the
only place that knows the kettle's {paint('token', 'bold')} (its local password). You need this once.

  {paint('1.', 'bold')} Install {paint('"Xiaomi Home"', 'bold')} (iOS / Android) and sign in. Remember the server region.
  {paint('2.', 'bold')} {paint('Add device > Xiaomi Smart Kettle 2 Pro', 'bold')}, and follow the in-app Wi-Fi setup.
     The kettle only works on a {paint('2.4 GHz', 'bold', 'yellow')} network.
  {paint('3.', 'bold')} Wait until the app shows the kettle as online.

{paint('Do not reset or re-add the kettle later: that creates a new token.', 'yellow')}""")
        ask("\n" + prompt("Press Enter when the kettle is online in the app... ", "bold"))

    # ---- 2. token ---------------------------------------------------
    if not scripted:
        step(2, "Get the token")
    token_hex = ""
    if scripted:
        token_hex = clean_token(args.token)
        if not token_hex:
            cli.die("--token must be 32 hex characters")
    else:
        out(f"""Use the free open-source extractor (MIT licensed):
  {ref(EXTRACTOR_URL)}

  {paint('Windows:', 'bold')}        download {ref('token_extractor.exe')} from the latest release and run it.
  {paint('macOS / Linux:', 'bold')}  needs Python 3; in a Terminal run
      {ref(f'curl -L -o token_extractor.zip {EXTRACTOR_ZIP}')}
      {ref('unzip token_extractor.zip && cd token_extractor')}
      {ref('pip3 install -r requirements.txt')}
      {ref('python3 token_extractor.py')}

It asks for your Xiaomi account login (or a QR code) and a server region; leave the
region empty to check all of them. Your login goes only to the extractor, never to kettle.
In its list find {paint('"Xiaomi Smart Kettle 2 Pro"', 'bold')} (model {cli.EXPECTED_MODEL}) and copy its
{paint('TOKEN', 'bold')}: 32 letters and digits. {paint('Treat it like a password.', 'yellow')}""")
        for attempt in range(3):
            token_hex = clean_token(secret("\n" + paint("Paste the token here", "bold")
                                           + paint(" (hidden, then Enter): ", "dim")))
            if token_hex:
                break
            out(paint("That is not a 32-character hex token (0-9, a-f). Copy just the token and try again.", "yellow"))
        if not token_hex:
            cli.die("no valid token entered; run `kettle setup` again when you have it", 2)
        out(f"{paint('Token accepted', 'bold', 'green')} (ends in ...{token_hex[-4:]}).")
    token = bytes.fromhex(token_hex)

    # ---- 3. find the kettle -----------------------------------------
    step(3, "Find the kettle on your network")
    ip = args.ip
    info = None
    if ip:
        out(f"Using {ref(ip)}.")
    else:
        base = args.subnet.rsplit(".", 1)[0] if args.subnet and args.subnet.count(".") == 3 else (
            args.subnet or local_subnet())
        out(f"Looking for Xiaomi devices on {ref(f'{base}.0/24')} (a few seconds)...")
        try:
            devices = discover(base)
        except OSError as e:
            cli.die(f"network scan failed: {e}")
        out(f"{paint(len(devices), 'bold')} Xiaomi device(s) answered; testing your token on each...")
        for dev_ip, _did in devices:
            found = probe(dev_ip, token)
            if found:
                ip, info = dev_ip, found
                out(f"  {ref(dev_ip)}: {paint(found.get('model'), 'bold')}  "
                    + paint("<- your token works here", "green"))
                break
            out(f"  {ref(dev_ip)}: {paint('not the kettle (token rejected)', 'dim')}")
    if not ip:
        if scripted:
            cli.die("kettle not found; check it is online, or pass --ip")
        out(f"""
{paint('Could not find the kettle automatically.', 'bold', 'yellow')} Its address is in your router's client list
(look for a device named "xiaomi", "kettle" or with a MAC starting with {paint('E4:FE:43', 'bold')}), or in
the extractor's output. Same Wi-Fi as this computer is required.""")
        for _ in range(3):
            raw = ask(prompt("Kettle IP address", "bold") + prompt(" (Enter to quit): ", "dim")).strip()
            if not raw:
                cli.die("setup cancelled", 2)
            try:
                ip = str(ipaddress.ip_address(raw))
                break
            except ValueError:
                out(paint("That is not an IPv4 address, like 192.168.1.36.", "yellow"))
        if not ip:
            cli.die("no valid IP entered", 2)

    # ---- 4. verify and save -----------------------------------------
    step(4, "Check and save")
    info = info or probe(ip, token, timeout=3.0)
    if info is None:
        cli.die(f"""{ip} did not accept the token, so nothing was saved. Usual reasons:
  - the token is from a different device or an old pairing (the extractor shows several);
  - the kettle was re-added to the app since, so its token changed: run the extractor again;
  - the kettle is offline or on another network.""")
    model = info.get("model")
    if model != cli.EXPECTED_MODEL and not args.force_model:
        cli.die(f"the device at {ip} is {model!r}, but kettle supports {cli.EXPECTED_MODEL!r} only "
                f"(Xiaomi Smart Kettle 2 Pro, EU). Nothing was saved.")
    c = MiioClient(ip, token, timeout=3.0)
    try:
        did = c.handshake().did
    finally:
        c.close()
    config.save_config({"ip": ip, "token": token_hex, "did": did, "model": model})
    out(f"{paint('Saved', 'bold', 'green')} to {ref(config.CONFIG_PATH)} (readable by you only).")
    out(f"\n{paint('Kettle:', 'bold', 'blue')} {paint(model, 'bold')}, "
        f"firmware {paint(info.get('fw_ver', '?'), 'bold')}, "
        f"MAC {paint(info.get('mac', '?'), 'bold')}, IP {ref(ip)}")
    out(f"{paint('Tip:', 'bold')} give it a fixed address (DHCP reservation) in your router so the IP never changes.")
    out(code("If it ever moves, `kettle find` locates it again."))
    tries = "".join(f"\n  {ref(f'kettle {c}')}" for c in ("status", "boil", "shell"))
    out(f"\n{rule}\n{paint('All set.', 'bold', 'green')} Try:{tries}\n{rule}")
