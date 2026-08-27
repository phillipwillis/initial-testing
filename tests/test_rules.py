"""Rule engine tests (CLAUDE.md §5).

Each rule gets a script that breaks it and a script that does not. The two show
fixtures then check the whole engine end to end: show_clean.txt must be silent,
show_broken.txt must trip every rule that runs without configuration.
"""

import dataclasses
import unittest

from newscast.config import BlockConfig, ShowConfig
from newscast.markup import parse_story
from newscast.model import StoryKind
from newscast.rules import Severity, all_rules
from newscast.validator import validate_show
from tests.helpers import codes, codes_at, fixture_show, one_story_show, show_of

SOT_STORY = """[CAM1 OX1 - D]
[MEGAN]
A CRASH ON SEVENTEENTH STREET SENT TWO PEOPLE TO THE HOSPITAL THIS AFTERNOON.
[VO]
[CG: TWO HURT IN 17TH STREET CRASH]
POLICE SAY A PICKUP RAN THE LIGHT AT HOLMES AND HIT A SEDAN BROADSIDE.
BOTH DRIVERS WERE TAKEN TO EASTERN IDAHO REGIONAL, AND BOTH ARE EXPECTED TO BE OKAY.
~~~New Segment~~~
[SOURCE: KIFI crew 08-27 CRASH-17TH-RAW]
[NOTE: clip 0:41 to 0:53, the sergeant on the light cycle]
[SOT 0:12]
[CG: SGT. AMY PRICE, IDAHO FALLS POLICE]
"That intersection gives you plenty of warning, and we see people run it anyway."
[ON CAM - BACK TO D]
[MEGAN]
NO CITATIONS HAVE BEEN ISSUED YET.
[#####]"""

PLAIN_VO = """[CAM1 OX1]
[MEGAN]
THE CITY COUNCIL TAKES UP THE WATER RATE PROPOSAL AT ITS TUESDAY MEETING.
[VO]
[CG: COUNCIL TAKES UP WATER RATES]
THE PROPOSAL WOULD RAISE THE BASE RATE BY ABOUT TWO DOLLARS A MONTH.
STAFF SAY THE MONEY GOES TO REPLACING THE OLDEST LINES ON THE NORTH SIDE.
THE COUNCIL TOOK PUBLIC COMMENT ON IT TWICE ALREADY.
[ON CAM]
TUESDAY'S MEETING STARTS AT SEVEN THIRTY.
[#####]"""

TEASE = """[CAM1 OX1]
[NO CG: bump]
[MEGAN]
[TEASE: WATER RATES]
STILL AHEAD -- THE WATER RATE PROPOSAL IN FRONT OF THE CITY COUNCIL.
[#####]"""


def config_for_1a(**kwargs) -> ShowConfig:
    """A ShowConfig whose 1A block carries the given settings."""
    base = ShowConfig()
    blocks = tuple(
        dataclasses.replace(b, **kwargs) if b.name == "1A" else b for b in base.blocks
    )
    return dataclasses.replace(base, blocks=blocks)


def report_for(*scripts, config=None, slugs=None):
    stories = []
    for i, script in enumerate(scripts):
        slug = (slugs or [])[i] if slugs and i < len(slugs) else f"S{i + 1}"
        stories.append(parse_story(script, slug=slug))
    return validate_show(show_of(*stories), config)


class RegistryTests(unittest.TestCase):
    def test_every_spec_rule_is_registered(self):
        registered = {r.code for r in all_rules()}
        self.assertTrue({f"R{n}" for n in range(1, 16)} <= registered)

    def test_rules_are_ordered_r_then_x_numerically(self):
        listed = [r.code for r in all_rules()]
        self.assertEqual(listed[:3], ["R1", "R2", "R3"])
        self.assertEqual(listed[14:16], ["R15", "X1"])


class R1BackToBackDTests(unittest.TestCase):
    def test_two_d_stories_back_to_back_is_an_error(self):
        self.assertIn("R1", codes(report_for(SOT_STORY, SOT_STORY, TEASE)))

    def test_a_non_d_story_between_them_is_fine(self):
        self.assertNotIn("R1", codes(report_for(SOT_STORY, PLAIN_VO, SOT_STORY, TEASE)))

    def test_the_documented_mitigation_clears_it(self):
        mitigated = SOT_STORY.replace(
            "[CAM1 OX1 - D]", "[CAM1 OX1 - D]\n[MONITOR PLACEHOLDER]"
        ).replace("[ON CAM - BACK TO D]", "[MONITOR DUPE]\n[ON CAM - BACK TO D]")
        self.assertNotIn("R1", codes(report_for(SOT_STORY, mitigated, TEASE)))

    def test_placeholder_without_the_duplicate_is_still_an_error(self):
        half = SOT_STORY.replace(
            "[CAM1 OX1 - D]", "[CAM1 OX1 - D]\n[MONITOR PLACEHOLDER]"
        )
        self.assertIn("R1", codes(report_for(SOT_STORY, half, TEASE)))


class R2DCueTests(unittest.TestCase):
    def test_sot_returning_to_camera_needs_the_d_park(self):
        broken = SOT_STORY.replace("[CAM1 OX1 - D]", "[CAM1 OX1]")
        self.assertIn("R2", codes(report_for(broken, TEASE)))

    def test_sot_returning_to_camera_needs_back_to_d(self):
        broken = SOT_STORY.replace("[ON CAM - BACK TO D]", "[ON CAM]")
        self.assertIn("R2", codes(report_for(broken, TEASE)))

    def test_a_correct_sot_is_clean(self):
        self.assertNotIn("R2", codes(report_for(SOT_STORY, TEASE)))

    def test_a_sotvo_that_never_returns_to_camera_needs_no_d(self):
        sotvo = SOT_STORY.replace("[ON CAM - BACK TO D]", "[CONT VO]").replace(
            "[CAM1 OX1 - D]", "[CAM1 OX1]"
        )
        self.assertNotIn("R2", codes(report_for(sotvo, TEASE)))

    def test_a_package_is_not_held_to_r2(self):
        """The §3 PKG example returns to camera with a plain [CAM1 OX1]."""
        report = validate_show(fixture_show("show_clean.txt"))
        self.assertNotIn("R2", codes(report))


class R3TerminatorTests(unittest.TestCase):
    def test_missing_terminator(self):
        self.assertIn("R3", codes(report_for(PLAIN_VO.replace("[#####]", ""), TEASE)))

    def test_present_terminator(self):
        self.assertNotIn("R3", codes(report_for(PLAIN_VO, TEASE)))


class R4CGTests(unittest.TestCase):
    def test_segment_without_a_cg(self):
        self.assertIn(
            "R4", codes(report_for(PLAIN_VO.replace("[CG: COUNCIL TAKES UP WATER RATES]\n", ""), TEASE))
        )

    def test_explicit_exemption_is_accepted(self):
        exempt = PLAIN_VO.replace(
            "[CG: COUNCIL TAKES UP WATER RATES]", "[NO CG: full-screen graphic instead]"
        )
        self.assertNotIn("R4", codes(report_for(exempt, TEASE)))


class R5CGLengthTests(unittest.TestCase):
    LONG = (
        "[CG: THE IDAHO FALLS FARMERS MARKET IS CLOSING DOWN EARLY BECAUSE OF THE "
        "WIND AND PEOPLE ARE NOT HAPPY ABOUT IT]"
    )

    def test_a_sentence_length_cg_fails(self):
        story = PLAIN_VO.replace("[CG: COUNCIL TAKES UP WATER RATES]", self.LONG)
        self.assertIn("R5", codes(report_for(story, TEASE)))

    def test_a_slug_length_cg_passes(self):
        self.assertNotIn("R5", codes(report_for(PLAIN_VO, TEASE)))

    def test_the_ceiling_is_configurable(self):
        config = dataclasses.replace(ShowConfig(), cg_char_ceiling=10)
        self.assertIn("R5", codes(report_for(PLAIN_VO, TEASE, config=config)))

    def test_the_provisional_ceiling_says_so(self):
        story = PLAIN_VO.replace("[CG: COUNCIL TAKES UP WATER RATES]", self.LONG)
        message = [v for v in report_for(story, TEASE).violations if v.code == "R5"][0]
        self.assertIn("PROVISIONAL", message.message)

    def test_a_lower_case_cg_is_a_warning_not_an_error(self):
        story = PLAIN_VO.replace(
            "[CG: COUNCIL TAKES UP WATER RATES]", "[CG: Council takes up water rates]"
        )
        report = report_for(story, TEASE)
        self.assertIn("R5", codes_at(report, Severity.WARNING))
        self.assertNotIn("R5", codes_at(report, Severity.ERROR))


class R6ReaderTests(unittest.TestCase):
    SHORT_RDR = """[CAM1 OX1]
[CG: MARKET CLOSES AT 2 PM]
[MEGAN]
THE IDAHO FALLS FARMERS MARKET CLOSES EARLY TODAY, AT TWO THIS AFTERNOON.
[#####]"""

    def test_a_long_reader_fails(self):
        long_rdr = self.SHORT_RDR.replace(
            "[#####]",
            "VENDORS SAY THE WIND FORECAST MADE THE CALL FOR THEM, AND THEY WOULD "
            "RATHER PACK UP EARLY THAN CHASE TENTS DOWN THE STREET LATER ON.\n"
            "THE MARKET IS BACK AT ITS USUAL HOURS NEXT SATURDAY MORNING.\n[#####]",
        )
        self.assertIn("R6", codes(report_for(long_rdr, TEASE)))

    def test_a_short_reader_passes(self):
        self.assertNotIn("R6", codes(report_for(self.SHORT_RDR, TEASE)))

    def test_a_tease_is_not_held_to_the_reader_ceiling(self):
        self.assertNotIn("R6", codes(report_for(PLAIN_VO, TEASE)))


class R7VOTests(unittest.TestCase):
    def test_a_short_vo_fails(self):
        short = """[CAM1 OX1]
[MEGAN]
[VO]
[CG: NEW MURAL DOWNTOWN]
A NEW MURAL WENT UP DOWNTOWN.
[#####]"""
        self.assertIn("R7", codes(report_for(short, TEASE)))

    def test_a_typical_vo_passes(self):
        self.assertNotIn("R7", codes(report_for(PLAIN_VO, TEASE)))

    def test_a_short_vo_inside_a_composite_is_not_flagged(self):
        """The story continues, so the leg does not have to carry 20 seconds."""
        self.assertNotIn("R7", codes(report_for(SOT_STORY, TEASE)))

    def test_an_overlong_vo_leg_inside_a_composite_warns(self):
        padded = SOT_STORY.replace(
            "BOTH DRIVERS WERE TAKEN TO EASTERN IDAHO REGIONAL, AND BOTH ARE EXPECTED TO BE OKAY.",
            "BOTH DRIVERS WERE TAKEN TO EASTERN IDAHO REGIONAL, AND BOTH ARE EXPECTED TO BE OKAY.\n"
            + "\n".join(
                [
                    "INVESTIGATORS SPENT THE MORNING MEASURING SKID MARKS AND TALKING TO WITNESSES.",
                    "THE INTERSECTION HAS SEEN ELEVEN CRASHES IN THE LAST THREE YEARS ALONE.",
                    "THE CITY LOOKED AT A LONGER YELLOW LIGHT THERE BACK IN THE SPRING.",
                    "ENGINEERS SAID AT THE TIME THAT THE TIMING WAS ALREADY INSIDE THE STATE STANDARD.",
                    "NEIGHBORS HAVE ASKED FOR A FOUR WAY STOP AT THE LAST TWO COUNCIL MEETINGS.",
                    "THE COUNTY SHERIFF SAYS HIS DEPUTIES WORKED FOUR CRASHES THERE LAST YEAR.",
                    "A TRAFFIC STUDY IS DUE BACK IN FRONT OF THE COUNCIL SOMETIME IN THE FALL.",
                ]
            ),
        )
        report = report_for(padded, TEASE)
        self.assertIn("R7", codes_at(report, Severity.WARNING))


class R8PackageTests(unittest.TestCase):
    PKG = """[CAM1 OX1]
[MEGAN]
THE STATE FAIR OPENS IN BLACKFOOT TOMORROW.
DANIELLE MULLENIX WALKED THE GROUNDS AS CREWS SET UP.
[SOURCE: KIFI package 08-27 FAIR-SETUP]
[NOTE: as delivered, no trim needed]
[PKG 1:25]
[CG: STATE FAIR OPENS TOMORROW]
CREWS SPENT THE MORNING RAISING THE LAST OF THE TENTS.
[ON CAM]
[MEGAN]
GATES OPEN AT TEN.
[#####]"""

    def test_a_package_with_intro_and_outro_passes(self):
        self.assertNotIn("R8", codes(report_for(self.PKG, TEASE)))

    def test_a_package_without_an_intro_is_an_error(self):
        no_intro = self.PKG.replace(
            "THE STATE FAIR OPENS IN BLACKFOOT TOMORROW.\n"
            "DANIELLE MULLENIX WALKED THE GROUNDS AS CREWS SET UP.\n",
            "",
        )
        self.assertIn("R8", codes_at(report_for(no_intro, TEASE), Severity.ERROR))

    def test_a_package_without_an_outro_is_a_warning(self):
        no_outro = self.PKG.replace("[ON CAM]\n[MEGAN]\nGATES OPEN AT TEN.\n", "")
        report = report_for(no_outro, TEASE)
        self.assertIn("R8", codes_at(report, Severity.WARNING))
        self.assertNotIn("R8", codes_at(report, Severity.ERROR))


class R9PackageBudgetTests(unittest.TestCase):
    def test_three_packages_in_a_block_fails(self):
        report = report_for(R8PackageTests.PKG, R8PackageTests.PKG, R8PackageTests.PKG, TEASE)
        self.assertIn("R9", codes(report))

    def test_two_packages_are_allowed(self):
        report = report_for(R8PackageTests.PKG, R8PackageTests.PKG, TEASE)
        self.assertNotIn("R9", codes(report))

    def test_zero_is_acceptable(self):
        self.assertNotIn("R9", codes(report_for(PLAIN_VO, TEASE)))

    def test_the_budget_is_configurable_per_block(self):
        report = report_for(
            R8PackageTests.PKG, R8PackageTests.PKG, TEASE, config=config_for_1a(max_pkgs=1)
        )
        self.assertIn("R9", codes(report))


class R10BumpTests(unittest.TestCase):
    def test_a_block_that_does_not_end_on_a_tease_fails(self):
        self.assertIn("R10", codes(report_for(PLAIN_VO)))

    def test_a_tease_cue_on_the_last_story_satisfies_it(self):
        self.assertNotIn("R10", codes(report_for(PLAIN_VO, TEASE)))

    def test_a_bump_element_satisfies_it(self):
        show = one_story_show(PLAIN_VO)
        bump = parse_story(TEASE.replace("[TEASE: WATER RATES]\n", ""), kind=StoryKind.BUMP)
        show.blocks[0].stories.append(bump)
        self.assertNotIn("R10", codes(validate_show(show)))

    def test_an_empty_block_fails(self):
        show = one_story_show(PLAIN_VO)
        show.blocks[0].stories.clear()
        self.assertIn("R10", codes(validate_show(show)))


class R11ShotTests(unittest.TestCase):
    def test_a_shot_change_inside_a_block_fails(self):
        other = PLAIN_VO.replace("[CAM1 OX1]", "[CAM3 OX1]")
        self.assertIn("R11", codes(report_for(PLAIN_VO, other, TEASE)))

    def test_a_flagged_exception_is_allowed(self):
        other = PLAIN_VO.replace(
            "[CAM1 OX1]", "[SHOT EXCEPTION: live shot from the council chamber]\n[CAM3 OX1]"
        )
        self.assertNotIn("R11", codes(report_for(PLAIN_VO, other, TEASE)))

    def test_the_configured_default_shot_wins_over_the_first_story(self):
        config = config_for_1a(default_shot="CAM2")
        self.assertIn("R11", codes(report_for(PLAIN_VO, TEASE, config=config)))


class R12AnchorTests(unittest.TestCase):
    def test_unconfigured_reports_info_and_enforces_nothing(self):
        report = report_for(PLAIN_VO, TEASE)
        self.assertIn("R12", codes_at(report, Severity.INFO))
        self.assertNotIn("R12", codes_at(report, Severity.ERROR))

    def test_an_anchor_outside_the_roster_fails(self):
        config = config_for_1a(anchors=("MEGAN",))
        other = PLAIN_VO.replace("[MEGAN]", "[JAY]")
        self.assertIn("R12", codes_at(report_for(other, TEASE, config=config), Severity.ERROR))

    def test_a_rostered_anchor_passes(self):
        config = config_for_1a(anchors=("MEGAN", "JAY"))
        self.assertNotIn("R12", codes_at(report_for(PLAIN_VO, TEASE, config=config), Severity.ERROR))

    def test_a_solo_block_with_two_anchors_fails(self):
        config = config_for_1a(anchors=("MEGAN", "JAY"), read_mode="solo")
        second = PLAIN_VO.replace("[MEGAN]", "[JAY]")
        self.assertIn(
            "R12", codes_at(report_for(PLAIN_VO, second, TEASE, config=config), Severity.ERROR)
        )

    def test_a_dual_block_with_one_anchor_fails(self):
        config = config_for_1a(anchors=("MEGAN", "JAY"), read_mode="dual")
        self.assertIn(
            "R12", codes_at(report_for(PLAIN_VO, TEASE, config=config), Severity.ERROR)
        )

    def test_a_dual_read_cue_counts_as_two_anchors(self):
        config = config_for_1a(anchors=("MEGAN", "JAY"), read_mode="dual")
        dual = PLAIN_VO.replace("[MEGAN]", "[MEGAN/JAY]")
        self.assertNotIn(
            "R12", codes_at(report_for(dual, TEASE, config=config), Severity.ERROR)
        )


class R13DaypartTests(unittest.TestCase):
    def test_wire_daypart_language_is_flagged(self):
        story = PLAIN_VO.replace(
            "THE COUNCIL TOOK PUBLIC COMMENT ON IT TWICE ALREADY.",
            "THE COUNCIL TAKES IT UP AGAIN TONIGHT.",
        )
        self.assertIn("R13", codes(report_for(story, TEASE)))

    def test_clean_copy_is_not_flagged(self):
        self.assertNotIn("R13", codes(report_for(PLAIN_VO, TEASE)))

    def test_a_soundbite_is_left_alone(self):
        """A source can say "tonight" -- the rule is about anchor copy."""
        story = SOT_STORY.replace(
            '"That intersection gives you plenty of warning, and we see people run it anyway."',
            '"We will have officers out there again tonight."',
        )
        self.assertNotIn("R13", codes(report_for(story, TEASE)))

    def test_the_phrase_list_is_configurable(self):
        config = dataclasses.replace(ShowConfig(), daypart_phrases=("tuesday meeting",))
        self.assertIn("R13", codes(report_for(PLAIN_VO, TEASE, config=config)))


class R14BudgetTests(unittest.TestCase):
    def test_unconfigured_reports_info_and_enforces_nothing(self):
        report = report_for(PLAIN_VO, TEASE)
        self.assertIn("R14", codes_at(report, Severity.INFO))
        self.assertNotIn("R14", codes_at(report, Severity.ERROR))

    def test_a_block_over_budget_fails(self):
        config = config_for_1a(budget_seconds=10)
        self.assertIn("R14", codes_at(report_for(PLAIN_VO, TEASE, config=config), Severity.ERROR))

    def test_a_block_under_budget_fails(self):
        config = config_for_1a(budget_seconds=600)
        self.assertIn("R14", codes_at(report_for(PLAIN_VO, TEASE, config=config), Severity.ERROR))

    def test_a_block_inside_tolerance_passes(self):
        from newscast.timing import block_seconds

        show = show_of(parse_story(PLAIN_VO), parse_story(TEASE))
        config = config_for_1a(budget_seconds=block_seconds(show.blocks[0]))
        self.assertNotIn("R14", codes_at(validate_show(show, config), Severity.ERROR))


class R15TraceabilityTests(unittest.TestCase):
    def test_a_sot_without_a_source_fails(self):
        story = SOT_STORY.replace("[SOURCE: KIFI crew 08-27 CRASH-17TH-RAW]\n", "")
        self.assertIn("R15", codes(report_for(story, TEASE)))

    def test_a_sot_without_an_editor_note_fails(self):
        story = SOT_STORY.replace(
            "[NOTE: clip 0:41 to 0:53, the sergeant on the light cycle]\n", ""
        )
        self.assertIn("R15", codes(report_for(story, TEASE)))

    def test_a_fully_sourced_sot_passes(self):
        self.assertNotIn("R15", codes(report_for(SOT_STORY, TEASE)))

    def test_a_vo_needs_no_source_cue(self):
        self.assertNotIn("R15", codes(report_for(PLAIN_VO, TEASE)))


class XCheckTests(unittest.TestCase):
    def test_x1_flags_copy_that_is_not_all_caps(self):
        story = PLAIN_VO.replace(
            "THE PROPOSAL WOULD RAISE THE BASE RATE BY ABOUT TWO DOLLARS A MONTH.",
            "The proposal would raise the base rate by about two dollars a month.",
        )
        self.assertIn("X1", codes(report_for(story, TEASE)))

    def test_x2_flags_a_video_cue_with_no_duration(self):
        story = SOT_STORY.replace("[SOT 0:12]", "[SOT]")
        self.assertIn("X2", codes(report_for(story, TEASE)))

    def test_x3_flags_a_story_with_no_camera_or_anchor(self):
        story = "[CG: POST FALLS MAN ARRESTED]\nA POST FALLS MAN IS IN CUSTODY.\n[#####]"
        found = [v for v in report_for(story, TEASE).violations if v.code == "X3"]
        self.assertEqual(len(found), 2)

    def test_x4_flags_a_missing_monitor(self):
        story = PLAIN_VO.replace("[CAM1 OX1]", "[CAM1]")
        self.assertIn("X4", codes(report_for(story, TEASE)))

    def test_x5_warns_at_three_minutes_and_errors_past_it(self):
        long_pkg = R8PackageTests.PKG.replace("[PKG 1:25]", "[PKG 2:30]")
        too_long = R8PackageTests.PKG.replace("[PKG 1:25]", "[PKG 3:30]")
        self.assertIn("X5", codes_at(report_for(long_pkg, TEASE), Severity.WARNING))
        self.assertIn("X5", codes_at(report_for(too_long, TEASE), Severity.ERROR))


class WholeShowTests(unittest.TestCase):
    def test_the_clean_rundown_has_nothing_to_fix(self):
        report = validate_show(fixture_show("show_clean.txt"))
        self.assertEqual(report.errors, [], report.format())
        self.assertEqual(report.warnings, [], report.format())
        self.assertTrue(report.ok)
        self.assertEqual(report.violation_rate, 0.0)

    def test_the_clean_rundown_still_reports_what_is_unconfigured(self):
        report = validate_show(fixture_show("show_clean.txt"))
        self.assertEqual(codes_at(report, Severity.INFO), {"R12", "R14"})

    def test_the_broken_rundown_trips_every_unconfigured_rule(self):
        report = validate_show(fixture_show("show_broken.txt"))
        expected = {f"R{n}" for n in range(1, 16)} - {"R12", "R14"}
        expected |= {"X1", "X2", "X3", "X4", "X5"}
        self.assertEqual(expected - codes(report), set())
        self.assertFalse(report.ok)

    def test_violation_rate_counts_errors_and_warnings_per_story(self):
        report = validate_show(fixture_show("show_broken.txt"))
        expected = (len(report.errors) + len(report.warnings)) / report.story_count
        self.assertAlmostEqual(report.violation_rate, expected, places=3)

    def test_only_runs_the_named_rules(self):
        report = validate_show(fixture_show("show_broken.txt"), only=["R3"])
        self.assertEqual(report.rules_run, ["R3"])
        self.assertEqual(codes(report), {"R3"})

    def test_violations_are_sorted_worst_first(self):
        report = validate_show(fixture_show("show_broken.txt"))
        severities = [v.severity for v in report.violations]
        self.assertEqual(severities, sorted(severities, reverse=True))


if __name__ == "__main__":
    unittest.main()
