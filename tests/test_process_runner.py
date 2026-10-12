"""Process runner tests: exit codes, timeouts, cancellation, large output."""

from __future__ import annotations

import sys
import threading
import time

import pytest

from pytaskwirecheck.diagnostics.errors import ProcessStartError
from pytaskwirecheck.processes.runner import CommandSpec, run_command


def _spec(argv, cwd, **kwargs):
    return CommandSpec(
        argv=tuple(argv), cwd=cwd, env={"PATH": "/usr/bin:/bin"}, **kwargs
    )


def test_successful_command(tmp_path):
    result = run_command(_spec([sys.executable, "-c", "print('hi')"], tmp_path))
    assert result.succeeded
    assert result.exit_code == 0


def test_nonzero_exit(tmp_path):
    result = run_command(
        _spec([sys.executable, "-c", "import sys; sys.exit(3)"], tmp_path)
    )
    assert result.exit_code == 3
    assert not result.succeeded


def test_missing_executable(tmp_path):
    with pytest.raises(ProcessStartError, match="not found"):
        run_command(_spec(["definitely-not-a-real-binary-xyz"], tmp_path))


def test_permission_denied(tmp_path):
    script = tmp_path / "script.sh"
    script.write_text("#!/bin/sh\necho hi\n")
    script.chmod(0o644)
    with pytest.raises(ProcessStartError):
        run_command(_spec([str(script)], tmp_path))


def test_captures_stdout_and_stderr(tmp_path):
    chunks = []

    def cb(stream, data):
        chunks.append((stream, data))

    result = run_command(
        _spec(
            [
                sys.executable,
                "-c",
                "import sys; print('out'); print('err', file=sys.stderr)",
            ],
            tmp_path,
        ),
        on_output=cb,
    )
    assert result.succeeded
    streams = {s for s, _ in chunks}
    assert "stdout" in streams
    assert "stderr" in streams
    combined = b"".join(d for _, d in chunks)
    assert b"out" in combined and b"err" in combined


def test_large_output(tmp_path):
    total = {"bytes": 0}

    def cb(stream, data):
        total["bytes"] += len(data)

    script = "import sys; [sys.stdout.write('x'*1000) for _ in range(5000)]"
    result = run_command(_spec([sys.executable, "-c", script], tmp_path), on_output=cb)
    assert result.succeeded
    assert total["bytes"] >= 5_000_000
    assert result.output_bytes >= 5_000_000


def test_output_budget(tmp_path):
    captured = {"n": 0}

    def cb(stream, data):
        captured["n"] += len(data)

    script = "print('y' * 100000)"
    result = run_command(
        _spec(
            [sys.executable, "-c", script],
            tmp_path,
            max_output_bytes=1000,
        ),
        on_output=cb,
    )
    assert result.succeeded
    assert result.output_truncated
    assert captured["n"] <= 2000


def test_timeout(tmp_path):
    start = time.monotonic()
    result = run_command(
        _spec(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            tmp_path,
            timeout_seconds=0.5,
        )
    )
    elapsed = time.monotonic() - start
    assert result.timed_out
    assert not result.succeeded
    assert elapsed < 10


def test_cancellation(tmp_path):
    cancel = threading.Event()

    def canceller():
        time.sleep(0.3)
        cancel.set()

    thread = threading.Thread(target=canceller)
    thread.start()
    start = time.monotonic()
    result = run_command(
        _spec([sys.executable, "-c", "import time; time.sleep(30)"], tmp_path),
        cancel_event=cancel,
    )
    thread.join()
    assert result.cancelled
    assert time.monotonic() - start < 10


def test_arguments_with_spaces_and_unicode(tmp_path):
    payload = "a b\tc\u00e9"
    code = "import sys; print(sys.argv[1] == %r)" % payload
    chunks = []

    def cb(stream, data):
        chunks.append(data)

    result = run_command(
        _spec([sys.executable, "-c", code, payload], tmp_path), on_output=cb
    )
    assert result.succeeded
    assert b"True" in b"".join(chunks)


def test_working_directory(tmp_path):
    chunks = []

    def cb(stream, data):
        chunks.append(data)

    result = run_command(
        _spec(
            [sys.executable, "-c", "import os; print(os.getcwd())"],
            tmp_path,
        ),
        on_output=cb,
    )
    assert result.succeeded
    out = b"".join(chunks).decode()
    assert str(tmp_path) in out


def test_shell_opt_in(tmp_path):
    result = run_command(_spec(["echo hello && exit 0"], tmp_path, shell=True))
    assert result.succeeded


def test_environment_override(tmp_path):
    chunks = []

    def cb(stream, data):
        chunks.append(data)

    spec = CommandSpec(
        argv=(sys.executable, "-c", "import os; print(os.environ['TW_TEST'])"),
        cwd=tmp_path,
        env={"TW_TEST": "value123"},
    )
    result = run_command(spec, on_output=cb)
    assert result.succeeded
    assert b"value123" in b"".join(chunks)
