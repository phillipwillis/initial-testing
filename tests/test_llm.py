"""Tests for the Claude layer (§11.12).

No network. The SDK is replaced by a fake that records what it was asked for
and returns what a real response looks like, so the budget arithmetic, the
forced-tool plumbing and the fallbacks are all checkable here.
"""

import unittest
from types import SimpleNamespace

from newscast.llm import (
    DEV_MODEL,
    GRADE_TOOL,
    PLACE_TOOL,
    PRICES,
    Budget,
    BudgetExceeded,
    LLMUnavailable,
    Producer,
    Spend,
    producer,
)
from newscast.scoring import Grade, StoryGroup
from newscast.wires.stub import StoryStub


def stub(n, slug=None, teaser=""):
    return StoryStub(id=f"id{n}", slug=slug or f"STORY {n}", teaser=teaser)


class FakeMessages:
    def __init__(self, tool_name, payload, input_tokens=1000, output_tokens=500):
        self.tool_name = tool_name
        self.payload = payload
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.calls = []

    def count_tokens(self, **kwargs):
        self.calls.append(("count", kwargs))
        return SimpleNamespace(input_tokens=self.input_tokens)

    def create(self, **kwargs):
        self.calls.append(("create", kwargs))
        block = SimpleNamespace(type="tool_use", name=self.tool_name, input=self.payload)
        return SimpleNamespace(
            content=[block],
            stop_reason="tool_use",
            usage=SimpleNamespace(
                input_tokens=self.input_tokens,
                output_tokens=self.output_tokens,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
            ),
        )


class FakeClient:
    def __init__(self, tool_name, payload, **kw):
        self.messages = FakeMessages(tool_name, payload, **kw)


class SpendTest(unittest.TestCase):
    def test_dollars_use_the_models_own_rates(self):
        spend = Spend(input_tokens=1_000_000, output_tokens=1_000_000)
        rate_in, rate_out = PRICES[DEV_MODEL]
        self.assertAlmostEqual(spend.dollars(DEV_MODEL), rate_in + rate_out)

    def test_cache_reads_are_cheaper_than_fresh_input(self):
        fresh = Spend(input_tokens=1_000_000).dollars(DEV_MODEL)
        cached = Spend(cache_read_tokens=1_000_000).dollars(DEV_MODEL)
        self.assertLess(cached, fresh)


class BudgetTest(unittest.TestCase):
    def test_the_worst_case_counts_max_tokens_not_a_guess(self):
        """A ceiling checked against an optimistic estimate is not a ceiling."""
        budget = Budget(model=DEV_MODEL)
        rate_in, rate_out = PRICES[DEV_MODEL]
        self.assertAlmostEqual(
            budget.worst_case(1_000_000, 1_000_000), rate_in + rate_out
        )

    def test_a_call_that_would_break_the_ceiling_is_refused(self):
        """§11.12 — the hard limit is $2, and §12 says checkable is checked."""
        budget = Budget(model=DEV_MODEL, ceiling=2.00)
        with self.assertRaises(BudgetExceeded):
            budget.check(input_tokens=10_000_000, max_tokens=1_000_000)

    def test_an_affordable_call_passes(self):
        Budget(model=DEV_MODEL, ceiling=2.00).check(2000, 8000)

    def test_spend_accumulates_across_calls(self):
        budget = Budget(model=DEV_MODEL)
        usage = SimpleNamespace(input_tokens=1000, output_tokens=500,
                                cache_read_input_tokens=0,
                                cache_creation_input_tokens=0)
        budget.record(usage)
        budget.record(usage)
        self.assertEqual(budget.spend.calls, 2)
        self.assertEqual(budget.spend.input_tokens, 2000)
        self.assertGreater(budget.dollars, 0)

    def test_going_over_the_expected_cost_is_noted_once(self):
        """A run that quietly costs $1.90 a day is worth knowing about before
        the ceiling stops it."""
        budget = Budget(model=DEV_MODEL, expected=0.0001, ceiling=100.0)
        usage = SimpleNamespace(input_tokens=500_000, output_tokens=100_000,
                                cache_read_input_tokens=0,
                                cache_creation_input_tokens=0)
        budget.record(usage)
        budget.record(usage)
        self.assertEqual(len(budget.notes), 1)
        self.assertIn("over expected", budget.notes[0])

    def test_a_missing_usage_field_does_not_crash_the_run(self):
        budget = Budget(model=DEV_MODEL)
        budget.record(SimpleNamespace())
        self.assertEqual(budget.spend.calls, 1)

    def test_the_report_never_shows_a_key(self):
        report = Budget(model=DEV_MODEL).report()
        self.assertIn(DEV_MODEL, report)
        self.assertNotIn("sk-", report)


class GradePoolTest(unittest.TestCase):
    def producer(self, ranking, **kw):
        client = FakeClient(GRADE_TOOL["name"], {"ranking": ranking}, **kw)
        return Producer(client=client, budget=Budget(model=DEV_MODEL)), client

    def test_the_pool_is_graded_in_one_call(self):
        """§11.12 — the budget only works if tool use collapses the calls."""
        p, client = self.producer([
            {"id": "id1", "viewer_impact": 0.9, "magnitude": 0.8,
             "visual_strength": 0.5, "audio_available": 0.4, "freshness": 1.0,
             "note": "local and today"},
            {"id": "id2", "viewer_impact": 0.2, "magnitude": 0.2,
             "visual_strength": 0.1, "audio_available": 0.0, "freshness": 0.5},
        ])
        grades = p.grade_pool([stub(1), stub(2)])
        self.assertEqual([g.stub.id for g in grades], ["id1", "id2"])
        self.assertGreater(grades[0].total, grades[1].total)
        self.assertEqual(grades[0].notes, ["local and today"])
        self.assertEqual(sum(1 for kind, _ in client.messages.calls if kind == "create"), 1)

    def test_the_tool_is_forced_so_the_answer_is_structured(self):
        p, client = self.producer([])
        p.grade_pool([stub(1)])
        create = next(kw for kind, kw in client.messages.calls if kind == "create")
        self.assertEqual(create["tool_choice"],
                         {"type": "tool", "name": "submit_ranking"})

    def test_a_story_the_model_skipped_is_graded_by_the_fallback(self):
        """A skipped story is not a story that scored zero."""
        p, _ = self.producer([
            {"id": "id1", "viewer_impact": 0.9, "magnitude": 0.8,
             "visual_strength": 0.5, "audio_available": 0.4, "freshness": 1.0},
        ])
        grades = p.grade_pool([stub(1), stub(2)])
        self.assertEqual(len(grades), 2)
        self.assertIn("skipped", " ".join(p.budget.notes))

    def test_scores_outside_zero_to_one_are_clamped(self):
        p, _ = self.producer([
            {"id": "id1", "viewer_impact": 7.0, "magnitude": -3.0,
             "visual_strength": "nonsense", "audio_available": 0.5,
             "freshness": 0.5},
        ])
        grade = p.grade_pool([stub(1)])[0]
        self.assertEqual(grade.viewer_impact, 1.0)
        self.assertEqual(grade.magnitude, 0.0)
        self.assertEqual(grade.visual_strength, 0.0)

    def test_an_id_the_pool_never_had_is_ignored(self):
        p, _ = self.producer([
            {"id": "invented", "viewer_impact": 1.0, "magnitude": 1.0,
             "visual_strength": 1.0, "audio_available": 1.0, "freshness": 1.0},
        ])
        grades = p.grade_pool([stub(1)])
        self.assertEqual([g.stub.id for g in grades], ["id1"])

    def test_a_response_with_no_tool_call_is_an_error_not_an_empty_pool(self):
        client = FakeClient("something_else", {})
        p = Producer(client=client, budget=Budget(model=DEV_MODEL))
        with self.assertRaises(LLMUnavailable):
            p.grade_pool([stub(1)])

    def test_the_budget_stops_a_call_before_it_is_made(self):
        client = FakeClient(GRADE_TOOL["name"], {"ranking": []},
                            input_tokens=50_000_000)
        p = Producer(client=client, budget=Budget(model=DEV_MODEL, ceiling=2.00))
        with self.assertRaises(BudgetExceeded):
            p.grade_pool([stub(1)])
        self.assertEqual([k for k, _ in client.messages.calls], ["count"])


class PlacePoolTest(unittest.TestCase):
    def groups(self):
        return [StoryGroup(lead=Grade(stub=stub(1, "IDAHO FALLS SHOOTING"))),
                StoryGroup(lead=Grade(stub=stub(2, "NEW MOVIE FRIDAY")))]

    def producer(self, placements):
        client = FakeClient(PLACE_TOOL["name"], {"placements": placements})
        return Producer(client=client, budget=Budget(model=DEV_MODEL))

    def test_placements_come_back_keyed_by_slug(self):
        """That is the shape slotting.place_pool takes as overrides."""
        p = self.producer([
            {"id": "id1", "primary": "1a", "backup": "2A", "heaviness": 0.95,
             "reason": "leads the show"},
        ])
        out = p.place_pool(self.groups())
        self.assertEqual(set(out), {"IDAHO FALLS SHOOTING"})
        placement = out["IDAHO FALLS SHOOTING"]
        self.assertEqual((placement.primary, placement.backup), ("1A", "2A"))
        self.assertEqual(placement.heaviness, 0.95)
        self.assertEqual(placement.reasons, ["leads the show"])

    def test_a_backup_equal_to_the_primary_is_dropped(self):
        """A backup that is the same block is not a backup."""
        p = self.producer([
            {"id": "id1", "primary": "1B", "backup": "1B", "heaviness": 0.9},
        ])
        self.assertEqual(p.place_pool(self.groups())["IDAHO FALLS SHOOTING"].backup, "")

    def test_a_story_the_model_skipped_simply_keeps_the_heuristic(self):
        p = self.producer([
            {"id": "id1", "primary": "1B", "backup": "2B", "heaviness": 0.9},
        ])
        out = p.place_pool(self.groups())
        self.assertNotIn("NEW MOVIE FRIDAY", out)


class ProducerFactoryTest(unittest.TestCase):
    def test_no_key_returns_a_reason_rather_than_raising(self):
        """A run with no key still has to produce a rundown."""
        made, why = producer({})
        self.assertIsNone(made)
        self.assertTrue(why)


if __name__ == "__main__":
    unittest.main()
