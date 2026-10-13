"""Exercise the version guard against disposable Git fixture repositories."""

import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import require_version_bump as guard

PROJECT = "Source/Fixture/Fixture.csproj"


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="version guard '")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.git("init", "-b", "main")
        self.git("config", "user.name", "Version guard fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        (self.root / ".rimworld-dev.json").write_text(json.dumps({"project": PROJECT}))
        self.set_versions("1.0.0")
        (self.root / "1.6/Defs").mkdir(parents=True)
        (self.root / "1.6/Defs/Things.xml").write_text("<Defs/>")
        self.commit("Initial fixture")

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.root), *args], text=True).strip()

    def set_versions(self, about, project=None):
        (self.root / "About").mkdir(exist_ok=True)
        (self.root / "About/About.xml").write_text(
            "<ModMetaData><packageId>fixture.mod</packageId><modVersion>%s</modVersion></ModMetaData>" % about)
        (self.root / "Source/Fixture").mkdir(parents=True, exist_ok=True)
        (self.root / PROJECT).write_text(
            '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><Version>%s</Version></PropertyGroup></Project>'
            % (project or about))

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)

    def change_content(self, stage=True):
        path = self.root / "1.6/Defs/Things.xml"
        path.write_text(path.read_text() + "<!-- change -->")
        if stage:
            self.git("add", "-A")

    def run_guard(self, command):
        stdout = io.StringIO()
        payload = {"tool_name": "Bash", "cwd": str(self.root / "Source"), "tool_input": {"command": command}}
        self.assertEqual(0, guard.main(io.StringIO(json.dumps(payload)), stdout))
        if not stdout.getvalue():
            return None
        output = json.loads(stdout.getvalue())["hookSpecificOutput"]
        self.assertEqual("deny", output["permissionDecision"])
        return output["permissionDecisionReason"]

    def test_unrelated_commands_and_bypasses_are_allowed(self):
        self.change_content()
        for command in ("git status", "echo git commit-tree", "git commit --amend -m x",
                        "git commit --no-verify -m x"):
            with self.subTest(command=command):
                self.assertIsNone(self.run_guard(command))

    def test_content_commit_on_primary_branch_needs_a_bump(self):
        self.change_content()
        self.assertIn("unchanged", self.run_guard('git commit -m "Fix doors"'))
        self.set_versions("1.0.1")
        self.git("add", "-A")
        self.assertIsNone(self.run_guard('git commit -m "Fix doors"'))

    def test_non_content_commit_needs_no_bump(self):
        (self.root / "README.md").write_text("Docs\n")
        (self.root / ".shared").mkdir()
        (self.root / ".shared/skill.md").write_text("Shared\n")
        self.git("add", "-A")
        self.assertIsNone(self.run_guard("git commit -m docs"))

    def test_commit_all_checks_working_tree(self):
        self.change_content(stage=False)
        self.assertIsNone(self.run_guard("git commit -m 'staged nothing'"))
        self.assertIn("unchanged", self.run_guard("git commit -am 'Fix doors'"))
        self.set_versions("1.0.1")
        self.assertIsNone(self.run_guard("git commit --all -m 'Fix doors'"))
        self.assertIsNone(self.run_guard("git commit -ma"))  # -m's argument, not --all

    def test_disagreeing_or_missing_project_version_is_denied(self):
        self.change_content()
        self.set_versions("1.1.0", "1.1")
        self.git("add", "-A")
        self.assertIn("byte-identical", self.run_guard("git commit -m x"))
        (self.root / PROJECT).write_text("<Project><PropertyGroup/></Project>")
        self.git("add", "-A")
        self.assertIn("Could not read <Version>", self.run_guard("git commit -m x"))

    def test_without_config_only_about_is_checked(self):
        (self.root / ".rimworld-dev.json").unlink()
        self.change_content()
        self.set_versions("1.0.1", "9.9.9")
        self.git("add", "-A")
        self.assertIsNone(self.run_guard("git commit -m x"))

    def test_backwards_version_is_denied(self):
        self.change_content()
        self.set_versions("0.9.0")
        self.git("add", "-A")
        self.assertIn("backwards", self.run_guard("git commit -m x"))

    def test_branch_commits_are_free_but_push_needs_one_bump(self):
        self.git("switch", "-q", "-c", "feature")
        self.change_content()
        self.assertIsNone(self.run_guard("git commit -m wip"))
        self.commit("wip")
        self.assertIn("left main", self.run_guard("git push -u origin feature"))
        self.set_versions("1.1.0")
        self.commit("Bump")
        self.assertIsNone(self.run_guard("git -C . push"))

    def test_chained_commit_and_push_is_checked_as_commit(self):
        self.change_content()
        self.set_versions("1.0.1")
        self.git("add", "-A")
        self.assertIsNone(self.run_guard("git commit -m x && git push"))


if __name__ == "__main__":
    unittest.main()
