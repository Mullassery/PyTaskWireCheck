"""Keep the documented `run --json` schema in sync with the real summary."""

import json
from pathlib import Path

from pytaskwirecheck.engine.scheduler import (
    RUN_SUMMARY_SCHEMA_VERSION,
    RunResult,
)
from pytaskwirecheck.engine.state import TaskRecord, TaskStatus

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "run-summary.schema.json"


def _empty_result() -> RunResult:
    return RunResult(run_id="run-1", records={}, duration_seconds=0.0)


def test_summary_declares_schema_version():
    summary = _empty_result().summary()
    assert summary["schema_version"] == RUN_SUMMARY_SCHEMA_VERSION


def test_schema_matches_real_summary_shape():
    schema = json.loads(SCHEMA_PATH.read_text())
    result = RunResult(
        run_id="run-1",
        records={
            "build": TaskRecord(
                task_id="build",
                status=TaskStatus.SUCCEEDED,
                exit_code=0,
                attempt=1,
                duration_seconds=0.5,
                cache_hit=False,
                message=None,
            )
        },
        duration_seconds=0.5,
    )
    summary = result.summary()

    assert set(schema["required"]) == set(summary)
    assert schema["properties"]["schema_version"]["const"] == RUN_SUMMARY_SCHEMA_VERSION
    task_schema = schema["properties"]["tasks"]["additionalProperties"]
    assert set(task_schema["required"]) == set(summary["tasks"]["build"])
