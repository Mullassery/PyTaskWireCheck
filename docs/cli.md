# Command-line reference

```
pytaskwirecheck [-C ROOT] [--config PATH] [--no-color] COMMAND ...
```

Global options:

| Option | Description |
| --- | --- |
| `-C, --root ROOT` | Project root (defaults to the config file's directory) |
| `--config PATH` | Path to `pytaskwirecheck.toml` (defaults to the nearest file) |
| `--no-color` | Disable ANSI colour output |
| `--version` | Print the version and exit |

Every command below accepts `--json` where noted, which prints a machine-readable
document and nothing else.

## `init`

```bash
pytaskwirecheck init [--path DIR] [--force]
```

Writes a starter `pytaskwirecheck.toml` (a two-task example) into `DIR` (default `.`).
`--force` overwrites an existing file.

## `validate`

```bash
pytaskwirecheck validate [--json]
```

Loads the configuration, builds the graph, and validates it (cycles, missing
dependencies). Exits `0` on success, `2` for configuration errors, `3` for graph
errors.

## `graph`

```bash
pytaskwirecheck graph [--format text|dot|json]
```

Prints the DAG. `dot` output is suitable for Graphviz; `json` is a
`{"tasks": {"<id>": {"depends_on": [...]}}}` document.

## `plan`

```bash
pytaskwirecheck plan [TASKS...] [--json]
```

Shows the topological levels, the total order, and the maximum parallelism. With
task names, the plan is restricted to those tasks and their dependencies.

## `run`

```bash
pytaskwirecheck run [TASKS...] [--no-cache] [--max-workers N]
             [--fail-fast | --no-fail-fast] [--json] [-q] [--no-output] [--tui]
```

| Option | Description |
| --- | --- |
| `TASKS...` | Run these tasks and their dependencies (default: all) |
| `--no-cache` | Disable cache reads and writes for this run |
| `--max-workers N` | Override `execution.max_workers` |
| `--fail-fast` / `--no-fail-fast` | Override `execution.fail_fast` |
| `--json` | Emit a JSON run summary |
| `-q, --quiet` | Suppress progress output |
| `--no-output` | Do not stream task output |
| `--tui` | Show a live dashboard (only when stdout is a TTY) |

The `--json` summary is a versioned contract: `schema_version` is `1`, and the
full schema is committed at
[`schemas/run-summary.schema.json`](../schemas/run-summary.schema.json).

## `cache`

```bash
pytaskwirecheck cache status [--json]
pytaskwirecheck cache clean [--force] [--json]
```

`status` reports the cache location, entry count, size, and corruption. `clean`
removes all cached data; it refuses to run without `--force` in a non-interactive
session.

## `explain`

```bash
pytaskwirecheck explain TASK [--json]
```

Explains a task: its command, dependencies, inputs/outputs, retry policy, and
whether it is cache-eligible (with the reason and, when eligible, the cache key).
Because dependency cache keys are unknown until a real run, this is an
*estimate*.

## `history`

```bash
pytaskwirecheck history [--limit N] [--json]
```

Shows recent run summaries from `.pytaskwirecheck/history.db`. If no configuration can
be found, it falls back to the current directory.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | success |
| `1` | one or more tasks failed |
| `2` | usage or configuration error |
| `3` | graph error |
| `130` | interrupted |
