"""Reading a .env file, with no dependency.

The work machine keeps its credentials in a .env beside where the tools are
run (`~/Desktop/monkey_king/.env`). Nothing here ever prints, logs or writes a
value — `describe()` reports which keys were found, never what they hold.
"""

from __future__ import annotations

import os
from typing import Iterable, Optional

DEFAULT_NAMES = (".env", "env", ".env.local")


def candidate_paths(explicit: Optional[str] = None, start: Optional[str] = None) -> list[str]:
    """Where to look for a .env, nearest first.

    The code and the credentials do not live in the same directory. The
    repository is unzipped *inside* the folder holding the .env:

        monkey_king/
            .env
            initial-testing-<branch>/
                newscast/

    and `python3 -m newscast...` only works from inside the unzipped folder,
    which is one level below the .env. So the search walks up from the working
    directory to the home directory, which finds it wherever in that nesting
    the command is run from, whatever the unzipped folder is called.
    """
    if explicit:
        return [explicit]

    paths: list[str] = []
    here = os.path.abspath(start or os.getcwd())
    home = os.path.abspath(os.path.expanduser("~"))

    walked = here
    while True:
        paths.extend(os.path.join(walked, name) for name in DEFAULT_NAMES)
        parent = os.path.dirname(walked)
        if parent == walked or walked == home:
            break
        walked = parent

    # Then the conventional spot, in case the command is run from elsewhere.
    for root in (os.path.join(home, "Desktop", "monkey_king"), os.path.join(home, "monkey_king"), home):
        paths.extend(os.path.join(root, name) for name in DEFAULT_NAMES)

    seen: set[str] = set()
    return [p for p in paths if not (p in seen or seen.add(p))]


def parse_env(text: str) -> dict[str, str]:
    """Parse .env text.

    Handles `KEY=value`, `export KEY=value`, quoted values, blank lines and
    `#` comments. Deliberately small: anything cleverer is a dependency.
    """
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def load_env(explicit: Optional[str] = None) -> tuple[dict[str, str], Optional[str]]:
    """Return (values, path_used). Process environment wins over the file."""
    for path in candidate_paths(explicit):
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as handle:
            values = parse_env(handle.read())
        for key in list(values):
            if os.environ.get(key):
                values[key] = os.environ[key]
        return values, path
    return {k: v for k, v in os.environ.items()}, None


def describe(values: dict[str, str], keys: Iterable[str]) -> str:
    """Report which keys are present. Never reports a value."""
    lines = []
    for key in keys:
        value = values.get(key)
        if value:
            lines.append(f"  [ ok ] {key} — set ({len(value)} characters)")
        else:
            lines.append(f"  [FAIL] {key} — missing")
    return "\n".join(lines)


def require(values: dict[str, str], *keys: str) -> list[str]:
    return [key for key in keys if not values.get(key)]
