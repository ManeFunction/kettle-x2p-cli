# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
