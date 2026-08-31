"""Reading .env, and never leaking what it holds."""

import os
import tempfile
import unittest

from newscast.env import candidate_paths, describe, load_env, parse_env, require


class ParseTests(unittest.TestCase):
    def test_plain_pairs(self):
        self.assertEqual(parse_env("CNN_USER=phil"), {"CNN_USER": "phil"})

    def test_export_prefix(self):
        self.assertEqual(parse_env("export CNN_USER=phil"), {"CNN_USER": "phil"})

    def test_quotes_are_stripped(self):
        self.assertEqual(parse_env('A="two words"')["A"], "two words")
        self.assertEqual(parse_env("A='two words'")["A"], "two words")

    def test_a_password_may_contain_an_equals_sign(self):
        self.assertEqual(parse_env("CNN_PASS=ab=cd=ef")["CNN_PASS"], "ab=cd=ef")

    def test_comments_and_blank_lines_are_ignored(self):
        self.assertEqual(parse_env("# note\n\nA=1\n"), {"A": "1"})

    def test_a_line_with_no_equals_is_ignored(self):
        self.assertEqual(parse_env("nonsense\nA=1"), {"A": "1"})

    def test_whitespace_around_the_key_and_value(self):
        self.assertEqual(parse_env("  A = 1 ")["A"], "1")


class LoadTests(unittest.TestCase):
    def test_the_working_directory_is_searched_first(self):
        self.assertEqual(candidate_paths()[0], os.path.join(os.getcwd(), ".env"))

    def test_the_search_walks_up_out_of_the_unzipped_folder(self):
        """The code and the credentials are not in the same directory.

            monkey_king/
                .env
                initial-testing-<branch>/     <- commands run from here

        `python3 -m newscast...` only works from inside the unzipped folder,
        which is one level below the .env.
        """
        with tempfile.TemporaryDirectory() as tmp:
            monkey = os.path.join(tmp, "monkey_king")
            unzipped = os.path.join(monkey, "initial-testing-some-branch")
            os.makedirs(unzipped)
            env_path = os.path.join(monkey, ".env")
            with open(env_path, "w") as handle:
                handle.write("CNN_USER=phil\n")

            paths = candidate_paths(start=unzipped)
            self.assertIn(env_path, paths)
            self.assertLess(
                paths.index(env_path),
                paths.index(os.path.join(os.path.expanduser("~"), ".env")),
                "the nearest .env should win over the home directory",
            )

    def test_the_nearest_env_wins_over_one_further_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            inner = os.path.join(tmp, "a", "b")
            os.makedirs(inner)
            paths = candidate_paths(start=inner)
            self.assertLess(
                paths.index(os.path.join(inner, ".env")),
                paths.index(os.path.join(tmp, "a", ".env")),
            )

    def test_the_search_terminates(self):
        """Walking up must stop, at the home directory or the filesystem root."""
        paths = candidate_paths(start="/")
        self.assertLess(len(paths), 200)
        self.assertEqual(len(paths), len(set(paths)), "no duplicates")

    def test_an_explicit_path_wins(self):
        self.assertEqual(candidate_paths("/tmp/x.env"), ["/tmp/x.env"])

    def test_values_load_from_a_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".env")
            with open(path, "w") as handle:
                handle.write("CNN_USER=phil\nCNN_PASS=secret\n")
            values, used = load_env(path)
        self.assertEqual(values["CNN_USER"], "phil")
        self.assertEqual(used, path)

    def test_the_process_environment_overrides_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, ".env")
            with open(path, "w") as handle:
                handle.write("CNN_USER=from-file\n")
            os.environ["CNN_USER"] = "from-environment"
            try:
                values, _ = load_env(path)
            finally:
                del os.environ["CNN_USER"]
        self.assertEqual(values["CNN_USER"], "from-environment")


class DescribeTests(unittest.TestCase):
    def test_a_value_is_never_reported(self):
        report = describe({"CNN_PASS": "hunter2"}, ["CNN_PASS"])
        self.assertNotIn("hunter2", report)
        self.assertIn("7 characters", report)

    def test_a_missing_key_is_named(self):
        self.assertIn("CNN_USER", describe({}, ["CNN_USER"]))

    def test_require_reports_what_is_missing(self):
        self.assertEqual(require({"A": "1"}, "A", "B"), ["B"])

    def test_an_empty_value_counts_as_missing(self):
        self.assertEqual(require({"A": ""}, "A"), ["A"])
