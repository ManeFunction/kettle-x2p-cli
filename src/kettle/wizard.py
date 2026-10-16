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


def run_setup(args, ask=input, secret=getpass.getpass, out=print) -> None:
    def step(n: int, title: str) -> None:
        out(f"\n{RULE}\nStep {n}/4: {title}\n{RULE}")

    scripted = bool(args.token)  # token on the command line: no prompts, for scripts
    if not scripted and not sys.stdin.isatty() and ask is input:
        cli.die("setup is interactive; for scripts pass --token (and --ip) instead")

    out("kettle setup: connect this computer to your Xiaomi Smart Kettle 2 Pro")
    saved = config.load_config()
    if saved.get("token") and saved.get("ip") and not scripted:
        out(f"\nAlready set up for {saved['ip']} ({saved.get('model', 'unknown model')}).")
        if ask("Run setup again? [y/N] ").strip().lower() != "y":
            out("Nothing changed. Try `kettle status`.")
            return

    # ---- 1. pairing -------------------------------------------------
    if not scripted:
        step(1, "Add the kettle to the Xiaomi Home app")
        out("""The kettle gets onto your Wi-Fi through Xiaomi's app, and Xiaomi's cloud is the
only place that knows the kettle's token (its local password). You need this once.

  1. Install "Xiaomi Home" (iOS / Android) and sign in. Remember the server region.
  2. Add device > Xiaomi Smart Kettle 2 Pro, and follow the in-app Wi-Fi setup.
     The kettle only works on a 2.4 GHz network.
  3. Wait until the app shows the kettle as online.

Do not reset or re-add the kettle later: that creates a new token.""")
        ask("\nPress Enter when the kettle is online in the app... ")

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
  {EXTRACTOR_URL}

  Windows:        download token_extractor.exe from the latest release and run it.
  macOS / Linux:  needs Python 3; in a Terminal run
      curl -L -o token_extractor.zip {EXTRACTOR_ZIP}
      unzip token_extractor.zip && cd token_extractor
      pip3 install -r requirements.txt
      python3 token_extractor.py

It asks for your Xiaomi account login (or a QR code) and a server region; leave the
region empty to check all of them. Your login goes only to the extractor, never to kettle.
In its list find "Xiaomi Smart Kettle 2 Pro" (model xiaomi.kettle.v20) and copy its
TOKEN: 32 letters and digits. Treat it like a password.""")
        for attempt in range(3):
            token_hex = clean_token(secret("\nPaste the token here (hidden, then Enter): "))
            if token_hex:
                break
            out("That is not a 32-character hex token (0-9, a-f). Copy just the token and try again.")
        if not token_hex:
            cli.die("no valid token entered; run `kettle setup` again when you have it", 2)
        out(f"Token accepted (ends in ...{token_hex[-4:]}).")
    token = bytes.fromhex(token_hex)

    # ---- 3. find the kettle -----------------------------------------
    step(3, "Find the kettle on your network")
    ip = args.ip
    info = None
    if ip:
        out(f"Using {ip}.")
    else:
        base = args.subnet.rsplit(".", 1)[0] if args.subnet and args.subnet.count(".") == 3 else (
            args.subnet or local_subnet())
        out(f"Looking for Xiaomi devices on {base}.0/24 (a few seconds)...")
        try:
            devices = discover(base)
        except OSError as e:
            cli.die(f"network scan failed: {e}")
        out(f"{len(devices)} Xiaomi device(s) answered; testing your token on each...")
        for dev_ip, _did in devices:
            found = probe(dev_ip, token)
            if found:
                ip, info = dev_ip, found
                out(f"  {dev_ip}: {found.get('model')}  <- your token works here")
                break
            out(f"  {dev_ip}: not the kettle (token rejected)")
    if not ip:
        if scripted:
            cli.die("kettle not found; check it is online, or pass --ip")
        out("""
Could not find the kettle automatically. Its address is in your router's client list
(look for a device named "xiaomi", "kettle" or with a MAC starting with E4:FE:43), or in
the extractor's output. Same Wi-Fi as this computer is required.""")
        for _ in range(3):
            raw = ask("Kettle IP address (Enter to quit): ").strip()
            if not raw:
                cli.die("setup cancelled", 2)
            try:
                ip = str(ipaddress.ip_address(raw))
                break
            except ValueError:
                out("That is not an IPv4 address, like 192.168.1.36.")
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
    out(f"Saved to {config.CONFIG_PATH} (readable by you only).")
    out(f"\nKettle: {model}, firmware {info.get('fw_ver', '?')}, MAC {info.get('mac', '?')}, IP {ip}")
    out("Tip: give it a fixed address (DHCP reservation) in your router so the IP never changes.")
    out("If it ever moves, `kettle find` locates it again.")
    out(f"\n{RULE}\nAll set. Try:\n  kettle status\n  kettle boil\n  kettle shell\n{RULE}")
