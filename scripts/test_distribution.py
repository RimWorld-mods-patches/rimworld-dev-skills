"""Exercise subtree distribution entirely in disposable Git fixture repositories."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class DistributionTests(unittest.TestCase):
    def test_clone_is_self_contained_and_updates_are_explicit(self):
        with tempfile.TemporaryDirectory(prefix="skills-distribution-") as temporary:
            root = Path(temporary).resolve()
            # In the shared repo this file lives under scripts/. Tests run unchanged
            # from a standalone source or a consumer's subtree snapshot.
            payload = Path(__file__).resolve().parents[1]
            source = root / "shared source"
            shutil.copytree(payload, source,
                            ignore=shutil.ignore_patterns(".git", "bin", "obj", "__pycache__", "*.pyc"))
            consumer = root / "mod"
            consumer.mkdir()

            def git(repo, *args):
                return subprocess.check_output(["git", "-C", str(repo), *args],
                                               text=True, stderr=subprocess.STDOUT).strip()

            def initialize(repo):
                git(repo, "init", "-b", "main")
                git(repo, "config", "user.name", "Skill test fixture")
                git(repo, "config", "user.email", "fixture@example.invalid")

            initialize(source)
            git(source, "add", ".")
            git(source, "commit", "-m", "Initial shared fixture")
            initialize(consumer)
            (consumer / "mod.txt").write_text("Unrelated mod content\n")
            git(consumer, "add", ".")
            git(consumer, "commit", "-m", "Initial mod fixture")
            git(consumer, "subtree", "add", "--prefix=.shared/rimworld-dev-skills",
                str(source), "main", "--squash")
            names = ("build-mod", "run-rimworld-dev", "use-rimapi-debug-actions")
            for agent in (".agents", ".claude"):
                discovery = consumer / agent / "skills"
                discovery.mkdir(parents=True)
                for name in names:
                    os.symlink("../../.shared/rimworld-dev-skills/skills/" + name, discovery / name)
            git(consumer, "add", ".agents", ".claude")
            git(consumer, "commit", "-m", "Discover shared fixture")

            clone = root / "independent clone"
            subprocess.check_call(["git", "clone", "--quiet", "--no-hardlinks", str(consumer), str(clone)])
            git(clone, "config", "user.name", "Skill test fixture")
            git(clone, "config", "user.email", "fixture@example.invalid")
            # Remove access through original paths; internal discovery must still work.
            source.rename(root / "hidden source")
            consumer.rename(root / "hidden mod")
            for agent in (".agents", ".claude"):
                for name in names:
                    skill = clone / agent / "skills" / name
                    self.assertTrue((skill / "SKILL.md").is_file())
                    skill.resolve().relative_to(clone)
            self.assertEqual("Unrelated mod content\n", (clone / "mod.txt").read_text())
            self.assertFalse((clone / ".gitmodules").exists())
            source = root / "hidden source"
            with (source / "README.md").open("a") as stream:
                stream.write("\nFixture upstream update\n")
            git(source, "add", "README.md")
            git(source, "commit", "-m", "Update shared fixture")
            self.assertNotIn("Fixture upstream update", (clone / ".shared/rimworld-dev-skills/README.md").read_text())

            updater = clone / ".shared/rimworld-dev-skills/scripts/update-subtree.sh"
            subprocess.check_output(["sh", str(updater), str(source)], cwd=clone,
                                    text=True, stderr=subprocess.STDOUT)
            self.assertEqual(git(source, "rev-parse", "HEAD^{tree}"),
                             git(clone, "rev-parse", "HEAD:.shared/rimworld-dev-skills"))
            self.assertEqual("Unrelated mod content\n", (clone / "mod.txt").read_text())
            head = git(clone, "rev-parse", "HEAD")
            (clone / "mod.txt").write_text("Uncommitted user work\n")
            refused = subprocess.run(["sh", str(updater), str(source)], cwd=clone,
                                     capture_output=True, text=True)
            self.assertNotEqual(0, refused.returncode)
            self.assertIn("preserve local changes", refused.stderr)
            self.assertEqual(head, git(clone, "rev-parse", "HEAD"))
            self.assertEqual("Uncommitted user work\n", (clone / "mod.txt").read_text())


if __name__ == "__main__":
    unittest.main()
