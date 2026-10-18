"""Content-addressed cache tests: hits, invalidation, integrity, safety."""

from __future__ import annotations

import sys
from pathlib import Path

from pytaskwirecheck.cache.fingerprint import compute_fingerprint
from pytaskwirecheck.cache.policy import build_store
from pytaskwirecheck.config.loader import load_config
from pytaskwirecheck.engine.cancellation import CancellationToken
from pytaskwirecheck.engine.events import EventBus
from pytaskwirecheck.engine.executor import TaskExecutor
from pytaskwirecheck.engine.scheduler import Scheduler
from pytaskwirecheck.engine.state import TaskStatus
from pytaskwirecheck.graph.builder import build_graph
from pytaskwirecheck.graph.validator import validate_graph

PY = sys.executable

BUILD_CONFIG = f"""
[project]
name = "cachetest"
version = 1

[tasks.build]
command = ["{PY}", "-c", "open('count.txt','a').write('x'); open('out.txt','w').write(open('src.txt').read().upper())"]
inputs = ["src.txt"]
outputs = ["out.txt"]
cache = true
"""


def _write(tmp_path: Path, text: str) -> None:
    (tmp_path / "pytaskwirecheck.toml").write_text(text, encoding="utf-8")


def _run(tmp_path, store, *, use_cache=True, base_env=None, workers=1):
    config = load_config(tmp_path / "pytaskwirecheck.toml")
    graph = build_graph(config)
    validate_graph(graph)
    events = EventBus()
    token = CancellationToken()
    env = base_env if base_env is not None else {}
    executor = TaskExecutor(
        root=config.project.root,
        default_timeout=None,
        events=events,
        cancel_token=token,
        base_env=env,
        cache=store,
    )
    execution = type(config.execution)(
        max_workers=workers,
        default_timeout_seconds=config.execution.default_timeout_seconds,
        fail_fast=False,
    )
    scheduler = Scheduler(
        graph=graph,
        execution=execution,
        executor=executor,
        events=events,
        cancel_token=token,
        use_cache=use_cache,
    )
    return scheduler.run(set(graph.nodes.keys()))


def _store(tmp_path, base_env=None):
    config = load_config(tmp_path / "pytaskwirecheck.toml")
    return build_store(config, base_env=base_env)


def test_cache_hit_and_reexecution(tmp_path):
    _write(tmp_path, BUILD_CONFIG)
    (tmp_path / "src.txt").write_text("hi")
    store = _store(tmp_path)
    first = _run(tmp_path, store)
    assert first.records["build"].status is TaskStatus.SUCCEEDED
    second = _run(tmp_path, store)
    assert second.records["build"].status is TaskStatus.CACHED
    assert (tmp_path / "count.txt").read_text() == "x"
    assert (tmp_path / "out.txt").read_text() == "HI"


def test_input_change_invalidates(tmp_path):
    _write(tmp_path, BUILD_CONFIG)
    (tmp_path / "src.txt").write_text("one")
    store = _store(tmp_path)
    _run(tmp_path, store)
    (tmp_path / "src.txt").write_text("two")
    second = _run(tmp_path, store)
    assert second.records["build"].status is TaskStatus.SUCCEEDED
    assert (tmp_path / "count.txt").read_text() == "xx"
    assert (tmp_path / "out.txt").read_text() == "TWO"


def test_command_change_invalidates(tmp_path):
    _write(tmp_path, BUILD_CONFIG)
    (tmp_path / "src.txt").write_text("hi")
    store = _store(tmp_path)
    _run(tmp_path, store)
    _write(
        tmp_path,
        BUILD_CONFIG.replace("open('count.txt','a').write('x')", "pass"),
    )
    second = _run(tmp_path, store)
    assert second.records["build"].status is TaskStatus.SUCCEEDED


def test_relevant_env_change_invalidates(tmp_path):
    config = BUILD_CONFIG + '\n[cache]\nrelevant_env = ["TW_CACHE_VAR"]\n'
    _write(tmp_path, config)
    (tmp_path / "src.txt").write_text("hi")
    base = {"TW_CACHE_VAR": "alpha"}
    store = _store(tmp_path, base_env=base)
    _run(tmp_path, store, base_env=base)
    base2 = {"TW_CACHE_VAR": "beta"}
    store2 = _store(tmp_path, base_env=base2)
    second = _run(tmp_path, store2, base_env=base2)
    assert second.records["build"].status is TaskStatus.SUCCEEDED


def test_corrupted_metadata_is_miss(tmp_path):
    _write(tmp_path, BUILD_CONFIG)
    (tmp_path / "src.txt").write_text("hi")
    store = _store(tmp_path)
    _run(tmp_path, store)
    entries = list((store.location / "entries").iterdir())
    assert entries
    (entries[0] / "meta.json").write_text("{ not json")
    second = _run(tmp_path, store)
    assert second.records["build"].status is TaskStatus.SUCCEEDED


def test_altered_artifact_is_miss(tmp_path):
    _write(tmp_path, BUILD_CONFIG)
    (tmp_path / "src.txt").write_text("hi")
    store = _store(tmp_path)
    _run(tmp_path, store)
    entry = next((store.location / "entries").iterdir())
    artifact = next((entry / "artifacts").rglob("out.txt"))
    artifact.write_text("tampered")
    second = _run(tmp_path, store)
    assert second.records["build"].status is TaskStatus.SUCCEEDED


def test_failed_task_not_cached(tmp_path):
    _write(
        tmp_path,
        f"""
[tasks.boom]
command = ["{PY}", "-c", "import sys; open('o.txt','w').write('x'); sys.exit(1)"]
inputs = []
outputs = ["o.txt"]
""",
    )
    store = _store(tmp_path)
    result = _run(tmp_path, store)
    assert result.records["boom"].status is TaskStatus.FAILED
    assert store.status()["entries"] == 0


def test_secrets_not_stored_plaintext(tmp_path):
    _write(
        tmp_path,
        f"""
[tasks.s]
command = ["{PY}", "-c", "open('o.txt','w').write('x')"]
inputs = []
outputs = ["o.txt"]
[tasks.s.env]
API_TOKEN = "super-secret-value-123"
""",
    )
    store = _store(tmp_path)
    _run(tmp_path, store)
    for meta in (store.location / "entries").rglob("meta.json"):
        assert "super-secret-value-123" not in meta.read_text()


def test_no_cache_mode(tmp_path):
    _write(tmp_path, BUILD_CONFIG)
    (tmp_path / "src.txt").write_text("hi")
    store = _store(tmp_path)
    _run(tmp_path, store, use_cache=False)
    second = _run(tmp_path, store, use_cache=False)
    assert second.records["build"].status is TaskStatus.SUCCEEDED
    assert (tmp_path / "count.txt").read_text() == "xx"


def test_concurrent_cache_writes(tmp_path):
    tasks = []
    for index in range(4):
        tasks.append(
            f"""
[tasks.t{index}]
command = ["{PY}", "-c", "open('o{index}.txt','w').write('{index}')"]
inputs = []
outputs = ["o{index}.txt"]
"""
        )
    _write(tmp_path, "\n".join(tasks))
    store = _store(tmp_path)
    first = _run(tmp_path, store, workers=4)
    assert first.succeeded
    assert store.status()["entries"] == 4
    second = _run(tmp_path, store, workers=4)
    assert all(second.records[f"t{i}"].status is TaskStatus.CACHED for i in range(4))


def test_cache_status_and_clean(tmp_path):
    _write(tmp_path, BUILD_CONFIG)
    (tmp_path / "src.txt").write_text("hi")
    store = _store(tmp_path)
    _run(tmp_path, store)
    status = store.status()
    assert status["entries"] == 1
    assert status["size_bytes"] > 0
    store.clean()
    assert store.status()["entries"] == 0


def test_fingerprint_changes_with_inputs(tmp_path):
    _write(tmp_path, BUILD_CONFIG)
    (tmp_path / "src.txt").write_text("a")
    config = load_config(tmp_path / "pytaskwirecheck.toml")
    task = config.tasks["build"]
    fp1 = compute_fingerprint(task, tmp_path, {}, base_env={})
    (tmp_path / "src.txt").write_text("b")
    fp2 = compute_fingerprint(task, tmp_path, {}, base_env={})
    assert fp1.key != fp2.key


def test_fingerprint_ignores_unrelated_files(tmp_path):
    _write(tmp_path, BUILD_CONFIG)
    (tmp_path / "src.txt").write_text("a")
    config = load_config(tmp_path / "pytaskwirecheck.toml")
    task = config.tasks["build"]
    fp1 = compute_fingerprint(task, tmp_path, {}, base_env={})
    (tmp_path / "unrelated.txt").write_text("noise")
    fp2 = compute_fingerprint(task, tmp_path, {}, base_env={})
    assert fp1.key == fp2.key


def test_fingerprint_uses_dependency_keys(tmp_path):
    _write(tmp_path, BUILD_CONFIG)
    (tmp_path / "src.txt").write_text("a")
    config = load_config(tmp_path / "pytaskwirecheck.toml")
    task = config.tasks["build"]
    fp1 = compute_fingerprint(task, tmp_path, {"dep": "aaa"}, base_env={})
    fp2 = compute_fingerprint(task, tmp_path, {"dep": "bbb"}, base_env={})
    assert fp1.key != fp2.key


def test_cache_evicts_least_recently_used_over_entry_bound(tmp_path):
    import time

    from pytaskwirecheck.cache.store import CacheStore

    _write(tmp_path, BUILD_CONFIG)
    store = CacheStore(tmp_path, base_env={}, max_entries=2, max_bytes=None)
    keys = []
    for i in range(4):
        (tmp_path / "src.txt").write_text("v%d" % i)
        (tmp_path / "out.txt").write_text("V%d" % i)
        task = load_config(tmp_path / "pytaskwirecheck.toml").tasks["build"]
        keys.append(store.store(task, {}))
        time.sleep(0.01)

    entries = {p.name for p in (store.location / "entries").iterdir() if p.is_dir()}
    assert entries == {keys[-2], keys[-1]}
    assert store.status()["max_entries"] == 2
    assert store.status()["entries"] == 2


def test_cache_evicts_over_byte_budget(tmp_path):
    from pytaskwirecheck.cache.store import CacheStore

    _write(tmp_path, BUILD_CONFIG)
    store = CacheStore(tmp_path, base_env={}, max_bytes=1, max_entries=None)
    last = None
    for i in range(3):
        (tmp_path / "src.txt").write_text("payload-%d" % i)
        (tmp_path / "out.txt").write_text("PAYLOAD-%d" % i)
        task = load_config(tmp_path / "pytaskwirecheck.toml").tasks["build"]
        last = store.store(task, {})

    entries = {p.name for p in (store.location / "entries").iterdir() if p.is_dir()}
    # The just-committed entry is protected; older ones are evicted to fit.
    assert entries == {last}


def test_cache_evict_command_is_idempotent(tmp_path):
    from pytaskwirecheck.cache.store import CacheStore

    _write(tmp_path, BUILD_CONFIG)
    store = CacheStore(tmp_path, base_env={}, max_entries=1, max_bytes=None)
    result = store.evict()
    assert result == {"removed_entries": 0, "removed_bytes": 0}
    assert store.status()["max_entries"] == 1


def test_diff_fingerprints_reports_modified_inputs(tmp_path):
    from pytaskwirecheck.cache.fingerprint import diff_fingerprints

    _write(tmp_path, BUILD_CONFIG)
    (tmp_path / "src.txt").write_text("one")
    config = load_config(tmp_path / "pytaskwirecheck.toml")
    task = config.get("build")
    store = _store(tmp_path)
    before = store.fingerprint(task, {}).payload

    (tmp_path / "src.txt").write_text("two")
    after = store.fingerprint(task, {}).payload

    diff = diff_fingerprints(before, after)
    assert diff["changed"] is True
    assert diff["components"]["inputs"]["modified"] == ["src.txt"]
    assert diff["components"]["inputs"]["added"] == []
    assert diff["components"]["inputs"]["removed"] == []


def test_explain_against_latest_reports_fingerprint_diff(tmp_path):
    _write(tmp_path, BUILD_CONFIG)
    (tmp_path / "src.txt").write_text("one")
    store = _store(tmp_path)
    _run(tmp_path, store)

    config = load_config(tmp_path / "pytaskwirecheck.toml")
    task = config.get("build")
    old_key = store.latest_key("build")
    assert old_key is not None

    (tmp_path / "src.txt").write_text("two")
    detail = store.explain(task, {}, against="latest")

    assert detail["against"] == old_key
    assert detail["diff"]["changed"] is True
    assert detail["diff"]["components"]["inputs"]["modified"] == ["src.txt"]
