"""Rule engine tests (CLAUDE.md §5).

Each rule gets a script that breaks it and a script that does not. The two show
fixtures then check the whole engine end to end: show_clean.txt must be silent,
show_broken.txt must trip every rule.

Targeted tests run against bare_config(), which strips the per-block shot,
anchor and budget pattern so a script written to exercise one rule does not
also trip R11, R12 or R14. The pattern itself is tested separately.
"""

import dataclasses
import unittest

from newscast.config import UNSET, ShowConfig
from newscast.markup import parse_story
from newscast.model import StoryKind
from newscast.rules import Severity, all_rules
from newscast.validator import validate_show
from tests.helpers import (
    bare_config,
    codes,
    codes_at,
    fixture,
    fixture_show,
    one_story_show,
    show_of,
)

# A VO leg and a SOT play over the monitor before it comes back, so this story
# has to park the monitor in D (§11.14).
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

# One video file over the monitor, so no D.
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

class Bump(str):
    """A bump script. Subclassing str keeps the kind attached through the
    .replace() calls the tests use to vary anchor and CG."""

    def replace(self, *args, **kwargs) -> "Bump":
        return Bump(str.replace(self, *args, **kwargs))


BUMP = Bump("""[CAM1 OX1]
[CG: NEXT: WATER RATES]
[MEGAN]
STILL AHEAD -- THE WATER RATE PROPOSAL IN FRONT OF THE CITY COUNCIL.
[#####]""")

PKG_STORY = """[CAM1 OX1]
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


def config_for_1a(**kwargs) -> ShowConfig:
    """bare_config with the given settings put back on block 1A."""
    base = bare_config()
    blocks = tuple(
        dataclasses.replace(b, **kwargs) if b.name == "1A" else b for b in base.blocks
    )
    return dataclasses.replace(base, blocks=blocks)


def report_for(*scripts, config=None, kinds=None, only=None):
    stories = []
    for i, script in enumerate(scripts):
        kind = (kinds or {}).get(i, StoryKind.NEWS)
        if kind is StoryKind.NEWS and isinstance(script, Bump):
            kind = StoryKind.BUMP
        stories.append(parse_story(script, slug=f"S{i + 1}", kind=kind))
    return validate_show(show_of(*stories), config or bare_config(), only=only)


class RegistryTests(unittest.TestCase):
    def test_every_spec_rule_is_registered(self):
        registered = {r.code for r in all_rules()}
        self.assertTrue({f"R{n}" for n in range(1, 16)} <= registered)

    def test_rules_are_ordered_r_then_x_numerically(self):
        listed = [r.code for r in all_rules()]
        self.assertEqual(listed[:3], ["R1", "R2", "R3"])
        self.assertEqual(listed[14:16], ["R15", "X1"])


class R2MonitorTests(unittest.TestCase):
    """§11.14: park the monitor in D when two video files play over it."""

    def test_the_five_spec_examples_all_agree_with_the_rule(self):
        for name in (
            "example_rdr.txt",
            "example_vo.txt",
            "example_sot.txt",
            "example_sotvo.txt",
            "example_pkg.txt",
        ):
            with self.subTest(name):
                report = report_for(fixture(name), only=["R2"])
                self.assertEqual(report.violations, [], report.format())

    def test_two_files_over_the_monitor_needs_the_d_park(self):
        broken = SOT_STORY.replace("[CAM1 OX1 - D]", "[CAM1 OX1]")
        self.assertIn("R2", codes(report_for(broken, BUMP)))

    def test_two_files_over_the_monitor_needs_back_to_d(self):
        broken = SOT_STORY.replace("[ON CAM - BACK TO D]", "[ON CAM]")
        self.assertIn("R2", codes(report_for(broken, BUMP)))

    def test_one_file_over_the_monitor_needs_neither(self):
        self.assertNotIn("R2", codes(report_for(PLAIN_VO, BUMP)))

    def test_a_package_alone_does_not_need_d(self):
        """A PKG is one video file, so it usually does not need D (§11.13)."""
        self.assertNotIn("R2", codes(report_for(PKG_STORY, BUMP)))

    def test_two_vo_legs_over_one_monitor_do_need_d(self):
        """Phil's own example: monitor, VO, VO, then back to the monitor."""
        two_legs = """[CAM1 OX1]
[MEGAN]
[CG: SNAKE RIVER FLOWS DROP]
FLOWS ON THE SNAKE ARE DOWN AGAIN THIS WEEK.
[VO]
THE BUREAU CUT RELEASES FROM PALISADES ON MONDAY.
[CONT VO]
IRRIGATORS SAY THEY EXPECTED IT AND HAVE FINISHED THEIR LAST WATERING.
[ON CAM]
THE NEXT ADJUSTMENT COMES IN TWO WEEKS.
[#####]"""
        self.assertIn("R2", codes(report_for(two_legs, BUMP)))

    def test_a_story_that_never_returns_to_camera_never_needs_d(self):
        sotvo = SOT_STORY.replace("[ON CAM - BACK TO D]", "[CONT VO]").replace(
            "[CAM1 OX1 - D]", "[CAM1 OX1]"
        )
        self.assertNotIn("R2", codes(report_for(sotvo, BUMP)))


class R1BackToBackDTests(unittest.TestCase):
    def test_two_d_stories_back_to_back_is_an_error(self):
        self.assertIn("R1", codes(report_for(SOT_STORY, SOT_STORY, BUMP)))

    def test_a_non_d_story_between_them_is_fine(self):
        self.assertNotIn("R1", codes(report_for(SOT_STORY, PLAIN_VO, SOT_STORY, BUMP)))

    def test_two_packages_back_to_back_are_fine(self):
        """Neither parks the monitor in D, so there is nothing to overwrite."""
        self.assertNotIn("R1", codes(report_for(PKG_STORY, PKG_STORY, BUMP)))

    def test_the_documented_mitigation_clears_it(self):
        mitigated = SOT_STORY.replace(
            "[CAM1 OX1 - D]", "[CAM1 OX1 - D]\n[MONITOR PLACEHOLDER]"
        ).replace("[ON CAM - BACK TO D]", "[MONITOR DUPE]\n[ON CAM - BACK TO D]")
        self.assertNotIn("R1", codes(report_for(SOT_STORY, mitigated, BUMP)))

    def test_placeholder_without_the_duplicate_is_still_an_error(self):
        half = SOT_STORY.replace(
            "[CAM1 OX1 - D]", "[CAM1 OX1 - D]\n[MONITOR PLACEHOLDER]"
        )
        self.assertIn("R1", codes(report_for(SOT_STORY, half, BUMP)))


class R3TerminatorTests(unittest.TestCase):
    def test_missing_terminator(self):
        self.assertIn("R3", codes(report_for(PLAIN_VO.replace("[#####]", ""), BUMP)))

    def test_present_terminator(self):
        self.assertNotIn("R3", codes(report_for(PLAIN_VO, BUMP)))


class R4CGTests(unittest.TestCase):
    def test_segment_without_a_cg(self):
        stripped = PLAIN_VO.replace("[CG: COUNCIL TAKES UP WATER RATES]\n", "")
        self.assertIn("R4", codes(report_for(stripped, BUMP)))

    def test_explicit_exemption_is_accepted(self):
        exempt = PLAIN_VO.replace(
            "[CG: COUNCIL TAKES UP WATER RATES]", "[NO CG: full-screen graphic instead]"
        )
        self.assertNotIn("R4", codes(report_for(exempt, BUMP)))

    def test_a_bump_needs_a_cg_of_its_own(self):
        """Bumps carry a bump CG (§11.15)."""
        no_cg = BUMP.replace("[CG: NEXT: WATER RATES]\n", "")
        self.assertIn("R4", codes(report_for(PLAIN_VO, no_cg)))

    def test_weather_carries_no_written_cg(self):
        """The weather CG is the weather anchor's prefilled name and title."""
        weather = """[WX GFX]
[JEFF]
THAT WIND ARRIVES AROUND THREE THIS AFTERNOON.
[#####]"""
        report = report_for(
            PLAIN_VO, weather, BUMP, kinds={1: StoryKind.WEATHER}
        )
        self.assertNotIn("R4", codes(report))


class R5CGLengthTests(unittest.TestCase):
    LONG = (
        "[CG: THE IDAHO FALLS FARMERS MARKET IS CLOSING DOWN EARLY BECAUSE OF THE "
        "WIND AND PEOPLE ARE NOT HAPPY ABOUT IT]"
    )

    def test_a_sentence_length_cg_fails(self):
        story = PLAIN_VO.replace("[CG: COUNCIL TAKES UP WATER RATES]", self.LONG)
        self.assertIn("R5", codes(report_for(story, BUMP)))

    def test_a_slug_length_cg_passes(self):
        self.assertNotIn("R5", codes_at(report_for(PLAIN_VO, BUMP), Severity.ERROR))

    def test_the_ceiling_is_thirty_nine_characters(self):
        self.assertEqual(ShowConfig().effective_cg_ceiling(), (39, False))

    def test_a_cg_one_over_the_ceiling_fails(self):
        forty = "[CG: " + "A" * 40 + "]"
        story = PLAIN_VO.replace("[CG: COUNCIL TAKES UP WATER RATES]", forty)
        self.assertIn("R5", codes_at(report_for(story, BUMP), Severity.ERROR))

    def test_a_cg_at_the_ceiling_passes(self):
        exact = "[CG: " + "A" * 39 + "]"
        story = PLAIN_VO.replace("[CG: COUNCIL TAKES UP WATER RATES]", exact)
        self.assertNotIn("R5", codes_at(report_for(story, BUMP), Severity.ERROR))

    def test_bump_cgs_are_not_measured_against_the_lower_third_ceiling(self):
        """A bump CG is a different graphic with a different format (§11.15)."""
        long_bump = BUMP.replace(
            "[CG: NEXT: WATER RATES]", "[CG: " + "A" * 80 + "]"
        )
        report = report_for(PLAIN_VO, long_bump)
        self.assertNotIn("R5", codes_at(report, Severity.ERROR))
        self.assertIn("R5", codes_at(report, Severity.INFO))

    def test_a_configured_bump_ceiling_is_enforced(self):
        config = dataclasses.replace(bare_config(), bump_cg_char_ceiling=20)
        long_bump = BUMP.replace(
            "[CG: NEXT: WATER RATES]", "[CG: " + "A" * 80 + "]"
        )
        report = report_for(PLAIN_VO, long_bump, config=config)
        self.assertIn("R5", codes_at(report, Severity.ERROR))

    def test_a_lower_case_cg_is_a_warning_not_an_error(self):
        story = PLAIN_VO.replace(
            "[CG: COUNCIL TAKES UP WATER RATES]", "[CG: Council takes up water rates]"
        )
        report = report_for(story, BUMP)
        self.assertIn("R5", codes_at(report, Severity.WARNING))
        self.assertNotIn("R5", codes_at(report, Severity.ERROR))


class R6ReaderTests(unittest.TestCase):
    SHORT_RDR = """[CAM1 OX1]
[CG: MARKET CLOSES AT 2 PM]
[NOTE: no video available, market would not allow a camera on the lot]
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
        self.assertIn("R6", codes(report_for(long_rdr, BUMP)))

    def test_a_short_justified_reader_passes(self):
        self.assertNotIn("R6", codes(report_for(self.SHORT_RDR, BUMP)))

    def test_a_reader_must_say_why_it_is_a_reader(self):
        """§11.18 — an RDR justifies itself."""
        unjustified = self.SHORT_RDR.replace(
            "[NOTE: no video available, market would not allow a camera on the lot]\n", ""
        )
        self.assertIn("R6", codes(report_for(unjustified, BUMP)))

    def test_justification_can_be_switched_off(self):
        config = dataclasses.replace(bare_config(), rdr_requires_justification=False)
        unjustified = self.SHORT_RDR.replace(
            "[NOTE: no video available, market would not allow a camera on the lot]\n", ""
        )
        self.assertNotIn("R6", codes(report_for(unjustified, BUMP, config=config)))

    def test_a_bump_is_not_held_to_the_reader_rule(self):
        self.assertNotIn("R6", codes(report_for(PLAIN_VO, BUMP)))


class R7VOTests(unittest.TestCase):
    """§11.16 — 20-45 seconds is a range, so this warns rather than errors."""

    def test_a_short_vo_warns(self):
        short = """[CAM1 OX1]
[MEGAN]
[VO]
[CG: NEW MURAL DOWNTOWN]
A NEW MURAL WENT UP DOWNTOWN.
[#####]"""
        report = report_for(short, BUMP)
        self.assertIn("R7", codes_at(report, Severity.WARNING))
        self.assertNotIn("R7", codes_at(report, Severity.ERROR))

    def test_a_typical_vo_passes(self):
        self.assertNotIn("R7", codes(report_for(PLAIN_VO, BUMP)))

    def test_a_short_vo_inside_a_composite_is_not_flagged(self):
        self.assertNotIn("R7", codes(report_for(SOT_STORY, BUMP)))


class R8PackageTests(unittest.TestCase):
    def test_a_package_with_intro_and_outro_passes(self):
        self.assertNotIn("R8", codes(report_for(PKG_STORY, BUMP)))

    def test_a_package_without_an_intro_is_an_error(self):
        no_intro = PKG_STORY.replace(
            "THE STATE FAIR OPENS IN BLACKFOOT TOMORROW.\n"
            "DANIELLE MULLENIX WALKED THE GROUNDS AS CREWS SET UP.\n",
            "",
        )
        self.assertIn("R8", codes_at(report_for(no_intro, BUMP), Severity.ERROR))

    def test_a_package_without_an_outro_is_a_warning(self):
        no_outro = PKG_STORY.replace("[ON CAM]\n[MEGAN]\nGATES OPEN AT TEN.\n", "")
        report = report_for(no_outro, BUMP)
        self.assertIn("R8", codes_at(report, Severity.WARNING))
        self.assertNotIn("R8", codes_at(report, Severity.ERROR))


class R9PackageBudgetTests(unittest.TestCase):
    def test_three_packages_in_a_block_fails(self):
        self.assertIn("R9", codes(report_for(PKG_STORY, PKG_STORY, PKG_STORY, BUMP)))

    def test_two_packages_are_allowed(self):
        self.assertNotIn("R9", codes(report_for(PKG_STORY, PKG_STORY, BUMP)))

    def test_zero_is_acceptable(self):
        self.assertNotIn("R9", codes(report_for(PLAIN_VO, BUMP)))

    def test_the_budget_is_configurable_per_block(self):
        config = config_for_1a(max_pkgs=1)
        self.assertIn("R9", codes(report_for(PKG_STORY, PKG_STORY, BUMP, config=config)))


class R10BumpTests(unittest.TestCase):
    def test_a_block_that_does_not_end_on_a_bump_fails(self):
        self.assertIn("R10", codes(report_for(PLAIN_VO)))

    def test_a_bump_element_satisfies_it(self):
        """Bumps are their own rundown element (§11.11)."""
        self.assertNotIn("R10", codes(report_for(PLAIN_VO, BUMP)))

    def test_an_empty_block_fails(self):
        show = one_story_show(PLAIN_VO)
        show.blocks[0].stories.clear()
        self.assertIn("R10", codes(validate_show(show, bare_config())))


class R11ShotTests(unittest.TestCase):
    """§11.17 — the shot is the camera and the over-shoulder together."""

    def test_a_camera_change_inside_a_block_fails(self):
        other = PLAIN_VO.replace("[CAM1 OX1]", "[CAM3 OX1]")
        self.assertIn("R11", codes(report_for(PLAIN_VO, other, BUMP)))

    def test_the_same_camera_on_a_different_monitor_is_a_different_shot(self):
        other = PLAIN_VO.replace("[CAM1 OX1]", "[CAM1 OX2]")
        self.assertIn("R11", codes(report_for(PLAIN_VO, other, BUMP)))

    def test_a_flagged_exception_is_allowed(self):
        other = PLAIN_VO.replace(
            "[CAM1 OX1]", "[SHOT EXCEPTION: live shot from the council chamber]\n[CAM3 OX1]"
        )
        self.assertNotIn("R11", codes(report_for(PLAIN_VO, other, BUMP)))

    def test_the_configured_default_shot_wins_over_the_first_story(self):
        config = config_for_1a(default_shot="CAM2 OX3")
        self.assertIn("R11", codes(report_for(PLAIN_VO, BUMP, config=config)))

    def test_the_a_block_may_open_on_its_own_shot(self):
        """§11.3 — the A blocks open on a different shot for the double read."""
        config = config_for_1a(default_shot="CAM2 OX3", open_shot="CAM3 OX2")
        opener = PLAIN_VO.replace("[CAM1 OX1]", "[CAM3 OX2]")
        rest = PLAIN_VO.replace("[CAM1 OX1]", "[CAM2 OX3]")
        bump = BUMP.replace("[CAM1 OX1]", "[CAM2 OX3]")
        self.assertNotIn("R11", codes(report_for(opener, rest, bump, config=config)))

    def test_only_the_first_story_may_use_the_open_shot(self):
        config = config_for_1a(default_shot="CAM2 OX3", open_shot="CAM3 OX2")
        rest = PLAIN_VO.replace("[CAM1 OX1]", "[CAM2 OX3]")
        late = PLAIN_VO.replace("[CAM1 OX1]", "[CAM3 OX2]")
        bump = BUMP.replace("[CAM1 OX1]", "[CAM2 OX3]")
        self.assertIn("R11", codes(report_for(rest, late, bump, config=config)))

    def test_weather_is_at_the_wall_not_the_block_shot(self):
        config = config_for_1a(default_shot="CAM1 OX1")
        weather = "[WX GFX]\n[JEFF]\nTHAT WIND ARRIVES AROUND THREE.\n[#####]"
        report = report_for(
            PLAIN_VO, weather, BUMP, config=config, kinds={1: StoryKind.WEATHER}
        )
        self.assertNotIn("R11", codes(report))


class R12AnchorTests(unittest.TestCase):
    """§11.2 — Jeff and Megan open, Jeff breaks for weather, Megan carries."""

    def test_unconfigured_reports_info_and_enforces_nothing(self):
        report = report_for(PLAIN_VO, BUMP)
        self.assertIn("R12", codes_at(report, Severity.INFO))
        self.assertNotIn("R12", codes_at(report, Severity.ERROR))

    def test_an_anchor_outside_the_roster_fails(self):
        config = config_for_1a(anchors=("MEGAN",))
        other = PLAIN_VO.replace("[MEGAN]", "[DANIELLE]")
        self.assertIn("R12", codes_at(report_for(other, BUMP, config=config), Severity.ERROR))

    def test_the_show_opens_on_a_double_read(self):
        config = config_for_1a(
            anchors=("JEFF", "MEGAN"), read_mode="open_dual", solo_anchor="MEGAN"
        )
        self.assertIn(
            "R12", codes_at(report_for(PLAIN_VO, BUMP, config=config), Severity.ERROR)
        )

    def test_megan_carries_the_a_block_after_the_open(self):
        config = config_for_1a(
            anchors=("JEFF", "MEGAN"), read_mode="open_dual", solo_anchor="MEGAN"
        )
        opener = PLAIN_VO.replace("[MEGAN]", "[JEFF/MEGAN]")
        jeff = PLAIN_VO.replace("[MEGAN]", "[JEFF]")
        self.assertIn(
            "R12", codes_at(report_for(opener, jeff, BUMP, config=config), Severity.ERROR)
        )

    def test_a_correct_a_block_passes(self):
        config = config_for_1a(
            anchors=("JEFF", "MEGAN"), read_mode="open_dual", solo_anchor="MEGAN"
        )
        opener = PLAIN_VO.replace("[MEGAN]", "[JEFF/MEGAN]")
        self.assertNotIn(
            "R12",
            codes_at(report_for(opener, PLAIN_VO, BUMP, config=config), Severity.ERROR),
        )

    def test_jeff_reads_the_weather_tease_closing_the_b_block(self):
        config = config_for_1a(
            anchors=("MEGAN", "JEFF"),
            read_mode="solo",
            solo_anchor="MEGAN",
            closing_anchor="JEFF",
        )
        self.assertIn(
            "R12", codes_at(report_for(PLAIN_VO, BUMP, config=config), Severity.ERROR)
        )

    def test_a_correct_b_block_passes(self):
        config = config_for_1a(
            anchors=("MEGAN", "JEFF"),
            read_mode="solo",
            solo_anchor="MEGAN",
            closing_anchor="JEFF",
        )
        jeff_bump = BUMP.replace("[MEGAN]", "[JEFF]")
        self.assertNotIn(
            "R12",
            codes_at(report_for(PLAIN_VO, jeff_bump, config=config), Severity.ERROR),
        )

    def test_a_dual_block_with_one_anchor_fails(self):
        config = config_for_1a(anchors=("JEFF", "MEGAN"), read_mode="dual")
        self.assertIn(
            "R12", codes_at(report_for(PLAIN_VO, BUMP, config=config), Severity.ERROR)
        )

    def test_a_dual_read_cue_counts_as_two_anchors(self):
        config = config_for_1a(anchors=("JEFF", "MEGAN"), read_mode="dual")
        dual = PLAIN_VO.replace("[MEGAN]", "[MEGAN/JEFF]")
        self.assertNotIn(
            "R12", codes_at(report_for(dual, BUMP, config=config), Severity.ERROR)
        )


class R13DaypartTests(unittest.TestCase):
    def test_wire_daypart_language_is_flagged(self):
        story = PLAIN_VO.replace(
            "THE COUNCIL TOOK PUBLIC COMMENT ON IT TWICE ALREADY.",
            "THE COUNCIL TAKES IT UP AGAIN TONIGHT.",
        )
        self.assertIn("R13", codes(report_for(story, BUMP)))

    def test_clean_copy_is_not_flagged(self):
        self.assertNotIn("R13", codes(report_for(PLAIN_VO, BUMP)))

    def test_a_soundbite_is_left_alone(self):
        story = SOT_STORY.replace(
            '"That intersection gives you plenty of warning, and we see people run it anyway."',
            '"We will have officers out there again tonight."',
        )
        self.assertNotIn("R13", codes(report_for(story, BUMP)))


class R14BudgetTests(unittest.TestCase):
    """§11.1 — the A blocks carry a range; the half hours need break and
    weather allowances before they can be reconciled."""

    def test_the_half_hour_clock_is_configured(self):
        self.assertEqual(ShowConfig().half_budget_seconds, {1: 1675.0, 2: 1920.0})

    def test_the_a_blocks_carry_a_five_to_seven_minute_range(self):
        config = ShowConfig()
        self.assertEqual(config.block(1, "A").budget_range, (300.0, 420.0))
        self.assertEqual(config.block(2, "A").budget_range, (300.0, 420.0))

    def test_a_block_under_its_range_fails(self):
        config = config_for_1a(budget_range=(300.0, 420.0))
        self.assertIn("R14", codes_at(report_for(PLAIN_VO, BUMP, config=config), Severity.ERROR))

    def test_a_block_over_its_range_fails(self):
        config = config_for_1a(budget_range=(1.0, 5.0))
        self.assertIn("R14", codes_at(report_for(PLAIN_VO, BUMP, config=config), Severity.ERROR))

    def test_a_block_inside_its_range_passes(self):
        from newscast.timing import block_seconds

        show = show_of(parse_story(PLAIN_VO), parse_story(BUMP, kind=StoryKind.BUMP))
        actual = block_seconds(show.blocks[0])
        config = config_for_1a(budget_range=(actual - 5, actual + 5))
        self.assertNotIn("R14", codes_at(validate_show(show, config), Severity.ERROR))

    def test_the_half_hour_check_waits_on_break_and_weather_times(self):
        report = report_for(PLAIN_VO, BUMP)
        self.assertIn("R14", codes_at(report, Severity.INFO))

    def test_the_half_hour_is_checked_once_those_are_known(self):
        config = dataclasses.replace(
            bare_config(), break_seconds=120.0, weather_seconds=180.0
        )
        report = report_for(PLAIN_VO, BUMP, config=config)
        self.assertIn("R14", codes_at(report, Severity.ERROR))
        self.assertNotIn("R14", codes_at(report, Severity.INFO))


class R15TraceabilityTests(unittest.TestCase):
    def test_a_sot_without_a_source_fails(self):
        story = SOT_STORY.replace("[SOURCE: KIFI crew 08-27 CRASH-17TH-RAW]\n", "")
        self.assertIn("R15", codes(report_for(story, BUMP)))

    def test_a_sot_without_an_editor_note_fails(self):
        story = SOT_STORY.replace(
            "[NOTE: clip 0:41 to 0:53, the sergeant on the light cycle]\n", ""
        )
        self.assertIn("R15", codes(report_for(story, BUMP)))

    def test_a_fully_sourced_sot_passes(self):
        self.assertNotIn("R15", codes(report_for(SOT_STORY, BUMP)))

    def test_a_vo_needs_no_source_cue(self):
        self.assertNotIn("R15", codes(report_for(PLAIN_VO, BUMP)))


class XCheckTests(unittest.TestCase):
    def test_x1_flags_copy_that_is_not_all_caps(self):
        story = PLAIN_VO.replace(
            "THE PROPOSAL WOULD RAISE THE BASE RATE BY ABOUT TWO DOLLARS A MONTH.",
            "The proposal would raise the base rate by about two dollars a month.",
        )
        self.assertIn("X1", codes(report_for(story, BUMP)))

    def test_x2_flags_a_video_cue_with_no_duration(self):
        story = SOT_STORY.replace("[SOT 0:12]", "[SOT]")
        self.assertIn("X2", codes(report_for(story, BUMP)))

    def test_x3_flags_a_story_with_no_camera_or_anchor(self):
        story = "[CG: POST FALLS MAN ARRESTED]\nA POST FALLS MAN IS IN CUSTODY.\n[#####]"
        found = [v for v in report_for(story, BUMP).violations if v.code == "X3"]
        self.assertEqual(len(found), 2)

    def test_x4_flags_a_missing_monitor(self):
        story = PLAIN_VO.replace("[CAM1 OX1]", "[CAM1]")
        self.assertIn("X4", codes(report_for(story, BUMP)))

    def test_x5_warns_at_two_minutes_and_errors_past_three(self):
        long_pkg = PKG_STORY.replace("[PKG 1:25]", "[PKG 2:30]")
        too_long = PKG_STORY.replace("[PKG 1:25]", "[PKG 3:30]")
        self.assertIn("X5", codes_at(report_for(long_pkg, BUMP), Severity.WARNING))
        self.assertIn("X5", codes_at(report_for(too_long, BUMP), Severity.ERROR))


class WholeShowTests(unittest.TestCase):
    """End to end, against the real ShowConfig — shots, anchors and budgets."""

    def test_the_clean_rundown_has_nothing_to_fix(self):
        report = validate_show(fixture_show("show_clean.txt"))
        self.assertEqual(report.errors, [], report.format())
        self.assertEqual(report.warnings, [], report.format())
        self.assertTrue(report.ok)

    def test_the_clean_rundown_still_reports_what_is_unconfigured(self):
        report = validate_show(fixture_show("show_clean.txt"))
        self.assertEqual(codes_at(report, Severity.INFO), {"R5", "R14"})

    def test_the_clean_a_blocks_are_inside_their_range(self):
        from newscast.timing import block_seconds

        show = fixture_show("show_clean.txt")
        for half in (1, 2):
            with self.subTest(half=half):
                seconds = block_seconds(show.block(half, "A"))
                self.assertGreaterEqual(seconds, 300.0)
                self.assertLessEqual(seconds, 420.0)

    def test_the_broken_rundown_trips_every_rule(self):
        report = validate_show(fixture_show("show_broken.txt"))
        expected = {f"R{n}" for n in range(1, 16)} | {f"X{n}" for n in range(1, 6)}
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
