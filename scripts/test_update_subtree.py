"""Test updater selection and preflight without contacting GitHub."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class UpdateSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="subtree-selection-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "nested").mkdir()
        self.calls = self.root / "calls.jsonl"
        shim = self.root / "git"
        shim.write_text("#!" + sys.executable + "\n" + '''
import json, os, sys
with open(os.environ["RW_TEST_CALL_LOG"], "a") as stream:
    stream.write(json.dumps(sys.argv[1:]) + "\\n")
if sys.argv[1:] == ["rev-parse", "--show-toplevel"]:
    print(os.environ["RW_TEST_ROOT"])
elif sys.argv[1:] == ["status", "--porcelain"]:
    print(os.environ.get("RW_TEST_STATUS", ""), end="")
''')
        shim.chmod(0o755)
        self.environment = dict(os.environ, PATH=str(self.root) + os.pathsep + os.environ["PATH"],
                                RW_TEST_ROOT=str(self.root), RW_TEST_CALL_LOG=str(self.calls))

    def run_updater(self, *args):
        result = subprocess.run(["sh", str(Path(__file__).with_name("update-subtree.sh")), *args],
                                cwd=self.root / "nested", env=self.environment,
                                capture_output=True, text=True)
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()] if self.calls.exists() else []
        return result, calls

    def test_no_arguments_select_published_main(self):
        result, calls = self.run_updater()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(["subtree", "pull", "--prefix=.shared/rimworld-dev-skills",
                          "https://github.com/RimWorld-mods-patches/rimworld-dev-skills.git",
                          "main", "--squash"], calls[-1])

    def test_source_override_keeps_main(self):
        result, calls = self.run_updater("../shared source")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(["../shared source", "main", "--squash"], calls[-1][-3:])

    def test_source_and_ref_overrides(self):
        result, calls = self.run_updater("https://example.invalid/fixture.git", "release/test")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(["https://example.invalid/fixture.git", "release/test", "--squash"], calls[-1][-3:])

    def test_excess_arguments_fail_before_git(self):
        result, calls = self.run_updater("one", "two", "three")
        self.assertEqual(2, result.returncode)
        self.assertIn("Usage:", result.stderr)
        self.assertEqual([], calls)

    def test_dirty_checkout_does_not_fetch(self):
        self.environment["RW_TEST_STATUS"] = " M mod.txt\n"
        result, calls = self.run_updater()
        self.assertEqual(1, result.returncode)
        self.assertIn("preserve local changes", result.stderr)
        self.assertFalse(any(call[0] == "subtree" for call in calls))


if __name__ == "__main__":
    unittest.main()
