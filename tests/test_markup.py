"""Parser and serializer tests (CLAUDE.md §4)."""

import unittest

from newscast.markup import MarkupError, parse_duration, parse_show, parse_story, serialize_story
from newscast.model import (
    AnchorCue,
    CameraCue,
    CGCue,
    Copy,
    CopyStyle,
    OnCamCue,
    PKGCue,
    SegmentMode,
    SOTCue,
    StoryKind,
    VOCue,
)
from tests.helpers import fixture, fixture_show

EXAMPLES = [
    "example_rdr.txt",
    "example_vo.txt",
    "example_sot.txt",
    "example_sotvo.txt",
    "example_pkg.txt",
]


class RoundTripTests(unittest.TestCase):
    def test_spec_examples_round_trip_exactly(self):
        for name in EXAMPLES:
            with self.subTest(name):
                src = fixture(name).rstrip("\n")
                self.assertEqual(serialize_story(parse_story(src)), src)

    def test_every_example_terminates(self):
        for name in EXAMPLES:
            with self.subTest(name):
                self.assertTrue(parse_story(fixture(name)).terminated)


class SegmentModeTests(unittest.TestCase):
    def test_modes_match_the_spec_headings(self):
        expected = {
            "example_rdr.txt": [SegmentMode.RDR],
            "example_vo.txt": [SegmentMode.VO],
            "example_sot.txt": [SegmentMode.VO, SegmentMode.SOT],
            "example_sotvo.txt": [SegmentMode.VO, SegmentMode.SOTVO],
            "example_pkg.txt": [SegmentMode.PKG],
        }
        for name, modes in expected.items():
            with self.subTest(name):
                self.assertEqual(parse_story(fixture(name)).modes, modes)

    def test_composite_form_reads_across_segment_breaks(self):
        self.assertEqual(parse_story(fixture("example_sot.txt")).form, "VOSOT")
        self.assertEqual(parse_story(fixture("example_sotvo.txt")).form, "VOSOTVO")
        self.assertEqual(parse_story(fixture("example_rdr.txt")).form, "RDR")

    def test_sot_without_cont_vo_is_a_plain_sot(self):
        story = parse_story(fixture("example_sot.txt"))
        self.assertIs(story.segments[1].mode, SegmentMode.SOT)
        self.assertTrue(story.segments[1].returns_to_camera())


class CueParsingTests(unittest.TestCase):
    def test_camera_cue_with_d_park(self):
        story = parse_story("[CAM1 OX1 - D]\n[MEGAN]\nHELLO.\n[#####]")
        cam = story.elements[0]
        self.assertIsInstance(cam, CameraCue)
        self.assertEqual((cam.shot, cam.monitor, cam.park_d), ("CAM1", "OX1", True))

    def test_camera_cue_without_monitor(self):
        cam = parse_story("[CAM2]\n[MEGAN]\nHI.\n[#####]").elements[0]
        self.assertEqual((cam.shot, cam.monitor, cam.park_d), ("CAM2", None, False))

    def test_on_cam_back_to_d(self):
        story = parse_story("[CAM1 OX1 - D]\n[SOT 0:05]\n[ON CAM - BACK TO D]\n[#####]")
        ret = [e for e in story.elements if isinstance(e, OnCamCue)][0]
        self.assertTrue(ret.back_to_d)

    def test_cont_vo(self):
        story = parse_story("[VO]\n[CONT VO]\n[#####]")
        vos = [e for e in story.elements if isinstance(e, VOCue)]
        self.assertEqual([v.cont for v in vos], [False, True])

    def test_anchor_dual_read(self):
        cue = parse_story("[MEGAN/JAY]\nHI.\n[#####]").elements[0]
        self.assertIsInstance(cue, AnchorCue)
        self.assertEqual(cue.names, ["MEGAN", "JAY"])
        self.assertTrue(cue.is_dual)

    def test_cg_text_is_captured_verbatim(self):
        cg = parse_story("[CG: I.F. FARMER'S MARKET CLOSES AT 2:00 PM]\n[#####]").elements[0]
        self.assertIsInstance(cg, CGCue)
        self.assertEqual(cg.text, "I.F. FARMER'S MARKET CLOSES AT 2:00 PM")

    def test_unknown_cue_is_a_markup_error(self):
        with self.assertRaises(MarkupError) as ctx:
            parse_story("[CAM1 OX1]\n[roll the thing]\n[#####]")
        self.assertEqual(ctx.exception.line_no, 2)

    def test_content_after_terminator_is_a_markup_error(self):
        with self.assertRaises(MarkupError):
            parse_story("[CAM1 OX1]\n[#####]\nMORE COPY.")

    def test_missing_terminator_parses_but_is_not_terminated(self):
        story = parse_story("[CAM1 OX1]\n[MEGAN]\nCOPY.")
        self.assertFalse(story.terminated)


class DurationTests(unittest.TestCase):
    def test_parse_duration_forms(self):
        self.assertEqual(parse_duration("1:25"), 85.0)
        self.assertEqual(parse_duration("0:13"), 13.0)
        self.assertEqual(parse_duration("13"), 13.0)
        self.assertIsNone(parse_duration("about a minute"))

    def test_video_cue_durations(self):
        story = parse_story(fixture("example_pkg.txt"))
        pkg = [e for e in story.elements if isinstance(e, PKGCue)][0]
        self.assertEqual(pkg.seconds, 85.0)
        self.assertEqual(pkg.duration_text, "1:25")

    def test_missing_duration_is_zero_not_an_error(self):
        story = parse_story("[SOT]\n[#####]")
        sot = [e for e in story.elements if isinstance(e, SOTCue)][0]
        self.assertEqual(sot.seconds, 0.0)


class CopyStyleTests(unittest.TestCase):
    def test_styles_are_classified_from_the_line_itself(self):
        story = parse_story(fixture("example_pkg.txt"))
        styles = [c.style for c in story.elements if isinstance(c, Copy)]
        self.assertIn(CopyStyle.NAT, styles)
        self.assertIn(CopyStyle.SOUNDBITE, styles)
        self.assertIn(CopyStyle.ANCHOR, styles)

    def test_consecutive_lines_of_one_style_merge(self):
        story = parse_story("[MEGAN]\nLINE ONE.\nLINE TWO.\n[#####]")
        copies = [c for c in story.elements if isinstance(c, Copy)]
        self.assertEqual(len(copies), 1)
        self.assertEqual(copies[0].lines, ["LINE ONE.", "LINE TWO."])

    def test_nat_sound_is_not_anchor_copy(self):
        story = parse_story("[PKG 0:30]\n-sounds of bustling-\n[#####]")
        copies = [c for c in story.elements if isinstance(c, Copy)]
        self.assertEqual(copies[0].style, CopyStyle.NAT)


class ShowParsingTests(unittest.TestCase):
    def setUp(self):
        self.show = fixture_show("show_clean.txt")

    def test_all_eight_blocks_parse(self):
        self.assertEqual(
            [b.name for b in self.show.blocks],
            ["1A", "1B", "1C", "1D", "2A", "2B", "2C", "2D"],
        )

    def test_slugs_and_kinds(self):
        block = self.show.block(1, "A")
        self.assertEqual(block.stories[0].slug, "SHOW OPEN")
        self.assertEqual(block.stories[1].slug, "I.F. FARMERS MARKET")
        self.assertIs(block.stories[-1].kind, StoryKind.BUMP)
        self.assertTrue(block.stories[-1].is_tease)

    def test_accepted_flag_survives_parsing(self):
        block = self.show.block(1, "A")
        self.assertTrue(block.stories[1].accepted)
        self.assertTrue(block.stories[1].submitted)
        self.assertFalse(block.stories[0].accepted)

    def test_line_numbers_point_back_at_the_source_file(self):
        story = self.show.block(1, "A").stories[1]
        source_lines = fixture("show_clean.txt").splitlines()
        first = story.elements[0]
        self.assertEqual(source_lines[first.line_no - 1].strip(), "[CAM2 OX3]")

    def test_comment_lines_are_ignored(self):
        self.assertTrue(all(s.slug for s in self.show.stories))


if __name__ == "__main__":
    unittest.main()
