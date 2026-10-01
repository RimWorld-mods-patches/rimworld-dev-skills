---
name: use-rimapi-debug-actions
description: Discover, filter, and invoke supported RimWorld debug actions through RIMAPI, with checked exact selection and optional fresh log evidence for queued actions.
---

# Use the RIMAPI debug-actions API

Applies to actions from any loaded mod. Require a loaded game with RIMAPI and its
debug-actions companion enabled after it. Use the configured HTTP address/port;
default `http://localhost:8765`. The tested macOS listener is IPv6-backed: use
`localhost`, not `127.0.0.1`, and bypass proxies. Installed RIMAPI 1.10.0 mounts
`/api/v1/debug-actions/debug-actions`; discover changed versions' routes through
`GET /api/v1/dev/endpoints`, not extension-ID guesses.

## Discover

For a configured consumer, read `.rimworld-dev.json` and `.rimworld-dev.md`, then:

```sh
RW_REPO_ROOT="$(git rev-parse --show-toplevel)"
RW_DEV_ENV="$(python3 "$RW_REPO_ROOT/.shared/rimworld-dev-skills/scripts/dev-env.py" --shell)" && eval "$RW_DEV_ENV"
curl --noproxy '*' --fail-with-body --max-time 8 --get \
  --data-urlencode "filter=$RW_ACTION_FILTER" \
  "$RW_RIMAPI_BASE/api/v1/debug-actions/debug-actions"
```

Stop if environment resolution fails. `filter` is a case-insensitive substring
of name/category/assembly/declaring type/signature/ID; omit it to list everything.
The response contains `actions`, `count`, and `filter`. Records have `id`, `name`,
`category`, `assembly`, `declaring_type`, `signature`, and `is_runnable`. Use a
freshly returned ID, URL-encoded; do not derive it from the name or cache a copied
ID indefinitely. Discovery isn't confined to the consumer's own mod.

## Checked invocation

The [runner](scripts/run_debug_action.py) requires Python 3 standard library only.
It rejects missing/ambiguous/non-runnable actions before mutation, bypasses
proxies, URL-encodes IDs, sends `{}` with JSON content type/Content-Length, and
checks HTTP plus JSON `success`. Select the **exact** discovered action name;
add exact `--category` or `--assembly` if names collide.

```sh
# Set these from the actual discovered action and the consumer's evidence contract.
python3 "$RW_SHARED_ROOT/skills/use-rimapi-debug-actions/scripts/run_debug_action.py" \
  "$RW_ACTION_NAME" --base-url "$RW_RIMAPI_BASE" \
  --log-file "$RW_LOG_FILE" --wait-event "$RW_COMPLETION_REGEX" \
  --fail-event "$RW_FAILURE_REGEX" \
  --request-timeout 120 --wait-timeout 180
```

Use consumer-specific regexes, including map/site IDs when known. Serialize
mutating tests so another encounter's completion cannot satisfy the wait.
`--fail-event` is optional/repeatable; native generation and fallback can have
different terminal events. The runner snapshots the log end immediately before
POST and accepts only newly appended complete lines. Replacement/truncation
fails verification. Request and evidence-wait timeouts are separate.

For a synchronous setup action, omit log/wait options. `invoked_only` proves
invocation, not generation. Queued generation requires `--log-file` **and**
`--wait-event`; rejected generation can still return successful HTTP invocation.
Timeout/uncertain POST outcome never automatically retries. Inspect logs and
state before another mutation; a queued request can execute later after the game
resumes.

The raw endpoint is POST `.../debug-actions/run?id=URL_ENCODED_ID` with
`Content-Type: application/json` and `{}`. `success: false` is an invocation
failure even if HTTP status is 200. The extension invokes only parameterless,
static `void` `[DebugAction]` methods; menu/cell/target/instance actions can be
listed as `is_runnable: false`. Inspect category and signature before execution;
this interface runs mod code in the live game, not a safety-filtered sandbox.

## Diagnose and verify

If routes are missing, confirm both mods enabled, restart/load a game, inspect
registered endpoint paths, and distinguish 404 from timeout or an empty list.
Optional RIMAPI logging enables registration details. For absent RimWorld 1.6
actions, check companion support for `LudeonTK.DebugActionAttribute`. If locked or
backgrounded, foreground the **verified disposable** game and retry a read-only
state request before changing configuration.

Run isolated runner tests without starting RimWorld:

```sh
python3 -m unittest discover \
  -s "$RW_SHARED_ROOT/skills/use-rimapi-debug-actions/scripts" -p 'test_*.py'
```
