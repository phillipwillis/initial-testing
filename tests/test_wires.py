"""Wire collection tests (§10.3).

Everything here runs against saved HTML and saved wire copy. No browser, no
network, no credentials — the point of the split in CLAUDE.md §14.
"""

import unittest
from datetime import datetime

from newscast.wires.cnn import parse_listing, parse_row
from newscast.wires.cnn_script import Super, parse_supers, parse_wire_script
from newscast.wires.dom import parse_html
from newscast.wires.stub import ContentType, parse_timestamp
from tests.helpers import fixture

PKG_SCRIPT = """Title: GRAND CANYON FLOOD
TRT: 01:45
Footage Type: PKG
--SUPERS--
:00-:06
Ivan Watson
CNN Senior International Correspondent
1:21-1:28
Mandy Gaither
Park Visitor
--LEAD IN--
A FLASH FLOOD TORE THROUGH THE GRAND CANYON OVERNIGHT.
IVAN WATSON HAS THE LATEST.
--REPORTER PKG-AS FOLLOWS--
-sounds of rushing water-
THE WATER CAME THROUGH HERE JUST AFTER MIDNIGHT.
--TAG--
SEARCH CREWS ARE BACK OUT THIS MORNING.
-----END-----CNN.SCRIPT-----
--KEYWORD TAGS--
flood, arizona"""

VO_SCRIPT = """Title: LETTUCE OUTBREAK
TRT: 00:28
Footage Type: VO
--LEAD IN--
FEDERAL HEALTH OFFICIALS ARE STILL LOOKING INTO THAT OUTBREAK.
--VO SCRIPT--
THE CASES HAVE BEEN TIED TO ICEBERG LETTUCE FROM ONE GROWER.
INVESTIGATORS SAY THE PRODUCT IS OFF THE SHELVES NOW.
--TAG--
THE CDC EXPECTS AN UPDATE LATER THIS WEEK.
-----END-----"""


class TimestampTests(unittest.TestCase):
    def test_the_wire_format(self):
        self.assertEqual(
            parse_timestamp("31 Aug 26 06:15 ET"), datetime(2026, 8, 31, 6, 15)
        )

    def test_case_does_not_matter(self):
        self.assertEqual(
            parse_timestamp("31 AUG 26 06:15 ET"), parse_timestamp("31 Aug 26 06:15 ET")
        )

    def test_a_four_digit_year(self):
        self.assertEqual(
            parse_timestamp("1 Sep 2026 23:04 ET"), datetime(2026, 9, 1, 23, 4)
        )

    def test_nonsense_is_none_not_an_exception(self):
        self.assertIsNone(parse_timestamp("sometime this morning"))
        self.assertIsNone(parse_timestamp(""))

    def test_an_impossible_date_is_none(self):
        self.assertIsNone(parse_timestamp("32 Aug 26 06:15 ET"))


class DomTests(unittest.TestCase):
    def test_classes_and_attributes(self):
        tree = parse_html('<div class="a b"><span class="title" title="X">Hi</span></div>')
        self.assertEqual(tree.find(cls="a").classes, {"a", "b"})
        self.assertEqual(tree.find(cls="title").attr("title"), "X")

    def test_text_collapses_whitespace_across_children(self):
        tree = parse_html("<p>Hello   <b>there</b>\n  friend</p>")
        self.assertEqual(tree.find(tag="p").text, "Hello there friend")

    def test_void_elements_do_not_swallow_siblings(self):
        tree = parse_html('<div><img src="a"><span class="after">x</span></div>')
        self.assertIsNotNone(tree.find(cls="after"))

    def test_an_unclosed_tag_does_not_corrupt_the_tree(self):
        tree = parse_html('<div class="outer"><span class="a">one<div class="b">two</div></div>')
        self.assertIsNotNone(tree.find(cls="a"))
        self.assertIsNotNone(tree.find(cls="b"))

    def test_a_stray_close_tag_is_ignored(self):
        tree = parse_html('</span><div class="ok">x</div>')
        self.assertIsNotNone(tree.find(cls="ok"))


class ListingTests(unittest.TestCase):
    def setUp(self):
        self.stubs = parse_listing(fixture("cnn_listing.html"))

    def test_every_row_is_found(self):
        self.assertEqual(len(self.stubs), 3)

    def test_the_headline_comes_from_the_title_attribute(self):
        """The visible text may be truncated by MuiTypography-noWrap."""
        flood = self.stubs[1]
        self.assertEqual(
            flood.slug,
            "1 dead and about 15 people may be missing as flash flood tears "
            "through the Grand Canyon",
        )
        self.assertNotIn("…", flood.slug)

    def test_the_timestamp_parses(self):
        self.assertEqual(self.stubs[0].timestamp, datetime(2026, 8, 31, 6, 15))
        self.assertEqual(self.stubs[0].timestamp_text, "31 Aug 26 06:15 ET")

    def test_the_version_comes_from_the_title_attribute_not_the_text(self):
        self.assertEqual(self.stubs[0].version, 1)
        self.assertEqual(self.stubs[1].version, 19)

    def test_a_high_version_marks_a_story_the_wire_keeps_rewriting(self):
        self.assertFalse(self.stubs[0].is_update)
        self.assertTrue(self.stubs[1].is_update)

    def test_the_source_is_read_per_row(self):
        self.assertEqual(self.stubs[0].source, "CNN")
        self.assertEqual(self.stubs[2].source, "CNN Wire")

    def test_the_dividers_are_not_mistaken_for_fields(self):
        for stub in self.stubs:
            self.assertNotIn("|", stub.source)

    def test_the_teaser_is_captured(self):
        self.assertTrue(
            self.stubs[0].teaser.startswith("A new potential tropical system")
        )

    def test_content_types_come_off_the_media_icons(self):
        self.assertIn(ContentType.SCRIPT, self.stubs[0].content_type)
        self.assertIn(ContentType.VIDEO, self.stubs[1].content_type)
        self.assertEqual(self.stubs[2].content_type, (ContentType.SCRIPT,))
        self.assertFalse(self.stubs[2].has_video)

    def test_fields_are_identified_by_content_not_position(self):
        """A reordered metadata line still parses."""
        reordered = fixture("cnn_listing.html").replace(
            '<span class="MuiTypography-root MuiTypography-caption css-1d6aoja">31 Aug 26 06:15 ET</span>\n'
            '        <span class="MuiTypography-root MuiTypography-body1 metadataDivider css-ypy096">|</span>\n'
            '        <span class="MuiTypography-root MuiTypography-caption css-1d6aoja" title="CNN">CNN</span>',
            '<span class="MuiTypography-root MuiTypography-caption css-1d6aoja" title="CNN">CNN</span>\n'
            '        <span class="MuiTypography-root MuiTypography-body1 metadataDivider css-ypy096">|</span>\n'
            '        <span class="MuiTypography-root MuiTypography-caption css-1d6aoja">31 Aug 26 06:15 ET</span>',
        )
        stub = parse_listing(reordered)[0]
        self.assertEqual(stub.source, "CNN")
        self.assertEqual(stub.timestamp, datetime(2026, 8, 31, 6, 15))

    def test_a_row_with_no_headline_is_skipped_not_crashed_on(self):
        tree = parse_html('<div class="storyLineItemWrapperBox"><p>nothing</p></div>')
        self.assertIsNone(parse_row(tree.find(cls="storyLineItemWrapperBox")))

    def test_an_empty_page_yields_no_stubs(self):
        self.assertEqual(parse_listing(""), [])
        self.assertEqual(parse_listing("<div>signed out</div>"), [])


class WireScriptTests(unittest.TestCase):
    def test_a_package_script(self):
        script = parse_wire_script(PKG_SCRIPT)
        self.assertEqual(script.title, "GRAND CANYON FLOOD")
        self.assertEqual(script.trt, "01:45")
        self.assertEqual(script.footage_type, "PKG")
        self.assertTrue(script.is_package)
        self.assertIn("IVAN WATSON HAS THE LATEST", script.lead_in)
        self.assertIn("THE WATER CAME THROUGH HERE", script.pkg_body)
        self.assertEqual(script.tag, "SEARCH CREWS ARE BACK OUT THIS MORNING.")

    def test_the_keyword_block_is_not_part_of_the_tag(self):
        self.assertNotIn("flood, arizona", parse_wire_script(PKG_SCRIPT).tag)

    def test_a_vo_script(self):
        script = parse_wire_script(VO_SCRIPT)
        self.assertFalse(script.is_package)
        self.assertIn("ICEBERG LETTUCE", script.vo_script)
        self.assertEqual(script.body, script.vo_script)

    def test_body_follows_the_footage_type(self):
        self.assertEqual(parse_wire_script(PKG_SCRIPT).body, parse_wire_script(PKG_SCRIPT).pkg_body)

    def test_marker_spellings_vary(self):
        for spelling in ("--LEAD IN--", "--LEAD-IN--", "--LEADIN--"):
            with self.subTest(spelling):
                script = parse_wire_script(VO_SCRIPT.replace("--LEAD IN--", spelling))
                self.assertIn("FEDERAL HEALTH OFFICIALS", script.lead_in)

    def test_a_script_with_no_markers_still_returns_its_copy(self):
        script = parse_wire_script("Script: THE MARKET CLOSES EARLY TODAY.")
        self.assertIn("MARKET CLOSES EARLY", script.vo_script)

    def test_empty_input_does_not_crash(self):
        self.assertEqual(parse_wire_script("").title, "")


class SupersTests(unittest.TestCase):
    def test_names_and_titles_pair_up(self):
        supers = parse_wire_script(PKG_SCRIPT).supers
        self.assertEqual(
            supers,
            [
                Super("Ivan Watson", "CNN Senior International Correspondent", ":00-:06"),
                Super("Mandy Gaither", "Park Visitor", "1:21-1:28"),
            ],
        )

    def test_a_name_with_no_title_after_it_is_dropped(self):
        """In real wire copy that pattern is a slate or a location."""
        block = ":00-:06\nKristyn Fisher\n1:21-1:28\nMandy Gaither\nPark Visitor"
        self.assertEqual(
            parse_supers(block), [Super("Mandy Gaither", "Park Visitor", "1:21-1:28")]
        )

    def test_both_timecode_shapes_are_recognised(self):
        self.assertEqual(len(parse_supers(":00-:06\nAmy Price\nSergeant")), 1)
        self.assertEqual(len(parse_supers("1:21-1:28\nAmy Price\nSergeant")), 1)

    def test_an_empty_block_is_no_supers(self):
        self.assertEqual(parse_supers(""), [])
