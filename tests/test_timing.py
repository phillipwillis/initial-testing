"""Timing tests: what counts as time on air and what is already inside a file."""

import unittest

from newscast.markup import parse_story
from newscast.model import Copy, CopyStyle
from newscast.readtime import estimate_read_time
from newscast.timing import block_seconds, story_timing, vo_stretches
from tests.helpers import fixture, fixture_show


class StoryTimingTests(unittest.TestCase):
    def test_reader_is_all_live_read(self):
        timing = story_timing(parse_story(fixture("example_rdr.txt")))
        self.assertEqual(timing.video_seconds, 0.0)
        self.assertGreater(timing.read_seconds, 0.0)

    def test_sot_duration_counts_but_the_soundbite_text_does_not(self):
        story = parse_story(fixture("example_sot.txt"))
        timing = story_timing(story)
        self.assertEqual(timing.video_seconds, 13.0)
        bite = (
            '"I know we\'re closing up early, but I\'m just glad I was able to sell '
            'my cheeses for even a few hours today!"'
        )
        self.assertGreater(estimate_read_time(bite), 5.0)  # it is not a short line
        self.assertLess(timing.read_seconds, 45.0)  # yet it is not in the read time

    def test_package_track_is_not_counted_twice(self):
        """The reporter track inside a PKG is already inside its 1:25."""
        story = parse_story(fixture("example_pkg.txt"))
        timing = story_timing(story)
        self.assertEqual(timing.video_seconds, 85.0)

        # Only the anchor intro and the outro are live; counting every capitalised
        # line in the story would be materially longer.
        every_caps_line = [
            line
            for copy in story.elements
            if isinstance(copy, Copy) and copy.style is CopyStyle.ANCHOR
            for line in copy.lines
        ]
        self.assertGreater(
            estimate_read_time(every_caps_line), timing.read_seconds + 25.0
        )

        intro_and_outro = story_timing(
            parse_story(
                "[CAM1 OX1]\n[MEGAN]\n"
                "IF YOU DIDN'T KNOW, THE IDAHO FALLS FARMERS MARKET CLOSES EARLY TODAY.\n"
                "DANIELLE MULLENIX GIVES US AN INSIDE LOOK AS TO WHY.\n"
                "WHILE THE FARMER'S MARKET WILL BE CLOSING SOON, THERE'S STILL SOME TIME "
                "TO GET SOME GREAT DEALS.\n"
                "DON'T FORGET TO MENTION THAT YOU WATCH LOCAL NEWS 8 AT THE POPCORN "
                "KETTLE STAND TO GET SOME FREE SAMPLE BAGS.\n[#####]"
            )
        )
        self.assertAlmostEqual(
            timing.read_seconds, intro_and_outro.read_seconds, delta=0.2
        )

    def test_cont_vo_copy_is_live_again(self):
        sot = story_timing(parse_story(fixture("example_sot.txt")))
        sotvo = story_timing(parse_story(fixture("example_sotvo.txt")))
        self.assertGreater(sotvo.read_seconds, sot.read_seconds)

    def test_total_is_read_plus_video(self):
        timing = story_timing(parse_story(fixture("example_sot.txt")))
        self.assertAlmostEqual(
            timing.total, timing.read_seconds + timing.video_seconds, places=1
        )


class VOStretchTests(unittest.TestCase):
    def test_a_plain_vo_has_one_stretch(self):
        self.assertEqual(len(vo_stretches(parse_story(fixture("example_vo.txt")))), 1)

    def test_a_sotvo_has_a_stretch_either_side_of_the_bite(self):
        self.assertEqual(len(vo_stretches(parse_story(fixture("example_sotvo.txt")))), 2)

    def test_a_reader_has_none(self):
        self.assertEqual(vo_stretches(parse_story(fixture("example_rdr.txt"))), [])


class BlockTimingTests(unittest.TestCase):
    def test_block_is_the_sum_of_its_stories(self):
        show = fixture_show("show_clean.txt")
        block = show.block(1, "A")
        total = sum(story_timing(s).total for s in block.stories)
        self.assertAlmostEqual(block_seconds(block), total, places=1)


if __name__ == "__main__":
    unittest.main()
