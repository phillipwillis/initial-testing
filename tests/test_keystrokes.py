"""Keystroke plan tests (§13.6).

Inception generates the markup from shortcuts, so this is the last translation
before a live rundown. A plan is data, which is why it can be asserted here
rather than discovered at 11:40am.
"""

import unittest

from newscast.keystrokes import (
    ANCHOR_SHORTCUTS,
    EXPAND_PAUSE_SECONDS,
    plan_keystrokes,
)
from newscast.markup import parse_story
from tests.helpers import fixture


def steps_of(kind, plan):
    return [s for s in plan.steps if s.kind == kind]


def chords(plan):
    return [s.value for s in plan.steps if s.kind == "chord"]


def texts(plan):
    return [s.value for s in plan.steps if s.kind == "text"]


def buttons(plan):
    return [s.value for s in plan.steps if s.kind == "button"]


class ShotTests(unittest.TestCase):
    def test_the_shortcut_is_the_over_shoulder_not_the_camera(self):
        """Inception's bracket shortcut is [OX2, not [CAM2."""
        plan = plan_keystrokes(parse_story("[CAM2 OX3]\n[MEGAN]\nHELLO.\n[#####]"))
        self.assertIn("[OX3", texts(plan))
        self.assertNotIn("[CAM2", texts(plan))

    def test_an_expansion_is_given_time_before_more_typing(self):
        plan = plan_keystrokes(parse_story("[CAM2 OX3]\n[MEGAN]\nHI.\n[#####]"))
        waits = steps_of("wait", plan)
        self.assertTrue(waits)
        self.assertEqual(waits[0].seconds, EXPAND_PAUSE_SECONDS)

    def test_shots_that_expand_with_a_d_have_it_removed(self):
        plan = plan_keystrokes(parse_story("[CAM2 OX3]\n[MEGAN]\nHI.\n[#####]"))
        fixes = steps_of("correction", plan)
        self.assertEqual(len(fixes), 1)
        self.assertEqual(fixes[0].expects, "-D")

    def test_ox2_does_not_expand_with_a_d_so_nothing_is_removed(self):
        plan = plan_keystrokes(parse_story("[CAM3 OX2]\n[MEGAN]\nHI.\n[#####]"))
        self.assertEqual(steps_of("correction", plan), [])

    def test_a_story_parking_the_monitor_in_d_keeps_the_appended_d(self):
        script = '[CAM2 OX3 - D]\n[MEGAN]\nHI.\n[#####]'
        self.assertEqual(steps_of("correction", plan_keystrokes(parse_story(script))), [])

    def test_a_shot_with_no_over_shoulder_warns_rather_than_guessing(self):
        plan = plan_keystrokes(parse_story("[WX GFX]\n[JEFF]\nWINDY.\n[#####]"))
        self.assertTrue(plan.warnings)
        self.assertIn("by hand", plan.warnings[0])


class AnchorTests(unittest.TestCase):
    def test_the_noon_anchors_map_to_their_shortcuts(self):
        self.assertEqual(ANCHOR_SHORTCUTS["MEGAN"], "2")
        self.assertEqual(ANCHOR_SHORTCUTS["JEFF"], "5")

    def test_an_anchor_becomes_a_chord_not_typed_text(self):
        plan = plan_keystrokes(parse_story("[CAM3 OX2]\n[MEGAN]\nHI.\n[#####]"))
        self.assertIn("option+2", chords(plan))
        self.assertNotIn("[MEGAN]", texts(plan))

    def test_a_double_read_emits_both_anchors(self):
        plan = plan_keystrokes(parse_story("[CAM3 OX2]\n[JEFF/MEGAN]\nHI.\n[#####]"))
        self.assertIn("option+5", chords(plan))
        self.assertIn("option+2", chords(plan))

    def test_an_unknown_anchor_warns_and_falls_back_to_typing(self):
        plan = plan_keystrokes(parse_story("[CAM3 OX2]\n[DANIELLE]\nHI.\n[#####]"))
        self.assertTrue(any("DANIELLE" in w for w in plan.warnings))
        self.assertIn("[DANIELLE]", texts(plan))


class ReturnToCameraTests(unittest.TestCase):
    """Returning to camera re-issues the shot; it does not type anything."""

    def test_on_cam_reissues_the_shot_shortcut(self):
        plan = plan_keystrokes(parse_story(fixture("example_vo.txt")))
        self.assertEqual(texts(plan).count("[OX1"), 2)

    def test_back_to_d_keeps_the_appended_d(self):
        script = (
            "[CAM2 OX3 - D]\n[MEGAN]\nONE.\n[VO]\n[CG: X]\nTWO.\n"
            "~~~New Segment~~~\n[SOT 0:10]\n[CG: Y]\n\"bite\"\n"
            "[ON CAM - BACK TO D]\n[MEGAN]\nTHREE.\n[#####]"
        )
        self.assertEqual(steps_of("correction", plan_keystrokes(parse_story(script))), [])


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.plan = plan_keystrokes(parse_story(fixture("example_pkg.txt")))

    def test_the_package_expands_from_a_bracket_shortcut(self):
        self.assertIn("[PKG", texts(self.plan))

    def test_both_auto_inserted_artefacts_are_corrected(self):
        expects = [s.expects for s in steps_of("correction", self.plan)]
        self.assertIn("- D", expects)
        self.assertIn("0:00", expects)

    def test_corrections_say_what_they_expect_to_remove(self):
        """Blind BACKSPACE runs eat real characters when Inception changes what
        it auto-fills; a correction that names its target can be verified."""
        for fix in steps_of("correction", self.plan):
            self.assertTrue(fix.expects)
            self.assertTrue(fix.reason)

    def test_the_trt_is_typed_after_the_placeholder_is_cleared(self):
        typed = texts(self.plan)
        self.assertIn("1:25", typed)

    def test_a_package_with_no_duration_warns(self):
        script = "[CAM3 OX2]\n[MEGAN]\nINTRO.\n[PKG]\n[CG: X]\nBODY.\n[#####]"
        self.assertTrue(
            any("TRT" in w for w in plan_keystrokes(parse_story(script)).warnings)
        )

    def test_the_reporter_track_is_typed_in_green(self):
        """Green marks text the anchor does not read, so it does not scroll on
        the prompter."""
        self.assertIn("SOT", buttons(self.plan))


class GreenModeTests(unittest.TestCase):
    def test_a_soundbite_turns_green_on(self):
        plan = plan_keystrokes(parse_story(fixture("example_sot.txt")))
        self.assertIn("SOT", buttons(plan))

    def test_a_cg_inside_green_re_enables_it(self):
        """Inserting a CG drops the editor out of green."""
        script = (
            "[CAM3 OX2]\n[MEGAN]\nINTRO.\n~~~New Segment~~~\n"
            "[SOT 0:10]\n[CG: NAME, TITLE]\n\"bite\"\n[#####]"
        )
        plan = plan_keystrokes(parse_story(script))
        self.assertGreaterEqual(buttons(plan).count("SOT"), 2)

    def test_cont_vo_leaves_green_because_the_anchor_reads_again(self):
        """A VOSOTVOSOT returns to a live mic between soundbites. Copy left in
        green does not scroll on the prompter."""
        script = (
            "[CAM3 OX2 - D]\n[MEGAN]\nONE.\n[VO]\n[CG: A]\nTWO.\n"
            "~~~New Segment~~~\n[SOT 0:10]\n[CG: B]\n\"bite one\"\n"
            "[CONT VO]\nTHREE.\n"
            "~~~New Segment~~~\n[SOT 0:10]\n[CG: C]\n\"bite two\"\n"
            "[ON CAM - BACK TO D]\n[MEGAN]\nFOUR.\n[#####]"
        )
        plan = plan_keystrokes(parse_story(script))

        leaves_green = [
            i for i, step in enumerate(plan.steps)
            if step.kind == "button" and "anchor reads again" in step.reason
        ]
        self.assertEqual(len(leaves_green), 1, "CONT VO should leave green once")

        typed_three = next(
            i for i, step in enumerate(plan.steps)
            if step.kind == "text" and step.value == "THREE."
        )
        self.assertLess(leaves_green[0], typed_three)

    def test_green_is_left_before_the_story_ends(self):
        script = "[CAM3 OX2]\n[MEGAN]\nINTRO.\n[SOT 0:10]\n[CG: X]\n\"bite\"\n[#####]"
        plan = plan_keystrokes(parse_story(script))
        self.assertEqual(plan.steps[-1].kind, "chord")
        self.assertEqual(buttons(plan)[-1], "SOT")


class StructureTests(unittest.TestCase):
    def test_every_story_ends_with_the_end_chord(self):
        for name in ("example_rdr.txt", "example_vo.txt", "example_pkg.txt"):
            with self.subTest(name):
                plan = plan_keystrokes(parse_story(fixture(name)))
                self.assertEqual(plan.steps[-1].value, "alt+command+h")

    def test_a_cg_is_a_shortcut_not_typed_text(self):
        plan = plan_keystrokes(parse_story(fixture("example_vo.txt")))
        self.assertIn("option+s", chords(plan))
        self.assertFalse(any("[CG:" in t for t in texts(plan)))

    def test_natural_sound_is_not_typed(self):
        """-sounds of bustling- is a note to the editor, not copy."""
        plan = plan_keystrokes(parse_story(fixture("example_pkg.txt")))
        self.assertFalse(any("sounds of bustling" in t for t in texts(plan)))

    def test_source_and_note_cues_stay_out_of_the_script_body(self):
        script = (
            "[CAM3 OX2]\n[MEGAN]\nINTRO.\n[SOURCE: KIFI 08-27 RAW]\n"
            "[NOTE: clip 0:14 to 0:25]\n[SOT 0:10]\n[CG: X]\n\"bite\"\n[#####]"
        )
        typed = texts(plan_keystrokes(parse_story(script)))
        self.assertFalse(any("KIFI" in t for t in typed))
        self.assertFalse(any("clip 0:14" in t for t in typed))

    def test_the_anchor_copy_all_reaches_the_plan(self):
        plan = plan_keystrokes(parse_story(fixture("example_vo.txt")))
        self.assertIn("FRESH PRODUCE", plan.typed_text)
        self.assertIn("FARMERS MARKET", plan.typed_text)

    def test_a_clean_story_plans_without_warnings(self):
        for name in ("example_rdr.txt", "example_vo.txt", "example_pkg.txt"):
            with self.subTest(name):
                self.assertEqual(plan_keystrokes(parse_story(fixture(name))).warnings, [])

    def test_a_shot_that_does_not_expand_with_d_gets_the_suffix_typed(self):
        """§11.24.

        OX3, OX4 and OX5 expand with -D appended; the others do not. Any camera
        and over-shoulder can still be parked in D, so a shot that does not
        expand with it has the suffix typed instead.
        """
        plan = plan_keystrokes(parse_story(fixture("example_sot.txt")))
        self.assertEqual(plan.warnings, [])
        self.assertIn("[OX1-D", plan.typed_text)
