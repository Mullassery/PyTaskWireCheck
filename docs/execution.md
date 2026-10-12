# Execution model

## Selecting what to run

`pytaskwirecheck run` with no arguments runs every task. With task names, it runs those
tasks **plus their transitive dependencies** (`resolve_targets`). Requesting an
unknown task is a graph error (exit code `3`).

## Scheduling

1. The graph is topologically sorted into levels.
2. A task becomes `READY` when all of its selected dependencies have finished
   successfully (or were served from cache).
3. Ready tasks are launched onto a thread pool bounded by
   `execution.max_workers`.
4. When a task finishes, its dependents' pending-dependency counts decrease; the
   ones that reach zero become ready.
5. Ties are broken by the graph's deterministic order, so runs are reproducible.

## Failure policy

### `fail_fast = true`

- The first failure stops the scheduler from launching any new tasks.
- In-flight tasks are cancelled (their process groups are signalled).
- Tasks that were never started are marked `CANCELLED`.

### `fail_fast = false` (default)

- Unrelated branches keep running to completion.
- The transitive dependents of the failed task are marked `BLOCKED`, because
  their inputs will never be produced.
- The run is unsuccessful overall, but PyTaskWireCheck does as much useful work as the
  graph allows.

In both modes a failed task's dependents are blocked; the difference is whether
*independent* work continues.

## Timeouts

Long-running jobs can be cut off. A final outcome of running a task with an
unknown duration is supported in three tiers:

1. `execution.default_timeout_seconds` — applies to every task.
2. `tasks.<id>.timeout_seconds` — per-task override.
3. No timeout — when neither is set.

On timeout, the task's process group is signalled, the task ends `TIMED_OUT`, and
the failure policy above applies. Timed-out tasks are never cached.

## Cancellation

PyTaskWireCheck installs signal handlers for `SIGINT`/`SIGTERM` (see
`pytaskwirecheck.processes.signals`). A signal flips a `CancellationToken`, which:

- stops launching new tasks,
- asks in-flight tasks to terminate their process groups, and
- marks not-started tasks `CANCELLED`.

`Ctrl-C` results in exit code `130`. Library users can pass their own
`CancellationToken` to `Workflow.run` to cancel cooperatively from another
thread.

## Retries

Retries are bounded by `max_attempts` (which counts the first attempt). A task
retries when it exits non-zero (or with a code listed in `retry_on_exit_codes`)
and attempts remain. Between attempts PyTaskWireCheck waits `delay_seconds`, optionally
with exponential `backoff`, capped by `max_delay_seconds`.

Each attempt runs the process journal; `RUNNING → RUNNING` across attempts is
recorded in the structured log. The final attempt decides the task status.

## Output handling

Task stdout/stderr are streamed live to the console (unless `--quiet`,
`--no-output`, or `--json` is used). Every task's output is also captured to a
per-task artifact file under `.pytaskwirecheck/`. A per-task output budget
(`max_output_bytes`, default 64 MiB) bounds memory use; excess output is
truncated with a marker rather than crashing the run.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | success |
| `1` | one or more tasks failed |
| `2` | usage or configuration error |
| `3` | graph error |
| `130` | interrupted |
