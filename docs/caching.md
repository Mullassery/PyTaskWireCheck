# Caching

The cache exists to skip work whose inputs haven't changed. It is
**content-addressed**, **integrity-checked**, and deliberately **conservative**:
when PyTaskWireCheck cannot prove a task is reproducible, it does not cache.

## Eligibility

A task is cache-eligible only if it declares `inputs` **or** `outputs`. A task
with neither has unknown side effects, so PyTaskWireCheck will not guess. Eligibility is
*not* affected by `inputs` matching nothing at run time — the missing pattern is
part of the fingerprint.

A task is excluded when any of the following hold (see `pytaskwirecheck explain`):

| Reason | Cause |
| --- | --- |
| `disabled for this run (--no-cache)` | `run --no-cache` |
| `disabled in configuration` | `[cache] enabled = false` |
| `opted out by task` | `cache = false` |
| `no declared inputs or outputs` | neither `inputs` nor `outputs` present |

## Fingerprint

The cache key is a sha256 over a canonical JSON payload containing:

- `schema` — the fingerprint schema version (`CACHE_SCHEMA_VERSION`, currently `1`)
- the task id, command, shell mode, working directory, and timeout
- **relevant environment variables**, each value hashed (never stored in
  plaintext). The set is `cache.relevant_env` plus any names in the task's `env`.
- resolved `inputs`: each file's path, sha256, and size
- declared `outputs` (as expectations)
- dependency cache keys (so an upstream change invalidates downstream work)
- a small runtime identity (Python version, platform, machine)

This means a change to an input's *contents*, the command, the environment, or an
upstream fingerprint produces a different key and forces a re-run.

> **Limitation.** Anything not declared is invisible. A task that reads
> undeclared files, the network, the clock, or other nondeterminism may receive
> an incorrect cache hit. Declare inputs honestly, or set `cache = false`.

## Storage layout

```
.pytaskwirecheck/cache/
  <key>/
    meta.json        # fingerprint payload + declared outputs
    files/           # stored copies of declared outputs
```

Commits are atomic: outputs are written to a staging directory and moved into
place with `os.replace`, guarded by a cross-process lock file. A partially
written entry is never observable.

## Integrity

On restore, every stored file's **sha256 and size** are re-verified. If any file
is missing or does not match, the entry is discarded (treated as a miss) rather
than trusted. Restores are confined to the workspace root — a stored path can
never write outside the project.

`pytaskwirecheck cache status` reports the number of entries, total size, and any
corrupted entries detected.

## When writes happen

Only **successful** tasks store outputs, and only when **all** declared outputs
are present on disk after the run. Failed, timed-out, and cancelled tasks never
write cache entries. Cache writes and reads are skipped entirely when caching is
disabled for the run.

## Managing the cache

```bash
pytaskwirecheck cache status            # entries, size, corruption
pytaskwirecheck cache status --json
pytaskwirecheck cache clean             # interactive confirmation
pytaskwirecheck cache clean --force     # no prompt
pytaskwirecheck cache evict             # drop least-recently-used entries now
pytaskwirecheck explain <task>          # per-task cache decision and key
```

The cache is bounded by `cache.max_entries` (default 1000) and `cache.max_bytes`
(default 1 GiB) in `pytaskwirecheck.toml`; after each commit the least-recently-used
entries are evicted until both hold. Set either to `0` to disable that bound. An
entry counts as "used" when it is restored (a cache hit), not when written.


## Shared (remote) cache

The cache is local by default. Set a remote endpoint to share entries across
machines or CI jobs:

```toml
[cache]
remote_url = "https://cache.example.internal/taskwire"
remote_token = "..."   # optional; sent as a bearer token
remote_timeout_seconds = 10
```

Protocol: `GET <remote_url>/<key>.tgz` returns a tar.gz of a cache entry, or
404; `PUT` stores it. The archive contains `meta.json` and `artifacts/...`
exactly like the local entry. Downloads are verified with the existing
artifact sha256/size checks, and extraction rejects absolute paths, `..`
components, symlinks, and non-file entries.

Remote access is best-effort: a download failure is a local miss, and an
upload failure never changes a task's result or exit code. Local entries remain
authoritative and can be used with the remote offline.
