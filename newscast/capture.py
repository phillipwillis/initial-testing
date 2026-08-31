"""Environment check and page capture.

Two jobs, both meant to be run on the work machine (CLAUDE.md §14):

    python3 -m newscast.capture doctor
    python3 -m newscast.capture page --out cnn-landing.html

`doctor` reports what this machine can actually do — Python version, whether
Selenium imports, whether Chrome is reachable on a debugging port — so "I'm not
sure where the line is" becomes a list of facts.

`page` attaches to a Chrome you have already logged into and saves the rendered
DOM. That is the piece the parsers need: the wire sites are React apps, so
Chrome's own "Save Page As" writes an empty `<div id="root">` and nothing else.
Only the rendered DOM is useful, and only a browser can produce it.

Nothing here logs in, and nothing here takes a password. It attaches to a
browser a human has already authenticated, which is the §14 preference: the
credentials never leave the machine.
"""

from __future__ import annotations

import argparse
import os
import platform
import re
import socket
import sys
from typing import Optional

DEFAULT_DEBUG_PORT = 9222

CHROME_PATHS = {
    "Darwin": [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ],
    "Windows": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ],
    "Linux": ["/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser"],
}

LAUNCH_HINT = {
    "Darwin": (
        '"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \\\n'
        "    --remote-debugging-port={port} \\\n"
        '    --user-data-dir="$HOME/.newscast-chrome"'
    ),
    "Windows": (
        '"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" '
        "--remote-debugging-port={port} --user-data-dir=%USERPROFILE%\\.newscast-chrome"
    ),
    "Linux": (
        "google-chrome --remote-debugging-port={port} "
        "--user-data-dir=$HOME/.newscast-chrome"
    ),
}


# --------------------------------------------------------------------------
# doctor
# --------------------------------------------------------------------------


def _ok(label: str, detail: str = "") -> None:
    print(f"  [ ok ] {label}" + (f" — {detail}" if detail else ""))


def _no(label: str, detail: str = "") -> None:
    print(f"  [FAIL] {label}" + (f" — {detail}" if detail else ""))


def _info(label: str, detail: str = "") -> None:
    print(f"  [ -- ] {label}" + (f" — {detail}" if detail else ""))


def port_is_open(port: int, host: str = "127.0.0.1", timeout: float = 1.0) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((host, port)) == 0


def find_chrome() -> Optional[str]:
    for path in CHROME_PATHS.get(platform.system(), []):
        if os.path.exists(path):
            return path
    return None


def launch_hint(port: int) -> str:
    template = LAUNCH_HINT.get(platform.system(), LAUNCH_HINT["Linux"])
    return template.format(port=port)


def doctor(port: int = DEFAULT_DEBUG_PORT) -> int:
    print(f"\nnewscast doctor — {platform.system()} {platform.release()}\n")

    print("Python")
    version = sys.version_info
    if version >= (3, 10):
        _ok(f"python {version.major}.{version.minor}.{version.micro}", sys.executable)
    else:
        _no(
            f"python {version.major}.{version.minor}",
            "this project uses 3.10+ syntax",
        )

    print("\nProject")
    try:
        import newscast  # noqa: F401

        _ok("newscast package imports")
    except Exception as exc:  # pragma: no cover - only fires on a broken checkout
        _no("newscast package imports", str(exc))

    print("\nSelenium")
    try:
        import selenium

        _ok("selenium installed", f"version {selenium.__version__}")
    except ImportError:
        _no("selenium installed", "run: pip install selenium")

    print("\nChrome")
    chrome = find_chrome()
    if chrome:
        _ok("chrome found", chrome)
    else:
        _info("chrome not found in the usual places", "it may still be installed")

    if port_is_open(port):
        _ok(f"chrome is listening on port {port}", "attach mode is available")
    else:
        _no(f"nothing listening on port {port}", "start Chrome with a debugging port:")
        print(f"\n{launch_hint(port)}\n")
        print("    Then log into the wire as normal and re-run this check.")

    print("\nDone. Send this output back and it answers what this machine can do.\n")
    return 0


# --------------------------------------------------------------------------
# capture
# --------------------------------------------------------------------------


def attach(port: int = DEFAULT_DEBUG_PORT):
    """Attach to a running Chrome. Never launches one, never logs in."""
    try:
        from selenium import webdriver
    except ImportError:
        raise SystemExit("selenium is not installed. Run: pip install selenium")

    if not port_is_open(port):
        raise SystemExit(
            f"Nothing is listening on port {port}.\n\n"
            f"{launch_hint(port)}\n\n"
            "Then log in as normal and run this again."
        )

    options = webdriver.ChromeOptions()
    options.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")
    return webdriver.Chrome(options=options)


def capture_page(out_path: str, port: int = DEFAULT_DEBUG_PORT, scrub: bool = True) -> int:
    driver = attach(port)
    url, title = driver.current_url, driver.title
    html = driver.page_source

    print(f"captured  {title}")
    print(f"from      {url}")
    print(f"size      {len(html):,} characters")

    if scrub:
        html, hits = scrub_html(html)
        if hits:
            print("\nredacted before saving:")
            for kind, count in sorted(hits.items()):
                print(f"  {count:>3} × {kind}")

    with open(out_path, "w", encoding="utf-8") as handle:
        handle.write(html)

    print(f"\nsaved to  {out_path}")
    print(
        "\nOpen it and read it before sending it anywhere. Scrubbing is best effort,\n"
        "and only you can see what is actually in there."
    )
    return 0


# --------------------------------------------------------------------------
# scrub
# --------------------------------------------------------------------------

SCRUB_PATTERNS = (
    ("email address", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")),
    ("bearer token", re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/-]{20,}={0,2}")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("api key field", re.compile(r'(?i)("(?:api[_-]?key|token|secret|password)"\s*:\s*")[^"]+')),
    ("long hex id", re.compile(r"\b[0-9a-f]{32,}\b")),
)


def scrub_html(html: str) -> tuple[str, dict[str, int]]:
    """Best-effort redaction of things that should not travel.

    Deliberately conservative about what it claims: it removes the patterns it
    knows, and it cannot know everything. A human reads the file before it goes
    anywhere.
    """
    hits: dict[str, int] = {}
    for label, pattern in SCRUB_PATTERNS:
        if label == "api key field":
            html, count = pattern.subn(r"\1REDACTED", html)
        elif label == "bearer token":
            html, count = pattern.subn(r"\1REDACTED", html)
        else:
            html, count = pattern.subn("REDACTED", html)
        if count:
            hits[label] = count
    return html, hits


def scrub_file(path: str, out_path: Optional[str] = None) -> int:
    with open(path, encoding="utf-8") as handle:
        html = handle.read()
    html, hits = scrub_html(html)
    target = out_path or path
    with open(target, "w", encoding="utf-8") as handle:
        handle.write(html)
    if hits:
        for kind, count in sorted(hits.items()):
            print(f"  {count:>3} × {kind}")
    else:
        print("  nothing matched the known patterns")
    print(f"\nwrote {target}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="newscast.capture", description=__doc__.splitlines()[0]
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_doctor = sub.add_parser("doctor", help="report what this machine can do")
    p_doctor.add_argument("--port", type=int, default=DEFAULT_DEBUG_PORT)

    p_page = sub.add_parser("page", help="save the rendered DOM of the current tab")
    p_page.add_argument("--out", default="captured-page.html")
    p_page.add_argument("--port", type=int, default=DEFAULT_DEBUG_PORT)
    p_page.add_argument(
        "--no-scrub", action="store_true", help="save without redacting (not advised)"
    )

    p_scrub = sub.add_parser("scrub", help="redact a saved HTML file in place")
    p_scrub.add_argument("path")
    p_scrub.add_argument("--out")

    args = parser.parse_args(argv)

    if args.command == "doctor":
        return doctor(args.port)
    if args.command == "page":
        return capture_page(args.out, args.port, scrub=not args.no_scrub)
    return scrub_file(args.path, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
