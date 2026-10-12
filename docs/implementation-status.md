# Implementation status

PyTaskWireCheck **0.1.0** is a complete, tested horizontal slice: configuration →
graph → scheduler → process runner → cache → CLI → TUI → history →
notifications. This page records what is implemented and how it is verified.

## Verified components

| Area | Status | Where |
| --- | --- | --- |
| Configuration schema + strict validation | ✅ Done | `config/schema.py`, `config/validation.py`, `config/loader.py` |
| DAG model, builder, cycle/missing-dep validation | ✅ Done | `graph/model.py`, `graph/builder.py`, `graph/validator.py` |
| Planner (levels, order, max parallelism) | ✅ Done | `graph/planner.py` |
| Task state machine | ✅ Done | `engine/state.py` |
| Event bus | ✅ Done | `engine/events.py` |
| Cancellation token | ✅ Done | `engine/cancellation.py` |
| Task executor (retries + cache hooks) | ✅ Done | `engine/executor.py` |
| Parallel scheduler (bounded, fail-fast, propagation) | ✅ Done | `engine/scheduler.py` |
| Streaming process runner (groups, timeout, output budget) | ✅ Done | `processes/runner.py`, `processes/signals.py` |
| Content-addressed cache (fingerprint, store, policy) | ✅ Done | `cache/` |
| CLI (`init` `validate` `graph` `plan` `run` `cache` `explain` `history`) | ✅ Done | `cli.py` |
| Plain reporter + live TUI dashboard | ✅ Done | `tui/renderer.py`, `tui/app.py` |
| Artifacts + structured JSONL logging | ✅ Done | `logging/` |
| Local history (SQLite, WAL) | ✅ Done | `history/store.py` |
| Webhook notifications (opt-in, best-effort) | ✅ Done | `notifications/` |
| Public Python API | ✅ Done | `api.py` |
| Error hierarchy | ✅ Done | `diagnostics/errors.py` |

## Verification

Run locally with:

```bash
pytest                       # 132 tests
pytest --cov=pytaskwirecheck # coverage
ruff check src tests
ruff format --check src tests
mypy src/pytaskwirecheck
```

Current status on Python 3.9:

- `pytest` — **132 passed**
- `ruff check` — clean
- `ruff format --check` — clean
- `mypy src/pytaskwirecheck` — clean
- coverage — roughly 83% of statements/branches (the scheduler, validator, and
  state machine are ≥ 95%)

## Test suite

| File | Focus |
| --- | --- |
| `test_config.py` | Schema, validation, unknown fields, path containment, versions |
| `test_graph.py` | Build, cycles, missing deps, topological order, levels |
| `test_state.py` | Legal/illegal state transitions |
| `test_process_runner.py` | Streaming, timeouts, output budget, cancellation |
| `test_scheduler.py` | Concurrency, worker limit, fail-fast, propagation |
| `test_cache.py` | Fingerprints, hits/misses, integrity, clean |
| `test_cli.py` | Every command, exit codes, JSON output |
| `test_integration.py` | End-to-end flows through `main([...])` |
| `test_history.py` | Recording, querying, pruning |
| `test_notifications.py` | Webhook selection, retries, failure isolation |
| `test_tui.py` | Dashboard snapshotting, TTY detection, truncation |
| `test_api.py` | The public Python API |

## Behavior guarantees

- Exit codes are stable: `0` success, `1` task failure, `2` usage/config,
  `3` graph, `130` interrupted.
- `fail_fast` cancels in-flight work; otherwise unrelated branches finish and
  only transitive dependents are `BLOCKED`.
- Failed, timed-out, and cancelled tasks are never cached.
- Cache restores verify sha256 + size and never escape the workspace root.
- History and notification failures never change a run's outcome or exit code.
- Environment values are hashed in the fingerprint, never stored in plaintext.

## Known limitations

- Only caching for tasks that declare `inputs`/`outputs`; undeclared inputs can
  cause stale hits (documented in [caching.md](caching.md)).
- No cache eviction beyond whole-cache clean (see [roadmap.md](roadmap.md)).
- One execution backend: local subprocesses. No distributed or container runners.
- The cache is per-project and not shared between machines.
- Dashboards require a TTY; otherwise the plain reporter is used.

## Compatibility

- Python **3.9 – 3.13**.
- No runtime dependencies on 3.11+ (`tomllib`); `tomli` on 3.9/3.10.
- Configuration schema **version 1**; unsupported versions are rejected.
- Distribution `PyTaskWireCheck`; import package and command `pytaskwirecheck`.
