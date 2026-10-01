---
name: run-rimworld-dev
description: Run a configured RimWorld mod against an isolated disposable profile, autoload a test save, operate the developer UI or API, and verify behavior from logs. Use for in-game testing, debug actions, runtime faults, and save/reload checks.
---

# Run RimWorld for mod development

Read the consumer's `.rimworld-dev.json` and `.rimworld-dev.md` for active mods,
reset save, scenario setup, and required evidence. Keep usernames out of shared
skills. Resolve the current checkout and its repository-local runtime paths:

```sh
RW_REPO_ROOT="$(git rev-parse --show-toplevel)"
RW_DEV_ENV="$(python3 "$RW_REPO_ROOT/.shared/rimworld-dev-skills/scripts/dev-env.py" --shell)" && eval "$RW_DEV_ENV"
```

Stop if configuration resolution fails. The default app is the current user's
macOS Steam library; override `RW_RIMWORLD_APP` before resolution for another
install. This workflow is macOS-specific; do not run its process/UI commands on
another platform without adapting them to the verified executable.

## Isolate the profile and process

All mutable test state belongs under ignored `.runtime/`, never the user's normal
profile. Do not copy normal user saves. The profile holds disposable `Config/`,
`Saves/`, and mod data. If absent, explicitly create a developer quick-test colony
with the configured baseline mod order, save the untouched reset point at
`RW_BASELINE_SAVE`, then stop the game before testing. A clone contains the skills,
not private runtime profiles/saves. Check instrumentation is installed and enabled
in `Config/ModsConfig.xml`; a mod present in `Mods/` is not automatically active.
RIMAPI and its companion are test instrumentation, not shipped mod dependencies.
Optional-mod tests must restore the configured baseline order afterwards.

Before building, resetting saves, editing configs, or relaunching, query the exact
disposable process:

```sh
ps -axo pid=,command= | rg -F 'RimWorld by Ludeon Studios' \
  | rg -F -- "-savedatafolder=$RW_PROFILE_DIR" | rg -v '/bin/zsh -c|rg -F'
```

Verify full command lines before sending `kill -TERM` to any exact PID. Repeat
until no matching process remains. Never use `killall` or a name-only match.
macOS may retain the game after its terminal exits; Ctrl-C is not proof it stopped.
Then build through [build-mod](../build-mod/SKILL.md). Only after it stops, restore
the disposable autoload copy without overwriting the immutable reset save:

```sh
cp "$RW_BASELINE_SAVE" "$RW_PROFILE_DIR/Saves/autostart.rws"
mkdir -p "$RW_REPO_ROOT/.runtime/logs"
"$RW_RIMWORLD_APP/Contents/MacOS/RimWorld by Ludeon Studios" \
  -savedatafolder="$RW_PROFILE_DIR" -logFile "$RW_LOG_FILE"
```

Steam need not be running. Retain the launch session and verify exactly one
matching process. Preserve logs needed from the preceding run before relaunching.
Keep `-logFile`; use separate flag/path arguments. The equals-sign form
`-logFile=...` was unreliable in this macOS setup. Check command-line/profile,
loaded-mod list, native autoload message, consumer startup markers and exceptions
in the selected log; visible map readiness alone is insufficient.

App-name/bundle-ID bindings can switch to another running game. Before new UI
sessions, after unexpected screens, and after process exit, verify the disposable
PID/profile and screen again. If it is gone, send no further UI input; the window
may belong to the user's normal game.

## Prefer the API

The API starts after a colony loads, not at the main menu. Use `localhost` (the
tested macOS listener is IPv6-backed) and bypass proxies. Discover version-specific
routes with `GET /api/v1/dev/endpoints`:

```sh
curl --noproxy '*' --fail --silent --show-error --max-time 4 "$RW_RIMAPI_BASE/api/v1/game/state"
curl --noproxy '*' --fail --silent --show-error --max-time 4 "$RW_RIMAPI_BASE/api/v1/maps"
```

Read [use-rimapi-debug-actions](../use-rimapi-debug-actions/SKILL.md) before invoking
a debug action. Prefer its checked runner for supported methods; require fresh
completion/failure evidence for queued generation. HTTP success proves invocation
only. Backgrounding/locking can delay requests: foreground the verified test game
and retry a read-only request. Inspect effects before retrying a timed-out POST.

Useful routes: `game/state`, `version`, `maps`, `map/pawns?map_id=ID`,
`colonists/positions`, `map/terrain?map_id=ID`, and POST `camera/screenshot` or
`game/speed?speed=0|1|2|3`, under `/api/v1`. Check HTTP and JSON `success`;
use snake_case keys and send `{}` plus JSON content type for otherwise bodyless
POSTs so Content-Length is present. Map/pawn edits and dev endpoints are God Mode
mutations, not read-only diagnosis. The tested `game/save` route produced a null
reference; prefer native save/load UI or a consumer's dedicated action.

After arrival/reload, re-query maps, target pawns, and pause state. Resolve the
actual target map; never assume map 0 or `Find.CurrentMap` is the encounter.
Verify audits and screenshots target it. Explicitly resume for tick-based
lifecycle/movement checks and pause before inspection. Consumer notes define
which actions keep a hostile map loaded and which markers establish acceptance.

## UI fallback and verification loop

Use Computer Use bound to `ludeon.rimworld`, then confirm the disposable window.
Unity exposes little accessibility information. For an unsupported API action:
press `slash`, type the exact label, then `Tab` and `Return` only when a single
result is confirmed. Refresh state/screenshot before the next input. Use English
keyboard input; coordinates were unreliable with Retina scaling. `grave` toggles
developer logs, `F8` toggles map/world, `space` pauses, and `1`/`2`/`3` set speed.
Inspect file logs before closing an automatic error overlay. Refresh UI state if
Computer Use reports the user changed apps.

Loop: resolve config → verify stopped → build/test → restore baseline → launch
one process → confirm loaded mods/startup → invoke → await consumer evidence →
recheck map/pause → runtime assertions → stop before the next edit/build.
Never substitute a screenshot, API invocation result, or stale log event for the
consumer's generation, initialization, lifecycle, reload, and error assertions.
