# PyTaskWireCheck — Audit Findings

Audit date: 2026-10-27
Scope: full source, configuration validation, cache/remote-cache path, process
runner, webhooks, persistence, CI, and documentation
Method: read-only source/docs/CI inspection; tests were not run to avoid
generated artifacts

## Summary

PyTaskWireCheck has a clear layered design and a conservative local cache:
strict config validation, path containment, argument-array execution by default,
hashed environment values, atomic cache commits, SHA-256/size-verified restores,
process groups, bounded output recording, and a strong Python 3.9–3.13 CI
matrix.

The main issue is the opt-in shared cache. A remote response is treated as a
trusted cache entry after only a schema-version check; its metadata is not bound
to the requested key. A malicious remote can therefore place files anywhere in
the workspace and have a task reported as `CACHED`. Token handling, transfer
limits, and manifest robustness also need hardening.

| Severity | Count |
|---|---:|
| Critical | 0 |
| High | 1 |
| Medium | 2 |
| Low | 6 |

## Findings

### 1. High — Remote cache metadata is not authenticated or bound to the requested key

**Evidence**

- `src/pytaskwirecheck/cache/remote.py:54-86` downloads `<base>/<key>.tgz`,
  extracts it, and copies the result into the local entry without inspecting
  `meta.json` or authenticating the archive.
- `src/pytaskwirecheck/cache/store.py:159-166` checks only
  `meta["schema"] == CACHE_SCHEMA_VERSION`; it never checks `meta["key"]`,
  `meta["fingerprint"]`, or `meta["task_id"]` against the task/key being
  requested.
- `src/pytaskwirecheck/cache/store.py:179-214` verifies and restores artifacts
  using paths and hashes from that same untrusted `meta.json`. Artifact hashes
  prove internal consistency, not authenticity.
- Restored paths are confined to the workspace root, but not to the task's
  declared outputs.

**Impact**

A compromised shared-cache endpoint, a cache hosted by an untrusted party, or a
plain-HTTP man-in-the-middle can return an archive for any key that is currently
a local miss. The archive can declare artifact paths such as
`pytaskwirecheck.toml`, source files, or `.git/hooks/*`, overwriting them with
attacker-controlled content. The task is then marked `CACHED` without executing
its command. This can become arbitrary code execution on the next run or
commit. The remote cache is opt-in, but it is intended for teams/CI, where a
shared cache is a high-value target.

**Root cause hypothesis**

The protocol was designed as a best-effort mirror and validates artifact
integrity internally, but does not treat the remote metadata as an untrusted
claim that must be bound to the requested fingerprint.

**Recommendation**

- Recompute the canonical fingerprint hash from `meta["fingerprint"]` and
  require it to equal the requested key; require `meta["task_id"]` to match.
- Validate the manifest schema strictly: bounded list, string paths, hex
  SHA-256, integer size.
- Restrict restored paths to the task's declared outputs and reject `.git`,
  `.pytaskwirecheck`, config, and other sensitive paths.
- Add an HMAC/signature over the manifest with a shared secret, or require
  HTTPS plus a pinned endpoint. Treat all validation failures as a cache miss.

### 2. Medium — Remote bearer token can be sent in cleartext and forwarded on redirects

**Evidence**

- `src/pytaskwirecheck/cache/remote.py:38-43` accepts `http` and `https`.
- `src/pytaskwirecheck/cache/remote.py:48-52` adds an `Authorization: Bearer`
  header whenever a token is configured.
- `src/pytaskwirecheck/cache/remote.py:58-60,108` use the default
  `urllib.request.urlopen` behavior, which follows redirects. CPython's
  redirect handler copies custom headers (including `Authorization`) to the new
  request.
- `docs/caching.md:97-99` shows `remote_token` as a literal in
  `pytaskwirecheck.toml`, which is commonly version-controlled.

**Impact**

A network observer can read the token when HTTP is used. A malicious HTTPS
endpoint can redirect to another host and receive the token. A leaked token
grants read/write access to the shared cache and, combined with finding 1,
enables cache poisoning. A committed token is exposed to everyone with
repository access.

**Root cause hypothesis**

The minimal HTTP client did not include TLS enforcement, redirect policy, or
secret indirection.

**Recommendation**

Require HTTPS whenever a token is configured, disable redirects or re-send
credentials only to the original origin, reject embedded credentials, and add
environment/secret indirection such as `remote_token_env`. Redact credentials
from errors and logs.

### 3. Medium — Remote downloads, uploads, and archive extraction are unbounded

**Evidence**

- `src/pytaskwirecheck/cache/remote.py:58-61` calls `response.read()` with no
  size limit.
- `src/pytaskwirecheck/cache/remote.py:95-99` builds the entire compressed
  archive in a `BytesIO` for upload.
- `src/pytaskwirecheck/cache/remote.py:69-77` extracts the archive without
  member-count or uncompressed-size limits.
- The remote client is not given `cache.max_bytes`; the timeout is a socket
  inactivity timeout, not a total transfer/decompression budget.

**Impact**

A compromised or misconfigured remote can exhaust client memory or disk with a
huge compressed response or tar bomb, or force long decompression. Uploading a
large local entry duplicates it in memory. The local cache byte bound does not
protect the network path.

**Root cause hypothesis**

Best-effort remote code remained minimal; resource bounds were implemented for
the local cache only.

**Recommendation**

Enforce compressed and uncompressed size limits derived from `cache.max_bytes`;
limit member count; stream downloads to a temp file and uploads from a file
object; use `tarfile.extractall(..., filter="data")` (with a compatibility
fallback) in addition to manual checks; make the timeout cover total transfer
or bound total bytes.

### 4. Low — Commit lock can be broken while still held

**Evidence**

- `src/pytaskwirecheck/cache/store.py:45-46`: lock timeout is 10 seconds.
- `src/pytaskwirecheck/cache/store.py:73-80`: after the deadline, the lock file
  is unlinked and the process proceeds.
- `src/pytaskwirecheck/cache/store.py:297-308`: the lock is held during
  recursive removal of an existing entry and `os.replace`.

**Impact**

Two processes committing the same key can interleave if removal/replacement
takes longer than 10 seconds. Entries can be lost or replaced
nondeterministically. Integrity checks prevent a partial entry from being
served as a hit, so this is not a false-success path.

**Root cause hypothesis**

A fixed timeout is used as a stale-lock heuristic without owner identity or an
atomic stale-break protocol.

**Recommendation**

Record PID/start time/nonce in the lock; break only when the owner is dead and
the lock is old; prefer an OS-level lock (`fcntl.flock`/`msvcrt`) or refresh the
lock during long commits.

### 5. Low — Output budget truncates recording but does not bound process runtime

**Evidence**

- `src/pytaskwirecheck/processes/runner.py:77-109` drops bytes after the limit
  but never signals the process.
- Termination happens only on timeout or cancellation
  (`processes/runner.py:242-253`), and there is no default timeout
  (`config/schema.py:115`).

**Impact**

A command that emits unbounded output can run indefinitely when no timeout is
set. The output budget prevents unbounded memory growth, but it is not a CPU or
wall-clock limit. Task commands are trusted, so this is a resource-exhaustion
footgun rather than a sandbox issue.

**Root cause hypothesis**

The budget was intentionally modeled after build tools that truncate logs
rather than kill builds, but the documentation can be read as a stronger
control.

**Recommendation**

Document that this is a recording bound; require or strongly recommend a
timeout; optionally add `kill_on_output_limit`; warn when output is truncated.

### 6. Low — Run artifacts and JSONL logs have no retention across runs

**Evidence**

- `src/pytaskwirecheck/logging/artifacts.py:37,48-50` writes per-run task logs
  (64 MiB per task by default).
- `src/pytaskwirecheck/logging/structured.py` writes per-run JSONL logs.
- `src/pytaskwirecheck/history/store.py:116-125` prunes history rows, but no
  code prunes logs or bounds total state size.

**Impact**

Repeated large-output runs can fill `.pytaskwirecheck/`. The state directory has
no global size cap or cleanup command.

**Recommendation**

Add configurable global log-size and age retention; prune old run directories
at startup or on a schedule; include logs in inspection/cleanup commands.

### 7. Low — Webhook URL validation is scheme-agnostic and redirects are followed

**Evidence**

- `src/pytaskwirecheck/config/validation.py:350-355` only requires a non-empty
  URL when notifications are enabled.
- `src/pytaskwirecheck/notifications/webhook.py:50-57` passes the URL directly
  to `urllib.request.urlopen`, which supports non-HTTP schemes and follows
  redirects.

**Impact**

An operator-supplied URL can use an unexpected scheme or redirect to an
unintended host. Because the config is trusted, this is defense-in-depth, but it
conflicts with the documented HTTP endpoint contract.

**Recommendation**

Parse the URL, require `http`/`https`, reject credentials, disable redirects,
and optionally allowlist non-loopback targets; add tests for non-HTTP schemes
and redirects.

### 8. Low — Malformed cache metadata raises instead of becoming a miss

**Evidence**

- `src/pytaskwirecheck/cache/store.py:159-163` reads `meta["artifacts"]` without
  validating its type.
- `src/pytaskwirecheck/cache/store.py:179-181` indexes `artifact["path"]`.
- `try_restore` catches only JSON/OS errors, so `KeyError`/`TypeError`
  propagate.

**Impact**

A corrupted local entry or malicious remote can crash the run instead of being
discarded. For example, `"artifacts": [{}]` raises `KeyError`, and
`"artifacts": null` raises `TypeError`.

**Recommendation**

Validate the full manifest with defensive type checks, discard invalid entries,
treat them as misses, and add tests for missing/non-string path, non-list
artifacts, bad hashes, and oversized manifests.

### 9. Low — Security and cache documentation contradict code and CI

**Evidence**

- `docs/security.md:11-13` and `SECURITY.md:37-40` say the only network
  activity is the webhook; the remote cache also makes outbound requests.
- `SECURITY.md:7-10` lists only 0.1.x as supported; the package is 0.3.0.
- `docs/caching.md:9` says eligibility is `inputs` OR `outputs`; code requires
  outputs (`config/schema.py:98-108`).
- `docs/caching.md:45-50` documents `<key>/files/`; code uses
  `entries/<key>/artifacts/` (`cache/store.py:10-13`).
- `docs/implementation-status.md` says the cache is not shared between machines
  and reports 132/138 tests; remote cache exists and 151 tests are present.

**Impact**

Operators and auditors cannot reliably determine egress, cache eligibility,
storage layout, supported versions, or current verification status.

**Recommendation**

Update the security/cache/status docs to match code; add a docs consistency
check for version, test count, egress, eligibility, and storage layout; make
`SECURITY.md` the single source of truth for supported versions and network
behavior.

## Positive Observations

- Strict config validation and explicit path containment for `cwd`, inputs,
  outputs, and restores.
- Conservative cache policy: only successful tasks with declared outputs commit;
  missing outputs prevent a commit.
- SHA-256/size verification before restore; corrupt entries are discarded.
- Atomic local commits via staging plus `os.replace`.
- Environment values are hashed; raw task output is not stored in JSONL.
- Argument-array execution by default; shell mode is explicit.
- Process groups, timeouts, cooperative cancellation, and bounded output
  recording.
- No inbound listener; no default egress; webhook and remote cache are opt-in.
- 151 tests and CI covering Ruff, mypy, Python 3.9–3.13, build, and `twine
  check`; Dependabot and OIDC PyPI publishing.

## Verification Notes

- Working tree was clean at audit time; no source/config changes were made.
- Tests and CI were not run to avoid generated artifacts; counts are static
  observations.
- Redirect/header behavior is based on CPython `urllib` semantics and was not
  exercised against a live proxy.
- Windows archive-extraction behavior was not run on Windows; the code path was
  inspected only.
- Whether production deployments add mTLS, a VPN, or signed cache entries is
  unknown; the repository does not require them.
