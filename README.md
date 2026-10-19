<div align="center">

# PyTaskWireCheck

**Local-first, dependency-aware task orchestration for Python.**

Describe your tasks and how they depend on each other. PyTaskWireCheck works out the
order, runs independent work in parallel, retries the flaky parts, skips work
that hasn't changed, and tells you exactly why — without a server, a daemon,
or a single byte leaving your machine.

[![CI](https://github.com/Mullassery/PyTaskWireCheck/actions/workflows/ci.yml/badge.svg)](https://github.com/Mullassery/PyTaskWireCheck/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/PyTaskWireCheck.svg)](https://pypi.org/project/PyTaskWireCheck/)
[![Python versions](https://img.shields.io/pypi/pyversions/PyTaskWireCheck.svg)](https://pypi.org/project/PyTaskWireCheck/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Typed](https://img.shields.io/badge/typing-py.typed-blue.svg)](src/pytaskwirecheck/py.typed)

</div>

---

> **Not to be confused with the security tools in this family ([PyDeepMesh](https://github.com/Mullassery/PyDeepMesh), [PyDependencyCheck](https://github.com/Mullassery/PyDependencyCheck)):** despite the "Check" in its name, PyTaskWireCheck is a local task orchestrator, not a security scanner.

## Which project do I need?

Part of the Mullassery open-source family. These tools have similar names — here is the short version of who does what:

| If you need to… | Use |
| --- | --- |
| Build a repository's dependency graph and match it against vulnerability advisories (Python, Rust, Node, containers) | [PyDeepMesh](https://github.com/Mullassery/PyDeepMesh) |
| Understand *why* a Python dependency exists, who added it, and whether it is actually used | [PyDependencyCheck](https://github.com/Mullassery/PyDependencyCheck) |
| Statically analyze a **dbt** project (risky tests, test blast radius, cost) | [PyDBTGuard](https://github.com/Mullassery/PyDBTGuard) |
| Statically analyze **Apache Beam / Dataflow** pipelines (cost, hot keys, reliability) | [PyBeamGuard](https://github.com/Mullassery/PyBeamGuard) |
| Validate **Airflow** DAGs and dbt runs | [PyAirflowTester](https://github.com/Mullassery/PyAirflowTester) |
| Simulate cascading-failure **blast radius** across infrastructure, data pipelines, and AI systems | [PyBlastRadius](https://github.com/Mullassery/PyBlastRadius) |
| Check the **quality of the data itself** at runtime (schema, drift, anomalies) | [StatGuardian](https://github.com/Mullassery/StatGuardian) |
| Discover **devices, services, and vulnerabilities on a network** | [PyNetworkIntel](https://github.com/Mullassery/PyNetworkIntel) |
| Discover and score **API security** risk (real traffic, agent/MCP, Cedar policy) | [PyAPICheck](https://github.com/Mullassery/PyAPICheck) |
| Trace and root-cause **AI agent** failures | [PyAgentHound](https://github.com/Mullassery/PyAgentHound) |
| Diagnose **RAG retrieval** failures | [PyVectorHound](https://github.com/Mullassery/PyVectorHound) |
| Orchestrate **local, dependency-aware tasks** (DAG scheduler + content-addressed cache) | [PyTaskWireCheck](https://github.com/Mullassery/PyTaskWireCheck) |

[Browse all projects →](https://github.com/Mullassery?tab=repositories)

## Why PyTaskWireCheck

Most build tools want to own your project. PyTaskWireCheck does one job: it orchestrates
*other* programs. You already have the scripts, the compilers, the test runners,
the data jobs — PyTaskWireCheck just knows which ones can run at once, which must wait,
and which can be skipped because nothing they depend on has changed.

- **Local-first.** No server, no account, no telemetry. State lives in
  `.pytaskwirecheck/` inside your project.
- **Dependency-aware.** Tasks declare `depends_on`; PyTaskWireCheck topologically sorts
  them and runs every independent branch concurrently.
- **Content-addressed cache.** Tasks declare `inputs` and `outputs`. If the
  fingerprint is unchanged, the task is skipped and its outputs restored.
- **Deterministic failure handling.** `fail_fast` or continue-and-block, with a
  documented state machine — never a half-observed status.
- **Scriptable and embeddable.** A first-class CLI *and* a small Python API.
- **Zero runtime dependencies** on Python 3.11+, one tiny backport otherwise.

## Install

```bash
pip install PyTaskWireCheck
# or, for the bleeding edge:
pip install "PyTaskWireCheck @ git+https://github.com/Mullassery/PyTaskWireCheck"
```

PyTaskWireCheck targets Python **3.9 – 3.13**. The import name and the command are both
`pytaskwirecheck`.

```bash
pytaskwirecheck --version
```

## Quick start

```bash
pytaskwirecheck init            # write a starter pytaskwirecheck.toml
pytaskwirecheck validate        # check the config and the graph
pytaskwirecheck graph           # print the DAG (text, dot, or json)
pytaskwirecheck plan            # show levels, order, and max parallelism
pytaskwirecheck run             # run everything, in dependency order
```

A minimal `pytaskwirecheck.toml`:

```toml
[project]
name = "example-workflow"
version = 1

[execution]
max_workers = 4
fail_fast = false

[tasks.fetch]
command = ["python", "scripts/fetch.py"]
outputs = ["data/raw.json"]

[tasks.transform]
command = ["python", "scripts/transform.py"]
depends_on = ["fetch"]
inputs = ["data/raw.json"]
outputs = ["data/clean.parquet"]

[tasks.test]
command = ["pytest", "-q"]
depends_on = ["transform"]
```

Run it:

```console
$ pytaskwirecheck run
run 3f9c1a2b4d5e
  fetch      running
  transform  pending
  test       pending
  fetch      succeeded   0.84s
  transform  running
  transform  succeeded   1.20s
  test       running
  test       succeeded   3.05s
ok: 3 succeeded in 5.11s
```

## Features at a glance

| Area | What you get |
| --- | --- |
| **Graph** | `depends_on`, cycle detection, missing-dependency detection, topological levels |
| **Scheduling** | bounded concurrency, deterministic ordering, `fail_fast` or continue-and-block |
| **Processes** | streaming output, process groups, timeouts, cooperative cancellation, output budget |
| **Retries** | bounded attempts, fixed or exponential backoff, retry-on-exit-code |
| **Cache** | content-addressed, sha256-verified, atomic commits, corrupt-entry recovery |
| **CLI** | `init` `validate` `graph` `plan` `run` `cache` `explain` `history`, each with `--json` |
| **TUI** | optional live dashboard when attached to a TTY (`run --tui`) |
| **Persistence** | local run history (SQLite, WAL) and optional webhook notifications |
| **Library** | `Workflow.from_file(...).run()` and functional helpers |

## Audit findings

The 2026-10-19 implementation audit — including the `explain --against`
fingerprint-diff work, verification results, and remaining gaps — is recorded
in [`AUDIT_FINDINGS.md`](AUDIT_FINDINGS.md).

## Command-line reference

```
pytaskwirecheck [-C ROOT] [--config PATH] [--no-color] COMMAND ...

  init [--path DIR] [--force]     create a starter configuration
  validate [--json]               validate configuration and graph
  graph [--format text|dot|json]  display the task DAG
  plan [TASKS...] [--json]        show the execution plan
  run [TASKS...] [--no-cache] [--max-workers N] [--fail-fast|--no-fail-fast]
      [--json] [-q] [--no-output] [--tui]
  cache status [--json]           show cache statistics
  cache clean [--force] [--json]  remove cached data
  explain TASK [--against KEY|latest] [--json]
                                  explain scheduling/cache status; optionally
                                  diff against a stored fingerprint
  history [--limit N] [--json]    show recent execution summaries
```

`run` accepts task names and runs only those tasks plus their dependencies.
`run --changed --since HEAD~1` runs only tasks affected by changed files and
their dependents. Add
`--json` for a machine-readable summary, and `-q` to silence progress.

Set `cache.remote_url` (HTTP/S) to share cache entries across machines/CI; it
is off by default, best-effort, and never changes a task result. See
[`docs/caching.md`](docs/caching.md#shared-remote-cache).

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | success |
| `1` | one or more tasks failed |
| `2` | usage or configuration error |
| `3` | graph error (cycle, missing dependency, unknown target) |
| `130` | interrupted (`Ctrl-C`) |

## Python API

```python
from pytaskwirecheck import Workflow

workflow = Workflow.from_file("pytaskwirecheck.toml")

# Inspect before running.
plan = workflow.plan(["test"])
print(plan.order, plan.max_parallelism)

# Run and react to events.
def on_event(event):
    print(type(event).__name__, event)

result = workflow.run(["test"], on_event=on_event)
if not result.succeeded:
    for task_id, record in result.records.items():
        if not record.status.is_success:
            print(task_id, record.status.value, record.exit_code)

raise SystemExit(0 if result.succeeded else 1)
```

Functional helpers are available for one-liners:

```python
import pytaskwirecheck

plan = pytaskwirecheck.validate(root=".")          # -> ExecutionPlan
result = pytaskwirecheck.run(["build"], path="ci.toml")
```

`Workflow.run` supports `use_cache`, `max_workers`, `fail_fast`, `on_event`,
`cancel_token`, `record_history`, and `notify`. See
[docs/python-api.md](docs/python-api.md).

## Caching model

The cache is **content-addressed** and conservative by design:

- A task is cache-eligible only if it declares `inputs` **or** `outputs`
  (otherwise its side effects are unknown, so PyTaskWireCheck never guesses).
- The fingerprint covers the command, resolved inputs (hashing file contents),
  declared outputs' expectations, relevant environment variables, the config
  schema version, and the cache keys of upstream dependencies.
- A hit restores declared outputs, but only after verifying every stored file's
  sha256 and size; anything corrupt is discarded rather than trusted.
- Commits are atomic (staged, then `os.replace`), and protected by a
  cross-process lock. Restores are confined to the workspace root.
- Environment values are **hashed, never stored in plaintext**.

Disable it globally (`[cache] enabled = false`), per task (`cache = false`), or
per run (`pytaskwirecheck run --no-cache`). Inspect decisions with
`pytaskwirecheck explain TASK`.

Add `--against latest` (or a specific cache key) to see exactly which
fingerprint component changed — inputs added/removed/modified, environment
variables added/removed/changed (names only), dependencies, command, cwd,
runtime, and timeout. Without `--against`, the output is the same as before.

## Execution semantics

Every task moves through an explicit state machine:

```
PENDING → READY → RUNNING → SUCCEEDED | FAILED | TIMED_OUT | CACHED
                                     ↘ CANCELLED
dependents of a failure → BLOCKED
```

- **`fail_fast = true`** stops launching new tasks and cancels in-flight work as
  soon as a task fails.
- **`fail_fast = false`** lets unrelated branches finish; only the transitive
  dependents of the failed task become `BLOCKED`.
- A cancelled, timed-out, or failed task is **never cached**.
- Persistence (history, notifications) is best-effort and **never** changes a
  run's outcome or exit code.

## Architecture

```
pytaskwirecheck.toml
     │
     ▼
 config ──▶ graph ──▶ planner ──▶ scheduler ──▶ executor ──▶ processes
 (schema,   (DAG,     (levels,    (bounded      (retries,    (streaming,
 validation) builder) order)      concurrency)  cache hooks) process groups)
                                     │
                                     ▼
                              events ──▶ CLI / TUI / logs / history
```

Each layer depends only on the one below it. The scheduler owns state
transitions; the executor owns retries and cache interaction; the process runner
owns the subprocess. Rendering and persistence are observers, never participants.
Read the full design in [docs/architecture.md](docs/architecture.md).

## Documentation

| Document | Contents |
| --- | --- |
| [docs/architecture.md](docs/architecture.md) | Layers, data flow, state machine, design rules |
| [docs/configuration.md](docs/configuration.md) | Every `pytaskwirecheck.toml` field |
| [docs/execution.md](docs/execution.md) | Scheduling, retries, timeouts, cancellation |
| [docs/caching.md](docs/caching.md) | Fingerprints, storage, integrity, eviction |
| [docs/cli.md](docs/cli.md) | Commands, flags, exit codes |
| [docs/python-api.md](docs/python-api.md) | Embedding PyTaskWireCheck as a library |
| [docs/security.md](docs/security.md) | Trust model and hardening |
| [docs/development.md](docs/development.md) | Contributing, tests, tooling |
| [docs/roadmap.md](docs/roadmap.md) | Where PyTaskWireCheck is going |
| [docs/implementation-status.md](docs/implementation-status.md) | What is done and verified |

## Status

PyTaskWireCheck is **0.3.0** — a complete, tested horizontal slice: config → graph →
scheduler → runner → cache → CLI → TUI → history → notifications. See
[docs/implementation-status.md](docs/implementation-status.md) for the verified
breakdown. It is pre-1.0, so the configuration schema is versioned (`version = 1`)
and unsupported versions are rejected rather than guessed at.

## Known issues and deferred work

**Blocked / failed:**
- Watch mode; Linux/Windows wheels.

**Rejected / deferred:**
- A server/daemon.

Full shipped/blocked/rejected detail: [`QUEUE_STATUS.md`](QUEUE_STATUS.md).

## Contributing

Issues and pull requests are welcome. Start with
[CONTRIBUTING.md](CONTRIBUTING.md) and [docs/development.md](docs/development.md).
Please follow the [Code of Conduct](CODE_OF_CONDUCT.md) and report
vulnerabilities via [SECURITY.md](SECURITY.md).

## License

MIT — see [LICENSE](LICENSE).
