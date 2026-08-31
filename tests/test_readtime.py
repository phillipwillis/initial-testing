"""Read-time estimator tests (build order §10.2).

The absolute rate is PROVISIONAL until it is calibrated against real KIFI
scripts, so these tests pin behaviour that must hold at any rate: ordering,
proportionality, and what does and does not get read aloud.
"""

import unittest

from newscast.config import ShowConfig
from newscast.readtime import count_spoken_words, estimate_read_time


class ReadTimeTests(unittest.TestCase):
    def test_empty_copy_is_zero(self):
        self.assertEqual(estimate_read_time(""), 0.0)
        self.assertEqual(estimate_read_time("   \n  "), 0.0)

    def test_more_copy_takes_longer(self):
        short = "THE MARKET CLOSES EARLY TODAY."
        long = short + " VENDORS PACK UP AT TWO THIS AFTERNOON, AND THE STREET REOPENS AT THREE."
        self.assertGreater(estimate_read_time(long), estimate_read_time(short))

    def test_rate_scales_inversely(self):
        copy = "VENDORS CLOSE UP SHOP AT TWO THIS AFTERNOON."
        slow = estimate_read_time(copy, ShowConfig(words_per_minute=120))
        fast = estimate_read_time(copy, ShowConfig(words_per_minute=240))
        self.assertAlmostEqual(slow / fast, 2.0, delta=0.15)

    def test_accepts_a_list_of_lines(self):
        lines = ["THE MARKET CLOSES EARLY.", "VENDORS PACK UP AT TWO."]
        self.assertEqual(
            estimate_read_time(lines), estimate_read_time("\n".join(lines))
        )

    def test_natural_sound_is_not_read_aloud(self):
        self.assertEqual(estimate_read_time("-sounds of bustling-"), 0.0)
        with_nat = "THE MARKET IS BUSY.\n-sounds of bustling-"
        without = "THE MARKET IS BUSY."
        self.assertEqual(estimate_read_time(with_nat), estimate_read_time(without))

    def test_numbers_take_longer_than_their_character_count_suggests(self):
        self.assertGreater(count_spoken_words("1,500"), count_spoken_words("HOUSE"))

    def test_initialisms_are_spoken_as_letters(self):
        self.assertGreater(count_spoken_words("F.B.I."), 1.0)

    def test_a_typical_vo_lands_in_the_spec_range(self):
        """The §3 VO example is the canonical 20-45 second VO."""
        copy = (
            "JUST SO YOU KNOW, THE IDAHO FALLS FARMERS MARKET CLOSES EARLY TODAY.\n"
            "VENDORS CLOSE UP SHOP AT 2 THIS AFTERNOON.\n"
            "THEY MADE THE DECISION DUE TO THE WILD WEATHER WE'RE GOING TO BE GETTING "
            "AROUND THREE, AND THEY WANTED TO BE SURE THERE WAS TIME TO CLOSE UP PROPERLY.\n"
            "GET OUT THERE FAST IF YOU WANTED TO GET SOME FRESH PRODUCE."
        )
        seconds = estimate_read_time(copy)
        self.assertGreaterEqual(seconds, 20.0)
        self.assertLessEqual(seconds, 45.0)

    def test_the_spec_reader_example_fits_the_reader_ceiling(self):
        """§3 calls this a reader, and R6 caps readers at ~15 seconds."""
        copy = (
            "JUST SO YOU KNOW, THE IDAHO FALLS FARMERS MARKET CLOSES EARLY TODAY. "
            "VENDORS CLOSE UP SHOP AT TWO THIS AFTERNOON.\n"
            "GET OUT THERE FAST IF YOU WANTED TO GET SOME FRESH PRODUCE."
        )
        self.assertLessEqual(estimate_read_time(copy), ShowConfig().rdr_max_seconds)


if __name__ == "__main__":
    unittest.main()
