#!/usr/bin/env python3
"""Check or prepare a consumer mod's disposable RimWorld development setup.

Without --apply it only reports what is ready and what is missing. With --apply
it creates the isolated profile under .runtime/, writes its ModsConfig.xml from
baseline_mods, downloads GitHub-release test mods into .runtime/mods and links
missing mods into the game's Mods folder. It never edits the normal game
profile, never deletes or replaces a real directory, and never launches the
game.
"""

import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

_spec = importlib.util.spec_from_file_location("dev_env", Path(__file__).with_name("dev-env.py"))
dev_env = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dev_env)

WORKSHOP_APP_ID = "294100"
WORKSHOP_URL = "https://steamcommunity.com/sharedfiles/filedetails/?id="
LINK_PREFIX = "dev-"
PREFS = """<?xml version="1.0" encoding="utf-8"?>
<PrefsData>
  <runInBackground>True</runInBackground>
  <pauseOnLoad>True</pauseOnLoad>
  <pauseOnError>False</pauseOnError>
  <openLogOnWarnings>False</openLogOnWarnings>
  <devMode>True</devMode>
</PrefsData>
"""


class Report:
    def __init__(self):
        self.lines = []

    def add(self, status, item, detail):
        self.lines.append((status, item, detail))

    @property
    def ready(self):
        return all(status in ("ok", "warn") for status, _, _ in self.lines)

    def print(self, stream=None):
        stream = stream or sys.stdout
        for status, item, detail in self.lines:
            print("{:5} {:32} {}".format(status, item, detail), file=stream)


def package_id(mod_dir):
    try:
        return (ET.parse(Path(mod_dir) / "About/About.xml").getroot().findtext("packageId") or "").strip().lower() or None
    except (OSError, ET.ParseError):
        return None


def scan_mods(mods_dir):
    found = {}
    if mods_dir.is_dir():
        for entry in sorted(mods_dir.iterdir()):
            pid = package_id(entry)
            if pid:
                found.setdefault(pid, []).append(entry)
    return found


def same_place(a, b):
    try:
        return Path(a).resolve() == Path(b).resolve()
    except OSError:
        return False


def game_paths(values):
    app = Path(values["RW_RIMWORLD_APP"])
    workshop = os.environ.get("RW_WORKSHOP_DIR")
    if workshop:
        workshop = Path(workshop)
    elif len(app.parents) > 2 and app.parents[1].name == "common":
        workshop = app.parents[2] / "workshop/content" / WORKSHOP_APP_ID
    return app, app / "Mods", app / "Data", workshop


def game_version(app):
    try:
        return (app / "Version.txt").read_text(encoding="utf-8-sig").split()[0]
    except (OSError, IndexError):
        return None


def mods_config(version, active):
    root = ET.Element("ModsConfigData")
    ET.SubElement(root, "version").text = version or ""
    mods = ET.SubElement(root, "activeMods")
    for pid in active:
        ET.SubElement(mods, "li").text = pid
    ET.SubElement(root, "knownExpansions")
    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


def active_mods(path):
    try:
        return [li.text.strip().lower() for li in ET.parse(path).getroot().find("activeMods") if li.text]
    except (OSError, ET.ParseError, TypeError):
        return None


def fetch_release(repo, tag, dest):
    """Download one release zip of a public GitHub repository into dest; return the zip path and tag."""
    api = "https://api.github.com/repos/" + repo + ("/releases/tags/" + tag if tag else "/releases/latest")
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "rimworld-dev-skills"}
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    with urllib.request.urlopen(urllib.request.Request(api, headers=headers), timeout=30) as response:
        release = json.load(response)
    zips = [a for a in release.get("assets", []) if a["name"].endswith(".zip")]
    if len(zips) != 1:
        raise ValueError(repo + " release " + release.get("tag_name", "?") + " needs exactly one .zip asset, found " + str(len(zips)))
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / zips[0]["name"]
    request = urllib.request.Request(zips[0]["browser_download_url"], headers={"User-Agent": "rimworld-dev-skills"})
    with urllib.request.urlopen(request, timeout=120) as response, open(target, "wb") as out:
        shutil.copyfileobj(response, out)
    return target, release["tag_name"]


def extract_mod(archive, dest, expected):
    """Extract a release zip and return the folder holding About/About.xml for the expected package."""
    with zipfile.ZipFile(archive) as zf:
        for name in zf.namelist():
            if name.startswith("/") or ".." in Path(name).parts:
                raise ValueError("Unsafe path in " + archive.name + ": " + name)
        if dest.exists():
            shutil.rmtree(dest)
        zf.extractall(dest)
    for about in sorted(dest.rglob("About/About.xml")):
        if package_id(about.parent.parent) == expected:
            return about.parent.parent
    raise ValueError(archive.name + " contains no mod with packageId " + expected)


def plan(root, values, config):
    """Return (report, actions). Actions are callables applied in order by --apply."""
    report, actions = Report(), []
    app, mods_dir, data_dir, workshop = game_paths(values)
    version = game_version(app)
    if not version:
        report.add("error", "RimWorld", "not found at " + str(app) + " (set RW_RIMWORLD_APP)")
        return report, actions
    report.add("ok", "RimWorld", version + " at " + str(app))
    if shutil.which("docker"):
        report.add("ok", "Docker", "found (builds and tests run in " + values["RW_SDK_IMAGE"] + ")")
    else:
        report.add("error", "Docker", "not found; install Docker Desktop for builds and tests")

    own = config["package_id"].lower()
    sources = {k.lower(): v for k, v in config.get("mod_sources", {}).items()}
    baseline = [pid.lower() for pid in config.get("baseline_mods", [])]
    if not baseline:
        report.add("error", "baseline_mods", "missing from .rimworld-dev.json")
        return report, actions
    installed = scan_mods(mods_dir)
    official = scan_mods(data_dir)
    runtime_mods = root / ".runtime/mods"

    def link(name, target):
        def run():
            mods_dir.mkdir(exist_ok=True)
            (mods_dir / name).symlink_to(target, target_is_directory=True)
        return run

    for pid in baseline:
        entries = installed.get(pid, [])
        source = sources.get(pid, {})
        if pid.startswith("ludeon.rimworld"):
            if pid in official:
                report.add("ok", pid, "official content")
            else:
                report.add("error", pid, "official content not installed in " + str(data_dir))
            continue
        if pid == own:
            links = [e for e in entries if not same_place(e, root) and e.is_symlink()]
            copies = [e for e in entries if not same_place(e, root) and not e.is_symlink()]
            for copy in copies:
                report.add("error", pid, "real folder " + str(copy) + " shadows this checkout; move it away")
            for other in links:
                report.add("todo", pid, "relink " + other.name + " from " + str(other.resolve()) + " to this checkout")

                def relink(other=other):
                    other.unlink()
                    other.symlink_to(root, target_is_directory=True)
                actions.append(relink)
            if not entries:
                report.add("todo", pid, "link " + LINK_PREFIX + pid + " to this checkout")
                actions.append(link(LINK_PREFIX + pid, root))
            elif not links and not copies:
                report.add("ok", pid, "this checkout via " + entries[0].name)
            continue
        if len(entries) > 1:
            report.add("warn", pid, "loaded from several folders: " + ", ".join(e.name for e in entries))
        if entries:
            report.add("ok", pid, "found at " + str(entries[0]))
            continue
        if "workshop" in source:
            item = str(source["workshop"])
            folder = workshop / item if workshop else None
            if folder and package_id(folder) == pid:
                report.add("todo", pid, "link Workshop item " + item)
                actions.append(link(LINK_PREFIX + pid, folder))
            else:
                report.add("error", pid, "subscribe to " + WORKSHOP_URL + item + " in Steam, then run again")
        elif "github_release" in source:
            repo, tag = source["github_release"], source.get("tag")
            report.add("todo", pid, "download " + repo + " release " + (tag or "latest") + " into .runtime/mods")

            def download(pid=pid, repo=repo, tag=tag):
                archive, resolved = fetch_release(repo, tag, runtime_mods / "_downloads")
                folder = extract_mod(archive, runtime_mods / (repo.split("/")[-1] + "-" + resolved), pid)
                link(LINK_PREFIX + pid, folder)()
            actions.append(download)
        else:
            report.add("error", pid, "not installed and no mod_sources entry says where to get it")

    profile = Path(values["RW_PROFILE_DIR"])
    config_file = profile / "Config/ModsConfig.xml"
    current = active_mods(config_file)
    if current == baseline:
        report.add("ok", "profile mods", "ModsConfig.xml matches baseline_mods")
    else:
        report.add("todo", "profile mods", ("write" if current is None else "reset") + " " + str(config_file.relative_to(root)))

        def write_mods():
            config_file.parent.mkdir(parents=True, exist_ok=True)
            config_file.write_text(mods_config(version, baseline), encoding="utf-8")
        actions.append(write_mods)
    prefs = profile / "Config/Prefs.xml"
    if prefs.exists():
        report.add("ok", "profile prefs", "Prefs.xml present")
    else:
        report.add("todo", "profile prefs", "write Prefs.xml with dev mode on")

        def write_prefs():
            prefs.parent.mkdir(parents=True, exist_ok=True)
            prefs.write_text(PREFS, encoding="utf-8")
        actions.append(write_prefs)
    for folder in (profile / "Saves", Path(values["RW_LOG_FILE"]).parent):
        if not folder.is_dir():
            actions.append(lambda folder=folder: folder.mkdir(parents=True, exist_ok=True))
    baseline_save = Path(values["RW_BASELINE_SAVE"])
    if baseline_save.is_file():
        report.add("ok", "baseline save", baseline_save.name)
    else:
        report.add("todo", "baseline save", baseline_save.name + " missing; create it as described in the run-rimworld-dev skill")
    return report, actions


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--apply", action="store_true", help="create the profile, download and link mods")
    args = parser.parse_args(argv)
    try:
        root = Path(args.repo_root or subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip()).resolve()
        values = dev_env.load(root)
        config = json.loads((root / ".rimworld-dev.json").read_text(encoding="utf-8"))
        report, actions = plan(root, values, config)
        if args.apply and actions and not any(s == "error" for s, i, _ in report.lines if i == "RimWorld"):
            for action in actions:
                action()
            report, _ = plan(root, values, config)
        report.print()
        if not args.apply and any(s == "todo" for s, _, _ in report.lines):
            print("\nRun again with --apply to make these changes.")
        return 0 if report.ready else 1
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError, zipfile.BadZipFile,
            subprocess.CalledProcessError) as error:
        print("Setup error: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
