# Shared RimWorld development skills

Authoritative workflows for `build-mod`, `run-rimworld-dev`, and
`use-rimapi-debug-actions`. No mod-specific project, save, event, or package IDs
belong in these skills. Never embed a concrete username or home-directory path.

## Distribution

Each mod commits this repository as a squashed Git subtree at
`.shared/rimworld-dev-skills`. Individual folders under `.agents/skills` (Codex)
and `.claude/skills` (Claude) link to the **in-repository** skill folders. No link
points to a sibling checkout, so an ordinary clone contains the entire snapshot.
Unrelated local skills remain local. On platforms checking symlinks out as text,
enable native Git symlink support or copy the bundled skill folders into the
discovery locations; the payload itself does not depend on symlinks.

Each consuming mod owns `.rimworld-dev.json` and `.rimworld-dev.md`. These select
its build project, test projects, shipped DLL allowlist, reset save, active-mod
order, and scenario-specific evidence. `scripts/dev-env.py --check` validates the
configuration against its actual project and About metadata without launching,
building, installing, or editing anything.

## Maintainer workflow

Edit and commit skills in the shared repository, then update each clean mod from
its root:

```sh
sh .shared/rimworld-dev-skills/scripts/update-subtree.sh ../rimworld-dev-skills
```

Pass the actual checkout path or a published Git URL if not using sibling
checkouts; a managed worktree need not have the same parent. The source repository
is not required for users who only consume the pinned snapshot. Subtree updates
are explicit commits, never automatic changes to every mod.

This helper uses the shared repository's `main` branch unless a second argument
selects another ref. Publish the shared repository separately when remote updates
are needed; no GitHub URL is assumed. Changes made inside a vendored snapshot
must be ported to the authoritative repository before synchronizing again.

## Validation

```sh
python3 -m unittest discover -s skills/use-rimapi-debug-actions/scripts -p 'test_*.py'
python3 -m unittest discover -s scripts -p 'test_*.py'
```

The API tests use an ephemeral loopback HTTP server, not RimWorld. Consumer
validation should include an ordinary fresh clone, all six skill links, config
resolution from a nested directory, and the tracked subtree tree matching its
pinned shared commit.

## Migration scope

| Deliverable | Scope |
| --- | --- |
| Three shared skills and existing helper programs | In scope |
| Per-mod configuration and runtime notes | In scope |
| Subtree snapshots and both agents' discovery links | In scope |
| Fresh-clone and helper verification | In scope |
| Normal game profiles, saves, installed mods, or game launches | Declined: not needed for distribution |
| Unrelated skill replacement or feature-branch merging | Declined: outside this migration |
| Publishing/pushing remote repositories | Deferred until explicitly requested |
