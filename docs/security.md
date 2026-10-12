# Security

## Trust model

PyTaskWireCheck runs the commands **you** put in `pytaskwirecheck.toml`. Treat that file as
code: anyone who can edit it can run arbitrary programs with your privileges.
PyTaskWireCheck does not sandbox tasks — it is an orchestrator, not a security boundary.

## What PyTaskWireCheck does to reduce risk

- **No network by default.** Nothing is uploaded or downloaded. The only network
  activity is the optional webhook notification, which is disabled by default and
  must be explicitly configured with a URL.
- **No secrets in the cache.** Environment variable *values* are hashed with
  sha256 in the fingerprint; plaintext values are never stored.
- **Path containment.** `cwd`, `inputs`, and `outputs` must be relative and must
  resolve inside the workspace root. Absolute paths and `..` escapes are rejected
  at configuration load. Cache restores are likewise confined to the root.
- **Integrity-checked restores.** Stored outputs are re-verified (sha256 + size)
  before use; a mismatch discards the entry.
- **Atomic writes.** Cache commits stage then `os.replace`, under a cross-process
  lock, so a crash cannot leave a half-written entry.
- **Local state only.** History is a local SQLite database with WAL enabled.
  Artifacts and logs live under `.pytaskwirecheck/` in your project.
- **Bounded output.** A per-task output budget prevents a runaway process from
  exhausting memory.

## Things to be careful about

- **`shell = true`** runs a single string through the shell. Avoid it with
  untrusted input; prefer an explicit argument array.
- **Undeclared inputs** can cause a *stale* cache hit, not a security issue, but
  it can mask a needed rebuild. Declare inputs or disable caching for tasks that
  read the network, the clock, or undeclared files.
- **Webhooks** send run metadata (run id, project, counts, failed task names) to
  the URL you configure. Do not point it at an untrusted endpoint. Delivery is
  best-effort and retried `max_attempts` times.
- **`--root`** is constrained to the current working directory to avoid operating
  on unintended trees.

## Reporting a vulnerability

Please do not open a public issue for security problems. Report privately via
GitHub's [Security Advisories](https://github.com/Mullassery/PyTaskWireCheck/security/advisories/new)
or email the maintainer. Include a minimal reproduction and the affected version.
We aim to acknowledge reports within a few days.
