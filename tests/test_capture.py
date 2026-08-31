"""Capture and scrub tests.

The Selenium parts cannot be tested here; the scrubber can, and it is the part
that matters, because it decides what leaves the work machine.
"""

import unittest

from newscast.capture import launch_hint, scrub_html


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


class LaunchHintTests(unittest.TestCase):
    def test_the_hint_carries_the_requested_port(self):
        self.assertIn("9333", launch_hint(9333))

    def test_the_hint_uses_a_separate_profile_directory(self):
        """Never point a debugging port at the user's main Chrome profile."""
        self.assertIn("user-data-dir", launch_hint(9222))
