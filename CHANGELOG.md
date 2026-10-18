# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-10-19

### Added
- Opt-in shared cache: `cache.remote_url`, `remote_token`, and
  `remote_timeout_seconds`. Entries are pushed/pulled as per-key tar.gz
  archives over HTTP/S. Remote failures are local misses and never change a
  task result. Extraction rejects path traversal, symlinks, and non-file
  members; restored artifacts keep the existing sha256/size verification.

### Added
- `pytaskwirecheck explain TASK --against KEY|latest` diffs the current cache
  fingerprint against a stored entry and reports exactly what changed: inputs
  (added/removed/modified), environment variable names (never values),
  dependencies, command, cwd, runtime, and timeout. JSON output includes a
  structured `diff` object.

## [0.1.2] - 2026-10-18

### Added
- **LRU cache eviction.** The cache is now bounded by `cache.max_entries`
  (default 1000) and `cache.max_bytes` (default 1 GiB); after each commit the
  least-recently-used entries are evicted until both hold (an entry is "used" on a
  restore, not on write). Set either to `0` to disable that bound. New
  `pytaskwirecheck cache evict` command and `cache status` fields for the limits
  (RECHECK-060).

## [0.1.1] - 2026-10-17

### Fixed
- Audit remediation: security hardening, correctness fixes, and lint/CI gates.

## [0.1.0] - 2026-10-12

The first release: a complete, tested horizontal slice.

### Added

- **Configuration** (`pytaskwirecheck.toml`, schema version 1) with strict
  validation: unknown fields, wrong types, out-of-workspace paths, and
  unsupported versions are rejected with actionable locations.
- **Dependency graph**: `depends_on`, cycle and missing-dependency detection,
  topological levels, deterministic ordering, and a planner that reports maximum
  parallelism.
- **Scheduler**: bounded concurrency, `fail_fast` or continue-and-block,
  transitive blocking of dependents, and cancellation of not-started tasks.
- **Process runner**: streaming output, process groups, timeouts, cooperative
  cancellation, and a per-task output budget.
- **Retries**: bounded attempts with fixed or exponential backoff and
  retry-on-exit-code.
- **Content-addressed cache**: sha256 fingerprints over command, inputs,
  dependencies, relevant environment (hashed), and runtime identity; atomic
  commits; integrity-checked restores confined to the workspace root.
- **CLI**: `init`, `validate`, `graph` (text/dot/json), `plan`, `run`, `cache
  status`, `cache clean`, `explain`, and `history`, with stable exit codes.
- **TUI**: an optional live dashboard (`run --tui`) and a plain streaming
  reporter, both non-blocking observers.
- **Persistence**: local run history (SQLite, WAL) and opt-in, best-effort
  webhook notifications.
- **Python API**: `Workflow`, `load_workflow`, `validate`, `plan`, `run`, event
  callbacks, and cooperative cancellation.
- Documentation (`docs/`), CI, and a full test suite (132 tests).

[Unreleased]: https://github.com/Mullassery/PyTaskWireCheck/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Mullassery/PyTaskWireCheck/releases/tag/v0.1.0
