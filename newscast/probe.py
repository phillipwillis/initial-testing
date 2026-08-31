"""Answer the open questions about CNN Newsource, on the machine that can see it.

    cd ~/Desktop/monkey_king
    python3 -m newscast.probe

Reads CNN_USER and CNN_PASS from a .env in the working directory, logs in, and
runs a series of read-only investigations. Writes evidence to ./probe-output/
and prints a summary.

What it is trying to settle (docs/wires/cnn-newsource.md, "Still unknown"):

  api        does the front end call a JSON API, and at what URLs
  scroll     how rows accumulate, and how far back a scroll session reaches
  expand     what an expanded story holds — Story Number, TRT, related stories
  duration   what the listing's duration actually corresponds to (§11.23)
  download   how video and script get out, from the markup alone

**Nothing here clicks download, publishes, or changes anything.** It navigates,
scrolls, expands rows, and reads. Every artefact is scrubbed before it is
written, but read them before sending them on.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Callable, Optional

from newscast.capture import DEFAULT_DEBUG_PORT, attach, scrub_html
from newscast.env import describe, load_env, require
from newscast.wires.cnn import LANDING_URL, parse_expanded_story, parse_listing
from newscast.wires.cnn_script import parse_wire_script

CNN_HOME = "https://newsource.ns.cnn.com/"
REQUIRED_KEYS = ("CNN_USER", "CNN_PASS")


def log(step: str, message: str = "", **extra) -> None:
    tail = ("  " + ", ".join(f"{k}={v!r}" for k, v in extra.items())) if extra else ""
    print(f"[{step:<9}] {message}{tail}", flush=True)


# --------------------------------------------------------------------------
# login
# --------------------------------------------------------------------------


def looks_signed_in(driver) -> bool:
    return "/landing" in (driver.current_url or "") or bool(
        driver.execute_script(
            "return !!document.querySelector('.storyLineItemWrapperBox');"
        )
    )


def login(driver, username: str, password: str, timeout: float = 45.0) -> bool:
    """Log into Newsource. The password is never logged or echoed."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    if looks_signed_in(driver):
        log("login", "already signed in")
        return True

    log("login", "opening", url=CNN_HOME)
    driver.get(CNN_HOME)
    wait = WebDriverWait(driver, timeout)

    try:
        user_field = wait.until(EC.element_to_be_clickable((By.ID, "username")))
        pass_field = wait.until(EC.element_to_be_clickable((By.ID, "password")))
    except Exception:
        if looks_signed_in(driver):
            log("login", "already signed in")
            return True
        log("login", "could not find the login form")
        return False

    user_field.clear()
    user_field.send_keys(username)
    pass_field.clear()
    pass_field.send_keys(password)
    pass_field.send_keys(Keys.RETURN)
    log("login", "submitted, waiting for the landing page")

    deadline = time.time() + timeout
    while time.time() < deadline:
        if looks_signed_in(driver):
            log("login", "signed in")
            return True
        time.sleep(0.5)

    log("login", "did not reach the landing page — MFA or a changed form?")
    return False


# --------------------------------------------------------------------------
# probes
# --------------------------------------------------------------------------


def probe_api(driver, out: str, **options) -> dict[str, Any]:
    """Which URLs the front end fetches.

    Read from the browser's own Performance timeline rather than a proxy, so
    there is nothing to install and nothing to intercept.
    """
    entries = driver.execute_script(
        """
        return performance.getEntriesByType('resource')
          .filter(e => e.initiatorType === 'xmlhttprequest' || e.initiatorType === 'fetch')
          .map(e => ({url: e.name, kind: e.initiatorType, ms: Math.round(e.duration)}));
        """
    ) or []

    hosts: dict[str, int] = {}
    for entry in entries:
        url = entry.get("url", "")
        host = url.split("/")[2] if "://" in url else ""
        hosts[host] = hosts.get(host, 0) + 1

    # Strip query strings: they carry session and search state.
    paths = sorted({e["url"].split("?")[0] for e in entries})
    _write(out, "api-calls.json", json.dumps({"hosts": hosts, "paths": paths}, indent=2))
    return {"xhr_count": len(entries), "hosts": hosts, "distinct_paths": len(paths)}


def probe_scroll(driver, out: str, scroll_passes: int = 12, **options) -> dict[str, Any]:
    """How rows accumulate, and how far back a scroll session reaches.

    §6 wants a day's stories. There is no date filter, so the question is how
    much scrolling a day costs.
    """
    counts: list[int] = []
    for index in range(scroll_passes):
        html = driver.page_source
        counts.append(len(parse_listing(html)))
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1.2)
        if index and counts[-1] == counts[-2]:
            time.sleep(1.5)  # one more beat before believing it has stopped

    stubs = parse_listing(driver.page_source)
    stamped = [s for s in stubs if s.timestamp]
    oldest = min((s.timestamp for s in stamped), default=None)
    newest = max((s.timestamp for s in stamped), default=None)

    return {
        "rows_after_each_scroll": counts,
        "rows_final": len(stubs),
        "newest": newest.isoformat() if newest else None,
        "oldest": oldest.isoformat() if oldest else None,
        "span_minutes": round((newest - oldest).total_seconds() / 60) if oldest and newest else None,
        "footage_types": sorted({s.footage_type for s in stubs if s.footage_type}),
        "sources": sorted({s.source for s in stubs})[:25],
    }


def _expand_first(driver, want_video: bool) -> Optional[int]:
    """Expand the first row, optionally the first that carries video."""
    return driver.execute_script(
        """
        const wantVideo = arguments[0];
        const rows = Array.from(document.querySelectorAll('.storyLineItemWrapperBox'));
        for (let i = 0; i < rows.length; i++) {
          const row = rows[i];
          const hasVideo = !!row.querySelector('[aria-label="Video"]');
          if (wantVideo && !hasVideo) continue;
          const toggle = row.querySelector('[data-testid="KeyboardArrowDownIcon"]');
          const button = toggle ? toggle.closest('button') : null;
          if (button) { button.click(); return i; }
        }
        return null;
        """,
        want_video,
    )


def probe_expand(driver, out: str, **options) -> dict[str, Any]:
    """What an expanded story holds: Story Number, TRT, related stories."""
    index = _expand_first(driver, want_video=False)
    if index is None:
        return {"error": "no expandable row found"}
    time.sleep(2.5)

    html = driver.page_source
    _write(out, "expanded-story.html", scrub_html(html)[0])

    text = parse_expanded_story(html)
    script = parse_wire_script(text) if text else None

    labels = driver.execute_script(
        """
        return Array.from(document.querySelectorAll('td, th, dt, .MuiTypography-subBody'))
          .map(e => (e.innerText || '').trim())
          .filter(t => t && t.length < 40 && t.endsWith(':'))
          .slice(0, 40);
        """
    ) or []

    related = driver.execute_script(
        """
        const hits = [];
        for (const e of document.querySelectorAll('*')) {
          const t = (e.getAttribute('aria-label') || '') + ' ' + (e.className || '');
          if (/related|similar|more from|see also/i.test(String(t))) {
            hits.push(String(t).slice(0, 120));
          }
        }
        return hits.slice(0, 20);
        """
    ) or []

    return {
        "expanded_row_index": index,
        "detail_labels": labels,
        "related_hits": related,
        "script_chars": len(text),
        "script_is_package": bool(script and script.is_package),
        "script_supers": len(script.supers) if script else 0,
        "has_trt_label": any("trt" in l.lower() for l in labels),
        "has_story_number_label": any("story number" in l.lower() for l in labels),
    }


def probe_duration(driver, out: str, **options) -> dict[str, Any]:
    """What the listing's duration actually corresponds to.

    Phil: the script may run 20 seconds while the printed duration counts the
    b-roll in the file, and packages are worst. So compare three numbers on one
    story — what the listing prints, what the media element reports, and what
    the script reads at — and see which agree.
    """
    index = _expand_first(driver, want_video=True)
    if index is None:
        return {"error": "no video row found to expand"}
    time.sleep(3.5)

    stubs = parse_listing(driver.page_source)
    stub = stubs[index] if index < len(stubs) else None

    media = driver.execute_script(
        """
        return Array.from(document.querySelectorAll('video, audio')).map(v => ({
          duration: (isFinite(v.duration) ? v.duration : null),
          readyState: v.readyState,
          src: (v.currentSrc || v.src || '').split('?')[0]
        }));
        """
    ) or []

    text = parse_expanded_story(driver.page_source)
    script = parse_wire_script(text) if text else None

    from newscast.readtime import estimate_read_time

    read_seconds = None
    if script:
        spoken = "\n".join(
            part for part in (script.lead_in, script.body, script.tag) if part
        )
        read_seconds = estimate_read_time(spoken)

    return {
        "story_number": stub.story_number if stub else None,
        "footage_type": stub.footage_type if stub else None,
        "listing_duration_seconds": stub.wire_duration_seconds if stub else None,
        "media_elements": media,
        "estimated_read_seconds": read_seconds,
        "trt_in_script": script.trt if script else None,
    }


def probe_download(driver, out: str, **options) -> dict[str, Any]:
    """How material gets out — from the markup only.

    Deliberately does not click anything: a download on a licensed account has
    consequences this script has no business causing.
    """
    controls = driver.execute_script(
        """
        const out = [];
        for (const e of document.querySelectorAll('button, a, [role="menuitem"]')) {
          const label = (e.getAttribute('aria-label') || e.getAttribute('title') || e.innerText || '').trim();
          if (!label || label.length > 60) continue;
          if (!/download|export|copy|send|save|ftp|transfer/i.test(label)) continue;
          out.push({
            label: label,
            tag: e.tagName.toLowerCase(),
            href: (e.getAttribute('href') || '').split('?')[0]
          });
        }
        return out.slice(0, 40);
        """
    ) or []
    return {"controls": controls}


# --------------------------------------------------------------------------
# runner
# --------------------------------------------------------------------------


def _write(out: str, name: str, content: str) -> str:
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)
    return path


PROBES: tuple[tuple[str, str, Callable], ...] = (
    ("api", "does the front end call a JSON API", probe_api),
    ("scroll", "how rows accumulate and how far back they reach", probe_scroll),
    ("expand", "what an expanded story holds", probe_expand),
    ("duration", "what the printed duration corresponds to", probe_duration),
    ("download", "how material gets out", probe_download),
)


def run(
    driver, out: str, only: Optional[list[str]] = None, **options
) -> dict[str, Any]:
    findings: dict[str, Any] = {}
    for name, question, probe in PROBES:
        if only and name not in only:
            continue
        log("probe", f"{name}: {question}")
        try:
            findings[name] = probe(driver, out, **options)
            log("probe", f"{name}: done")
        except Exception as exc:  # one probe failing must not lose the others
            findings[name] = {"error": f"{type(exc).__name__}: {exc}"}
            log("probe", f"{name}: FAILED — {type(exc).__name__}: {exc}")
    return findings


def write_report(findings: dict[str, Any], out: str) -> str:
    lines = ["# CNN Newsource probe", ""]
    for name, question, _ in PROBES:
        if name not in findings:
            continue
        lines += [f"## {name} — {question}", "", "```json",
                  json.dumps(findings[name], indent=2, default=str), "```", ""]
    return _write(out, "report.md", "\n".join(lines))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="newscast.probe", description=__doc__.splitlines()[0])
    parser.add_argument("--env-file", help="path to the .env (default: ./.env)")
    parser.add_argument("--port", type=int, default=DEFAULT_DEBUG_PORT)
    parser.add_argument("--out", default="probe-output")
    parser.add_argument("--only", nargs="+", metavar="NAME",
                        help=f"run only these: {', '.join(n for n, _, _ in PROBES)}")
    parser.add_argument("--scroll-passes", type=int, default=12)
    args = parser.parse_args(argv)

    values, env_path = load_env(args.env_file)
    log("env", f"read {env_path}" if env_path else "no .env found; using the environment")
    print(describe(values, REQUIRED_KEYS))
    missing = require(values, *REQUIRED_KEYS)
    if missing:
        raise SystemExit(
            f"\nMissing {', '.join(missing)}. Put them in a .env in this directory:\n\n"
            "    CNN_USER=...\n    CNN_PASS=...\n"
        )

    driver = attach(args.port)

    if not login(driver, values["CNN_USER"], values["CNN_PASS"]):
        raise SystemExit(
            "Could not sign in. If Newsource asks for a second factor, sign in\n"
            "by hand in the window that is already open, then run this again."
        )

    if "/landing" not in (driver.current_url or ""):
        driver.get(LANDING_URL)
        time.sleep(3)

    # The browser is the producer's and stays open; this attaches, it does not own it.
    findings = run(driver, args.out, args.only, scroll_passes=args.scroll_passes)

    path = write_report(findings, args.out)
    print(f"\nwrote {path}")
    print(f"      {os.path.abspath(args.out)}/")
    print("\nRead the output before sending it on — it is scrubbed, best effort.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
