#!/usr/bin/env python3
"""Claude PreToolUse/Bash guard: refuse a commit or push that ships mod content
without a synchronized version bump. See the version-bump skill.

  commit on the primary branch -> must bump against HEAD; the primary branch carries releases
  commit on another branch     -> not checked, so a branch can iterate freely
  push (any branch)            -> the pushed range must contain a bump, checked against
                                  the upstream if any, else the merge base with the primary branch

Either way About/About.xml <modVersion> and the configured project's <Version> must agree.
"""

import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import xml.etree.ElementTree as ET

ABOUT = "About/About.xml"
CONFIG = ".rimworld-dev.json"
# Paths a player receives. Shared skills, agent config and docs never need a bump.
CONTENT_RE = re.compile(r"^(About/|Sources?/|[0-9]+\.[0-9]+/|Common/|Defs/|Patches/|"
                        r"Languages/|Textures/|Sounds/|Assemblies/|LoadFolders\.xml$)")
GIT_COMMAND_RE = re.compile(r"(?:^|[;&|(\s])git(?:\s+-C\s+\S+|\s+-c\s+\S+)*\s+(commit|push)(?=$|[\s;&|)])")
CORE_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)")


def git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def classify(command):
    events = [match.group(1) for match in GIT_COMMAND_RE.finditer(command)]
    if not events or "--amend" in command or "--no-verify" in command:
        return None, False
    # A chained `commit && push` is checked as the commit; HEAD does not exist yet for the push.
    event = "commit" if "commit" in events else "push"
    return event, event == "commit" and stages_all(command)


def stages_all(command):
    """True when commit -a/--all would stage tracked changes the index does not hold yet."""
    try:
        words = shlex.split(command)
    except ValueError:
        return False
    if "commit" not in words:
        return False
    for word in words[words.index("commit") + 1:]:
        if word in ("&&", "||", ";", "|"):
            break
        if word == "--all":
            return True
        if word.startswith("-") and not word.startswith("--"):
            for flag in word[1:]:
                if flag == "a":
                    return True
                if flag in "mFCctS":  # the rest of the cluster is this flag's argument
                    break
    return False


def read_at(root, revision, path):
    """revision None: working tree; ":": index; otherwise a commit-ish."""
    if revision is None:
        try:
            return (root / path).read_text(encoding="utf-8")
        except OSError:
            return None
    return git(root, "show", (revision if revision == ":" else revision + ":") + path)


def element_texts(text, tag):
    try:
        tree = ET.fromstring(text)
    except ET.ParseError:
        return None
    values = set()
    for element in tree.iter():
        # MSBuild projects may declare an XML namespace.
        if element.tag.rsplit("}", 1)[-1] == tag and element.text and element.text.strip():
            values.add(element.text.strip())
    return values


def mod_version(root, revision):
    text = read_at(root, revision, ABOUT)
    values = element_texts(text, "modVersion") if text else None
    return next(iter(values)) if values and len(values) == 1 else None


def configured_project(root):
    try:
        project = json.loads((root / CONFIG).read_text(encoding="utf-8"))["project"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(project, str) or not project or Path(project).is_absolute() or ".." in Path(project).parts:
        return None
    return project


def check(root, event, all_flag, primary_branch):
    """Return a denial reason, or None to allow."""
    branch = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if event == "commit":
        if branch != primary_branch:
            return None
        # -a commits tracked working-tree changes; otherwise the commit is exactly the index.
        changed = git(root, "diff", "--name-only", *([] if all_flag else ["--cached"]), "HEAD")
        version_rev, baseline_rev = (None if all_flag else ":"), "HEAD"
        baseline_desc, retry = "the previous commit on " + primary_branch, "commit again"
    else:
        baseline = git(root, "rev-parse", "--abbrev-ref", "@{upstream}")
        baseline_desc = baseline
        if not baseline:
            baseline = git(root, "merge-base", "HEAD", primary_branch)
            baseline_desc = "where this branch left " + primary_branch
        if not baseline:
            return None
        changed = git(root, "diff", "--name-only", baseline, "HEAD")
        version_rev, baseline_rev, retry = "HEAD", baseline, "push again"
    if not changed or not any(CONTENT_RE.match(path) for path in changed.splitlines()):
        return None

    new = mod_version(root, version_rev)
    if not new:
        return "Could not read a single <modVersion> from %s. Fix the mod metadata, then %s." % (ABOUT, retry)

    project = configured_project(root)
    if project:
        text = read_at(root, version_rev, project)
        versions = element_texts(text, "Version") if text else None
        if not versions:
            return ("Could not read <Version> from %s, the project configured in %s. Add it with the "
                    "same value as %s <modVersion> (%s), rebuild, then %s." % (project, CONFIG, ABOUT, new, retry))
        if versions != {new}:
            return ("The version fields disagree: %s says <modVersion>%s</modVersion> but %s says <Version>%s</Version>.\n\n"
                    "They must be byte-identical. Invoke the version-bump skill, set both to the same value, "
                    "rebuild, then %s." % (ABOUT, new, project, "/".join(sorted(versions)), retry))

    old = mod_version(root, baseline_rev)
    if new == old:
        return ("This %s ships mod content but the version is still %s, unchanged from %s.\n\n"
                "Invoke the version-bump skill: choose the level from what changed, set the same new version in %s%s, "
                "rebuild so the DLL carries it, then %s.\n\nIf this %s genuinely ships no player-visible change, "
                "re-run with --no-verify." % (event, new, baseline_desc, ABOUT, " and " + project if project else "",
                                               retry, event))
    old_core, new_core = (CORE_RE.match(value or "") for value in (old, new))
    if old_core and new_core and tuple(map(int, new_core.groups())) < tuple(map(int, old_core.groups())):
        return "The version moves backwards, from %s to %s. Choose a higher version, then %s." % (old, new, retry)
    return None


def primary_branch_of(root):
    remote_head = git(root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if remote_head:
        return remote_head.split("/", 1)[-1]
    return git(root, "config", "--get", "init.defaultBranch") or "main"


def main(stdin=sys.stdin, stdout=sys.stdout):
    try:
        payload = json.load(stdin)
    except ValueError:
        return 0
    event, all_flag = classify((payload.get("tool_input") or {}).get("command") or "")
    if not event:
        return 0
    top = git(Path(payload.get("cwd") or "."), "rev-parse", "--show-toplevel")
    if not top:
        return 0
    root = Path(top)
    if not (root / ABOUT).is_file() or not git(root, "rev-parse", "--verify", "--quiet", "HEAD"):
        return 0
    reason = check(root, event, all_flag, primary_branch_of(root))
    if reason:
        json.dump({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                          "permissionDecision": "deny",
                                          "permissionDecisionReason": reason}}, stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
