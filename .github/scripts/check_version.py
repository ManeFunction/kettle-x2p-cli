#!/usr/bin/env python3
"""
Fail unless the release tag matches the version in src/kettle/__init__.py.

The tag comes from the GITHUB_REF_NAME environment variable (e.g. "v1.0.0");
a leading "v" is ignored. The package takes its version from kettle.version
(see pyproject.toml), so that is the single source compared here.
"""

import os
import re
import sys


def main() -> int:
    tag = os.environ.get("GITHUB_REF_NAME", "")
    with open("src/kettle/__init__.py", encoding="utf-8") as f:
        match = re.search(r'^version\s*=\s*"([^"]+)"', f.read(), re.MULTILINE)
    if match is None:
        print("::error::Could not find a version = \"...\" line in src/kettle/__init__.py.")
        return 1
    version = match.group(1)

    if tag.removeprefix("v") != version:
        print(
            f"::error::Tag {tag!r} does not match src/kettle/__init__.py version {version!r}. "
            "Bump the version (or retag) before releasing."
        )
        return 1
    print(f"Tag {tag} matches src/kettle/__init__.py version {version}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
