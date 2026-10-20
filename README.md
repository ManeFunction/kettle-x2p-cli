# kettle

Control your [Xiaomi Smart Kettle 2 Pro](https://www.mi.com/global/product/xiaomi-smart-kettle-2-pro/) from the
Terminal: boil, heat to a temperature, keep warm for up to 24 hours, check the state or stop it. Everything runs over
your own Wi-Fi, directly to the kettle - no Xiaomi Home app and no cloud connection when you use it.

```
$ kettle warm 80 --keep 2
warm to 80 C and keep warm at 80 C for 2 h: water at 41 C, idle, no fault.
About to send set_properties:
  (2,4) = 80
  ...
Start heating? [y/N] y
status: heating, 41 C, fault 0
```

Written for the EU model (BHR9107EU, `xiaomi.kettle.v20`, 1.7 L, 1800 W), tested on firmware `2.2.7_0016`.
It has no dependencies except Python itself. This is the standalone tool and a documented protocol reference ([SPEC.md](https://github.com/ManeFunction/kettle-x2p-cli/blob/main/SPEC.md))
made just for fun... or not. Setting a kettle right from the Terminal while working is pretty neat, actually :)

---

## Features

| Command | What it does |
|---|---|
| `kettle setup` | Guided first-time setup: asks for the token, finds the kettle, checks and saves it. |
| `kettle boil` | Heats to boiling (99 °C, the kettle's boil mode), then stops. |
| `kettle warm <40-99>` | Heats to that temperature in °C, then stops. |
| `--keep [[<40-99>] <1-24>]` (`-k`) | Option for `boil` and `warm`: after heating, keep the water warm at that temperature for that many hours (fractions like `1.5` work). Both parts are optional: the temperature defaults to the heating target (99 °C for `boil`), the time to 1 hour, and a single value is the time. |
| `kettle cancel` (or `stop`) | Stops heating / keep-warm. |
| `kettle status` | State, current temperature, target, fault, keep-warm settings. |
| `kettle shell` | Interactive session with the same commands. |
| `kettle info` | Model, firmware and MAC from the kettle. |
| `kettle find` | Finds the kettle on the network again if its IP changed. |

Options after the command: `--dry-run` (print the requests, send nothing), `--yes` (skip the heating confirmation),
`--debug` (raw packets), `--timeout` (seconds to wait for a reply). Options before it: `--ip`, `--token`,
`--force-model` (send commands even to a model other than `xiaomi.kettle.v20`; the property IDs may differ there, so only
use it if you know they match).

**Safety.** Heating commands refuse to start unless the kettle is a `xiaomi.kettle.v20`, idle, on its base and
reporting no fault, and a status read that fails or is unclear never starts anything. They print exactly what they
will send and ask `y/N` (without a terminal, `--yes` is required). This model has no water-level reading, so a
low-water condition only shows up as a fault code. Heat water remotely only when you know the kettle has water in it.

---

## Installation

**kettle** is available from a variety of sources.
`pip` or `brew` is recommended, because they have a convenient way to manage updates automatically.

1) **pip (Recommended for everyone with a Python environment)**
    - You can check if you have Python installed by running `python --version` in the Terminal or cmd.
    - For Mac and Linux users, there is a high chance that you already have Python installed on your system.
    - For Windows users, you can download Python from the [official website](https://www.python.org/downloads/).
      The tool is built and tested for macOS and Linux; it should work on Windows too, but that is untested.
    - After confirmation, install **kettle** through the [PyPI](https://pypi.org/project/kettle-x2p-cli) package
      manager, typing `pip install kettle-x2p-cli` in the Terminal. For Mac users, you may need to use `pip3`
      instead of `pip`. The package is called `kettle-x2p-cli`; the command it installs is `kettle`.
    - Verify the installation with `kettle --version`.
    - You are perfect, you can use the app with `kettle` from any folder in your system.
2) **brew (Recommended for Mac and Linux users)**
    - Type `brew tap manefunction/tap` in your Terminal to add my custom tap (app source) to your brew sources,
      if you haven't already.
    - Type `brew install kettle` to install the application itself.
    - Verify the installation with `kettle --version`.
    - You are perfect, you can use the app with `kettle` from any folder in your system.
3) **Python package (manual installation, for advanced users)**
    - Clone the repository or download the source code from GitHub.
    - Go to the folder with the code in your Terminal.
    - Run `pip install .` to install `kettle` to your system.
    - Run `kettle --version` to verify the install.
4) **Ready-to-use Windows binary (for Windows users without Python)**
    - Download `kettle.exe` from the [GitHub Releases](https://github.com/ManeFunction/kettle-x2p-cli/releases) page.
    - Since it isn't code-signed, Windows SmartScreen may warn about an unrecognized publisher the first time
      you run it — click "More info" → "Run anyway" to proceed.
    - Open Command Prompt or PowerShell, `cd` to the folder with `kettle.exe`, and run `.\kettle.exe --version`
      to verify it works.
    - You are perfect, you can use the app with `.\kettle.exe`. The binary is built automatically for each release;
      CI only checks that it starts and reports the right version, so the Windows build is less tested than macOS and Linux.

Updates arrive with `pip install --upgrade kettle-x2p-cli` or `brew upgrade`. Your saved kettle settings live outside the install
(`~/.config/kettle/`), so upgrading or reinstalling never loses them. (`pip` may ask you to use a virtual environment or `pipx` on newer
systems; `pipx install kettle-x2p-cli` is a good fit for a command line tool.)

---

## First-time setup

Run `kettle setup` and follow the instructions on the screen. It takes about five minutes the first time and is
never needed again unless you re-pair the kettle.

1. **Add the kettle to the Xiaomi Home app** (iOS / Android) so it joins your 2.4 GHz Wi-Fi.
2. **Get the kettle's token** with the free, open-source
   [Xiaomi Cloud Tokens Extractor](https://github.com/PiotrMachowski/Xiaomi-Cloud-Tokens-Extractor). The setup
   screen shows the exact commands for Windows, macOS and Linux. It asks for your Xiaomi login and lists your devices
   with their tokens; copy the 32-character token of *Xiaomi Smart Kettle 2 Pro* (`xiaomi.kettle.v20`).
3. **Paste the token** into `kettle setup` (the input is hidden). It scans your network, tries the token on every
   Xiaomi device it finds, and the one that answers is your kettle.
4. It checks the model and saves everything to `~/.config/kettle/config.json` (readable by you only).

Then try `kettle status`. Reserve the kettle's address in your router (DHCP reservation) so it never moves; if it
does, `kettle find` locates it again.

For scripts, skip the prompts: `kettle --token <token> --ip <ip> setup`. Note that a token typed on the command
line is visible in your shell history, so the interactive prompt is the safer way.

### Why the Xiaomi app and cloud are needed once

The kettle talks to the local network with a secret 16-byte token, and only Xiaomi's cloud keeps it for you.
On firmware `2.2.7` the kettle changes that token when it joins your Wi-Fi, so the token it shows while in
setup mode stops working afterwards. I tried the alternatives (including the app's own extra provisioning parameters,
`kettle provision --app-params`); none gave a usable token without the cloud. After the one-time extraction,
all control is local. If you re-pair or reset the kettle, the token changes and you run `kettle setup` again.

---

## Usage

```bash
kettle status                  # what is it doing?
kettle boil                    # asks for confirmation, then heats to boiling
kettle warm 70                 # 70 °C, then stop (green tea)
kettle warm 85 --keep 1.5      # 85 °C and keep it there for 1.5 hours
kettle warm 85 -k 60 2         # 85 °C, then keep it at 60 °C for 2 hours
kettle warm 60 --keep          # 60 °C and keep 60 °C for the default hour
kettle boil -k 60 2            # boil, then keep at 60 °C for 2 hours
kettle boil -k 3               # boil and keep 99 °C for 3 hours
kettle boil --keep             # boil and keep 99 °C for an hour
kettle stop                    # stop everything (same as cancel)
kettle warm 70 --dry-run       # show what would be sent
kettle shell                   # keep a session open
```

In `kettle shell` you type the same commands without the `kettle` prefix (`boil`, `warm 70`, `status`, `stop`, `quit`).
Keep-warm time is limited by the kettle to 1-24 hours, and the target temperature to 40-99 °C; anything
else is rejected before it is sent.

### Troubleshooting

- **"no reply from ..."**: the kettle is offline, the IP changed (`kettle find`), or the token is out of date
  (the kettle silently ignores requests it cannot decrypt). Run `kettle setup` again if you re-paired it.
- **Setup does not find the kettle**: your computer and the kettle must be on the same network (no guest network
  or VLAN between them). You can enter the IP by hand; it is in your router's client list.
- **"kettle reports fault ..."**: check the water level and that the kettle sits on its base. Fault codes are not
  documented by Xiaomi; `0` means none.

---

## How it works

The kettle speaks Xiaomi's *miio* protocol over UDP port 54321: a hello handshake that returns the device id and
a timestamp, then JSON-RPC calls encrypted with AES-128-CBC keyed from the token. Its functions are described by
a MIoT spec (service/property numbers); the ones used here are listed in [SPEC.md](https://github.com/ManeFunction/kettle-x2p-cli/blob/main/SPEC.md). The client is a few hundred
lines of standard-library Python, including its own AES, and handles re-handshakes and timestamp drift by itself.

---

## Development

```bash
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/python -m unittest discover -s tests -v
```

The tests run against a fake kettle on the loopback interface that speaks the real wire format; nothing touches a
real device. The release workflow checks that the tag matches `src/kettle/__init__.py`, builds the package and
publishes it to PyPI and creates the GitHub release; the Homebrew formula is bumped automatically.

---

## Credits

- [python-miio](https://github.com/rytilahti/python-miio) for documenting the miio protocol.
- [Xiaomi Cloud Tokens Extractor](https://github.com/PiotrMachowski/Xiaomi-Cloud-Tokens-Extractor) by Piotr Machowski.
- [miot-spec.org](https://home.miot-spec.com/) for the device specs, and username-ardrey for
  [Xiaomi Smart Kettle integration for Home Assistant](https://github.com/username-andrey/xiaomi-smart-kettle-ha),
  which shows how this model is started.

This is an unofficial project and is not affiliated with Xiaomi.


## Repository info

This repo follows the [Conventional Commits](https://www.conventionalcommits.org/) specification.

[![GitHub release (latest by date)](https://img.shields.io/github/v/release/ManeFunction/kettle-x2p-cli)](https://github.com/ManeFunction/kettle-x2p-cli/releases/latest)
[![GitHub All Releases](https://img.shields.io/github/downloads/ManeFunction/kettle-x2p-cli/total)](https://github.com/ManeFunction/kettle-x2p-cli/releases)
[![PyPI version](https://img.shields.io/pypi/v/kettle-x2p-cli)](https://pypi.org/project/kettle-x2p-cli/)
[![PyPI downloads](https://img.shields.io/pypi/dm/kettle-x2p-cli)](https://pypi.org/project/kettle-x2p-cli/)
[![GitHub Sponsors](https://img.shields.io/github/sponsors/ManeFunction?label=Sponsor&logo=GitHubSponsors&style=flat)](https://github.com/sponsors/ManeFunction)
