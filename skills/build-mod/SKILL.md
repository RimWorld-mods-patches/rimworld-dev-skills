---
name: build-mod
description: Build and test a configured RimWorld mod in Docker, and inspect installed vanilla or mod code with the bundled decompiler. Use for C# changes, compilation, regression tests, or verifying game signatures before patching.
---

# Build a RimWorld mod

Read the consumer's `.rimworld-dev.json` and `.rimworld-dev.md` first. Shared
instructions must not contain concrete usernames or mod-specific assumptions.
Resolve the current worktree, not a sibling or main checkout:

```sh
RW_REPO_ROOT="$(git rev-parse --show-toplevel)"
RW_DEV_ENV="$(python3 "$RW_REPO_ROOT/.shared/rimworld-dev-skills/scripts/dev-env.py" --shell)" && eval "$RW_DEV_ENV"
docker version --format '{{.Server.Version}}'
```

The helper emits quoted values from the tracked consumer configuration. Stop if
it fails; do not continue with unset variables. If Docker is unavailable, ask the
user to start Docker Desktop. Do not install a host SDK, Mono, MSBuild or ILSpy.
Before building, stop and verify the exact disposable game process as described
in [run-rimworld-dev](../run-rimworld-dev/SKILL.md). Restart after every DLL build;
the game does not hot-reload assemblies. Do not change normal profiles, active
mods, or installation links as an ordinary build step.

## Build and test

```sh
docker run --rm \
  -v "$RW_REPO_ROOT":/mod \
  -v "$RW_NUGET_VOLUME":/root/.nuget/packages \
  -w "/mod/$RW_PROJECT_DIR" \
  "$RW_SDK_IMAGE" dotnet build -c Release
```

The source project is authoritative for framework, pinned game references and
output location. Builds use NuGet reference assemblies, not the Steam install.
Run the consumer's `test_projects` as warranted; an empty list does not imply
tests passed. For each selected project, use:

```sh
# Set RW_TEST_PROJECT to an exact configured repository-relative .csproj path.
docker run --rm \
  -v "$RW_REPO_ROOT":/mod \
  -v "$RW_NUGET_VOLUME":/root/.nuget/packages \
  -w /mod "$RW_SDK_IMAGE" \
  dotnet run --project "$RW_TEST_PROJECT" -c Release
```

Use consumer notes for focused-test arguments and additional non-C# tests. Retain
long-running sessions until their final result. Pure tests/builds do not prove
Harmony startup, live generation, movement, or save/reload behavior.

Check the consumer's `output_dlls` allowlist. Keep game/Unity/reference DLLs out of
the output; preserve existing `PrivateAssets`/`ExcludeAssets` isolation. Some mods
intentionally ship a runtime API DLL, so do not impose an own-assembly-only rule
on all consumers. Do not commit `bin/`, `obj/`, generated assemblies or `.runtime`.
For a clean build prefer `dotnet clean`; do not erase a shared NuGet volume.

## Inspect implementation code

Prefer version-matched pre-generated vanilla source if present. Locate the
external `vanilla-decompiled` tree through workspace configuration; a managed
worktree's parent need not be the parent of the main checkout. Files can use flat
namespace-qualified names rather than namespace subdirectories. Never guess a
namespace or behavior from a symbol name. Verify the installed version against
the project reference pin before trusting a decompilation.

If source is missing/stale or belongs to an optional mod, use the bundled helper:

```sh
docker run --rm \
  -v "$RW_MANAGED":/rw:ro \
  -v "$RW_SHARED_ROOT/skills/build-mod/decompile":/decompile \
  -v "$RW_NUGET_VOLUME":/root/.nuget/packages \
  -w /decompile "$RW_SDK_IMAGE" \
  dotnet run -c Release -- /rw/Assembly-CSharp.dll RimWorld.Building_Door /rw
```

Verify `RW_MANAGED` exists first; export `RW_RIMWORLD_APP` before resolving the
environment if the game is not in the default macOS Steam library. Arguments are
`ASSEMBLY TYPE [REFERENCE_DIRECTORY ...]`. For optional mods mount their assembly
directories read-only and pass them as additional resolver paths. Assembly names
matter: a bundled `HarmonyLib.dll` need not satisfy a `0Harmony.dll` reference.
Inspect installed implementation assemblies, not stripped `Krafs.Rimworld.Ref`
method bodies. Check base classes and inherited declaring methods before Harmony
patches. Verify patch resolution with a clean game startup; compilation cannot
detect an undefined runtime Harmony target. Keep large decompiled trees external.
