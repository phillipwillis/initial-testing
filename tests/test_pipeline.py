"""Scoring, culling and assembly (§6 phases 1, 2 and 4)."""

import unittest
from datetime import datetime

from newscast.assemble import assemble_story, shorten_cg
from newscast.collect import _is_sport, cull
from newscast.config import ShowConfig
from newscast.scoring import compile_words, grade_pool, similarity, story_key
from newscast.wires.cnn_script import parse_wire_script
from newscast.wires.stub import ContentType, StoryStub

NOW = datetime(2026, 8, 31, 12, 0)


def stub(slug, **kwargs):
    kwargs.setdefault("timestamp", NOW)
    kwargs.setdefault("content_type", (ContentType.SCRIPT,))
    return StoryStub(slug=slug, **kwargs)


class WordMatchingTests(unittest.TestCase):
    """A substring match for "nfl" fired inside the Spanish word "conflicto"
    and culled a story about US and Iran trading attacks as sports."""

    def test_a_word_does_not_match_inside_another_word(self):
        pattern = compile_words(("nfl", "war", "dead", "tax"))
        self.assertFalse(pattern.search("un conflicto perjudicial"))
        self.assertFalse(pattern.search("moving toward a warm evening"))
        self.assertFalse(pattern.search("the deadline passed"))
        self.assertFalse(pattern.search("he called a taxi"))

    def test_whole_words_still_match_with_inflections(self):
        pattern = compile_words(("war", "closure"))
        self.assertTrue(pattern.search("the war continues"))
        self.assertTrue(pattern.search("two closures today"))

    def test_a_starred_entry_is_a_stem(self):
        pattern = compile_words(("evacuat*",))
        for word in ("evacuate", "evacuated", "evacuation", "evacuations"):
            with self.subTest(word):
                self.assertTrue(pattern.search(f"the {word} order"))

    def test_a_stem_still_respects_the_leading_boundary(self):
        self.assertFalse(compile_words(("rest*",)).search("arrest warrant"))


class SportsTests(unittest.TestCase):
    def test_the_iran_story_is_not_sports(self):
        self.assertFalse(
            _is_sport(stub("EE.UU. e Irán intercambian ataques", teaser="un conflicto"))
        )

    def test_actual_sports_are_sports(self):
        self.assertTrue(_is_sport(stub("Aaron Donald returns to the Rams")))
        self.assertTrue(_is_sport(stub("NFL season opens Thursday")))


class ScoringTests(unittest.TestCase):
    def test_the_local_road_closure_beats_the_distant_explosion(self):
        """§0's own example: it changes what the viewer does today."""
        pool = [
            stub("Idaho Falls bridge closure snarls traffic",
                 teaser="Crews shut the bridge in Idaho Falls"),
            stub("Indonesian chemical plant explosion kills 4",
                 teaser="An explosion at a plant", footage_type="PKG",
                 content_type=(ContentType.VIDEO,)),
        ]
        ranked = grade_pool(pool, now=NOW)
        self.assertIn("Idaho Falls", ranked[0].slug)

    def test_grading_is_comparative_not_absolute(self):
        """Corroboration is measured against the pool, so the same stub scores
        differently in different company."""
        twin = stub("Storm floods downtown", teaser="Flooding downtown today")
        alone = grade_pool([twin], now=NOW)[0]
        crowded = grade_pool(
            [twin, stub("Storm floods downtown streets", teaser="Downtown flooding today")],
            now=NOW,
        )[0]
        self.assertGreater(crowded.corroboration, alone.corroboration)

    def test_fresher_wins_all_else_equal(self):
        old = stub("Council meets on water rates", timestamp=datetime(2026, 8, 30, 6, 0))
        new = stub("Council meets on water rates today",
                   timestamp=datetime(2026, 8, 31, 11, 30))
        ranked = grade_pool([old, new], now=NOW)
        self.assertGreater(ranked[0].freshness, ranked[-1].freshness)

    def test_an_empty_pool_grades_to_nothing(self):
        self.assertEqual(grade_pool([]), [])


class DuplicateTests(unittest.TestCase):
    """CNN files one row per speaker, so one story arrives several times."""

    def test_the_slug_convention_identifies_the_story(self):
        self.assertEqual(
            story_key(stub("CA: MASS SHOOTING ARREST/FBI-$20K REWARD")),
            "mass shooting arrest",
        )

    def test_two_speakers_on_one_story_are_the_same_story(self):
        self.assertEqual(
            similarity(
                stub("CA: MASS SHOOTING ARREST/FBI-$20K REWARD"),
                stub("CA: MASS SHOOTING ARREST/FBI-TIPS HELPED SOLVE CASE"),
            ),
            1.0,
        )

    def test_a_truncated_slug_still_matches(self):
        """CNN clips the story half when the speaker half is long."""
        self.assertEqual(
            similarity(
                stub("CA: MASS SHOOTING ARREST/FBI-$20K REWARD"),
                stub("CA: MASS SHOOTING ARRES/ATTY- TERRORIZED THE PARTY"),
            ),
            1.0,
        )

    def test_different_stories_from_one_state_are_not_duplicates(self):
        self.assertLess(
            similarity(
                stub("CA: MASS SHOOTING ARREST/FBI-$20K REWARD"),
                stub("CA: RARE TRIPLETS/DOCTOR-ALL THE SAME SEX"),
            ),
            0.45,
        )

    def test_culling_keeps_one_and_says_which(self):
        pool = [
            stub("CA: MASS SHOOTING ARREST/FBI-$20K REWARD", footage_type="SOT"),
            stub("CA: MASS SHOOTING ARREST/ATTY-TERRORIZED", footage_type="SOT"),
            stub("Council raises water rates", footage_type="VO"),
        ]
        result = cull(grade_pool(pool, now=NOW), keep=5)
        self.assertEqual(len(result.kept), 2)
        self.assertTrue(any("same story as" in reason for _, reason in result.dropped))


class CullTests(unittest.TestCase):
    def test_material_with_nothing_to_build_from_is_dropped(self):
        result = cull(grade_pool([stub("Photo of a cat", content_type=())], now=NOW))
        self.assertEqual(result.kept, [])
        self.assertIn("nothing to build from", result.dropped[0][1])

    def test_the_package_budget_is_enforced(self):
        """Distinct stories, or deduplication drops them before the budget can."""
        pool = [
            stub(slug, footage_type="PKG", content_type=(ContentType.VIDEO,))
            for slug in (
                "State fair opens in Blackfoot tomorrow",
                "Hospital breaks ground on a new tower",
                "Snowpack survey finds a dry winter ahead",
                "Guitar found in an attic sells at auction",
            )
        ]
        result = cull(grade_pool(pool, now=NOW), keep=10, max_packages=2)
        self.assertEqual(len(result.kept), 2)
        self.assertTrue(any("package budget" in r for _, r in result.dropped))

    def test_duplicates_are_removed_before_the_package_budget(self):
        """Otherwise three soundbites off one story spend the whole budget."""
        pool = [
            stub("CA: MASS SHOOTING ARREST/FBI-REWARD", footage_type="PKG",
                 content_type=(ContentType.VIDEO,)),
            stub("CA: MASS SHOOTING ARREST/ATTY-PARTY", footage_type="PKG",
                 content_type=(ContentType.VIDEO,)),
            stub("State fair opens in Blackfoot", footage_type="PKG",
                 content_type=(ContentType.VIDEO,)),
        ]
        result = cull(grade_pool(pool, now=NOW), keep=10, max_packages=2)
        self.assertEqual(len(result.kept), 2)
        self.assertFalse(any("package budget" in r for _, r in result.dropped))

    def test_nothing_is_dropped_silently(self):
        pool = [stub(f"Story {n}", footage_type="VO") for n in range(6)]
        result = cull(grade_pool(pool, now=NOW), keep=2)
        self.assertEqual(len(result.kept) + len(result.dropped), len(pool))
        self.assertTrue(all(reason for _, reason in result.dropped))


class CGTests(unittest.TestCase):
    def test_a_short_cg_is_left_alone(self):
        text, trimmed = shorten_cg("BRIDGE CLOSED UNTIL 6 PM", 39)
        self.assertEqual(text, "BRIDGE CLOSED UNTIL 6 PM")
        self.assertFalse(trimmed)

    def test_a_long_wire_title_is_trimmed_at_a_word_boundary(self):
        text, trimmed = shorten_cg("CA: RARE TRIPLETS/DOCTOR-ALL THE SAME SEX", 39)
        self.assertTrue(trimmed)
        self.assertLessEqual(len(text), 39)
        self.assertFalse(text.endswith(" "))

    def test_cgs_come_out_in_caps(self):
        self.assertEqual(shorten_cg("bridge closed", 39)[0], "BRIDGE CLOSED")


class AssemblyTests(unittest.TestCase):
    VO_WIRE = """Title: COUNCIL RAISES WATER RATES
Footage Type: VO
--LEAD IN--
THE CITY COUNCIL VOTED TO RAISE WATER RATES.
--VO SCRIPT--
THE INCREASE ADDS ABOUT TWO DOLLARS A MONTH TO A TYPICAL BILL.
STAFF SAY THE MONEY REPLACES THE OLDEST LINES ON THE NORTH SIDE.
--TAG--
THE NEW RATE STARTS IN OCTOBER.
-----END-----"""

    def test_the_result_is_parseable_markup(self):
        wire = parse_wire_script(self.VO_WIRE)
        assembly = assemble_story(wire, stub("COUNCIL RAISES WATER RATES"))
        self.assertTrue(assembly.story.terminated)
        self.assertIn("[#####]", assembly.markup)

    def test_the_configured_shot_and_anchor_are_used(self):
        wire = parse_wire_script(self.VO_WIRE)
        assembly = assemble_story(
            wire, stub("X"), shot="CAM2 OX3", anchor="JEFF"
        )
        self.assertIn("[CAM2 OX3]", assembly.markup)
        self.assertIn("[JEFF]", assembly.markup)

    def test_a_soundbite_story_parks_the_monitor_in_d(self):
        """Two video files play over the monitor, so §5 R2 applies."""
        wire = parse_wire_script(
            self.VO_WIRE.replace("--TAG--", "--SOT --\nWe had to act.\n--TAG--")
        )
        assembly = assemble_story(wire, stub("X"))
        self.assertIn("- D", assembly.markup)
        self.assertIn("BACK TO D", assembly.markup)

    def test_a_package_carries_its_source_and_editor_note(self):
        """§5 R15 — the editor needs the source and what to pull."""
        wire = parse_wire_script(
            "Title: FAIR OPENS\nFootage Type: PKG\nTRT: 01:25\n"
            "--LEAD IN--\nTHE FAIR OPENS TOMORROW.\n"
            "--REPORTER PKG-AS FOLLOWS--\nCREWS RAISED THE TENTS.\n"
            "--TAG--\nGATES OPEN AT TEN.\n-----END-----"
        )
        assembly = assemble_story(wire, stub("FAIR OPENS", story_number="WE-001MO"))
        self.assertIn("[SOURCE: CNN Newsource WE-001MO]", assembly.markup)
        self.assertIn("[NOTE:", assembly.markup)
        self.assertIn("[PKG 01:25]", assembly.markup)

    def test_an_embargo_is_never_dropped_silently(self):
        wire = parse_wire_script(self.VO_WIRE)
        assembly = assemble_story(wire, stub("X", embargo="Los Angeles, CA"))
        self.assertTrue(any("EMBARGO" in n for n in assembly.notes))

    def test_daypart_language_is_flagged_for_a_human(self):
        wire = parse_wire_script(
            self.VO_WIRE.replace("THE NEW RATE STARTS IN OCTOBER.",
                                 "THE COUNCIL MEETS AGAIN TONIGHT.")
        )
        assembly = assemble_story(wire, stub("X"))
        self.assertTrue(any("daypart" in n for n in assembly.notes))

    def test_a_speaker_line_becomes_a_cg_and_a_quote(self):
        wire = parse_wire_script(
            "Title: RAVE\nFootage Type: PKG\nTRT: 01:31\n"
            "--LEAD IN--\nA CONCERT DREW A CROWD.\n"
            "--REPORTER PKG-AS FOLLOWS--\n"
            "THE CROWD FILLED THE PARK.\n"
            'Kelly/Seattle Resident: "I could not have planned this."\n'
            "--TAG--\nFANS WORE RAVE ATTIRE.\n-----END-----"
        )
        assembly = assemble_story(wire, stub("RAVE"))
        self.assertIn("[CG: KELLY, SEATTLE RESIDENT]", assembly.markup)
        self.assertIn('"I could not have planned this."', assembly.markup)
