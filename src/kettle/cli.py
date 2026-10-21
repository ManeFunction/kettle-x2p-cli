"""Command line interface: argument parsing, the commands and the interactive shell."""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import textwrap
import time

from . import config, version
from .miio import MiioClient, MiioError, MiioRpcError, discover, local_subnet

EXPECTED_MODEL = "xiaomi.kettle.v20"

# (siid, piid) from SPEC.md
STATUS, FAULT, TEMP, TARGET, AUTO_KEEP, KEEP_TEMP, ON = (2, 1), (2, 2), (2, 3), (2, 4), (2, 5), (2, 6), (2, 7)
KEEP_MIN, LIFTED, WARMING, TARGET_MODE, HEAT_MODE, BOIL_MODE = (3, 1), (3, 7), (3, 10), (3, 11), (3, 12), (3, 13)
STOP_ACTION = (3, 1)
STATUS_NAMES = {0: "idle", 1: "heating", 2: "boiling", 3: "cooling down", 4: "keep warm"}
TARGET_MODE_NAMES = {0: "heating", 1: "boiling", **{n: f"preset {n - 9}" for n in range(10, 16)}}


class KettleError(Exception):
    def __init__(self, msg: str, code: int = 1):
        super().__init__(msg)
        self.code = code


def die(msg: str, code: int = 1):
    raise KettleError(msg, code)


def connect(args, use_saved_token: bool = True, need_token: bool = True) -> tuple[MiioClient, dict]:
    cfg = config.load_config()
    shared = getattr(args, "_client", None)
    if shared is not None and use_saved_token:
        return shared, cfg
    ip = args.ip or cfg.get("ip") or die("no kettle configured yet: run `kettle setup`")
    token_hex = args.token or (cfg.get("token") if use_saved_token else None)
    token = bytes.fromhex(token_hex) if token_hex else None
    if token is not None and len(token) != 16:
        die("token must be 32 hex characters")
    if token is None and need_token:
        die("no token saved: run `kettle setup`")
    return MiioClient(ip, token, timeout=args.timeout, debug=args.debug), cfg


def read_props(c: MiioClient, props) -> dict:
    """Read properties; any non-zero code or missing value aborts (never act on ambiguous data)."""
    out = {}
    for item in c.get_properties(props):
        key = (item.get("siid"), item.get("piid"))
        if item.get("code") != 0 or "value" not in item:
            die(f"could not read property {key}: {item}")
        out[key] = item["value"]
    if len(out) != len(props):
        die(f"expected {len(props)} properties, got {len(out)}")
    return out


def get_info(c: MiioClient, cfg: dict, save: bool = True) -> dict:
    h = c.handshake()
    info = c.call("miIO.info")
    if save and isinstance(info, dict):
        cfg.update(ip=c.ip, token=c.token.hex(), did=h.did, model=info.get("model"))
        config.save_config(cfg)
    return info


def check_model(c: MiioClient, cfg: dict, args) -> None:
    if getattr(args, "_model_ok", False):
        return
    info = get_info(c, cfg)
    model = info.get("model")
    if model != EXPECTED_MODEL and not args.force_model:
        die(f"model is {model!r}, SPEC.md is for {EXPECTED_MODEL!r}; refusing to send commands "
            f"(--force-model to override)")
    if getattr(args, "_client", None) is not None:
        args._model_ok = True


# --- commands ---------------------------------------------------------

def cmd_hello(args):
    c, _ = connect(args, need_token=False)
    with c:
        h = c.handshake()
    print(f"device id : {h.did} ({h.did:#010x})")
    print(f"stamp     : {h.stamp}")
    print(f"checksum  : {h.checksum.hex()}")
    if h.token:
        print(f"TOKEN LEAKED in hello reply: {h.token.hex()}")
        print("  (keep it private; `kettle info` will save it to the config)")
    else:
        print("token not exposed in hello reply (zeros/ff): supply it with --token or run `kettle setup`")


def cmd_info(args):
    c, cfg = connect(args, need_token=False)
    with c:
        if c.token is None:
            c.handshake()
            if c.token is None:
                die("no token available; run `kettle setup`")
        info = get_info(c, cfg)
    shown = {k: ("<saved to config, hidden>" if k == "token" else v) for k, v in info.items()}
    print(json.dumps(shown, indent=2))
    print(f"\nmodel: {info.get('model')}"
          + ("" if info.get("model") == EXPECTED_MODEL else f"   <-- differs from {EXPECTED_MODEL}"))
    print(f"saved to {config.CONFIG_PATH}")


def cmd_status(args):
    c, cfg = connect(args)
    with c:
        v = read_props(c, [STATUS, FAULT, TEMP, TARGET, AUTO_KEEP, KEEP_TEMP, KEEP_MIN, LIFTED, WARMING, TARGET_MODE])
    print(f"status       : {STATUS_NAMES.get(v[STATUS], v[STATUS])} ({v[STATUS]})")
    print(f"fault        : {v[FAULT]}")
    print(f"temperature  : {v[TEMP]} C")
    print(f"target       : {v[TARGET]} C")
    print(f"keep warm    : {'on' if v[AUTO_KEEP] else 'off'} at {v[KEEP_TEMP]} C for {v[KEEP_MIN]} min")
    print(f"warming time : {v[WARMING]} min")
    print(f"target mode  : {TARGET_MODE_NAMES.get(v[TARGET_MODE], 'unknown')} ({v[TARGET_MODE]})")
    print(f"lifted       : {v[LIFTED]}")
    print("water level  : not exposed by this model (a low-water fault shows up in `fault`)")


def show_items(items) -> None:
    for s_, p_, val in items:
        print(f"  ({s_},{p_}) = {val!r}")


def confirm(args, items) -> None:
    print("About to send set_properties:")
    show_items(items)
    if args.yes:
        return
    if not sys.stdin.isatty():
        die("non-interactive: pass --yes to start heating")
    if input("Start heating? [y/N] ").strip().lower() != "y":
        die("aborted", 2)


TEMP_MIN, TEMP_MAX = 40, 99          # spec: (2,4) target-temperature
KEEP_MIN_LO, KEEP_MIN_HI = 60, 1440  # spec: (3,1) keep-warm-time, minutes


def heat_items(target, boil: bool, keep, keep_temp, keep_min) -> list:
    """keep is (temp, minutes) for --keep, or None to leave keep-warm off (the kettle's stored values are echoed)."""
    if keep:
        keep_temp, keep_min = keep
    mode, mode_prop = (1, BOIL_MODE) if boil else (0, HEAT_MODE)
    return [(*TARGET, target), (*AUTO_KEEP, keep is not None), (*KEEP_TEMP, keep_temp), (*KEEP_MIN, keep_min),
            (*TARGET_MODE, mode), (*mode_prop, f"{target},{int(keep is not None)},{keep_temp},{keep_min}")]


def check_temp(temp: int) -> int:
    if not TEMP_MIN <= temp <= TEMP_MAX:
        die(f"temperature must be {TEMP_MIN}-{TEMP_MAX} C (kettle limits), got {temp}")
    return temp


def check_hours(hours: float) -> int:
    """Keep-warm time in hours (fractions allowed) -> the kettle's minutes."""
    minutes = round(hours * 60)
    if not KEEP_MIN_LO <= minutes <= KEEP_MIN_HI:
        die(f"keep-warm time must be {KEEP_MIN_LO // 60}-{KEEP_MIN_HI // 60} hours (kettle limits), got {hours:g}")
    return minutes


def start_heating(args, build, label: str) -> None:
    """Shared flow for boil / warm: preflight reads, confirm, write, verify.

    build(keep_temp, keep_min) -> items. On --dry-run nothing is sent (no network at all)."""
    if args.dry_run:
        items = build("<current keep temp>", "<current keep min>")
        if args.set_on:
            items.append((*ON, True))
        print(f"dry-run, {label}: set_properties would be:")
        show_items(items)
        return
    c, cfg = connect(args)
    with c:
        check_model(c, cfg, args)
        v = read_props(c, [STATUS, FAULT, TEMP, LIFTED, KEEP_TEMP, KEEP_MIN])
        if v[FAULT] != 0:
            die(f"kettle reports fault {v[FAULT]} (possibly low water); not heating")
        if v[LIFTED]:
            die("kettle is lifted off its base; not heating")
        if v[STATUS] != 0:
            die(f"kettle is not idle ({STATUS_NAMES.get(v[STATUS], v[STATUS])}); run `cancel` first")
        keep_min = min(max(v[KEEP_MIN], KEEP_MIN_LO), KEEP_MIN_HI)
        if keep_min != v[KEEP_MIN]:
            print(f"note: keep-warm minutes {v[KEEP_MIN]} out of spec range, using {keep_min}")
        print(f"{label}: water at {v[TEMP]} C, idle, no fault.")
        items = build(v[KEEP_TEMP], keep_min)
        if args.set_on:
            items.append((*ON, True))
        confirm(args, items)
        results = c.set_properties(items)
        bad = [r for r in results if r.get("code") != 0]
        if bad:
            die(f"device rejected some writes: {bad}")
        print("accepted. waiting 3 s then reading status...")
        time.sleep(3)
        v = read_props(c, [STATUS, FAULT, TEMP])
    print(f"status: {STATUS_NAMES.get(v[STATUS], v[STATUS])}, {v[TEMP]} C, fault {v[FAULT]}")
    if v[STATUS] == 0:
        print("kettle is still idle: the batch alone did not start it. Re-run with --set-on "
              "(also writes on=true) once you are watching the kettle.")


def check_keep(keep, target: int):
    """--keep [[TEMP] TIME] -> (temp, minutes) or None. TIME is in hours. Missing TEMP is the heating target,
    missing TIME is 1 h."""
    if keep is None:
        return None
    if len(keep) > 2:
        die("--keep takes at most TEMP and TIME")
    temp = keep[0] if len(keep) == 2 else target  # a single value is TIME
    if temp != int(temp):
        die(f"keep-warm temperature must be a whole number, got {temp:g}")
    minutes = check_hours(keep[-1]) if keep else KEEP_MIN_LO
    return check_temp(int(temp)), minutes


def cmd_boil(args):
    keep = check_keep(args.keep, 99)
    label = "boil" + (f" and keep warm at {keep[0]} C for {keep[1] / 60:g} h" if keep else "")
    start_heating(args, lambda kt, km: heat_items(99, True, keep, kt, km), label)


def cmd_warm(args):
    t = check_temp(args.temp)
    keep = check_keep(args.keep, t)
    label = f"warm to {t} C" + (f" and keep warm at {keep[0]} C for {keep[1] / 60:g} h" if keep else ", then stop")
    start_heating(args, lambda kt, km: heat_items(t, False, keep, kt, km), label)


def cmd_cancel(args):
    if args.dry_run:
        print(f"dry-run, action would be: siid={STOP_ACTION[0]} aiid={STOP_ACTION[1]} in=[]")
        return
    c, cfg = connect(args)
    with c:
        check_model(c, cfg, args)
        res = c.action(*STOP_ACTION)
        print(f"action result: {res}")
        if isinstance(res, dict) and res.get("code") not in (0, None):
            die("device rejected stop-work")
        time.sleep(1)
        v = read_props(c, [STATUS, TEMP])
    print(f"status: {STATUS_NAMES.get(v[STATUS], v[STATUS])}, {v[TEMP]} C")


def local_tz_name() -> str:
    """Olson name of the Mac's timezone (e.g. Europe/Berlin), or '' if it cannot be determined."""
    try:
        target = os.path.realpath("/etc/localtime")
        return target.split("zoneinfo/", 1)[1]
    except (OSError, IndexError):
        return ""


def router_params(ssid: str, password: str, uid: int, app_params: bool, cc: str) -> dict:
    """Params for miIO.config_router. app_params mirrors what the Xiaomi Home app 11.7.704 sends
    in AP mode, minus bind_key (cloud-issued, deliberately omitted)."""
    params = {"ssid": ssid, "passwd": password, "uid": uid}
    if app_params:
        params.update(config_type="app",
                      gmt_offset=time.localtime().tm_gmtoff,
                      tz=local_tz_name(),
                      wifi_config={"cc": cc})
    return params


def cmd_provision(args):
    """Send home Wi-Fi credentials via miIO.config_router. Run while joined to the kettle's AP."""
    import getpass
    cfg = config.load_config()
    args.ip = args.ip or "10.10.1.1"
    if not args.ssid:
        die("--ssid is required (must be a 2.4 GHz network)")
    password = getpass.getpass(f"Password for {args.ssid!r} (hidden, not stored): ")
    if getpass.getpass("Type it again to confirm: ") != password:
        die("passwords differ; nothing was sent")
    if args.dry_run:
        shown = router_params(args.ssid, "<hidden>", args.uid, args.app_params, args.cc)
        print(f"dry-run: miIO.config_router {json.dumps(shown)}")
        return
    # In setup mode the token is re-generated each time, so never trust the saved one here:
    # take the fresh one the kettle leaks in its hello reply.
    c, cfg = connect(args, use_saved_token=False, need_token=False)
    with c:
        c.handshake()
        if c.token is None:
            die("kettle did not leak its token in the hello reply; supply --token")
        info = get_info(c, cfg)  # also saves token/did/model
        if info.get("model") != EXPECTED_MODEL and not args.force_model:
            die(f"unexpected model {info.get('model')!r}")
        params = router_params(args.ssid, password, args.uid, args.app_params, args.cc)
        try:
            res = c.call("miIO.config_router", params, retry=False)
        except MiioError as e:
            # The kettle drops its AP as soon as it accepts the config, so a lost reply is expected.
            print(f"no clean reply ({e}); this is normal if the kettle dropped its AP.")
            res = None
    print(f"device replied: {res}")
    print("Rejoin your normal Wi-Fi, give the kettle ~30 s, then run `kettle find`.")


def cmd_find(args):
    """Locate the saved device on the LAN by sweeping a /24 with hello packets."""
    cfg = config.load_config()
    did = cfg.get("did") or die("no saved device id; run `kettle setup` first")
    base = (args.subnet.rsplit(".", 1)[0] if args.subnet and args.subnet.count(".") == 3
            else args.subnet) or local_subnet()
    print(f"sweeping {base}.0/24 for device id {did} ...")
    found = next((ip for ip, d in discover(base) if d == did), None)
    if not found:
        die("device not found; is it online and on the same Wi-Fi/LAN as this computer?")
    cfg["ip"] = found
    config.save_config(cfg)
    print(f"found at {found}, saved to config. Consider a DHCP reservation for it.")


def cmd_setup(args):
    from .wizard import run_setup
    run_setup(args)


def cmd_shell(args):
    """Interactive session: one open socket, model checked once, same commands as the CLI."""
    import shlex
    try:
        import readline  # noqa: F401  (line editing/history where available)
    except ImportError:
        pass
    parser = build_parser()
    c, _cfg = connect(args)
    c.persistent = True
    args._client = c
    try:
        c.handshake()
        print(f"connected to {c.ip}. Type `help` for commands, `quit` to leave.")
    except MiioError as e:
        print(f"warning: handshake failed ({e}); commands will retry")
    try:
        while True:
            try:
                line = input("kettle> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not line:
                continue
            if line in ("quit", "exit", "q"):
                break
            if line in ("help", "?"):
                print("boil [-k [[TEMP] TIME]] | warm <40-99> [-k [[TEMP] TIME]] | cancel | stop | status | info")
                print("options go after the command: --yes skips the heating confirmation, --dry-run only prints the RPC")
                continue
            try:
                tokens = shlex.split(line)
                if tokens[0] in ("shell", "setup", "provision", "find", "hello"):
                    print(f"`{tokens[0]}` is not available inside the shell")
                    continue
                sub_args = parser.parse_args(tokens, namespace=copy.copy(args))
                run_command(sub_args)
            except SystemExit:
                pass  # argparse already printed its message
            except KettleError as e:
                print(f"error: {e}")
            except (MiioError, OSError, ValueError) as e:
                print(f"error: {e}")
    finally:
        c.persistent = False
        c.close()


COMMANDS = {"hello": cmd_hello, "info": cmd_info, "status": cmd_status, "boil": cmd_boil,
            "warm": cmd_warm, "cancel": cmd_cancel, "stop": cmd_cancel,
            "provision": cmd_provision, "find": cmd_find, "shell": cmd_shell, "setup": cmd_setup}


def run_command(args) -> None:
    COMMANDS[args.cmd](args)


KEEP_HELP = (f"then keep warm at TEMP C ({TEMP_MIN}-{TEMP_MAX}) for TIME hours ({KEEP_MIN_LO // 60}-{KEEP_MIN_HI // 60}, "
             f"e.g. 1.5); TEMP defaults to the heating target, TIME to {KEEP_MIN_LO // 60}. "
             f"Without it the kettle stops after heating")


DEFAULT_TIMEOUT = 3.0
# options that go after the command: name -> (option strings, usage example, add_argument kwargs)
COMMAND_OPTIONS = {
    "keep": (("-k", "--keep"), "boil --keep", dict(nargs="*", type=float, help=KEEP_HELP)),
    "yes": (("--yes",), "boil --yes", dict(action="store_true", help="skip heating confirmation")),
    "dry_run": (("--dry-run",), "warm 70 --dry-run",
                dict(action="store_true", help="print the RPC instead of sending")),
    "timeout": (("--timeout",), "status --timeout 5",
                dict(type=float, help=f"seconds to wait for a reply (default: {DEFAULT_TIMEOUT:g})")),
    "debug": (("--debug",), "status --debug", dict(action="store_true", help="print raw packets and RPC")),
    "set_on": (("--set-on",), "boil --set-on", dict(action="store_true", help="also write on=true (2,7)")),
}
# these may also be given to `kettle shell` and then apply to every command typed in it
SESSION_OPTIONS = ("yes", "dry_run", "timeout", "debug")


class HelpFormatter(argparse.HelpFormatter):
    def __init__(self, prog, indent_increment=2, max_help_position=28, width=None):
        # 28 so that `-k, --keep [[TEMP] TIME]` keeps its description on the same line
        super().__init__(prog, indent_increment, max_help_position, width)

    def _format_args(self, action, default_metavar):
        # argparse would print the optional pair behind nargs="*" as `[TEMP [TIME ...]]`
        return "[[TEMP] TIME]" if action.dest == "keep" else super()._format_args(action, default_metavar)

    def _format_action_invocation(self, action):
        # Python < 3.13 repeats the metavar after every option string (`-k [..], --keep [..]`)
        if action.dest == "keep" and action.option_strings:
            return f"{', '.join(action.option_strings)} {self._format_args(action, None)}"
        return super()._format_action_invocation(action)

    def _usage_part(self, action) -> str:
        flag = action.option_strings[-1]  # the long form
        part = flag if action.nargs == 0 else f"{flag} {self._format_args(action, action.dest.upper())}"
        return f"[{part}]"

    def _format_usage(self, usage, actions, groups, prefix):
        # Built by hand (argparse wraps these differently per Python version). Command options work behind
        # the command, so they are shown there, not before it.
        if usage is not None:
            return super()._format_usage(usage, actions, groups, prefix)
        optionals = [a for a in actions if a.option_strings and not getattr(a, "after_command", False)]
        tail = [a for a in actions if getattr(a, "after_command", False)]
        positionals = [a for a in actions if not a.option_strings]
        parts = [self._usage_part(a) for a in optionals]
        for a in positionals:
            command = isinstance(a, argparse._SubParsersAction)
            parts.append(a.metavar or a.dest if command else self._format_args(a, a.dest))
            if a is positionals[-1]:
                parts += [self._usage_part(t) for t in tail]
            if command:
                parts.append("...")
        if not positionals:
            parts += [self._usage_part(t) for t in tail]
        prefix = "usage: " if prefix is None else prefix
        indent = " " * (len(prefix) + len(self._prog) + 1)
        text = textwrap.fill(" ".join([self._prog, *(p.replace(" ", "\xa0") for p in parts)]),
                             width=self._width, initial_indent=prefix, subsequent_indent=indent,
                             break_long_words=False, break_on_hyphens=False)
        return text.replace("\xa0", " ") + "\n\n"


class Parser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("formatter_class", HelpFormatter)
        super().__init__(*args, **kwargs)


class AfterCommand(argparse.Action):
    """Top-level help entry for an option that really goes after the command."""
    def __init__(self, *args, example: str, **kwargs):
        super().__init__(*args, **kwargs)
        self.example = example

    def __call__(self, parser, namespace, values, option_string=None):
        parser.error(f"{option_string} goes after the command, e.g. `kettle {self.example}`")


def add_command_options(parser: argparse.ArgumentParser, *names: str) -> None:
    """Add options to a command's parser. Unset session options stay out of the namespace so that
    `kettle shell --yes` can pass its value on to the commands typed in the shell."""
    group = parser.add_argument_group("command options")
    for name in names:
        flags, _, kwargs = COMMAND_OPTIONS[name]
        if name in SESSION_OPTIONS:
            kwargs = {**kwargs, "default": argparse.SUPPRESS}
        group.add_argument(*flags, **kwargs).after_command = True


def build_parser() -> argparse.ArgumentParser:
    p = Parser(prog="kettle", description="Local control of the Xiaomi Smart Kettle 2 Pro.", add_help=False)
    p.set_defaults(timeout=DEFAULT_TIMEOUT, debug=False, dry_run=False, yes=False)
    group = p.add_argument_group("call options (go before the command)")
    group.add_argument("-h", "--help", action="help", help="show this help message and exit")
    group.add_argument("-v", "--version", action="version", version=f"kettle v{version}")
    group.add_argument("--ip", help="kettle IP address (default: the one saved by `kettle setup`)")
    group.add_argument("--token", help="32 hex chars")
    group.add_argument("--force-model", action="store_true",
                       help=f"send commands even if the device is not a {EXPECTED_MODEL} (property IDs may differ)")
    group = p.add_argument_group("command options (go after the command)")
    for name, (flags, example, kwargs) in COMMAND_OPTIONS.items():
        if name == "set_on":
            continue
        nargs = 0 if kwargs.get("action") == "store_true" else kwargs.get("nargs")
        group.add_argument(*flags, action=AfterCommand, example=example, nargs=nargs, default=argparse.SUPPRESS,
                           help=kwargs["help"]).after_command = True
    sub = p.add_subparsers(dest="cmd", metavar="command")
    hello = sub.add_parser("hello", help="raw handshake, shows whether the token is exposed")
    add_command_options(hello, "timeout", "debug")
    st = sub.add_parser("setup", help="guided first-time setup (token, IP, check)")
    st.add_argument("--subnet", help="e.g. 192.168.1 (default: this computer's /24)")
    info = sub.add_parser("info", help="miIO.info; saves ip/token/did/model to config")
    add_command_options(info, "timeout", "debug")
    boil = sub.add_parser("boil", help="heat to boiling")
    add_command_options(boil, "keep", "yes", "dry_run", "timeout", "debug", "set_on")
    w = sub.add_parser("warm", help="heat to TEMP C")
    w.add_argument("temp", type=int, help=f"{TEMP_MIN}-{TEMP_MAX} C")
    add_command_options(w, "keep", "yes", "dry_run", "timeout", "debug", "set_on")
    cancel = sub.add_parser("cancel", aliases=["stop"], help="stop heating / keep-warm")
    sub._choices_actions[-1].metavar = "cancel | stop"  # argparse would list it as `cancel (stop)`
    add_command_options(cancel, "dry_run", "timeout", "debug")
    status = sub.add_parser("status", help="temperature, mode, target, fault, keep-warm")
    add_command_options(status, "timeout", "debug")
    f = sub.add_parser("find", help="find the kettle's LAN IP by device id and save it")
    f.add_argument("--subnet", help="e.g. 192.168.1 (default: the Mac's current /24)")
    shell = sub.add_parser("shell", help="interactive session")
    add_command_options(shell, *SESSION_OPTIONS)
    pr = sub.add_parser("provision", help="advanced: send Wi-Fi to a kettle in setup mode (see README)")
    pr.add_argument("--ssid")
    pr.add_argument("--uid", type=int, default=0)
    pr.add_argument("--app-params", action="store_true",
                    help="also send config_type/gmt_offset/tz/wifi_config like the Xiaomi Home app")
    pr.add_argument("--cc", default="GB", help="country code for --app-params (app sends the account's)")
    add_command_options(pr, "dry_run", "timeout", "debug")
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd is None:
        parser.print_help()
        if not config.load_config().get("token"):
            print("\nFirst time here? Run `kettle setup`.")
        return
    try:
        run_command(args)
    except KettleError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(e.code)
    except (MiioError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
