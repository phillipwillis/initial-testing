"""Capture and scrub tests.

The Selenium parts cannot be tested here; the scrubber can, and it is the part
that matters, because it decides what leaves the work machine.
"""

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from newscast.capture import browser_on_port, launch_hint, probe_debug_port, scrub_html


class _FakeDevTools(BaseHTTPRequestHandler):
    payload: dict = {}

    def do_GET(self):
        body = json.dumps(self.payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class _Endpoint:
    """A throwaway DevTools-ish endpoint on an ephemeral port."""

    def __init__(self, payload):
        handler = type("H", (_FakeDevTools,), {"payload": payload})
        self.server = HTTPServer(("127.0.0.1", 0), handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


class DebugPortIdentityTests(unittest.TestCase):
    """An open port is not proof that Chrome is behind it.

    Adobe's UXP tooling speaks the DevTools protocol on 9222, accepts the
    connection, and only fails once the driver tries to use it — with
    "unrecognized Chrome version: Adobe UXP".
    """

    def test_chrome_is_recognised(self):
        with _Endpoint({"Browser": "Chrome/131.0.6778.86"}) as endpoint:
            browser, is_chrome = browser_on_port(endpoint.port)
        self.assertEqual(browser, "Chrome/131.0.6778.86")
        self.assertTrue(is_chrome)

    def test_chromium_is_recognised(self):
        with _Endpoint({"Browser": "Chromium/120.0.0.0"}) as endpoint:
            self.assertTrue(browser_on_port(endpoint.port)[1])

    def test_adobe_uxp_is_rejected_by_name(self):
        with _Endpoint({"Browser": "Adobe UXP"}) as endpoint:
            browser, is_chrome = browser_on_port(endpoint.port)
        self.assertEqual(browser, "Adobe UXP")
        self.assertFalse(is_chrome)

    def test_an_endpoint_that_names_no_browser_is_not_chrome(self):
        with _Endpoint({"Protocol-Version": "1.3"}) as endpoint:
            browser, is_chrome = browser_on_port(endpoint.port)
        self.assertEqual(browser, "unidentified")
        self.assertFalse(is_chrome)

    def test_a_closed_port_answers_nothing_rather_than_raising(self):
        with _Endpoint({"Browser": "Chrome/1"}) as endpoint:
            closed = endpoint.port
        self.assertIsNone(probe_debug_port(closed, timeout=0.4))
        self.assertEqual(browser_on_port(closed), (None, False))


class ScrubTests(unittest.TestCase):
    def test_email_addresses_go(self):
        html, hits = scrub_html('<span>phil@localnews8.com</span>')
        self.assertNotIn("phil@localnews8.com", html)
        self.assertEqual(hits["email address"], 1)

    def test_bearer_tokens_go_but_the_word_bearer_stays(self):
        html, _ = scrub_html('Authorization: Bearer abcdefghijklmnopqrstuvwxyz012345')
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz012345", html)
        self.assertIn("Bearer", html)

    def test_jwts_go(self):
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        html, hits = scrub_html(f'<script>var t="{jwt}";</script>')
        self.assertNotIn(jwt, html)
        self.assertIn("JWT", hits)

    def test_key_fields_are_emptied_but_keep_their_shape(self):
        html, _ = scrub_html('{"api_key": "sk-live-9999", "title": "Storm"}')
        self.assertNotIn("sk-live-9999", html)
        self.assertIn('"api_key": "REDACTED"', html)
        self.assertIn("Storm", html)

    def test_long_hex_session_ids_go(self):
        html, _ = scrub_html("<div data-session='0123456789abcdef0123456789abcdef'>")
        self.assertNotIn("0123456789abcdef0123456789abcdef", html)

    def test_ordinary_markup_survives_untouched(self):
        markup = '<span class="title" title="Storm Edouard">Storm Edouard</span>'
        html, hits = scrub_html(markup)
        self.assertEqual(html, markup)
        self.assertEqual(hits, {})

    def test_the_story_content_we_actually_want_is_not_eaten(self):
        row = (
            '<span class="title" title="1 dead in Grand Canyon flood">x</span>'
            '<span class="MuiTypography-caption" title="19">Version 19</span>'
        )
        html, _ = scrub_html(row)
        self.assertIn('title="19"', html)
        self.assertIn("Grand Canyon flood", html)


class LaunchTests(unittest.TestCase):
    def test_launch_is_a_no_op_when_chrome_is_already_there(self):
        from newscast.capture import launch_chrome

        with _Endpoint({"Browser": "Chrome/131.0.0.0"}) as endpoint:
            self.assertEqual(launch_chrome(endpoint.port), 0)

    def test_launch_refuses_a_port_something_else_holds(self):
        from newscast.capture import launch_chrome

        with _Endpoint({"Browser": "Adobe UXP"}) as endpoint:
            with self.assertRaises(SystemExit) as caught:
                launch_chrome(endpoint.port)
        self.assertIn("Adobe UXP", str(caught.exception))

    def test_the_profile_directory_is_not_the_default_chrome_one(self):
        """A debugging port on the everyday profile exposes every session on it."""
        from newscast.capture import profile_dir

        self.assertIn(".newscast-chrome", profile_dir())
        self.assertNotIn("Application Support/Google", profile_dir())


class LaunchHintTests(unittest.TestCase):
    def test_the_hint_carries_the_requested_port(self):
        self.assertIn("9333", launch_hint(9333))

    def test_the_hint_uses_a_separate_profile_directory(self):
        """Never point a debugging port at the user's main Chrome profile."""
        self.assertIn("user-data-dir", launch_hint(9222))
