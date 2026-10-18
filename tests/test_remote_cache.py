"""Opt-in shared-cache tests: push/pull, auth, and failure isolation."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from pytaskwirecheck.cache.policy import build_store
from pytaskwirecheck.cache.remote import RemoteCache
from pytaskwirecheck.config.loader import load_config

CONFIG = """
[project]
name = "remote-demo"
version = 1

[cache]
remote_url = "{url}"
remote_token = "{token}"

[tasks.build]
command = ["python3", "-c", "open('out.txt','w').write(open('src.txt').read().upper())"]
inputs = ["src.txt"]
outputs = ["out.txt"]
cache = true
"""


class _Handler(BaseHTTPRequestHandler):
    blobs: dict = {}
    token = "secret"

    def log_message(self, *_args):  # keep test output quiet
        pass

    def do_GET(self):
        if self.headers.get("Authorization") != "Bearer %s" % self.token:
            self.send_response(401)
            self.end_headers()
            return
        key = self.path.rsplit("/", 1)[-1].removesuffix(".tgz")
        payload = self.blobs.get(key)
        if payload is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/gzip")
        self.end_headers()
        self.wfile.write(payload)

    def do_PUT(self):
        if self.headers.get("Authorization") != "Bearer %s" % self.token:
            self.send_response(401)
            self.end_headers()
            return
        key = self.path.rsplit("/", 1)[-1].removesuffix(".tgz")
        length = int(self.headers.get("Content-Length", "0"))
        self.blobs[key] = self.rfile.read(length)
        self.send_response(201)
        self.end_headers()


def _serve():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, "http://127.0.0.1:%d" % server.server_address[1]


def _project(root: Path, url: str, token: str):
    (root / "pytaskwirecheck.toml").write_text(
        CONFIG.format(url=url, token=token), encoding="utf-8"
    )
    (root / "src.txt").write_text("hello")
    return load_config(root / "pytaskwirecheck.toml")


def test_remote_cache_round_trip(tmp_path):
    server, url = _serve()
    try:
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.mkdir()
        b.mkdir()
        config_a = _project(a, url, "secret")
        config_b = _project(b, url, "secret")

        task_a = config_a.get("build")
        (a / "out.txt").write_text("HELLO")
        store_a = build_store(config_a)
        key = store_a.store(task_a, {})
        assert key is not None
        assert _Handler.blobs

        task_b = config_b.get("build")
        store_b = build_store(config_b)
        restored = store_b.try_restore(task_b, {})
        assert restored == key
        assert (b / "out.txt").read_text() == "HELLO"
    finally:
        server.shutdown()


def test_remote_cache_requires_matching_token(tmp_path):
    server, url = _serve()
    try:
        a = tmp_path / "a"
        b = tmp_path / "b"
        a.mkdir()
        b.mkdir()
        config_a = _project(a, url, "secret")
        (a / "out.txt").write_text("HELLO")
        key = build_store(config_a).store(config_a.get("build"), {})
        assert key is not None

        config_b = _project(b, url, "wrong")
        assert build_store(config_b).try_restore(config_b.get("build"), {}) is None
        assert not (b / "out.txt").exists()
    finally:
        server.shutdown()


def test_remote_cache_failure_does_not_break_local_cache(tmp_path):
    # Port 1 is not a listening HTTP server in the test environment.
    config = _project(tmp_path, "http://127.0.0.1:1", "secret")
    (tmp_path / "out.txt").write_text("LOCAL")
    key = build_store(config).store(config.get("build"), {})
    assert key is not None

    # A fresh store still restores from the local entry even though the remote
    # is unreachable.
    restored = build_store(config).try_restore(config.get("build"), {})
    assert restored == key
    assert (tmp_path / "out.txt").read_text() == "LOCAL"


def test_remote_cache_rejects_non_http_url():
    try:
        RemoteCache("file:///tmp/cache")
    except ValueError:
        return
    raise AssertionError("file:// must be rejected")
