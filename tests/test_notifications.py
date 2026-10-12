"""Notification (webhook) tests, including a local HTTP receiver."""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from pytaskwirecheck.cli import EXIT_OK, main
from pytaskwirecheck.diagnostics.errors import ConfigError
from pytaskwirecheck.notifications.base import RunNotification
from pytaskwirecheck.notifications.webhook import WebhookNotifier

PY = sys.executable


class _Receiver:
    def __init__(self, status=200):
        self.payloads = []
        self.status = status
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                outer.payloads.append(json.loads(body.decode("utf-8")))
                self.send_response(outer.status)
                self.end_headers()

            def log_message(self, *args):
                pass

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d/hook" % self._server.server_port
        self._thread = threading.Thread(target=self._server.serve_forever)
        self._thread.daemon = True

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


def _notification(event="failure"):
    return RunNotification(
        event=event,
        run_id="abc123",
        project="demo",
        succeeded=False,
        cancelled=False,
        duration_seconds=1.25,
        counts={"failed": 1},
        failed_tasks=[{"task": "test", "status": "failed", "exit_code": 1}],
    )


def test_webhook_delivers_payload():
    with _Receiver() as receiver:
        notifier = WebhookNotifier(receiver.url, events=("failure",), max_attempts=1)
        assert notifier.send(_notification())
    assert receiver.payloads[0]["run_id"] == "abc123"
    assert receiver.payloads[0]["failed_tasks"][0]["task"] == "test"


def test_webhook_event_filter_skips():
    notifier = WebhookNotifier("http://127.0.0.1:1/hook", events=("failure",))
    assert notifier.send(_notification(event="success")) is True


def test_webhook_failure_is_best_effort():
    notifier = WebhookNotifier(
        "http://127.0.0.1:1/hook", events=("failure",), max_attempts=1
    )
    assert notifier.send(_notification()) is False
    assert notifier.errors


def test_notifications_enabled_requires_url():
    import tempfile
    from pathlib import Path

    from pytaskwirecheck.config.loader import load_config

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "pytaskwirecheck.toml"
        path.write_text(
            '[notifications]\nenabled = true\n\n[tasks.a]\ncommand = ["true"]\n'
        )
        with pytest.raises(ConfigError, match="url is required"):
            load_config(path)


def test_run_sends_failure_notification(monkeypatch, tmp_path):
    with _Receiver() as receiver:
        (tmp_path / "pytaskwirecheck.toml").write_text(
            f"""
[notifications]
enabled = true
url = "{receiver.url}"
on = ["failure"]

[tasks.bad]
command = ["{PY}", "-c", "import sys; sys.exit(1)"]
"""
        )
        monkeypatch.chdir(tmp_path)
        assert main(["run", "--quiet"]) == 1
    assert receiver.payloads
    assert receiver.payloads[0]["event"] == "failure"


def test_notification_failure_does_not_change_exit(monkeypatch, tmp_path, capsys):
    (tmp_path / "pytaskwirecheck.toml").write_text(
        f"""
[notifications]
enabled = true
url = "http://127.0.0.1:1/hook"
on = ["success"]
max_attempts = 1

[tasks.ok]
command = ["{PY}", "-c", "print('ok')"]
"""
    )
    monkeypatch.chdir(tmp_path)
    assert main(["run", "--quiet"]) == EXIT_OK
    assert "not delivered" in capsys.readouterr().err
