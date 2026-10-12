"""Task state machine tests."""

from __future__ import annotations

import pytest

from pytaskwirecheck.diagnostics.errors import ExecutionError
from pytaskwirecheck.engine.state import (
    TaskRecord,
    TaskStatus,
    ensure_transition,
    is_transition_allowed,
)


def test_terminal_classification():
    assert TaskStatus.SUCCEEDED.is_terminal
    assert TaskStatus.CACHED.is_terminal
    assert not TaskStatus.RUNNING.is_terminal
    assert TaskStatus.SUCCEEDED.is_success
    assert TaskStatus.FAILED.is_failure
    assert TaskStatus.BLOCKED.is_failure


def test_allowed_forward_transition():
    ensure_transition("t", TaskStatus.PENDING, TaskStatus.READY)
    ensure_transition("t", TaskStatus.READY, TaskStatus.RUNNING)
    ensure_transition("t", TaskStatus.RUNNING, TaskStatus.SUCCEEDED)


def test_illegal_transition_from_terminal():
    with pytest.raises(ExecutionError):
        ensure_transition("t", TaskStatus.SUCCEEDED, TaskStatus.RUNNING)


def test_illegal_transition_pending_to_succeeded():
    with pytest.raises(ExecutionError):
        ensure_transition("t", TaskStatus.PENDING, TaskStatus.SUCCEEDED)


def test_ready_can_be_cached():
    assert is_transition_allowed(TaskStatus.READY, TaskStatus.CACHED)


def test_record_transition_updates_status():
    record = TaskRecord(task_id="t")
    record.transition(TaskStatus.READY)
    record.transition(TaskStatus.RUNNING)
    record.transition(TaskStatus.FAILED, message="boom")
    assert record.status is TaskStatus.FAILED
    assert record.message == "boom"
