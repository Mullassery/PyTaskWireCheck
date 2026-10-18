# Audit findings — 2026-10-19

Scope: the pending near-term roadmap item **"Richer `explain`: show exactly
which fingerprint component changed between two runs."** No other roadmap
items were started.

## What changed

- Added `diff_fingerprints(previous, current)` in
  `src/pytaskwirecheck/cache/fingerprint.py`.
  - Reports changed command, shell, cwd, timeout, input patterns, outputs,
    runtime, environment variable names (never values), dependencies, and
    inputs split into added / removed / modified.
- Added `CacheStore.load_payload(key)` and `CacheStore.latest_key(task_id)`.
- Extended `CacheStore.explain(..., against=KEY)` (and `"latest"`) to include a
  structured `diff` object.
- Added `pytaskwirecheck explain TASK --against KEY|latest` to the CLI, with a
  human-readable summary and JSON support.
- Updated `README.md`, `docs/roadmap.md`, `docs/implementation-status.md`, and
  `CHANGELOG.md`.

## Verification

```
PYTHONPATH=src python3 -m pytest -q
# 134 passed

ruff check src tests
ruff format --check src tests
# clean
```

`mypy` could not run in this environment because the installed `mypy` script
points at a missing Homebrew Python 3.11 interpreter.

## Implementation status

Implemented the mid-term roadmap item **remote cache backend**:

- `cache.remote_url` / `remote_token` / `remote_timeout_seconds` (off by default).
- Per-key tar.gz GET/PUT with bearer auth; remote failure is a local miss.
- Safe extraction (no absolute paths, `..`, symlinks, or non-file members).
- Local sha256/size verification still runs after download.
- New `tests/test_remote_cache.py` covers round-trip, token mismatch, remote
  failure isolation, and URL validation.

Verification: `PYTHONPATH=src python3 -m pytest -q` → 138 passed;
`ruff check` / `ruff format --check` clean.

## Remaining work / follow-ups

- `explain` still assumes dependency cache keys are absent; a real run's diff
  may include dependency-key changes once keys are resolved.
- The roadmap's remote cache, watch mode, structured output schema, runners,
  resource limits, plugin entry points, and graph diffing remain open.
- There is no CLI-level regression test for `--against`; coverage is at the
  cache-store and fingerprint-diff level.
