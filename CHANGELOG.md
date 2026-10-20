# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.2.0] - 2026-10-20
### Changed
- **Breaking:** `--timeout`, `--debug`, `--dry-run` and `--yes` now go after the command, like `--keep`
  (`kettle warm 70 --dry-run`, not `kettle --dry-run warm 70`). Before the command they are rejected with a hint.
  In `kettle shell` they can be given once for the whole session (`kettle shell --yes`) or per command.
- `--help` and the README list the options in two blocks: call options (before the command: `--ip`, `--token`,
  `--force-model`) and command options (after it: `--keep`, `--yes`, `--dry-run`, `--timeout`, `--debug`).
- The `usage:` line shows them behind the command too, and spells every option in its long form (`--help`, not `-h`).

## [1.1.0] - 2026-10-19
### Added
- `stop` as an alias of `cancel`.
- `-v` as a short form of `--version`.
- `--keep [[temp] hours]` (`-k`) for `boil` and `warm`: keep the water warm after heating. The time is in hours (1-24,
  fractions like `1.5` work). The temperature defaults to the heating target (99 °C for `boil`), the time to 1 hour;
  a single value is the time (`warm 70 -k 2`).
- `--ip`, `--timeout` and `--force-model` are now described in `--help`.

### Changed
- **Breaking:** `warm-to <temp>` and `warm-keep <temp> <minutes>` are replaced by a single `warm <temp>`. Without
  `--keep` the kettle stops after heating; `warm-keep 80 120` is now `warm 80 --keep 2` (the time is in hours).
- `kettle --help` output was updated.

## [1.0.1] - 2026-10-18
### Added
- A standalone Windows binary, `kettle.exe` (built with Nuitka, not code-signed), is attached to GitHub releases for
  Windows users without Python.

## [1.0.0] - 2026-10-16
### Added
- Initial release, available from [PyPI](https://pypi.org/project/kettle-x2p-cli/) (`pip install kettle-x2p-cli`),
  the [mane tap](https://github.com/ManeFunction/homebrew-tap) (`brew install kettle`) and GitHub releases.
  Local control of the Xiaomi Smart Kettle 2 Pro (EU, `xiaomi.kettle.v20`) over the LAN:
  `boil`, `warm-to <temp>`, `warm-keep <temp> <minutes>`, `cancel` and `status`, plus an interactive `shell`.
- `kettle setup`: guided first-time setup with on-screen instructions. It explains how to pair the kettle in the
  Xiaomi Home app, where to get the token extractor, asks for the token (hidden input), finds the kettle on the
  network by trying the token on each Xiaomi device, then verifies and saves it.
- `info`, `find` (re-locates the kettle after an IP change) and `hello` (raw handshake, for diagnostics).
- `provision` for an advanced, experimental Wi-Fi setup of a kettle in setup mode.
- Safety checks before heating: the kettle must be `xiaomi.kettle.v20`, idle, without a fault and on its base;
  the exact writes are printed and confirmed (`--yes` is required without a terminal). `--dry-run` prints the
  requests without sending anything.
- Config in `~/.config/kettle/config.json` (mode 600). The client re-handshakes and re-syncs the device
  timestamp on its own.
- No dependencies: AES-128-CBC is implemented in pure Python (checked against the FIPS-197 and NIST SP 800-38A
  test vectors).
