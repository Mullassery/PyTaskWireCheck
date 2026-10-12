# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
