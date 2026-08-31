"""Frame addressing tests (§9, §10.6).

No Selenium here: the matching logic is pure, so the part of frame handling most
likely to be wrong is testable without a browser.
"""

import unittest

from newscast.inception.frames import (
    CG_EDITOR,
    FrameDescriptor,
    LOGIN_DIALOG,
    RUNNING_ORDER_MANAGER,
    STORY_EDITOR,
    any_of,
    by_id_prefix,
    by_src,
    by_title,
    describe_path,
    path,
    resolve,
    show_frame,
)

# A plausible Inception frame tree: two shows open, the ROM, a story editor.
FRAMES = [
    FrameDescriptor(0, "Running Order Manager", "/apps/RunningOrderManager/Index.do", ""),
    FrameDescriptor(1, "5:00 AM 01/22/26", "/apps/RunningOrder/View.do?id=1", ""),
    FrameDescriptor(2, "5:30 AM 01/22/26", "/apps/RunningOrder/View.do?id=2", ""),
    FrameDescriptor(3, None, "/apps/BroadcastStory/View.do?id=88", "view-10"),
]


class TitleMatchingTests(unittest.TestCase):
    def test_a_show_matches_by_prefix_because_the_date_is_appended(self):
        self.assertEqual(resolve(show_frame("5:00 AM"), FRAMES).index, 1)
        self.assertEqual(resolve(show_frame("5:30 AM"), FRAMES).index, 2)

    def test_a_show_that_is_not_open_resolves_to_nothing(self):
        self.assertIsNone(resolve(show_frame("11:00 PM"), FRAMES))

    def test_exact_titles_do_not_match_on_a_prefix(self):
        self.assertIsNone(resolve(by_title("Running Order", exact=True), FRAMES))
        self.assertIsNotNone(resolve(by_title("Running Order Manager", exact=True), FRAMES))

    def test_matching_ignores_case_and_extra_whitespace(self):
        frames = [FrameDescriptor(0, "  RUNNING   ORDER  MANAGER ", "", "")]
        self.assertIsNotNone(resolve(by_title("Running Order Manager", exact=True), frames))

    def test_a_frame_with_no_readable_title_never_matches_by_title(self):
        """Cross-origin frames report None, and must not match by accident."""
        self.assertIsNone(resolve(by_title("anything"), [FrameDescriptor(0, None, "", "")]))

    def test_an_exact_title_outranks_a_prefix_when_both_are_open(self):
        frames = [
            FrameDescriptor(0, "5:00 AM 01/22/26", "", ""),
            FrameDescriptor(1, "5:00 AM", "", ""),
        ]
        self.assertEqual(resolve(by_title("5:00 AM"), frames).index, 1)


class SrcMatchingTests(unittest.TestCase):
    def test_the_story_editor_is_found_by_route(self):
        """Server routes outlast generated markup, so they are the best handle."""
        self.assertEqual(resolve(STORY_EDITOR, FRAMES).index, 3)

    def test_the_login_dialog(self):
        frames = [FrameDescriptor(0, None, "/User/Authentication/Dialog.do", "")]
        self.assertIsNotNone(resolve(LOGIN_DIALOG, frames))

    def test_src_matching_is_case_insensitive(self):
        frames = [FrameDescriptor(0, None, "/APPS/BROADCASTSTORY/VIEW.DO", "")]
        self.assertIsNotNone(resolve(by_src("BroadcastStory/View.do"), frames))

    def test_a_missing_src_does_not_crash(self):
        self.assertIsNone(resolve(by_src("anything"), [FrameDescriptor(0, "t", "", "")]))


class IdMatchingTests(unittest.TestCase):
    def test_the_cg_editor_opens_with_a_numbered_id(self):
        self.assertEqual(resolve(CG_EDITOR, FRAMES).index, 3)

    def test_a_prefix_that_matches_nothing(self):
        self.assertIsNone(resolve(by_id_prefix("editor-"), FRAMES))


class AnyOfTests(unittest.TestCase):
    def test_the_rom_is_found_by_either_route_or_title(self):
        by_route = [FrameDescriptor(0, None, "/apps/RunningOrderManager/Index.do", "")]
        by_name = [FrameDescriptor(0, "Running Order Manager", "/other", "")]
        self.assertIsNotNone(resolve(RUNNING_ORDER_MANAGER, by_route))
        self.assertIsNotNone(resolve(RUNNING_ORDER_MANAGER, by_name))

    def test_any_of_reports_the_best_ranked_match(self):
        spec = any_of(by_title("5:00 AM", exact=True), by_title("5:00 AM"))
        frames = [
            FrameDescriptor(0, "5:00 AM 01/22/26", "", ""),
            FrameDescriptor(1, "5:00 AM", "", ""),
        ]
        self.assertEqual(resolve(spec, frames).index, 1)


class ResolutionTests(unittest.TestCase):
    def test_resolution_is_deterministic_when_several_frames_match(self):
        frames = [
            FrameDescriptor(0, "5:00 AM 01/22/26", "", ""),
            FrameDescriptor(1, "5:00 AM 01/23/26", "", ""),
        ]
        for _ in range(5):
            self.assertEqual(resolve(show_frame("5:00 AM"), frames).index, 0)

    def test_an_empty_frame_list(self):
        self.assertIsNone(resolve(STORY_EDITOR, []))


class PathTests(unittest.TestCase):
    def test_a_path_reads_as_a_route_through_the_tree(self):
        self.assertEqual(
            describe_path(path(show_frame("5:00 AM"), STORY_EDITOR)),
            "title startswith '5:00 AM' > src contains 'BroadcastStory/View.do'",
        )

    def test_the_empty_path_is_the_document_root(self):
        self.assertEqual(describe_path(path()), "(document root)")
