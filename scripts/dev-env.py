#!/usr/bin/env python3
"""Resolve a consumer mod's tracked configuration; never install or launch anything."""

import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import xml.etree.ElementTree as ET


def local_path(root, value):
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError("Expected a nonempty repository-relative path")
    resolved = (root / value).resolve()
    resolved.relative_to(root)
    return resolved


def load(root):
    root = Path(root).resolve()
    config = json.loads((root / ".rimworld-dev.json").read_text(encoding="utf-8"))
    if config.get("schema_version") != 1:
        raise ValueError("Unsupported .rimworld-dev.json schema_version")
    project = local_path(root, config["project"])
    project_xml = ET.parse(project).getroot()
    about = ET.parse(root / "About/About.xml").getroot()
    if about.findtext("packageId") != config["package_id"]:
        raise ValueError("Configured package_id does not match About/About.xml")
    if project_xml.findtext(".//AssemblyName") + ".dll" not in config["output_dlls"]:
        raise ValueError("Own assembly missing from output_dlls")
    if not all(isinstance(name, str) and name.endswith(".dll") and Path(name).name == name
               for name in config["output_dlls"]):
        raise ValueError("output_dlls must contain DLL filenames only")
    tests = config["test_projects"]
    if not isinstance(tests, list):
        raise ValueError("test_projects must be a list")
    for test in tests:
        if not local_path(root, test).is_file():
            raise ValueError("Missing test project: " + test)
    if not isinstance(config["baseline_save"], str) or not config["baseline_save"] or Path(config["baseline_save"]).name != config["baseline_save"]:
        raise ValueError("baseline_save must be a filename stem")
    notes = local_path(root, config["runtime_notes"])
    if not notes.is_file():
        raise ValueError("Missing runtime notes")
    app = os.environ.get("RW_RIMWORLD_APP") or str(Path.home() / "Library/Application Support/Steam/steamapps/common/RimWorld/RimWorldMac.app")
    profile = root / ".runtime/rimworld-dev-profile"
    return {
        "RW_REPO_ROOT": str(root),
        "RW_SHARED_ROOT": str(root / ".shared/rimworld-dev-skills"),
        "RW_PROJECT_DIR": str(project.parent.relative_to(root)),
        "RW_SDK_IMAGE": config["sdk_image"],
        "RW_NUGET_VOLUME": "rimworld-nuget",
        "RW_TEST_PROJECTS": "\n".join(tests),
        "RW_OUTPUT_DLLS": "\n".join(config["output_dlls"]),
        "RW_PROFILE_DIR": str(profile),
        "RW_LOG_FILE": str(root / ".runtime/logs/rimworld.log"),
        "RW_BASELINE_SAVE": str(profile / "Saves" / (config["baseline_save"] + ".rws")),
        "RW_RIMWORLD_APP": app,
        "RW_MANAGED": str(Path(app) / "Contents/Resources/Data/Managed"),
        "RW_RIMAPI_BASE": os.environ.get("RW_RIMAPI_BASE") or "http://localhost:8765",
        "RW_ACTION_FILTER": config["mod_name"],
        "RW_RUNTIME_NOTES": str(notes),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--shell", action="store_true", help="emit safely quoted shell assignments")
    mode.add_argument("--check", action="store_true", help="validate and print resolved config as JSON")
    args = parser.parse_args(argv)
    try:
        root = args.repo_root or subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip()
        values = load(root)
        if args.shell:
            for key, value in values.items():
                print(key + "=" + shlex.quote(value))
        else:
            print(json.dumps(values, indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError, subprocess.CalledProcessError) as error:
        print("Development configuration error: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
