# Roadmap

PyTaskWireCheck 0.1.0 is a complete horizontal slice. This is where it is heading;
nothing here is a commitment, and the configuration schema is versioned so that
changes can be made honestly.

## Near term

- **More runners.** First-class adapters for common ecosystems (Python virtualenv
  discovery, Node, containers) behind the existing process interface.
- **Cache eviction.** Size- and age-based pruning (`cache clean --older-than`,
  `--max-size`) on top of today's whole-cache clean.
- **Richer `explain`.** Show exactly which fingerprint component changed between
  two runs.
- **Watch mode.** Re-run the affected subgraph when inputs change.
- **Structured output.** A stable JSON schema for `run --json` across versions.

## Mid term

- **Remote cache backend.** An opt-in shared cache (the backend interface already
  exists) for teams and CI, still disabled by default and strictly opt-in.
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
