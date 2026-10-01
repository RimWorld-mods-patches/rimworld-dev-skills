import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("dev_env", Path(__file__).with_name("dev-env.py"))
dev_env = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dev_env)


class EnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="skills space '")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "Source/Fixture").mkdir(parents=True)
        (self.root / "About").mkdir()
        (self.root / "Source/Fixture/Fixture.csproj").write_text("<Project><PropertyGroup><AssemblyName>Fixture</AssemblyName></PropertyGroup></Project>")
        (self.root / "About/About.xml").write_text("<ModMetaData><packageId>fixture.mod</packageId></ModMetaData>")
        (self.root / ".rimworld-dev.md").write_text("Fixture runtime contract")
        self.config = dict(schema_version=1, mod_name="Fixture", package_id="fixture.mod",
                           project="Source/Fixture/Fixture.csproj", sdk_image="fixture/sdk:8",
                           test_projects=[], output_dlls=["Fixture.dll"],
                           baseline_save="Fixture-Disposable", runtime_notes=".rimworld-dev.md")
        self.write_config()

    def write_config(self):
        (self.root / ".rimworld-dev.json").write_text(json.dumps(self.config))

    def test_paths_are_current_checkout_and_runtime_is_isolated(self):
        values = dev_env.load(self.root)
        self.assertEqual(str(self.root / ".runtime/rimworld-dev-profile"), values["RW_PROFILE_DIR"])
        self.assertEqual("Source/Fixture", values["RW_PROJECT_DIR"])
        self.assertEqual(str(self.root / ".runtime/rimworld-dev-profile/Saves/Fixture-Disposable.rws"), values["RW_BASELINE_SAVE"])
        self.assertFalse((self.root / ".runtime").exists())

    def test_explicit_host_overrides_are_preserved(self):
        with patch.dict(os.environ, {"RW_RIMWORLD_APP": "/opt/game location/Game.app", "RW_RIMAPI_BASE": "http://localhost:8888"}):
            values = dev_env.load(self.root)
        self.assertEqual("/opt/game location/Game.app/Contents/Resources/Data/Managed", values["RW_MANAGED"])
        self.assertEqual("http://localhost:8888", values["RW_RIMAPI_BASE"])

    def test_missing_or_mismatched_project_metadata_fails(self):
        for key, value in (("package_id", "wrong.mod"), ("output_dlls", ["Wrong.dll"]),
                           ("project", "Source/Missing.csproj"), ("schema_version", 2),
                           ("test_projects", ["Source/Missing.csproj"])):
            with self.subTest(key=key):
                original = self.config[key]
                self.config[key] = value
                self.write_config()
                with self.assertRaises((ValueError, OSError)):
                    dev_env.load(self.root)
                self.config[key] = original

    def test_external_paths_and_baseline_traversal_rejected(self):
        for key, value in (("project", "/tmp/external.csproj"), ("project", "../external.csproj"),
                           ("runtime_notes", "../external.md"), ("baseline_save", "../normal-save")):
            with self.subTest(key=key):
                original = self.config[key]
                self.config[key] = value
                self.write_config()
                with self.assertRaises(ValueError):
                    dev_env.load(self.root)
                self.config[key] = original

    def test_shell_output_is_quoted_and_cli_checks(self):
        self.config["mod_name"] = "$(exit 9) ' quoted"
        self.write_config()
        helper = str(Path(__file__).with_name("dev-env.py"))
        emitted = subprocess.check_output(["python3", helper, "--repo-root", str(self.root), "--shell"], text=True)
        result = subprocess.check_output(["sh", "-c", emitted + '\nprintf "%s" "$RW_ACTION_FILTER"'], text=True)
        self.assertEqual(self.config["mod_name"], result)
        checked = subprocess.check_output(["python3", helper, "--repo-root", str(self.root), "--check"], text=True)
        self.assertEqual(str(self.root), json.loads(checked)["RW_REPO_ROOT"])


if __name__ == "__main__":
    unittest.main()
