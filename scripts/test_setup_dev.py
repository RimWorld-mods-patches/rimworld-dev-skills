import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

spec = importlib.util.spec_from_file_location("setup_dev", Path(__file__).with_name("setup-dev.py"))
setup_dev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup_dev)


def about(folder, package):
    (folder / "About").mkdir(parents=True, exist_ok=True)
    (folder / "About/About.xml").write_text("<ModMetaData><packageId>" + package + "</packageId></ModMetaData>")


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="setup space '")
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name).resolve()
        self.root = base / "repo"
        (self.root / "Source/Fixture").mkdir(parents=True)
        (self.root / "Source/Fixture/Fixture.csproj").write_text(
            "<Project><PropertyGroup><AssemblyName>Fixture</AssemblyName></PropertyGroup></Project>")
        about(self.root, "fixture.mod")
        (self.root / ".rimworld-dev.md").write_text("Fixture runtime contract")
        self.config = dict(schema_version=1, mod_name="Fixture", package_id="fixture.mod",
                           project="Source/Fixture/Fixture.csproj", sdk_image="fixture/sdk:8",
                           test_projects=[], output_dlls=["Fixture.dll"],
                           baseline_save="Fixture-Disposable", runtime_notes=".rimworld-dev.md",
                           baseline_mods=["Brrainz.Harmony", "Ludeon.RimWorld", "Test.Helper", "fixture.mod"],
                           mod_sources={"brrainz.harmony": {"workshop": "111"},
                                        "test.helper": {"github_release": "org/helper"}})
        self.write_config()
        steamapps = base / "Steam/steamapps"
        self.app = steamapps / "common/RimWorld/RimWorldMac.app"
        (self.app / "Mods").mkdir(parents=True)
        (self.app / "Version.txt").write_text("1.6.4871 rev595")
        about(self.app / "Data/Core", "Ludeon.RimWorld")
        self.workshop = steamapps / "workshop/content/294100"
        about(self.workshop / "111", "brrainz.harmony")
        release = base / "release"
        about(release / "Helper", "test.helper")
        self.release_zip = base / "Helper-1.0.zip"
        with zipfile.ZipFile(self.release_zip, "w") as zf:
            for path in release.rglob("*"):
                zf.write(path, path.relative_to(release))
        env = patch.dict(os.environ, {"RW_RIMWORLD_APP": str(self.app)})
        env.start()
        self.addCleanup(env.stop)
        which = patch.object(setup_dev.shutil, "which", return_value="/usr/bin/docker")
        which.start()
        self.addCleanup(which.stop)
        fetch = patch.object(setup_dev, "fetch_release", side_effect=self.fake_fetch)
        self.fetch = fetch.start()
        self.addCleanup(fetch.stop)
        self.create_baseline = setup_dev.create_baseline
        baseline = patch.object(setup_dev, "create_baseline", side_effect=self.fake_baseline)
        self.baseline = baseline.start()
        self.addCleanup(baseline.stop)

    def fake_baseline(self, values, timeout, log=print):
        Path(values["RW_BASELINE_SAVE"]).write_text("save")

    def fake_fetch(self, repo, tag, dest):
        dest.mkdir(parents=True, exist_ok=True)
        target = dest / self.release_zip.name
        target.write_bytes(self.release_zip.read_bytes())
        return target, "v1.0"

    def write_config(self):
        (self.root / ".rimworld-dev.json").write_text(json.dumps(self.config))

    def run_setup(self, *args):
        out = io.StringIO()
        with patch("sys.stdout", out):
            code = setup_dev.main(["--repo-root", str(self.root), *args])
        return code, out.getvalue()

    def test_check_mode_reports_and_changes_nothing(self):
        code, out = self.run_setup()
        self.assertEqual(1, code)
        self.assertIn("link Workshop item 111", out)
        self.assertIn("download org/helper release latest", out)
        self.assertIn("--apply", out)
        self.assertFalse((self.root / ".runtime").exists())
        self.assertEqual([], list((self.app / "Mods").iterdir()))
        self.fetch.assert_not_called()

    def test_apply_builds_profile_and_links_then_is_idempotent(self):
        code, out = self.run_setup("--apply")
        mods = self.app / "Mods"
        self.assertTrue(mods.joinpath("dev-fixture.mod").resolve() == self.root)
        self.assertEqual(self.workshop / "111", mods.joinpath("dev-brrainz.harmony").resolve())
        helper = mods.joinpath("dev-test.helper").resolve()
        self.assertEqual(self.root / ".runtime/mods/helper-v1.0/Helper", helper)
        profile = self.root / ".runtime/rimworld-dev-profile"
        self.assertEqual(["brrainz.harmony", "ludeon.rimworld", "test.helper", "fixture.mod"],
                         setup_dev.active_mods(profile / "Config/ModsConfig.xml"))
        self.assertIn("<devMode>True</devMode>", (profile / "Config/Prefs.xml").read_text())
        self.assertTrue((profile / "Saves").is_dir())
        # The baseline save is created last, once everything else is ready.
        self.assertEqual(0, code, out)
        self.assertEqual(1, self.baseline.call_count)
        code, out = self.run_setup("--apply")
        self.assertEqual(0, code, out)
        self.assertEqual(1, self.fetch.call_count)
        self.assertEqual(1, self.baseline.call_count)

    def test_existing_installs_are_reused(self):
        about(self.app / "Mods/Harmony", "brrainz.harmony")
        about(self.app / "Mods/MyHelperBuild", "test.helper")
        self.run_setup("--apply")
        names = sorted(p.name for p in (self.app / "Mods").iterdir())
        self.assertEqual(["Harmony", "MyHelperBuild", "dev-fixture.mod"], names)
        self.fetch.assert_not_called()

    def test_link_to_another_checkout_is_repointed_but_copies_are_untouched(self):
        other = Path(self.temp.name) / "other-checkout"
        about(other, "fixture.mod")
        (self.app / "Mods/FixtureOld").symlink_to(other, target_is_directory=True)
        code, out = self.run_setup()
        self.assertIn("relink FixtureOld", out)
        self.run_setup("--apply")
        self.assertEqual(self.root, (self.app / "Mods/FixtureOld").resolve())
        (self.app / "Mods/FixtureOld").unlink()
        about(self.app / "Mods/FixtureCopy", "fixture.mod")
        code, out = self.run_setup("--apply")
        self.assertIn("shadows this checkout", out)
        self.assertTrue((self.app / "Mods/FixtureCopy/About/About.xml").is_file())
        self.assertFalse((self.app / "Mods/FixtureCopy").is_symlink())

    def test_missing_workshop_item_asks_to_subscribe(self):
        (self.workshop / "111/About/About.xml").unlink()
        code, out = self.run_setup("--apply")
        self.assertEqual(1, code)
        self.assertIn("subscribe to https://steamcommunity.com/sharedfiles/filedetails/?id=111", out)
        self.assertFalse((self.app / "Mods/dev-brrainz.harmony").exists())
        self.baseline.assert_not_called()

    def test_missing_game_stops_before_changes(self):
        with patch.dict(os.environ, {"RW_RIMWORLD_APP": str(Path(self.temp.name) / "nowhere.app")}):
            code, out = self.run_setup("--apply")
        self.assertEqual(1, code)
        self.assertIn("not found", out)
        self.assertFalse((self.root / ".runtime").exists())

    def values(self):
        return setup_dev.dev_env.load(self.root)

    def test_baseline_refuses_when_a_game_already_answers(self):
        with patch.object(setup_dev, "running", return_value=[]), \
                patch.object(setup_dev, "api_up", return_value=True), \
                patch.object(setup_dev.subprocess, "Popen") as popen:
            with self.assertRaisesRegex(ValueError, "Another game"):
                self.create_baseline(self.values(), 5, log=lambda _: None)
        popen.assert_not_called()
        with patch.object(setup_dev, "running", return_value=[123]), \
                patch.object(setup_dev.subprocess, "Popen") as popen:
            with self.assertRaisesRegex(ValueError, "already running"):
                self.create_baseline(self.values(), 5, log=lambda _: None)
        popen.assert_not_called()

    def test_baseline_launches_quicktest_saves_and_stops(self):
        values = self.values()
        save = Path(values["RW_BASELINE_SAVE"])
        save.parent.mkdir(parents=True)
        (save.parent / "autostart.rws").write_text("old")

        class Process:
            returncode = None
            stopped = False

            def poll(self):
                return 0 if self.stopped else None

            def terminate(self):
                self.stopped = True

            def wait(self, timeout=None):
                return 0

        process = Process()

        def fake_api(base, path, post=False, timeout=10):
            self.assertTrue(post)
            self.assertEqual(setup_dev.SAVE_ROUTE + "Fixture-Disposable", path)
            save.write_text("saved")
            return {"success": True, "path": str(save), "tick": 1}

        with patch.object(setup_dev, "running", return_value=[]), \
                patch.object(setup_dev, "api_up", return_value=False), \
                patch.object(setup_dev, "map_loaded", return_value=True), \
                patch.object(setup_dev, "api", side_effect=fake_api), \
                patch.object(setup_dev.subprocess, "Popen", return_value=process) as popen:
            self.create_baseline(values, 5, log=lambda _: None)
        command = popen.call_args.args[0]
        self.assertEqual(str(self.app / setup_dev.EXECUTABLE), command[0])
        self.assertIn("-quicktest", command)
        self.assertIn("-savedatafolder=" + values["RW_PROFILE_DIR"], command)
        self.assertFalse((save.parent / "autostart.rws").exists())
        self.assertEqual("saved", save.read_text())
        self.assertTrue(process.stopped)

    def test_baseline_failure_still_stops_the_game(self):

        class Process:
            returncode = None
            stopped = False

            def poll(self):
                return 0 if self.stopped else None

            def terminate(self):
                self.stopped = True

            def wait(self, timeout=None):
                return 0

        process = Process()
        with patch.object(setup_dev, "running", return_value=[]), \
                patch.object(setup_dev, "api_up", return_value=False), \
                patch.object(setup_dev, "map_loaded", return_value=True), \
                patch.object(setup_dev, "api", return_value={"success": False, "error": "no route"}), \
                patch.object(setup_dev.subprocess, "Popen", return_value=process):
            with self.assertRaisesRegex(ValueError, "0.1.2 or later"):
                self.create_baseline(self.values(), 5, log=lambda _: None)
        self.assertTrue(process.stopped)

    def test_map_loaded_needs_a_successful_reply_with_maps(self):
        for reply, loaded in (({"success": True, "data": [{"id": 0}]}, True),
                              ({"success": True, "data": []}, False),
                              ({"success": False, "errors": ["Game not loaded"]}, False)):
            with self.subTest(reply=reply), patch.object(setup_dev, "api", return_value=reply):
                self.assertEqual(loaded, setup_dev.map_loaded("http://localhost:1"))

    def test_unsafe_release_zip_is_rejected(self):
        bad = Path(self.temp.name) / "bad.zip"
        with zipfile.ZipFile(bad, "w") as zf:
            zf.writestr("../escape/About/About.xml", "<ModMetaData><packageId>test.helper</packageId></ModMetaData>")
        with self.assertRaises(ValueError):
            setup_dev.extract_mod(bad, Path(self.temp.name) / "out", "test.helper")


if __name__ == "__main__":
    unittest.main()
