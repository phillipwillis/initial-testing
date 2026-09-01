"""Tests for slotting (§6 phase 2, §11.27)."""

import unittest

from newscast.scoring import Grade, StoryGroup
from newscast.slotting import (
    Fill,
    Hole,
    Placement,
    fill_holes,
    heaviness,
    is_entertainment,
    order_block,
    place_group,
    place_pool,
    target_seconds,
)
from newscast.wires.stub import StoryStub


def group(slug, teaser="", footage="VO", total=1.0):
    stub = StoryStub(id=slug, slug=slug, teaser=teaser, footage_type=footage)
    return StoryGroup(lead=Grade(stub=stub, total=total))


class HeavinessTest(unittest.TestCase):
    def test_a_shooting_is_heavy(self):
        """§11.27 gives the number: 0.9–1.0."""
        weight, _ = heaviness(StoryGroup(lead=Grade(stub=StoryStub(
            slug="IDAHO FALLS SHOOTING"))).stub)
        self.assertGreaterEqual(weight, 0.9)
        self.assertLessEqual(weight, 1.0)

    def test_a_small_business_going_under_is_lighter(self):
        """§11.27's other example: sad, but 0.6–0.7."""
        weight, _ = heaviness(StoryStub(slug="LOCAL BAKERY BANKRUPT AFTER 30 YEARS"))
        self.assertGreaterEqual(weight, 0.6)
        self.assertLessEqual(weight, 0.75)

    def test_a_talker_is_light(self):
        weight, _ = heaviness(StoryStub(slug="PUPPY REUNITED WITH OWNER AT PARADE"))
        self.assertLess(weight, 0.4)

    def test_a_heavy_word_beats_the_light_ones_around_it(self):
        """A shooting at a festival is a shooting story."""
        weight, _ = heaviness(StoryStub(
            slug="SHOOTING AT SUMMER FESTIVAL",
            teaser="The parade and the concert were both cancelled.",
        ))
        self.assertGreaterEqual(weight, 0.85)

    def test_an_unreadable_slug_lands_in_the_middle_and_says_so(self):
        weight, reasons = heaviness(StoryStub(slug="WE-001MO FEED THREE"))
        self.assertEqual(weight, 0.5)
        self.assertIn("nothing in the slug", " ".join(reasons))

    def test_word_matching_respects_boundaries(self):
        """'war' must not match inside 'warehouse' — the same class of bug that
        made 'nfl' match 'conflicto'."""
        weight, _ = heaviness(StoryStub(slug="NEW WAREHOUSE OPENS ON YELLOWSTONE"))
        self.assertLess(weight, 0.85)


class EntertainmentTest(unittest.TestCase):
    def test_a_movie_release_is_entertainment(self):
        self.assertTrue(is_entertainment(StoryStub(slug="NEW MARVEL FILM PREMIERES")))

    def test_a_road_closure_is_not(self):
        self.assertFalse(is_entertainment(StoryStub(slug="BROADWAY BRIDGE CLOSES")))


class PlaceGroupTest(unittest.TestCase):
    def test_every_story_gets_a_primary_and_a_backup(self):
        """§11.27 — a story that loses its slot has somewhere to go rather than
        being re-graded from scratch."""
        for g in (group("IDAHO FALLS SHOOTING"),
                  group("NEW MOVIE OUT FRIDAY"),
                  group("PUPPY PARADE")):
            p = place_group(g)
            self.assertTrue(p.primary)
            self.assertTrue(p.backup)
            self.assertNotEqual(p.primary, p.backup)

    def test_a_local_hard_story_leads_the_a_block(self):
        p = place_group(group("IDAHO FALLS SHOOTING ON BROADWAY"))
        self.assertEqual(p.primary, "1A")

    def test_entertainment_goes_to_the_closing_block(self):
        p = place_group(group("NEW MARVEL FILM PREMIERES FRIDAY"))
        self.assertEqual(p.primary, "2D")

    def test_a_placement_explains_itself(self):
        p = place_group(group("IDAHO FALLS SHOOTING"))
        self.assertTrue(p.reasons)
        self.assertIn("1A", p.explain())

    def test_a_model_answer_overrides_the_heuristic(self):
        """§11.27 — placement is the model's judgement; this file is the
        stand-in for when it has nothing to say."""
        g = group("IDAHO FALLS SHOOTING")
        p = place_group(g, Placement(group=g, primary="2C", backup="1D", heaviness=0.4))
        self.assertEqual((p.primary, p.backup), ("2C", "1D"))
        self.assertEqual(p.heaviness, 0.4)

    def test_a_partial_model_answer_inherits_the_rest(self):
        g = group("IDAHO FALLS SHOOTING")
        p = place_group(g, Placement(group=g, primary="2C"))
        self.assertEqual(p.primary, "2C")
        self.assertTrue(p.backup)

    def test_target_seconds_come_from_the_form(self):
        self.assertGreater(target_seconds(StoryStub(footage_type="PKG")),
                           target_seconds(StoryStub(footage_type="VO")))


class OrderBlockTest(unittest.TestCase):
    def test_heavier_runs_first(self):
        """§2's 'heavy to light', made numeric and therefore checkable."""
        heavy = place_group(group("IDAHO FALLS SHOOTING"))
        light = place_group(group("PUPPY PARADE DOWNTOWN"))
        ordered = order_block([light, heavy])
        self.assertEqual([p.slug for p in ordered],
                         ["IDAHO FALLS SHOOTING", "PUPPY PARADE DOWNTOWN"])

    def test_a_tie_is_broken_by_the_grade(self):
        a = Placement(group=group("A SLUG", total=2.0), heaviness=0.5)
        b = Placement(group=group("B SLUG", total=9.0), heaviness=0.5)
        self.assertEqual([p.slug for p in order_block([a, b])], ["B SLUG", "A SLUG"])


class FillHolesTest(unittest.TestCase):
    def holes(self, seconds=120.0):
        return [Hole(1, "A", seconds), Hole(1, "B", seconds),
                Hole(1, "C", seconds), Hole(2, "B", seconds),
                Hole(2, "C", seconds), Hole(2, "D", seconds)]

    def test_stories_land_in_their_primary_block(self):
        placements = place_pool([group("NEW MARVEL FILM PREMIERES")])
        fill = fill_holes(placements, self.holes())
        self.assertEqual([p.slug for p in fill.order("2D")],
                         ["NEW MARVEL FILM PREMIERES"])

    def test_a_full_primary_pushes_a_story_to_its_backup(self):
        """The whole point of a backup block (§11.27)."""
        placements = [
            Placement(group=group("FIRST"), primary="1B", backup="2B",
                      heaviness=0.9, target_seconds=100.0),
            Placement(group=group("SECOND"), primary="1B", backup="2B",
                      heaviness=0.9, target_seconds=100.0),
        ]
        fill = fill_holes(placements, self.holes(seconds=120.0))
        self.assertEqual([p.slug for p in fill.order("1B")], ["FIRST"])
        self.assertEqual([p.slug for p in fill.order("2B")], ["SECOND"])
        self.assertEqual(fill.unplaced, [])

    def test_a_story_that_fits_nowhere_says_why_for_both_blocks(self):
        placements = [
            Placement(group=group("HUGE"), primary="1B", backup="2B",
                      target_seconds=999.0),
        ]
        fill = fill_holes(placements, self.holes(seconds=60.0))
        self.assertEqual(len(fill.unplaced), 1)
        reason = fill.unplaced[0][1]
        self.assertIn("1B", reason)
        self.assertIn("2B", reason)

    def test_the_package_budget_is_enforced_per_block(self):
        """§5 R9 — max two per block, and a third goes to the backup."""
        placements = [
            Placement(group=group(f"PKG {n}", footage="PKG"), primary="1B",
                      backup="2B", target_seconds=10.0)
            for n in range(3)
        ]
        fill = fill_holes(placements, self.holes(seconds=600.0))
        self.assertEqual(len(fill.order("1B")), 2)
        self.assertEqual(len(fill.order("2B")), 1)

    def test_a_block_is_ordered_heavy_to_light_not_in_arrival_order(self):
        """A story that arrives late is not therefore a light story."""
        placements = [
            Placement(group=group("LIGHT"), primary="1A", heaviness=0.2,
                      target_seconds=20.0),
            Placement(group=group("HEAVY"), primary="1A", heaviness=0.95,
                      target_seconds=20.0),
        ]
        fill = fill_holes(placements, self.holes())
        self.assertEqual([p.slug for p in fill.order("1A")], ["HEAVY", "LIGHT"])

    def test_a_block_the_human_left_no_room_in_is_not_a_crash(self):
        placements = [Placement(group=group("ORPHAN"), primary="2A", backup="")]
        fill = fill_holes(placements, self.holes())
        self.assertEqual(len(fill.unplaced), 1)
        self.assertIn("no backup", fill.unplaced[0][1])

    def test_used_seconds_are_tracked_per_block(self):
        placements = [
            Placement(group=group("ONE"), primary="1C", target_seconds=25.0),
            Placement(group=group("TWO"), primary="1C", target_seconds=35.0),
        ]
        fill = fill_holes(placements, self.holes())
        self.assertAlmostEqual(fill.used_seconds["1C"], 60.0)
        self.assertEqual(fill.placed_count, 2)


if __name__ == "__main__":
    unittest.main()
