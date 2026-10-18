"""PyTaskWireCheck: local-first, dependency-aware task orchestration.

PyTaskWireCheck orchestrates work. It does not own the internals of the tools it runs.

The public API is intentionally small: load a workflow, inspect its plan, and
run it. See :mod:`pytaskwirecheck.api` for details.
"""

__version__ = "0.2.0"

from pytaskwirecheck.api import (  # noqa: E402
    Workflow,
    load_workflow,
    plan,
    run,
    validate,
)
from pytaskwirecheck.engine.scheduler import RunResult  # noqa: E402
from pytaskwirecheck.engine.state import TaskStatus  # noqa: E402
from pytaskwirecheck.graph.planner import ExecutionPlan  # noqa: E402

__all__ = [
    "__version__",
    "Workflow",
    "ExecutionPlan",
    "RunResult",
    "TaskStatus",
    "load_workflow",
    "validate",
    "plan",
    "run",
]
