# PyTaskWireCheck (TaskWire) — Systems Design Audit

Audit date: 2026-10-27
Repository: `TaskWire`
Revision observed: `d6bfb7a4cdfa5f39716e3d2f56897b0b2ba53bed` (2026-10-25), working tree clean
Version: 0.3.0
License: MIT
Runtime: Python 3.9–3.13

## Overview

PyTaskWireCheck is a local-first, dependency-aware task orchestrator. It loads a
strict `pytaskwirecheck.toml`, builds a task DAG, validates it, and executes a
selected subgraph with bounded worker concurrency. Tasks are ordinary local
subprocesses, preferably argument arrays, with opt-in shell execution. Results
can be cached by content-addressed fingerprints, optionally mirrored to a shared
HTTP(S) cache. Observers (CLI reporter, TUI, per-task logs, JSONL event log,
SQLite history, and webhooks) never decide a task's outcome.

The repository contains one Python package (`pytaskwirecheck`, ~5,584 source
lines), 17 test modules, a JSON Schema for `run --json`, documentation, and CI.
There is no server, database service, plugin loader, or remote execution backend.

## Architecture

```text
CLI (cli.py) / Python API (api.py)
        |
        v
config loader -> strict validation -> immutable WorkflowConfig
        |
        v
graph builder -> validator -> planner -> Scheduler (bounded ThreadPoolExecutor)
                                      |
                                      v
                               TaskExecutor
                         (retries, cache decision)
                          |                  |
                          v                  v
                  TaskRunner            CacheStore
              (process groups,       (fingerprint, local entries,
               pipes, timeout)        LRU, optional RemoteCache)
                          |
                          v
                    EventBus -> reporter / TUI / ArtifactWriter /
                               StructuredLogger / HistoryStore / webhook
```

Documented invariants (`docs/architecture.md`):

1. The scheduler owns task-state transitions.
2. The executor owns retries and cache interaction.
3. The process runner owns subprocess lifetime and stream handling.
4. Observers are read-only and cannot change results or exit codes.
5. Invalid configuration is rejected, never guessed.
6. Local-first by default; egress requires explicit remote-cache or webhook
   configuration.

A run is a single in-process orchestration. The scheduler submits ready tasks to
a `ThreadPoolExecutor`; blocking work happens on workers. Each task process gets
its own session/process group on POSIX and a new process group on Windows, so
timeouts and cancellation can signal the descendant tree.

## Entry Points

- `pytaskwirecheck` CLI (`src/pytaskwirecheck/cli.py`): `init`, `validate`,
  `graph`, `plan`, `run`, `cache status|clean|evict`, `explain`, `history`,
  `watch` (optional `watchfiles` extra).
- Python API (`src/pytaskwirecheck/api.py`): `Workflow.from_file`,
  `from_text`, `validate`, `plan`, `run`.
- Optional live TUI (`run --tui`), plain reporter, JSON/JSONL output.
- Outbound network paths: optional `cache.remote_url` GET/PUT and optional
  webhook POST. No inbound listener.
- State paths under `<root>/.pytaskwirecheck/`: cache, logs, runs, history DB.

## Dependencies

Runtime:

- Standard library only on Python 3.11+: `subprocess`, `threading`,
  `sqlite3`, `urllib`, `tarfile`, `tomllib`, `dataclasses`.
- `tomli>=2.0` only on Python < 3.11.
- Optional `watchfiles>=0.21` for `watch`.

Development/release: `pytest`, `pytest-cov`, `ruff`, `mypy`, `build`, `twine`.
There is no runtime HTTP framework, ORM, or third-party cache library. The
small dependency surface keeps supply-chain exposure low, but the hand-rolled
remote-cache protocol carries most of the security burden.

## Module Structure

- `src/pytaskwirecheck/config/` — schema, strict TOML validation, discovery,
  root normalization.
- `src/pytaskwirecheck/graph/` — DAG model, builder, cycle/missing-dependency
  validation, planner, affected-task selection.
- `src/pytaskwirecheck/engine/` — task state machine, event bus, cancellation,
  per-task executor, parallel scheduler.
- `src/pytaskwirecheck/processes/` — subprocess runner, process groups, stream
  readers, signal installation.
- `src/pytaskwirecheck/cache/` — fingerprints, policy, local store, remote
  HTTP client.
- `src/pytaskwirecheck/logging/` — bounded per-task artifact logs and JSONL
  event logs.
- `src/pytaskwirecheck/history/` — SQLite run history.
- `src/pytaskwirecheck/notifications/` — webhook payload and delivery.
- `src/pytaskwirecheck/tui/` — plain reporter and live dashboard.
- `src/pytaskwirecheck/api.py`, `cli.py` — public facade and CLI wiring.
- `tests/` — config, graph, scheduler, process runner, cache, remote cache,
  CLI, integration, history, notifications, TUI, watch, and schema tests.

## Data, State, APIs, and Contracts

### Configuration

- Schema version 1; unknown fields, wrong types, unsupported versions, and
  out-of-workspace paths are rejected.
- Task fields: `command` (tuple/array), `depends_on`, `inputs`, `outputs`,
  `cache`, `cwd`, `env`, `inherit_env`, `timeout_seconds`, retry policy,
  `shell`, `description`, `max_output_bytes`.
- Cache settings: `enabled`, `relevant_env`, `max_bytes` (default 1 GiB),
  `max_entries` (default 1000), `remote_url`, `remote_token`,
  `remote_timeout_seconds`.
- Notifications: opt-in webhook URL, timeout, attempts, event selection.
- History: SQLite, enabled by default, 500-run retention.
- `--root` is constrained to the current working directory; task `cwd`,
  `inputs`, and `outputs` must resolve inside the project root.

### Fingerprint and cache contract

The cache key is SHA-256 over canonical JSON containing:

- cache schema version;
- task id, command, shell mode, working directory, timeout;
- relevant environment values, each SHA-256 hashed (plaintext is not stored);
- input patterns and resolved inputs (path, SHA-256, size, including missing
  patterns);
- declared outputs;
- dependency cache keys;
- runtime identity (Python version, platform, machine).

A task is cache-eligible only when `cache = true` **and** it declares at least
one output. Missing declared outputs after a successful run prevent a commit.
Only successful tasks commit entries.

Local layout:

```text
.pytaskwirecheck/cache/
  entries/<key>/meta.json
  entries/<key>/artifacts/...
  stage/
  locks/
```

Commits copy outputs into a staging directory, write `meta.json`, then rename
the directory under a per-key lock. Restores re-check every artifact's size and
SHA-256 before copying it to the workspace. Paths are resolved and must remain
inside the root.

Remote protocol:

```text
GET <base>/<key>.tgz  -> 200 + tar.gz entry, or 404
PUT <base>/<key>.tgz  -> store body
```

The archive is expected to contain `entry/meta.json` and `entry/artifacts/...`.
The remote is a best-effort mirror; a download failure is a local miss, and an
upload failure cannot change a task result. Local entries remain authoritative
when present.

### Execution and process contract

- Argument-array execution by default; `shell = true` requires one string.
- stdin is `/dev/null`; stdout/stderr are streamed by dedicated reader threads.
- POSIX: `start_new_session=True`; cancellation/timeout signals the process
  group, then escalates after a 5-second grace period.
- Windows: new process group and best-effort `taskkill /T`.
- Timeout and cooperative cancellation are polled every 50 ms.
- `max_output_bytes` limits what is recorded, not process lifetime.

### Observability and persistence

- `ArtifactWriter` writes per-task logs under
  `.pytaskwirecheck/logs/<run_id>/<task>.log`, capped at 64 MiB per task.
- `StructuredLogger` writes `.pytaskwirecheck/runs/<run_id>.jsonl`; task output
  is represented by byte counts, not contents.
- `HistoryStore` writes `.pytaskwirecheck/history.db` with WAL and 500-run
  retention.
- `run --json` emits schema version 1, mirrored by
  `schemas/run-summary.schema.json`.
- Exit codes: 0 success, 1 task failure, 2 usage/config, 3 graph, 130
  interrupted.
- Observers are event subscribers; history and notification errors are logged
  as warnings and do not change the result.

## Security Observations

### Positive controls

- Strict validation and path containment for `cwd`, inputs, outputs, and
  restore destinations; no shell by default.
- Cache restores verify size and SHA-256 and discard corrupt entries.
- Environment values are hashed in fingerprints; output is not stored in the
  JSONL event log.
- Atomic cache commits via staging plus `os.replace`.
- No inbound listener; webhook and remote cache are opt-in.
- Remote extraction rejects absolute paths, `..`, symlinks, and non-file
  members; local cache entries stay authoritative.
- Process groups and bounded output recording reduce runaway-output risk.
- CI runs Ruff, Ruff format check, mypy, tests on Python 3.9–3.13, and a build
  plus `twine check`; Dependabot covers pip and GitHub Actions.

### Risk areas

1. **Remote cache metadata is trusted without binding it to the requested
   key.** `RemoteCache.fetch` writes whatever archive the endpoint returns for
   `<key>.tgz`. `CacheStore.try_restore` checks only `meta["schema"]`, then
   verifies artifacts against hashes supplied by that same untrusted
   `meta.json`. It never checks `meta["key"]`, the fingerprint payload, or the
   task id. A malicious/compromised cache endpoint (or a plain-HTTP
   man-in-the-middle) can return an entry for a different key whose artifact
   paths overwrite files anywhere inside the workspace, then the task is marked
   `CACHED` without running its command. This is a supply-chain code-execution
   path on the next run or commit.
2. **Bearer tokens are sent over plain HTTP and across redirects.**
   `remote_url` accepts `http`, and `urllib.request.urlopen` follows redirects
   by default. CPython's redirect handler copies custom headers (including
   `Authorization`) to the new request, so a 3xx from an HTTPS endpoint can
   leak the token to another host. The token is also stored literally in
   `pytaskwirecheck.toml` with no environment-variable indirection.
3. **Remote transfer and extraction are unbounded.** `response.read()` buffers
   the whole archive, `push` builds the whole compressed archive in memory, and
   extraction accepts any decompressed size/member count. A malicious or
   misconfigured remote can exhaust memory/disk or spend excessive CPU before
   artifact verification. The 10-second timeout is a socket inactivity timeout,
   not a total transfer/decompression budget.
4. **The local commit lock is broken after 10 seconds, even if still held.**
   Large entries can take longer to remove/replace, allowing two writers to
   interleave. Integrity checks prevent a corrupt entry from being used as a
   hit, but entries can be lost or replaced nondeterministically.
5. **The output budget does not stop a process.** Once the limit is reached,
   output is dropped from recording but the process keeps running until its
   timeout or completion. With no timeout configured, a runaway command can
   consume CPU indefinitely; the documentation's "runaway process" language
   can be read as a stronger control than it is.
6. **Per-run logs have no retention bound.** Artifact logs (64 MiB per task)
   and JSONL event logs accumulate under `.pytaskwirecheck/` across runs; only
   SQLite history is pruned. Repeated large-output runs can exhaust disk.
7. **Webhook URLs are not scheme-checked or redirect-hardened.** Validation
   only requires a non-empty URL. `urllib` supports schemes beyond HTTP(S) and
   follows redirects; an operator-supplied URL can therefore target unexpected
   local or non-HTTP handlers. The config is trusted, so this is primarily
   defense-in-depth.
8. **Malformed cache manifests can crash a run instead of missing.** After the
   schema check, `artifacts` is used without type validation. `"artifacts":
   [{}]` raises `KeyError` at `artifact["path"]`; `null` or a non-list raises
   `TypeError`. The exception is not caught and is not treated as a cache miss.
9. **Security and cache documentation has drifted.** `docs/security.md` says
   the only network activity is the webhook, `SECURITY.md` lists only 0.1.x as
   supported, `docs/caching.md` says eligibility is inputs *or* outputs and
   documents a `<key>/files/` layout, while code requires outputs and uses
   `entries/<key>/artifacts/`. `docs/implementation-status.md` says the cache
   is not shared between machines and reports 132/138 tests. These conflicts
   make the security posture and cache contract hard to review.

## Findings

| Severity | Finding | Evidence | Impact | Root Cause Hypothesis | Recommendation |
|---|---|---|---|---|---|
| High | Remote cache metadata is not authenticated or bound to the requested key | `cache/remote.py:54-86` fetches and writes `<key>.tgz`; `cache/store.py:159-166` checks only `meta["schema"]`; `cache/store.py:179-214` verifies/restores artifacts using paths and hashes from that same meta; no check of `meta["key"]`, `meta["fingerprint"]`, or `meta["task_id"]` | A malicious/compromised remote, or an HTTP MITM, can serve a self-consistent archive for any cache-miss key. Artifact paths are confined to the workspace but can overwrite source, config, `.git/hooks`, or other files, and the task is marked `CACHED` without executing. This can become arbitrary code execution on the next run/commit | The remote protocol treats the archive as data to verify internally, not as an untrusted claim that must be bound to the requested fingerprint; no signing/authenticity layer exists | Recompute the canonical fingerprint hash from `meta["fingerprint"]` and require it to equal the requested key; require matching `task_id`; validate the artifact manifest with a schema; constrain restored paths to the task's declared outputs (and exclude `.git`/state/config); add an HMAC/signature over the manifest with a shared secret, or require HTTPS plus a pinned endpoint. Reject invalid metadata as a miss |
| Medium | Remote bearer token can be sent in cleartext and forwarded on redirects | `cache/remote.py:39` accepts `http` and `https`; `cache/remote.py:48-52` adds `Authorization`; `cache/remote.py:58-60,108` use default `urlopen` redirect handling; `config/validation.py:321-326` allows `http`; docs show the token inline in TOML (`docs/caching.md:97-99`) | A network observer can read the token when HTTP is used. A malicious HTTPS endpoint can redirect to another host and receive the token; the token may also be committed with the config. This grants read/write access to the shared cache | TLS enforcement and redirect policy were not part of the minimal protocol; config has no secret indirection | Require HTTPS whenever a token is configured (explicit insecure opt-in if needed); disable redirects or re-send credentials only to the original origin; reject embedded credentials; support `remote_token_env`/secret indirection; redact endpoint credentials in errors/logs |
| Medium | Remote downloads, uploads, and archive extraction have no size limits | `cache/remote.py:58-61` calls `response.read()` with no cap; `cache/remote.py:95-99` builds the full `.tgz` in a `BytesIO`; `cache/remote.py:69-77` extracts without member-count/uncompressed-size limits; `cache/store.py` never passes `max_bytes` to the remote client | A compromised or misconfigured remote can exhaust client memory/disk with a huge compressed response or tar bomb, or force long decompression; uploading a large local entry also duplicates it in memory | Best-effort remote code was kept minimal; limits were applied to the local cache but not the network path | Enforce a maximum compressed and uncompressed entry size derived from `cache.max_bytes`; count members and reject excessive counts; stream downloads to a temp file and uploads from a file object; use `tarfile.extractall(..., filter="data")` (with a fallback for older Python) in addition to manual checks; make the timeout cover total transfer or bound total bytes |
| Low | Commit lock can be broken while still held | `cache/store.py:45-46` sets a 10 s timeout; `cache/store.py:73-80` unlinks the lock after the deadline and proceeds; `cache/store.py:297-308` holds the lock during recursive removal and `os.replace` | Two processes committing the same key can interleave; entries can be lost or replaced nondeterministically. Integrity checks prevent a corrupt entry from being served as a hit, so this is not a false-success path | A fixed timeout was used as a stale-lock heuristic without owner identity or an atomic stale-break protocol | Store PID/start time/nonce in the lock; break only if the owner is dead and the lock is old; use `fcntl.flock`/`msvcrt` or an OS-level lock; refresh the lock during long commits |
| Low | Output budget truncates recording but does not bound process runtime | `processes/runner.py:77-109` drops bytes after the limit but never signals the process; `processes/runner.py:242-253` only terminates on timeout/cancel; no default timeout (`config/schema.py:115`) | A command that emits unbounded output can run forever when no timeout is set; this is a resource-exhaustion footgun rather than a sandbox escape, because task commands are trusted | The budget was intentionally designed to match build tools that truncate logs rather than kill builds | Document that it is a recording bound, not a resource limit; require or strongly recommend a timeout; optionally add `kill_on_output_limit`; surface a warning when output is truncated |
| Low | Run artifacts and JSONL logs have no retention across runs | `logging/artifacts.py:37,48-50` writes per-run logs with a 64 MiB per-task cap; `logging/structured.py` writes per-run JSONL; only history has retention (`history/store.py:116-125`) | Repeated large-output runs can fill `.pytaskwirecheck/`; the state directory has no global size cap or cleanup command | Retention was implemented for history, the user-facing index, but not for the larger raw logs | Add a configurable global state/log size cap and age-based retention; prune old run directories at startup or on a schedule; include logs in `cache`/state inspection commands |
| Low | Webhook URL validation is scheme-agnostic and redirects are followed | `config/validation.py:350-355` only checks non-empty when enabled; `notifications/webhook.py:50-57` passes the URL to `urlopen`; default redirect handling is enabled | An operator-supplied URL can use non-HTTP schemes or redirect to an unintended host; with a trusted config this is defense-in-depth, but it conflicts with the documented HTTP endpoint contract | URL validation was limited to presence; redirect policy was not considered | Parse the URL, require `http`/`https`, reject credentials, disable redirects, and optionally require an allowlist for non-loopback targets; test non-HTTP schemes and redirects |
| Low | Malformed cache metadata raises instead of becoming a miss | `cache/store.py:159-163` reads `meta["artifacts"]` without schema validation; `cache/store.py:179-181` indexes `artifact["path"]`; `try_restore` catches only JSON/OS errors | A corrupted local entry or malicious remote can crash the run with `KeyError`/`TypeError` instead of discarding the entry and executing the task | Metadata is assumed to be well-formed after the schema-version check; no schema validation or defensive type checks | Validate the full manifest (required string `path`, hex `sha256`, integer `size`, bounded list); treat any validation failure as `_discard` + cache miss; add tests for `{}`, `null`, non-list, and non-string fields |
| Low | Security and cache documentation contradict code and CI | `docs/security.md:11-13` and `SECURITY.md:37-40` say only webhooks use the network; `SECURITY.md:7-10` lists 0.1.x while `pyproject.toml` is 0.3.0; `docs/caching.md:9` says inputs OR outputs, code requires outputs (`config/schema.py:98-108`); `docs/caching.md:45-50` says `<key>/files/`, actual is `entries/<key>/artifacts/` (`cache/store.py:10-13`); `docs/implementation-status.md` says 132/138 tests and “not shared between machines” | Operators and auditors cannot reliably determine egress, cache eligibility/layout, supported versions, or current verification status; security review may miss the remote cache | Documentation evolved faster than the implementation and no consistency test links prose to code | Update all security/cache/status docs to match code; add a docs consistency check for version, test count, network egress, eligibility, and storage layout; make `SECURITY.md` the single source of truth for supported versions and egress |

## Tests and CI

- 151 tests across 17 modules (`grep -R "def test_" tests | wc -l`), covering
  config validation, graph/DAG behavior, scheduling, process runner, cache,
  remote cache, CLI/integration, history, notifications, TUI, watch mode, and
  the run-summary schema.
- CI (`.github/workflows/ci.yml`) has separate lint, typecheck, test, and build
  jobs. Tests run on Python 3.9, 3.10, 3.11, 3.12, and 3.13. Ruff runs both
  `check` and `format --check`; mypy runs against `src/pytaskwirecheck`; the
  distribution is built and checked with `twine check`.
- Dependabot covers pip and GitHub Actions weekly.
- Release workflow uses PyPI Trusted Publishing (OIDC), no stored PyPI token.
- Gaps: no Windows/macOS CI despite Windows-specific process and archive code;
  no coverage threshold; no dedicated dependency-vulnerability scan in CI
  (Dependabot only); no test that a remote entry's key/fingerprint matches the
  request; no test for malformed manifest types or redirect/token behavior; no
  test for symlink/hardlink extraction on Windows.

## Strengths

- Clear layered design with a small runtime dependency surface.
- Strict configuration validation and explicit path containment.
- Conservative caching: only successful tasks with declared outputs commit;
  missing outputs prevent a commit; size/SHA-256 checked restores.
- Atomic local cache commits and a cross-process lock (with the stale-break
  caveat above).
- Hashed environment values and no raw output in JSONL logs.
- Process groups, timeouts, cancellation, and bounded output recording.
- Local-first defaults: no listener, no default egress; remote cache and
  webhooks are explicitly opt-in.
- Deterministic scheduling/planning, stable JSON contract with a checked-in
  schema, and a strong multi-version CI matrix.

## Open Questions / Not Verified

- Whether the shared cache is deployed behind additional network controls
  (mTLS, VPN, signed artifacts) that mitigate the High finding; the repository
  itself does not require or document such controls.
- Whether `remote_token` is ever committed in real deployments; the documented
  inline configuration makes accidental disclosure plausible.
- Live behavior of 3xx redirects through corporate proxies was not exercised;
  the finding is based on CPython `urllib` semantics.
- Windows extraction behavior was not run on Windows; the platform-specific
  drive-path gap is inferred from the code path.
- Tests and CI were not executed during this audit to avoid generated artifacts.

## References

- `docs/architecture.md`
- `docs/caching.md`
- `docs/security.md`
- `docs/implementation-status.md`
- `SECURITY.md`
- `src/pytaskwirecheck/cache/remote.py`
- `src/pytaskwirecheck/cache/store.py`
- `src/pytaskwirecheck/cache/fingerprint.py`
- `src/pytaskwirecheck/processes/runner.py`
- `src/pytaskwirecheck/notifications/webhook.py`
- `src/pytaskwirecheck/config/schema.py`
- `src/pytaskwirecheck/config/validation.py`
- `schemas/run-summary.schema.json`
- `.github/workflows/ci.yml`, `.github/workflows/release.yml`
- `tests/test_remote_cache.py`
