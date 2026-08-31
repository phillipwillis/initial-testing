"""Answer the open questions about CNN Newsource, on the machine that can see it.

    cd ~/Desktop/monkey_king/initial-testing-<branch>
    python3 -m newscast.probe

Reads CNN_USER and CNN_PASS from the nearest .env — found by walking up from the
working directory, because the repo is unzipped inside the folder that holds the
credentials — logs in, and runs a series of read-only investigations. Evidence is
written beside the .env rather than into the unzipped folder, which gets replaced
on every download.

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
from newscast.wires.cnn import (
    LANDING_URL,
    parse_expanded_story,
    parse_listing,
    parse_story_details,
)
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

    The timeline belongs to the current document and is cleared by navigation,
    so this reloads the landing page itself and waits for the list to render
    before collecting. Reading it straight after a login navigation catches the
    login call and almost nothing else.
    """
    driver.execute_script(
        "try { performance.setResourceTimingBufferSize(1000); } catch (e) {}"
    )
    driver.get(LANDING_URL)
    rows = wait_for_rows(driver)
    time.sleep(3)

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

    # Query strings carry session and search state, so only the shapes are kept.
    params = driver.execute_script(
        """
        const keys = new Set();
        for (const e of performance.getEntriesByType('resource')) {
          if (e.initiatorType !== 'xmlhttprequest' && e.initiatorType !== 'fetch') continue;
          try { for (const k of new URL(e.name).searchParams.keys()) keys.add(k); } catch (err) {}
        }
        return Array.from(keys).sort();
        """
    ) or []

    _write(
        out,
        "api-calls.json",
        json.dumps({"hosts": hosts, "paths": paths, "query_keys": params}, indent=2),
    )
    return {
        "rows_rendered": rows,
        "xhr_count": len(entries),
        "hosts": hosts,
        "distinct_paths": len(paths),
        "query_keys": params,
        "content_api_paths": [p for p in paths if "content" in p or "stories" in p or "search" in p],
    }


def probe_scroll(driver, out: str, scroll_passes: int = 12, **options) -> dict[str, Any]:
    """How rows accumulate, and how far back a scroll session reaches.

    §6 wants a day's stories. There is no date filter, so the question is how
    much scrolling a day costs.
    """
    if not wait_for_rows(driver):
        return {"error": "the list never rendered"}

    # The list scrolls inside its own container, not the window. Scrolling the
    # window does nothing at all, which looks exactly like a list that has
    # stopped loading.
    # Pick the scrollable ancestor that actually contains the story rows. The
    # page has several scrollable panes — the live-channel rail is one — and a
    # 322px-tall one was chosen last run, which moved but was not the list.
    scroller = driver.execute_script(
        """
        const rows = Array.from(document.querySelectorAll('.storyLineItemWrapperBox'));
        if (!rows.length) return null;
        const scored = new Map();
        for (const row of rows) {
          let node = row.parentElement;
          while (node && node !== document.body) {
            const style = getComputedStyle(node);
            if (/auto|scroll/.test(style.overflowY) && node.scrollHeight > node.clientHeight + 10) {
              scored.set(node, (scored.get(node) || 0) + 1);
            }
            node = node.parentElement;
          }
        }
        let best = null, bestRows = 0;
        for (const [node, count] of scored) {
          if (count > bestRows || (count === bestRows && best && node.clientHeight > best.clientHeight)) {
            best = node; bestRows = count;
          }
        }
        window.__newscastScroller = best;
        if (!best) return {note: 'no scrollable ancestor contains rows; falling back to the window'};
        return {tag: best.tagName.toLowerCase(), cls: (best.className || '').slice(0, 90),
                rowsInside: bestRows, scrollHeight: best.scrollHeight, clientHeight: best.clientHeight};
        """
    )

    counts: list[int] = []
    tops: list[Any] = []
    for index in range(scroll_passes):
        counts.append(len(parse_listing(driver.page_source)))
        tops.append(
            driver.execute_script(
                """
                const el = window.__newscastScroller;
                if (el) { el.scrollTop = el.scrollHeight; return Math.round(el.scrollTop); }
                window.scrollTo(0, document.body.scrollHeight);
                return Math.round(window.scrollY);
                """
            )
        )
        time.sleep(1.8)
        if index >= 2 and counts[-1] == counts[-2] == counts[-3]:
            time.sleep(2.0)
            if len(parse_listing(driver.page_source)) == counts[-1]:
                break

    stubs = parse_listing(driver.page_source)
    # Rows with no clock time (graphics: "31 Aug 26") sit at midnight and would
    # report a false 14-hour span.
    timed = [s for s in stubs if s.timestamp and s.timestamp_text.count(":")]
    oldest = min((s.timestamp for s in timed), default=None)
    newest = max((s.timestamp for s in timed), default=None)

    return {
        "scroll_container": scroller,
        "scroll_top_after_each_pass": tops,
        "rows_after_each_scroll": counts,
        "rows_final": len(stubs),
        "rows_with_a_clock_time": len(timed),
        "newest": newest.isoformat() if newest else None,
        "oldest": oldest.isoformat() if oldest else None,
        "span_minutes": round((newest - oldest).total_seconds() / 60) if oldest and newest else None,
        "footage_types": sorted({s.footage_type for s in stubs if s.footage_type}),
        "sources": sorted({s.source for s in stubs})[:25],
    }


# The row's expand control. Its own label answers a question the notes had
# listed as unknown: expanding a row is how related content surfaces.
EXPAND_SELECTORS = (
    'button[title="Show related content"]',
    'button[aria-label="Show related content"]',
    'button[title^="Show"]',
    '[data-testid="ExpandMoreIcon"]',
    '[data-testid="KeyboardArrowDownIcon"]',
)


def wait_for_rows(driver, timeout: float = 30.0) -> int:
    """Wait until the list has rendered.

    The app fetches its content after the document loads, so probing straight
    away reads an empty page and concludes there is nothing there.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        count = driver.execute_script(
            "return document.querySelectorAll('.storyLineItemWrapperBox').length;"
        )
        if count:
            return count
        time.sleep(0.5)
    return 0


def _expand_first(driver, want_video: bool) -> dict[str, Any]:
    """Expand the first row, optionally the first carrying video.

    Returns which selector worked, so a failure says what was actually tried
    rather than just "not found".
    """
    return driver.execute_script(
        """
        const wantVideo = arguments[0];
        const selectors = arguments[1];
        const rows = Array.from(document.querySelectorAll('.storyLineItemWrapperBox'));
        const tried = [];
        for (let i = 0; i < rows.length; i++) {
          const row = rows[i];
          if (wantVideo && !row.querySelector('[aria-label="Video"]')) continue;
          for (const sel of selectors) {
            const hit = row.querySelector(sel);
            const button = hit ? (hit.closest('button') || hit) : null;
            if (button) {
              button.scrollIntoView({block: 'center'});
              button.click();
              return {index: i, selector: sel, rows: rows.length};
            }
            tried.push(sel);
          }
        }
        return {index: null, tried: Array.from(new Set(tried)), rows: rows.length,
                videoRows: rows.filter(r => r.querySelector('[aria-label="Video"]')).length};
        """,
        want_video,
        list(EXPAND_SELECTORS),
    )


def probe_expand(driver, out: str, **options) -> dict[str, Any]:
    """What an expanded story holds: Story Number, TRT, related stories."""
    wait_for_rows(driver)
    opened = _expand_first(driver, want_video=False)
    if opened.get("index") is None:
        return {"error": "no expandable row found", "attempt": opened}
    time.sleep(3.0)

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
        "expanded_row": opened,
        "detail_labels": labels,
        "related_hits": related,
        "script_chars": len(text),
        "script_is_package": bool(script and script.is_package),
        "script_supers": len(script.supers) if script else 0,
        "has_trt_label": any("trt" in l.lower() for l in labels),
        "has_story_number_label": any("story number" in l.lower() for l in labels),
    }


def probe_duration(driver, out: str, **options) -> dict[str, Any]:
    """What the printed duration actually corresponds to.

    Phil: the script may run 20 seconds while the printed duration counts the
    b-roll in the file, and packages are worst. So put four numbers against one
    story — what the listing prints, what the detail table calls TRT, what the
    media file reports, and what our own estimator says the copy reads at — and
    see which agree.
    """
    wait_for_rows(driver)
    opened = _expand_first(driver, want_video=True)
    if opened.get("index") is None:
        return {"error": "no video row found to expand", "attempt": opened}
    time.sleep(4.0)

    html = driver.page_source
    _write(out, "expanded-video.html", scrub_html(html)[0])

    # The detail table is the reliable correlation: the listing re-renders while
    # the probe works — the row count changed between probes on the last run —
    # so a row index taken before expanding may point at a different story after.
    details = parse_story_details(html)
    story_number = details.get("Story Number", "")

    stub = None
    for candidate in parse_listing(html):
        if story_number and candidate.story_number == story_number:
            stub = candidate
            break

    # Media elements are created with no source loaded (readyState 0 reports
    # nothing), so metadata has to be asked for and waited on.
    media = driver.execute_async_script(
        """
        const done = arguments[arguments.length - 1];
        const videos = Array.from(document.querySelectorAll('video'))
          .filter(v => (v.currentSrc || v.src));
        if (!videos.length) { done([]); return; }

        let settled = 0;
        const out = videos.map(() => null);
        const finish = () => { if (++settled >= videos.length) done(out); };

        videos.forEach((v, i) => {
          const record = () => {
            out[i] = {
              duration: isFinite(v.duration) ? Math.round(v.duration * 100) / 100 : null,
              readyState: v.readyState,
              src: (v.currentSrc || v.src || '').split('?')[0].slice(0, 200)
            };
          };
          if (v.readyState >= 1) { record(); finish(); return; }
          const onMeta = () => { record(); cleanup(); finish(); };
          const onErr = () => { record(); cleanup(); finish(); };
          const cleanup = () => {
            v.removeEventListener('loadedmetadata', onMeta);
            v.removeEventListener('error', onErr);
          };
          v.addEventListener('loadedmetadata', onMeta);
          v.addEventListener('error', onErr);
          try { v.preload = 'metadata'; v.load(); } catch (e) { onErr(); }
        });

        setTimeout(() => { videos.forEach((v, i) => { if (!out[i]) out[i] = {
          duration: isFinite(v.duration) ? v.duration : null, readyState: v.readyState,
          src: (v.currentSrc || v.src || '').split('?')[0].slice(0, 200), timedOut: true }; });
          done(out); }, 12000);
        """
    ) or []

    loaded = [m for m in media if m and m.get("duration")]

    from newscast.readtime import estimate_read_time

    script = parse_wire_script(details.get("Script", "")) if details.get("Script") else None
    read_seconds = None
    anchor_copy = ""
    if script:
        anchor_copy = "\n".join(
            part for part in (script.lead_in, script.vo_script, script.tag) if part
        )
        read_seconds = estimate_read_time(anchor_copy) if anchor_copy else None

    return {
        "story_number": story_number,
        "footage_type": details.get("Footage Type"),
        "listing_duration_seconds": stub.wire_duration_seconds if stub else None,
        "detail_table_trt": details.get("TRT"),
        "estimated_read_seconds": read_seconds,
        "anchor_copy_chars": len(anchor_copy),
        "media_with_a_duration": loaded[:6],
        "media_elements_seen": len(media),
        "media_without_a_duration": len(media) - len(loaded),
        "matched_listing_row": stub is not None,
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


# Order matters. `api` reloads the page to collect a clean timeline, so it runs
# last, where it cannot disturb the probes that need an expanded row.
PROBES: tuple[tuple[str, str, Callable], ...] = (
    ("scroll", "how rows accumulate and how far back they reach", probe_scroll),
    ("expand", "what an expanded story holds", probe_expand),
    ("duration", "what the printed duration corresponds to", probe_duration),
    ("download", "how material gets out", probe_download),
    ("api", "does the front end call a JSON API", probe_api),
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
    parser.add_argument(
        "--out",
        help="where to write evidence (default: beside the .env, so it survives "
        "replacing the unzipped folder)",
    )
    parser.add_argument("--only", nargs="+", metavar="NAME",
                        help=f"run only these: {', '.join(n for n, _, _ in PROBES)}")
    parser.add_argument("--scroll-passes", type=int, default=12)
    args = parser.parse_args(argv)

    values, env_path = load_env(args.env_file)
    log("env", f"read {env_path}" if env_path else "no .env found; using the environment")

    # Default the output beside the .env rather than into the unzipped folder,
    # which gets replaced every time a new build is downloaded.
    out_dir = args.out or (
        os.path.join(os.path.dirname(env_path), "probe-output")
        if env_path
        else "probe-output"
    )
    log("out", os.path.abspath(out_dir))
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
    findings = run(driver, out_dir, args.only, scroll_passes=args.scroll_passes)

    path = write_report(findings, out_dir)
    print(f"\nwrote {path}")
    print(f"      {os.path.abspath(out_dir)}/")
    print("\nRead the output before sending it on — it is scrubbed, best effort.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
