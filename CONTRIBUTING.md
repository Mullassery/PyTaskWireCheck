# Contributing

Thanks for your interest in PyTaskWireCheck. Contributions of all kinds are
welcome: bug reports, documentation improvements, tests, and code.

## Getting set up

```bash
git clone ../PyTaskWireCheck
cd PyTaskWireCheck
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

See [docs/development.md](docs/development.md) for the full developer guide.

## Before you open a pull request

Run the same checks CI runs, and make sure they all pass:

```bash
ruff check src tests
ruff format --check src tests
mypy src/pytaskwirecheck
pytest
```

- Keep changes focused; small pull requests are easier to review.
- Add or update tests for any behaviour change.
- Update the relevant file under `docs/` (and `CHANGELOG.md`) when you change
  user-facing behaviour.
- Match the existing style: `from __future__ import annotations`, `%`-style
  formatting, and no comments unless they explain *why*.

## Commit messages

Write clear, imperative commit subjects (for example, "Add cache eviction by
age"). Explain the *why* in the body when it is not obvious.

## Reporting bugs and requesting features

Use the [issue templates](../PyTaskWireCheck/issues/new/choose).
For security issues, follow [SECURITY.md](SECURITY.md) instead of opening a
public issue.

## Code of conduct

Participation is governed by the [Code of Conduct](CODE_OF_CONDUCT.md).

## License

By contributing, you agree that your contributions are licensed under the
project's [MIT License](LICENSE).
