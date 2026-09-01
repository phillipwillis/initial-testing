"""Shared browser driving for CNN Newsource.

Selenium navigates and authenticates; it never parses (CLAUDE.md §14). Every
function here either moves the browser or waits for it to settle, and hands the
resulting `page_source` to the pure parsers in `newscast.wires`.

Lessons from the probe runs are baked in rather than left to each caller:

* The list renders after the document loads, so waiting for rows is mandatory.
* Expanding a story is a fetch, not a reveal — poll for its detail table.
* Do not try to identify the scrolling element. Two runs picked two different
  wrappers, one of which moved 20 pixels. Scrolling the last row into view moves
  whatever actually needs to move.
"""

from __future__ import annotations

import time
from typing import Any, Optional

CNN_HOME = "https://newsource.ns.cnn.com/"
LANDING = "https://newsource.ns.cnn.com/landing"

ROW_SELECTOR = ".storyLineItemWrapperBox"

EXPAND_SELECTORS = (
    'button[title="Show related content"]',
    'button[aria-label="Show related content"]',
    'button[title^="Show"]',
    '[data-testid="ExpandMoreIcon"]',
)
COLLAPSE_SELECTORS = (
    'button[title="Hide related content"]',
    'button[aria-label="Hide related content"]',
)


def looks_signed_in(driver) -> bool:
    return "/landing" in (driver.current_url or "") or bool(
        driver.execute_script(f"return !!document.querySelector('{ROW_SELECTOR}');")
    )


def login(driver, username: str, password: str, timeout: float = 45.0) -> bool:
    """Sign in. The password is never logged, echoed or stored."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    if looks_signed_in(driver):
        return True

    driver.get(CNN_HOME)
    wait = WebDriverWait(driver, timeout)
    try:
        user_field = wait.until(EC.element_to_be_clickable((By.ID, "username")))
        pass_field = wait.until(EC.element_to_be_clickable((By.ID, "password")))
    except Exception:
        return looks_signed_in(driver)

    user_field.clear()
    user_field.send_keys(username)
    pass_field.clear()
    pass_field.send_keys(password)
    pass_field.send_keys(Keys.RETURN)

    deadline = time.time() + timeout
    while time.time() < deadline:
        if looks_signed_in(driver):
            return True
        time.sleep(0.5)
    return False


def wait_for_rows(driver, timeout: float = 30.0) -> int:
    deadline = time.time() + timeout
    while time.time() < deadline:
        count = driver.execute_script(
            f"return document.querySelectorAll('{ROW_SELECTOR}').length;"
        )
        if count:
            return count
        time.sleep(0.5)
    return 0


def wait_for_details(driver, timeout: float = 25.0) -> bool:
    """Wait for an expanded story's detail table. Expanding is a fetch."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if driver.execute_script(
            """
            for (const cell of document.querySelectorAll('td, th')) {
              if ((cell.innerText || '').trim().startsWith('Story Number')) return true;
            }
            return false;
            """
        ):
            return True
        time.sleep(0.4)
    return False


def scroll_for_rows(
    driver, target: int, max_passes: int = 40, settle: float = 1.6
) -> list[int]:
    """Scroll until the list holds `target` rows, or stops growing.

    Returns the row count after each pass, so a run that stalls says where.
    """
    counts: list[int] = []
    stalls = 0
    for _ in range(max_passes):
        count = driver.execute_script(
            f"return document.querySelectorAll('{ROW_SELECTOR}').length;"
        )
        counts.append(count)
        if count >= target:
            break

        driver.execute_script(
            f"""
            const rows = document.querySelectorAll('{ROW_SELECTOR}');
            if (rows.length) rows[rows.length - 1].scrollIntoView({{block: 'end'}});
            """
        )
        time.sleep(settle)

        grown = driver.execute_script(
            f"return document.querySelectorAll('{ROW_SELECTOR}').length;"
        )
        if grown <= count:
            stalls += 1
            if stalls >= 3:
                break
            time.sleep(settle)
        else:
            stalls = 0
    return counts


def collapse_open_rows(driver) -> int:
    """Close any expanded story, so one story's detail is never read as another's."""
    return driver.execute_script(
        """
        const selectors = arguments[0];
        let closed = 0;
        for (const sel of selectors) {
          for (const button of document.querySelectorAll(sel)) { button.click(); closed++; }
        }
        return closed;
        """,
        list(COLLAPSE_SELECTORS),
    )


def expand_row(driver, index: int) -> dict[str, Any]:
    """Expand one row by position, after collapsing anything already open."""
    collapse_open_rows(driver)
    time.sleep(0.6)
    return driver.execute_script(
        """
        const wanted = arguments[0];
        const selectors = arguments[1];
        const rows = Array.from(document.querySelectorAll(arguments[2]));
        if (wanted >= rows.length) return {ok: false, rows: rows.length};
        const row = rows[wanted];
        for (const sel of selectors) {
          const hit = row.querySelector(sel);
          const button = hit ? (hit.closest('button') || hit) : null;
          if (button) {
            button.scrollIntoView({block: 'center'});
            button.click();
            return {ok: true, index: wanted, selector: sel};
          }
        }
        return {ok: false, index: wanted, reason: 'no expand control in this row'};
        """,
        index,
        list(EXPAND_SELECTORS),
        ROW_SELECTOR,
    )
