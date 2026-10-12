# Architecture

PyTaskWireCheck is a layered pipeline. Each layer depends only on the one below it, and
the layers that face the user (rendering, persistence) are *observers*: they can
never change what the engine decides.

## Design rules

1. **The scheduler owns state.** No other component mutates task status.
2. **The executor owns retries and cache interaction.** The scheduler never
   touches the cache directly.
3. **The process runner owns the subprocess.** Process groups, timeouts, and
   stream handling live in one place.
4. **Observers are read-only.** CLI, TUI, logs, history, and notifications
   subscribe to events; they never influence the outcome or exit code.
5. **Invalid configuration is an error, never a guess.** Unknown fields, wrong
   types, out-of-workspace paths, and unsupported schema versions are rejected
   with an actionable location.
6. **Local-first.** Nothing is sent anywhere unless you configure a webhook.

## Layers

```
                    pytaskwirecheck.toml
                         │
                         ▼
   config ──▶ graph ──▶ planner ──▶ scheduler ──▶ executor ──▶ processes
  (schema,    (DAG,     (levels,    (bounded      (retries,   (streaming,
 validation)  builder)  order)      concurrency)  cache)      groups)
                                        │
                                        ▼
                              events ──▶ CLI / TUI / logs / history / notify
```

| Layer | Package | Responsibility |
| --- | --- | --- |
| Config | `pytaskwirecheck.config` | Parse TOML, validate strictly, produce an immutable `WorkflowConfig` |
| Graph | `pytaskwirecheck.graph` | Build the DAG, detect cycles/missing deps, compute levels and order |
| Engine | `pytaskwirecheck.engine` | Task state machine, event bus, cancellation, executor, scheduler |
| Processes | `pytaskwirecheck.processes` | Stream a subprocess safely with a timeout and cancellation |
| Cache | `pytaskwirecheck.cache` | Fingerprint tasks and store/restore outputs content-addressed |
| Render | `pytaskwirecheck.tui` | Progress reporter and optional live dashboard |
| Persist | `pytaskwirecheck.logging`, `pytaskwirecheck.history`, `pytaskwirecheck.notifications` | Artifacts, JSONL logs, SQLite history, webhooks |
| API | `pytaskwirecheck.api` | High-level, embeddable facade over all of the above |
| CLI | `pytaskwirecheck.cli` | Argument parsing, exit codes, wiring |

## Data flow of a run

```
load config ─▶ build graph ─▶ validate ─▶ resolve targets ─▶ build plan
     │
     ▼
Scheduler.run(selected)
     ├─ emit RunStarted
     ├─ pick ready tasks (no unfinished deps), up to max_workers
     ├─ submit to TaskExecutor on a bounded thread pool
     │      └─ compute fingerprint ─▶ cache hit? restore : run process (+ retries) ─▶ store
     ├─ apply outcome: mark status, unblock dependents, or block transitive dependents
     └─ emit RunFinished
     │
     ▼
observers: artifacts, structured log, reporter/TUI, history, notifications
```

## Task state machine

```
PENDING ──▶ READY ──▶ RUNNING ──▶ SUCCEEDED
                                 ├─ CACHED        (cache hit)
                                 ├─ FAILED        (non-zero exit / signal)
                                 ├─ TIMED_OUT     (exceeded timeout_seconds)
                                 └─ CANCELLED     (cancellation requested)

dependents of any failure ─────▶ BLOCKED
not started after fail-fast ───▶ CANCELLED
```

`succeeded` is true only when every selected task ends in `SUCCEEDED` or
`CACHED`. Failed, timed-out, and cancelled tasks are never cached.

## Concurrency model

- One `ThreadPoolExecutor` bounded by `execution.max_workers`.
- The scheduler thread only *orchestrates*; blocking work happens on workers.
- Subprocesses are created in their own process group so an entire task tree can
  be signalled at once (timeout and cancellation).
- Cancellation is cooperative via a `CancellationToken`; `fail_fast` cancels
  in-flight work, and unrelated branches are only allowed to finish when it is
  disabled.
- The event bus dispatches listeners synchronously; the TUI therefore mutates a
  lock-protected snapshot and redraws from a separate daemon thread so rendering
  never blocks scheduling.

## Observers and persistence

Artifacts (per-task logs), the structured JSONL log, the progress reporter, the
TUI, run history, and webhook notifications are all event subscribers. History
writes and notifications are best-effort: any failure is logged as a warning and
never changes a task's status or the process exit code.

## Extensibility

The public seams are:

- **`pytaskwirecheck.api.Workflow`** to embed the engine.
- **`on_event`** callbacks for custom progress reporting.
- **Cache backend** injection (`TaskExecutor(cache=...)`) for alternative stores.
- **Event listener** registration on the `EventBus`.

Everything else is intentionally internal and free to change.
