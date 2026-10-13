---
name: version-bump
description: Bump a configured RimWorld mod's version in About/About.xml and its assembly project together, choosing the semver level from the effect on existing saves. Use before committing mod content to the primary branch, before pushing a branch, or whenever the version guard blocks a commit or push.
---

# Bump a RimWorld mod version

Read the consumer's `.rimworld-dev.json` and `.rimworld-dev.md` first. The
configured `project` is the shipped assembly project; do not pick a test or
tooling project by filename. Consumer notes override the defaults below for
pre-1.0 policy, prerelease suffixes, and mod-specific save-breaking examples.

The version lives in **two files** that must always agree byte for byte:

| File | Field | Who reads it |
|---|---|---|
| `About/About.xml` | `<modVersion>` | `Verse.ModMetaData`, the in-game mod list, mod managers |
| configured `project` | `<Version>` | The .NET SDK, which stamps the DLL's assembly, file and informational versions |

RimWorld loads mod assemblies by path without checking their version, so
`<modVersion>` is the one players see; the DLL version traces bug reports back to
source. `<modVersion>` is free text to RimWorld, so nothing but this workflow
catches a typo. `1.1.0` and `1.1` are a mismatch even though both parse.

## Choose the level

Judge by the effect on **a player with an existing save**, not by how much code
moved. When a change spans levels, take the highest one that applies.

**MAJOR**: existing saves break or silently change meaning.
- Renaming or removing a `defName` that saves reference
- Changing a `thingClass`, comp or worker so previously scribed data no longer loads
- Removing a scribed field, building, comp or other saved object
- Removing or incompatibly changing a public API or interop contract other mods use

**MINOR**: new capability; existing saves unaffected.
- A new def, building, comp, research project, setting or gizmo
- A new `supportedVersions` entry for another RimWorld release
- A backward-compatible public API addition

**PATCH**: no new content and no save impact.
- Bug fixes, including behavior corrections to existing content
- Balance changes to costs, work amounts, power draw and similar values
- Textures, labels, descriptions, translations
- Refactors, comments, build or packaging changes that ship

Below `1.0.0`, unless consumer notes say otherwise, a breaking change bumps MINOR
and everything else bumps PATCH. Leaving 0.x for `1.0.0` is a deliberate release
decision. Ask the user instead of making it as a side effect. Preserve an
existing prerelease suffix convention (for example `-p0`) as consumer notes
describe; do not invent one.

## Apply the bump

1. Read `<modVersion>` and the configured project's `<Version>`. If they
   already disagree, report that before choosing a value.
2. Decide the level from what will be committed or pushed, not from the whole
   working tree.
3. Set the **same** new version in both files. If the project sets versions per
   configuration or through `VersionPrefix`/`VersionSuffix`, keep every effective
   value aligned with `<modVersion>`.
4. Rebuild with the [build-mod](../build-mod/SKILL.md) skill so the DLL carries
   the version. Follow the consumer's convention for committing build output;
   do not start committing generated assemblies.
5. State the level chosen and the save-compatibility reason, in one line, when
   reporting the commit.

## Version guard

`scripts/require_version_bump.py` is an optional Claude `PreToolUse` hook. A
consumer opts in from its `.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"$CLAUDE_PROJECT_DIR/.shared/rimworld-dev-skills/skills/version-bump/scripts/require_version_bump.py\"",
            "timeout": 10,
            "statusMessage": "Checking mod version bump"
          }
        ]
      }
    ]
  }
}
```

It inspects `git commit` and `git push` and acts only when shipped content
changed: `About/`, `Source/` or `Sources/`, version folders such as `1.6/`,
`Common/`, `Defs/`, `Patches/`, `Languages/`, `Textures/`, `Sounds/`,
`Assemblies/`, or `LoadFolders.xml`. Shared skills, agent configuration, and
docs never need a bump.

| Situation | Enforced? | Baseline |
|---|---|---|
| `git commit` on the primary branch | Yes | `HEAD`. Every content commit carries its own bump |
| `git commit` on another branch | No | Branches iterate freely; the gate is at push |
| `git push` | Yes | The upstream if set, else the merge base with the primary branch. One bump covers the branch |

The primary branch is `origin/HEAD`, else `init.defaultBranch`, else `main`.
The guard checks the index, or the working tree for `commit -a`. It also denies a
disagreement between the two files, a missing project `<Version>`, and a version
that moves backwards. Without `.rimworld-dev.json` it checks `About.xml` only.

`--amend` and `--no-verify` bypass it. Use `--no-verify` only when the content
change genuinely ships no player-visible difference, and say so. Do not bypass
it just to avoid choosing a version. Codex has no equivalent hook; follow this
skill manually there.
