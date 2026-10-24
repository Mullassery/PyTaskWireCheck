# Roadmap

> 2026-10-19 implementation findings: see [`../AUDIT_FINDINGS.md`](internal/AUDIT_FINDINGS.md).

PyTaskWireCheck 0.1.0 is a complete horizontal slice. This is where it is heading;
nothing here is a commitment, and the configuration schema is versioned so that
changes can be made honestly.

## Near term

- **More runners.** First-class adapters for common ecosystems (Python virtualenv
  discovery, Node, containers) behind the existing process interface.
- ~~**Cache eviction.** Size- and age-based pruning on top of the whole-cache
  clean.~~ Shipped in 0.1.2 as LRU `cache.max_entries`/`cache.max_bytes` and
  `cache evict`.
- ~~**Richer `explain`.** Show exactly which fingerprint component changed
  between two runs.~~ Shipped: `explain TASK --against KEY|latest` diffs the
  current fingerprint against a stored cache entry (inputs, env names, command,
  dependencies, runtime, and more).
- ~~**Watch mode.** Re-run the affected subgraph when inputs change.~~
  Shipped as `pytaskwirecheck watch` with the optional `[watch]` extra
  (`watchfiles`).
- ~~**Structured output.** A stable JSON schema for `run --json` across versions.~~ Shipped: every `run --json` summary carries `schema_version: 1` and `schemas/run-summary.schema.json`; a regression test keeps the schema in sync.

## Mid term

- ~~**Remote cache backend.** An opt-in shared cache for teams and CI.~~
  Shipped as `cache.remote_url` / `remote_token` / `remote_timeout_seconds`
  (HTTP/S GET/PUT of a per-key tar.gz). Disabled by default; failures are
  local misses and never change a task result.
- **Resource limits.** CPU/memory ceilings where the platform allows it.
- **Plugin entry points.** Discover task presets and runners via
  `importlib.metadata`.
- **Graph diffing.** Explain what a config change would re-run before running it.

## Long term

- **Distributed execution.** Farm tasks to remote workers while keeping the
  local-first default.
- **Rich TUI.** Per-task panes, scroll-back, and interactive retry.
- **Editors and integrations.** A language server for `pytaskwirecheck.toml`, plus
  GitHub Actions and pre-commit integrations.

## Explicit non-goals

- Owning your build system, package manager, or language toolchain.
- A hosted service or account. PyTaskWireCheck stays local-first.
- Being a security sandbox. Configured commands run with your privileges by
  design; see [security.md](security.md).
