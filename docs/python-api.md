# Python API

PyTaskWireCheck is a library first and a CLI second. The CLI is a thin shell over
`pytaskwirecheck.api`.

```python
from pytaskwirecheck import Workflow

workflow = Workflow.from_file("pytaskwirecheck.toml")
result = workflow.run()
if not result.succeeded:
    raise SystemExit(1)
```

## Constructing a workflow

```python
Workflow.from_file(path=None, *, root=None)   # path defaults to the nearest pytaskwirecheck.toml
Workflow.from_text(text, *, root=None, name="pytaskwirecheck.toml")
```

`from_text` is convenient in tests: it parses an in-memory TOML document and uses
`root` (default: the current directory) as the workspace.

## Inspecting

| Member | Returns | Description |
| --- | --- | --- |
| `workflow.config` | `WorkflowConfig` | The validated configuration |
| `workflow.graph` | `TaskGraph` | The validated DAG (built once, cached) |
| `workflow.validate()` | `ExecutionPlan` | Validate and return the full plan |
| `workflow.plan(targets=None)` | `ExecutionPlan` | Leveled plan for targets or everything |

```python
plan = workflow.plan(["test"])
print(plan.order)            # ('fetch', 'transform', 'test')
print(plan.max_parallelism)  # e.g. 2
for level in plan.levels:
    print(list(level))
```

## Running

```python
result = workflow.run(
    targets=None,            # None => every task; else targets + their dependencies
    *,
    use_cache=True,          # honour the cache (still gated by config/task settings)
    max_workers=None,        # override execution.max_workers
    fail_fast=None,          # override execution.fail_fast
    on_event=None,           # callable receiving engine events
    cancel_token=None,       # pytaskwirecheck.engine.cancellation.CancellationToken
    record_history=True,     # best-effort local history
    notify=True,             # best-effort webhook notifications
)
```

Returns a `RunResult`:

| Member | Description |
| --- | --- |
| `result.run_id` | Run identifier |
| `result.records` | `dict[str, TaskRecord]` |
| `result.duration_seconds` | Wall-clock duration |
| `result.cancelled` | Whether cancellation was requested |
| `result.succeeded` | `True` iff every task is `SUCCEEDED` or `CACHED` |
| `result.counts` | `dict[str, int]` keyed by status value |
| `result.summary()` | JSON-serialisable summary dict |

`TaskRecord` exposes `status`, `exit_code`, `attempt`, `max_attempts`,
`duration_seconds`, `cache_hit`, `cache_key`, `output_bytes`, and `message`.

## Progress events

```python
def on_event(event):
    if isinstance(event, TaskStateChanged):
        print(event.task_id, event.status.value)

workflow.run(on_event=on_event)
```

Event types: `RunStarted`, `TaskStateChanged`, `RunFinished` (plus task output
events). Subscribe directly to an `EventBus` if you need finer control.

## Functional helpers

```python
import pytaskwirecheck

pytaskwirecheck.validate(path="pytaskwirecheck.toml")     # -> ExecutionPlan
pytaskwirecheck.plan(["build"], path="pytaskwirecheck.toml")
pytaskwirecheck.run(["build"], path="pytaskwirecheck.toml", use_cache=False)
pytaskwirecheck.load_workflow(root=".")
```

## Cooperative cancellation

```python
import threading
from pytaskwirecheck.engine.cancellation import CancellationToken

token = CancellationToken()
threading.Timer(30.0, lambda: token.cancel("time budget exceeded")).start()
result = workflow.run(cancel_token=token)
if result.cancelled:
    ...
```

## Public surface

Only `pytaskwirecheck` (and `pytaskwirecheck.api`) is considered stable. Submodules are
available but may change between minor releases before 1.0.
