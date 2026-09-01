"""Tests for the transcript pipeline (§11.7, §11.23, §11.26)."""

import unittest
from pathlib import Path

from newscast.config import ShowConfig
from newscast.transcript import (
    Clip,
    Sentence,
    Soundbite,
    Transcript,
    TranscriptError,
    Word,
    build_soundbite,
    build_transcript,
    drop_hallucinations,
    group_sentences,
    locate,
    locate_bite,
    select_bite,
    timecode,
    trim_package,
)


def words(spec):
    """`spec` is (text, start, end) triples, or a sentence split on spaces."""
    out = []
    for text, start, end in spec:
        pieces = text.split(" ")
        step = (end - start) / max(len(pieces), 1)
        for n, piece in enumerate(pieces):
            out.append(
                Word(
                    text=(" " if out else "") + piece,
                    start=round(start + n * step, 3),
                    end=round(start + (n + 1) * step, 3),
                )
            )
    return out


class GroupSentencesTest(unittest.TestCase):
    def test_terminal_punctuation_ends_a_sentence(self):
        sents = group_sentences(
            words([("The market closes early today.", 0.0, 3.0),
                   ("Vendors pack up at two this afternoon.", 3.2, 6.4)])
        )
        self.assertEqual(len(sents), 2)
        self.assertEqual(sents[0].text, "The market closes early today.")
        self.assertAlmostEqual(sents[0].start, 0.0)
        self.assertAlmostEqual(sents[1].end, 6.4)

    def test_a_long_silence_ends_a_sentence_without_punctuation(self):
        """Interview subjects pause, and ASR punctuation over broadcast audio
        is not dependable."""
        sents = group_sentences(
            words([("well I guess we are closing up early which is a shame", 0.0, 4.0),
                   ("but I sold my cheeses anyway and that is something", 9.0, 13.0)]),
            max_gap=1.0,
        )
        self.assertEqual(len(sents), 2)
        self.assertTrue(sents[1].text.startswith("but I sold"))

    def test_an_abbreviation_does_not_end_a_sentence(self):
        sents = group_sentences(
            words([("The reward came from the F.B.I. and the city of Idaho Falls today.", 0.0, 5.0)])
        )
        self.assertEqual(len(sents), 1)

    def test_sentences_are_numbered_from_zero(self):
        sents = group_sentences(
            words([("One thing happened here today.", 0.0, 2.0),
                   ("Another thing happened there too.", 2.0, 4.0),
                   ("A third thing happened as well.", 4.0, 6.0)])
        )
        self.assertEqual([s.idx for s in sents], [0, 1, 2])


class HallucinationTest(unittest.TestCase):
    def test_filler_over_the_logo_sting_is_dropped(self):
        sents = [
            Sentence(0, 0.0, 4.0, "The market closes early today."),
            Sentence(1, 28.0, 30.0, "Thanks for watching."),
        ]
        kept = drop_hallucinations(sents)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].idx, 0)

    def test_a_repeat_loop_is_dropped(self):
        looped = " ".join(["closing early"] * 8)
        kept = drop_hallucinations([Sentence(0, 0.0, 9.0, looped)])
        self.assertEqual(kept, [])

    def test_indices_are_renumbered_after_a_drop(self):
        sents = [
            Sentence(0, 0.0, 1.0, "[Music]"),
            Sentence(1, 1.0, 4.0, "The market closes early today."),
            Sentence(2, 4.0, 7.0, "Vendors pack up at two."),
        ]
        kept = drop_hallucinations(sents)
        self.assertEqual([s.idx for s in kept], [0, 1])


class TimecodeTest(unittest.TestCase):
    def test_it_is_the_section_four_form(self):
        self.assertEqual(timecode(13), "0:13")
        self.assertEqual(timecode(85), "1:25")
        self.assertEqual(timecode(0), "0:00")

    def test_it_never_goes_negative(self):
        self.assertEqual(timecode(-4), "0:00")


class TranscriptTest(unittest.TestCase):
    def transcript(self):
        return build_transcript(
            words([("The market closes early today.", 0.0, 3.0),
                   ("Vendors pack up at two this afternoon.", 3.0, 7.0),
                   ("Organizers blame the wind.", 7.0, 10.0)]),
            source_ref="CNN 1234567",
            media_ref="market.mp4",
            media_duration=95.0,
        )

    def test_the_gap_to_the_media_duration_is_the_b_roll(self):
        """§11.23 — CNN's printed number counts video the script never covers."""
        t = self.transcript()
        self.assertAlmostEqual(t.spoken_duration, 10.0)
        self.assertAlmostEqual(t.media_duration, 95.0)

    def test_a_clip_spans_whole_sentences(self):
        clip = self.transcript().clip(0, 1)
        self.assertAlmostEqual(clip.start, 0.0)
        self.assertAlmostEqual(clip.end, 7.0)
        self.assertEqual(clip.first_sentence, 0)
        self.assertEqual(clip.last_sentence, 1)

    def test_a_clip_inherits_the_transcripts_source(self):
        """R15 — an editor has to be able to find the file."""
        clip = self.transcript().clip(2, 2)
        self.assertEqual(clip.source_ref, "CNN 1234567")
        self.assertIn("CNN 1234567", clip.editor_note())
        self.assertIn("0:07", clip.editor_note())

    def test_clipping_an_empty_transcript_raises(self):
        with self.assertRaises(TranscriptError):
            Transcript().clip(0, 0)

    def test_out_of_range_indices_clamp(self):
        clip = self.transcript().clip(-3, 99)
        self.assertEqual((clip.first_sentence, clip.last_sentence), (0, 2))


class LocateTest(unittest.TestCase):
    def transcript(self):
        return build_transcript(
            words([("Reporter Danielle Mullenix has the story tonight.", 0.0, 4.0),
                   ("I know we are closing up early today.", 4.0, 8.0),
                   ("But I am glad I sold my cheeses anyway.", 8.0, 12.0),
                   ("The market reopens on Saturday morning.", 12.0, 16.0)]),
            source_ref="CNN 999",
        )

    def test_a_wire_quote_finds_its_in_and_out_points(self):
        clip = locate_bite(
            self.transcript(),
            "I know we're closing up early, but I'm just glad I sold my cheeses",
            speaker="DEBRA JONES",
        )
        self.assertIsNotNone(clip)
        self.assertAlmostEqual(clip.start, 4.0)
        self.assertAlmostEqual(clip.end, 12.0)
        self.assertEqual(clip.speaker, "DEBRA JONES")

    def test_a_stale_wire_script_matches_poorly_and_returns_nothing(self):
        """§11.7 — wires ship old scripts against revamped packages, and a bad
        match has to be visible rather than a wrong in-point."""
        clip = locate_bite(
            self.transcript(),
            "The county commission voted four to one on the bond measure",
        )
        self.assertIsNone(clip)

    def test_the_match_carries_a_score(self):
        match = locate(self.transcript(), "the market reopens on Saturday")
        self.assertTrue(match.confident)
        self.assertEqual((match.first, match.last), (3, 3))

    def test_locating_in_an_empty_transcript_returns_nothing(self):
        self.assertIsNone(locate(Transcript(), "anything"))


class SelectBiteTest(unittest.TestCase):
    def raw_interview(self):
        """The §11.26 case: five minutes of tape, twenty seconds of use."""
        spec = []
        for n in range(12):
            start = n * 25.0
            spec.append((f"This is interview sentence number {n} about the market.", start, start + 24.0))
        return build_transcript(words(spec), source_ref="CNN RAW")

    def test_it_picks_a_run_close_to_the_target(self):
        clip = select_bite(self.raw_interview(), target_seconds=24.0, max_seconds=30.0)
        self.assertIsNotNone(clip)
        self.assertLessEqual(clip.duration, 30.0)
        self.assertGreaterEqual(clip.duration, 20.0)

    def test_it_never_returns_a_bite_over_the_ceiling(self):
        clip = select_bite(self.raw_interview(), target_seconds=90.0, max_seconds=26.0)
        self.assertLessEqual(clip.duration, 26.0)

    def test_excluding_the_first_bite_gives_a_different_second_one(self):
        """The second leg of a VOSOTVOSOT is a different bite, not the same
        one twice."""
        t = self.raw_interview()
        first = select_bite(t, target_seconds=24.0, max_seconds=30.0)
        used = range(first.first_sentence, first.last_sentence + 1)
        second = select_bite(t, target_seconds=24.0, max_seconds=30.0, exclude=list(used))
        self.assertIsNotNone(second)
        self.assertNotEqual(first.first_sentence, second.first_sentence)

    def test_nothing_long_enough_returns_nothing(self):
        t = build_transcript(words([("Yes.", 0.0, 0.5)]))
        self.assertIsNone(select_bite(t, min_seconds=4.0))


class SoundbiteTest(unittest.TestCase):
    def clips(self):
        return [
            Clip("CNN 111", 4.0, 12.0, "First bite.", speaker="DEBRA JONES"),
            Clip("CNN 222", 30.0, 37.0, "Second bite.", speaker="MANDY GAITHER"),
        ]

    def test_two_clips_from_different_sources_make_one_sot(self):
        """§11.26 — a single SOT can hold clips from several people across
        different sources."""
        bite = build_soundbite(self.clips())
        self.assertAlmostEqual(bite.duration, 15.0)
        self.assertEqual(bite.speakers, ["DEBRA JONES", "MANDY GAITHER"])
        self.assertEqual(bite.sources, ["CNN 111", "CNN 222"])

    def test_every_clip_keeps_its_own_editor_note(self):
        """R15 — losing the mapping means an editor cannot find the clip."""
        notes = build_soundbite(self.clips()).editor_notes()
        self.assertEqual(len(notes), 2)
        self.assertIn("clip 1 of 2", notes[0])
        self.assertIn("CNN 111", notes[0])
        self.assertIn("CNN 222", notes[1])

    def test_a_single_clip_bite_is_not_numbered(self):
        notes = build_soundbite(self.clips()[:1]).editor_notes()
        self.assertEqual(len(notes), 1)
        self.assertNotIn("clip 1", notes[0])

    def test_more_than_three_clips_are_dropped(self):
        many = self.clips() * 3
        self.assertEqual(len(build_soundbite(many).clips), 3)


class TrimPackageTest(unittest.TestCase):
    def package(self):
        return build_transcript(
            words([("This morning the Idaho Falls farmers market opened as usual.", 0.0, 5.0),
                   ("But organizers say it closes at two this afternoon.", 5.0, 11.0),
                   ("They blame winds reaching twenty seven miles an hour.", 11.0, 17.0),
                   ("Reporting in Idaho Falls, Danielle Mullenix.", 17.0, 21.0)]),
            source_ref="CNN 55555",
        )

    def test_a_this_morning_open_comes_off_for_a_noon_show(self):
        """§11.26 — the fix is to cut the sentence, because the reporter's
        voice is in the file and cannot be rewritten."""
        trim = trim_package(self.package(), ShowConfig().daypart_phrases)
        self.assertEqual(len(trim.dropped_head), 1)
        self.assertAlmostEqual(trim.clip.start, 5.0)
        self.assertAlmostEqual(trim.duration, 16.0)
        self.assertIn("this morning", trim.editor_note())

    def test_daypart_language_in_the_middle_stays(self):
        """A 'this morning' inside the story is the news, not the daypart."""
        t = build_transcript(
            words([("Organizers say the market closes at two.", 0.0, 5.0),
                   ("The decision came down this morning.", 5.0, 9.0)]),
        )
        trim = trim_package(t, ShowConfig().daypart_phrases)
        self.assertEqual(trim.dropped_head, [])
        self.assertAlmostEqual(trim.clip.start, 0.0)

    def test_a_long_package_is_trimmed_off_the_tail(self):
        trim = trim_package(self.package(), ShowConfig().daypart_phrases, max_seconds=12.0)
        self.assertLessEqual(trim.duration, 12.0)
        self.assertTrue(trim.dropped_tail)
        self.assertIn("tail", trim.editor_note())

    def test_the_trim_carries_the_source_for_r15(self):
        trim = trim_package(self.package(), ShowConfig().daypart_phrases)
        self.assertIn("CNN 55555", trim.editor_note())

    def test_trimming_nothing_raises(self):
        with self.assertRaises(TranscriptError):
            trim_package(Transcript(), ShowConfig().daypart_phrases)


if __name__ == "__main__":
    unittest.main()
