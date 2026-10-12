# Configuration reference

PyTaskWireCheck reads a single `pytaskwirecheck.toml`, discovered by walking upward from the
current directory (or given explicitly with `--config`). The file is validated
strictly: **unknown fields are errors**, not ignored.

## Complete example

```toml
[project]
name = "example-workflow"
version = 1

[execution]
max_workers = 4
default_timeout_seconds = 900
fail_fast = false

[cache]
enabled = true
relevant_env = ["PATH", "PYTHONPATH", "TZ"]

[history]
enabled = true
max_runs = 500

[notifications]
enabled = false
url = ""
timeout_seconds = 5.0
max_attempts = 2
on = ["failure"]

[tasks.fetch]
command = ["python", "scripts/fetch.py"]
outputs = ["data/raw.json"]
timeout_seconds = 120
retry = { max_attempts = 3, delay_seconds = 2, backoff = true }

[tasks.transform]
command = ["python", "scripts/transform.py"]
depends_on = ["fetch"]
inputs = ["data/raw.json"]
outputs = ["data/clean.parquet"]
env = { MODE = "prod" }

[tasks.test]
command = ["pytest", "-q"]
depends_on = ["transform"]
cache = false
```

## `[project]`

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `name` | string | directory name | Used in reports and history |
| `version` | integer | `1` | Configuration schema version; only `1` is supported |
| `root` | string | config directory | Workspace root; must stay inside the working directory |

An unsupported `version` raises `ConfigVersionError` rather than being ignored.

## `[execution]`

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `max_workers` | integer ≥ 1 | `1` | Upper bound is 256 |
| `default_timeout_seconds` | number > 0 | none | Applied to tasks without their own timeout |
| `fail_fast` | boolean | `false` | Stop launching after the first failure |

## `[cache]`

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `enabled` | boolean | `true` | Global cache switch |
| `relevant_env` | array of strings | `PATH, PYTHONPATH, PYTHONHASHSEED, LANG, LC_ALL, TZ` | Environment variables folded into the fingerprint |

See [caching.md](caching.md).

## `[history]`

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `enabled` | boolean | `true` | Record run summaries in `.pytaskwirecheck/history.db` |
| `max_runs` | integer ≥ 1 | `500` | Retained runs; older rows are pruned |

## `[notifications]`

Disabled by default. When enabled, `url` is required. Delivery is best-effort
and never affects the run outcome.

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `enabled` | boolean | `false` | Master switch |
| `url` | string | `""` | Webhook endpoint |
| `timeout_seconds` | number > 0 | `5.0` | Per-request timeout |
| `max_attempts` | integer ≥ 1 | `2` | Delivery attempts |
| `on` | array of `start`/`success`/`failure` | `["failure"]` | Events that trigger a notification |

## `[tasks.<id>]`

Task identifiers may contain letters, digits, `.`, `-`, and `_`.

| Key | Type | Default | Notes |
| --- | --- | --- | --- |
| `command` | array of strings | — | **Required.** Program and arguments |
| `depends_on` | array of strings | `[]` | Must reference other tasks; no self-deps or duplicates |
| `inputs` | array of strings | `[]` | Globs, relative to the root; hashed for the cache |
| `outputs` | array of strings | `[]` | Paths, relative to the root; restored on a cache hit |
| `cache` | boolean | `true` | Per-task opt-out |
| `cwd` | string | root | Working directory, relative to the root |
| `env` | table of strings | `{}` | Extra environment variables |
| `inherit_env` | boolean | `true` | Whether to start from the parent environment |
| `timeout_seconds` | number > 0 | execution default | Per-task timeout |
| `shell` | boolean | `false` | When `true`, `command` must be a single string run by the shell |
| `description` | string | `""` | Shown by `pytaskwirecheck explain` |
| `max_output_bytes` | integer ≥ 1 | `64 MiB` | Per-task output budget before truncation |

### Retries

Either a table or a shorthand integer:

```toml
retries = 2                       # shorthand: 2 retries after the first attempt

[tasks.build.retry]
max_attempts = 3                  # counts the first attempt
delay_seconds = 2.0
backoff = true                    # exponential: delay * 2^(attempt-2)
max_delay_seconds = 60.0
retry_on_exit_codes = [5, 6]      # default: any non-zero exit code
```

## Path rules

- Every path (`cwd`, `inputs`, `outputs`) must be **relative** to the project
  root and must resolve **inside** it. Absolute paths and `..` escapes are
  rejected at load time.
- The root itself must reside inside the current working directory (a
  containment check that also constrains `--root`).

## Environment variables that affect PyTaskWireCheck

| Variable | Effect |
| --- | --- |
| `NO_COLOR` | Disables ANSI colour (also `--no-color`) |
| `COLUMNS` / `LINES` | Hint the dashboard/report width and height |
