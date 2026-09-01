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
import json
import os
import platform
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Optional

# Not 9222. That is the conventional Chrome debugging port, which is exactly why
# it is contested: Adobe's UXP tooling binds it for plugin debugging, and on a
# machine with Premiere or Photoshop installed it usually wins the race. Chrome
# then starts with no debugging port at all and says nothing about it.
DEFAULT_DEBUG_PORT = 9333

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


def probe_debug_port(port: int, timeout: float = 2.0) -> Optional[dict]:
    """Ask whatever is on the port to identify itself.

    Any DevTools-protocol endpoint answers /json/version with a `Browser`
    string. An open port is not enough to know Chrome is behind it — Adobe UXP
    speaks the same protocol on 9222 and will happily accept the connection,
    then fail with "unrecognized Chrome version" once the driver tries to use
    it. Returns None if nothing answers.
    """
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/json/version", timeout=timeout
        ) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        return None


def browser_on_port(port: int) -> tuple[Optional[str], bool]:
    """Return (browser identity, is it Chrome).

    The identity string looks like "Chrome/131.0.6778.86", or "Adobe UXP" when
    something else got to the port first.
    """
    info = probe_debug_port(port)
    if not info:
        return None, False
    browser = info.get("Browser") or info.get("browser") or ""
    is_chrome = bool(re.match(r"(?i)(chrome|chromium|headlesschrome)/", browser))
    return browser or "unidentified", is_chrome


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

    print("\nTranscript pipeline (§11.7)")
    from .media import DEFAULT_ASR_MODEL, have

    for binary, why in (("ffprobe", "reads a video's real duration"),
                        ("ffmpeg", "extracts the audio ASR reads")):
        if have(binary):
            _ok(f"{binary} found", why)
        else:
            _no(f"{binary} not found", f"{why} — install ffmpeg")
    try:
        import faster_whisper  # noqa: F401

        _ok("faster-whisper installed", f"model {DEFAULT_ASR_MODEL} downloads on first run")
    except ImportError:
        _no("faster-whisper installed", "run: pip install faster-whisper")

    print("\nChrome")
    chrome = find_chrome()
    if chrome:
        _ok("chrome found", chrome)
    else:
        _info("chrome not found in the usual places", "it may still be installed")

    if not port_is_open(port):
        _no(f"nothing listening on port {port}", "no browser to attach to yet")
        print(f"\n    python3 -m newscast.capture launch --port {port}\n")
        print("    …starts one. Then log into the wire and re-run this check.")
    else:
        browser, is_chrome = browser_on_port(port)
        if is_chrome:
            _ok(f"chrome is listening on port {port}", browser)
            _info("attach mode is available")
        elif browser:
            _no(f"port {port} is taken by something else", browser)
            print(
                f"\n    Something that is not Chrome answered on {port}."
                "\n    Adobe's UXP tooling does this on 9222 if Premiere or Photoshop"
                "\n    is installed, and Chrome then starts with no debugging port at"
                "\n    all without complaining. Pick a free port instead:\n"
            )
            print(f"{launch_hint(port + 1)}\n")
            print(f"    …then: python3 -m newscast.capture page --port {port + 1}")
        else:
            _no(
                f"port {port} is open but does not speak the DevTools protocol",
                "something unrelated is using it; try another port",
            )

    print("\nDone. Send this output back and it answers what this machine can do.\n")
    return 0


# --------------------------------------------------------------------------
# launch
# --------------------------------------------------------------------------


def profile_dir() -> str:
    return os.path.join(os.path.expanduser("~"), ".newscast-chrome")


def launch_chrome(
    port: int = DEFAULT_DEBUG_PORT, url: Optional[str] = None, wait: float = 20.0
) -> int:
    """Start Chrome with a debugging port and leave it running.

    Detached, so closing the terminal does not take the browser with it, and so
    the producer gets their prompt back instead of a blocked terminal.

    Uses a separate profile directory on purpose. Opening a debugging port on
    the everyday profile would expose every session logged in on it to anything
    that can reach the port.
    """
    # Check the port before looking for the binary. If Chrome is already
    # serving the port there is nothing to launch and the binary is irrelevant,
    # and if something else holds the port that is the more useful diagnosis.
    browser, is_chrome = browser_on_port(port)
    if is_chrome:
        print(f"Chrome is already on port {port} — nothing to do.")
        return 0
    if browser:
        raise SystemExit(
            f"Port {port} is taken by {browser}. Pick another with --port."
        )

    chrome = find_chrome()
    if not chrome:
        raise SystemExit(
            "Could not find Chrome in the usual places. Start it by hand:\n\n"
            f"{launch_hint(port)}"
        )

    argv = [
        chrome,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir()}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if url:
        argv.append(url)

    print(f"starting chrome on port {port}")
    print(f"profile   {profile_dir()}")
    subprocess.Popen(
        argv,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    deadline = time.time() + wait
    while time.time() < deadline:
        _, is_chrome = browser_on_port(port)
        if is_chrome:
            print(f"\nChrome is up on port {port}.")
            print(
                "\nThis is a separate profile, so log into the wire in it once."
                "\nThen capture the page:\n"
            )
            print(f"    python3 -m newscast.capture page --tab newsource --port {port}\n")
            return 0
        time.sleep(0.4)

    raise SystemExit(
        f"Chrome did not come up on port {port} within {wait:.0f}s.\n"
        "It may still be starting — re-run doctor in a moment."
    )


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
            f"Nothing is listening on port {port}. Start Chrome first:\n\n"
            f"    python3 -m newscast.capture launch --port {port}\n\n"
            "…then log into the wire in the window it opens, and run this again."
        )

    browser, is_chrome = browser_on_port(port)
    if not is_chrome:
        raise SystemExit(
            f"Port {port} is not Chrome — it answered as {browser or 'something unidentified'}.\n\n"
            "Adobe's UXP tooling binds 9222 for plugin debugging, and Chrome then\n"
            "starts without a debugging port and does not say so.\n\n"
            f"Start Chrome on a free port:\n\n{launch_hint(port + 1)}\n\n"
            f"…then re-run with --port {port + 1}."
        )

    options = webdriver.ChromeOptions()
    options.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")
    return webdriver.Chrome(options=options)


def select_tab(driver, wanted: Optional[str]) -> None:
    """Focus the tab whose title or URL contains `wanted`.

    Attaching to a browser with several tabs open lands on an arbitrary one, and
    silently capturing the wrong page is worse than failing.
    """
    if not wanted:
        return
    needle = wanted.casefold()
    for handle in driver.window_handles:
        driver.switch_to.window(handle)
        if needle in (driver.title or "").casefold() or needle in (
            driver.current_url or ""
        ).casefold():
            return
    titles = []
    for handle in driver.window_handles:
        driver.switch_to.window(handle)
        titles.append(f"  - {driver.title} — {driver.current_url}")
    raise SystemExit(
        f"No open tab matches {wanted!r}. Tabs currently open:\n" + "\n".join(titles)
    )


def capture_page(
    out_path: str,
    port: int = DEFAULT_DEBUG_PORT,
    scrub: bool = True,
    tab: Optional[str] = None,
) -> int:
    driver = attach(port)
    select_tab(driver, tab)
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
    p_page.add_argument(
        "--tab",
        help="capture the tab whose title or URL contains this, e.g. --tab newsource",
    )

    p_launch = sub.add_parser(
        "launch", help="start Chrome with a debugging port and leave it running"
    )
    p_launch.add_argument("--port", type=int, default=DEFAULT_DEBUG_PORT)
    p_launch.add_argument("--url", help="open this page on startup")

    p_scrub = sub.add_parser("scrub", help="redact a saved HTML file in place")
    p_scrub.add_argument("path")
    p_scrub.add_argument("--out")

    args = parser.parse_args(argv)

    if args.command == "doctor":
        return doctor(args.port)
    if args.command == "launch":
        return launch_chrome(args.port, args.url)
    if args.command == "page":
        return capture_page(
            args.out, args.port, scrub=not args.no_scrub, tab=args.tab
        )
    return scrub_file(args.path, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
