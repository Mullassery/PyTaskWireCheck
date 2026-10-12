# Development

## Setup

```bash
git clone https://github.com/Mullassery/PyTaskWireCheck
cd PyTaskWireCheck
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

PyTaskWireCheck supports Python 3.9 – 3.13. CI runs the full matrix.

## Everyday commands

```bash
pytest                             # full suite
pytest -q tests/test_scheduler.py  # one file
pytest --cov=pytaskwirecheck              # with coverage
ruff check src tests               # lint
ruff format src tests              # format
mypy src/pytaskwirecheck                  # type-check
```

All four must be green before a pull request is merged.

## Layout

```
src/pytaskwirecheck/
  api.py            # public embedding API
  cli.py            # argument parsing + wiring
  config/           # schema, validation, loader
  graph/            # model, builder, validator, planner
  engine/           # state, events, cancellation, executor, scheduler
  processes/        # subprocess runner + signal handling
  cache/            # fingerprint, store, policy
  logging/          # artifacts + structured JSONL
  history/          # SQLite run history
  notifications/    # webhook notifier
  tui/              # plain reporter + live dashboard
  diagnostics/      # error types and reporting
tests/              # pytest suite (unit + integration)
docs/               # this documentation
```

## Conventions

- `from __future__ import annotations` everywhere; target Python 3.9.
- `%`-style formatting for user-facing strings; no f-strings in library code.
- Dataclasses are frozen and side-effect free in `config/`.
- The scheduler is the only component that transitions task state.
- Observers (CLI/TUI/logs/history/notifications) never change outcomes.
- No comments unless they explain *why*, not *what*.

## Adding a configuration field

1. Add the field to the relevant dataclass in `config/schema.py`.
2. Parse and validate it in `config/validation.py` (add to the allowed-keys set).
3. If it affects the cache, fold it into `cache/fingerprint.py` and bump
   `CACHE_SCHEMA_VERSION`.
4. Update `docs/configuration.md` and add tests in `tests/test_config.py`.

## Adding a CLI command

1. Add the subparser in `build_parser()` in `cli.py`.
2. Implement a `cmd_<name>(args) -> int` that returns a stable exit code.
3. Add integration coverage in `tests/test_cli.py` (drive `main([...])`).
4. Document it in `docs/cli.md`.

## Release process

```bash
# 1. Bump the version in pyproject.toml, src/pytaskwirecheck/__init__.py, CHANGELOG.md
# 2. Build
python -m build
# 3. Verify and upload
python -m twine check dist/*
python -m twine upload dist/*
```

The distribution is published as `PyTaskWireCheck`; the import package and the
command remain `pytaskwirecheck`.

## Reproducible environments

`.pytaskwirecheck/` (cache, artifacts, history) is created on demand and should be
git-ignored. It is safe to delete; the next run recreates it.
