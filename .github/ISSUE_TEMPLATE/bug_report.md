name: Bug report
description: Report a reproducible problem with PyTaskWireCheck
title: "[bug] "
labels: ["bug", "triage"]
body:
  - type: markdown
    attributes:
      value: |
        Thanks for taking the time to file a bug. Please search existing issues
        first. For security problems, use SECURITY.md instead.
  - type: input
    id: version
    attributes:
      label: PyTaskWireCheck version
      description: Output of `pytaskwirecheck --version`
      placeholder: "0.1.0"
    validations:
      required: true
  - type: input
    id: python
    attributes:
      label: Python version
      placeholder: "3.12.4"
    validations:
      required: true
  - type: input
    id: os
    attributes:
      label: Operating system
      placeholder: "macOS 15, Ubuntu 24.04, Windows 11"
    validations:
      required: true
  - type: textarea
    id: what-happened
    attributes:
      label: What happened?
      description: A clear description of the bug and what you expected instead.
    validations:
      required: true
  - type: textarea
    id: reproduce
    attributes:
      label: Steps to reproduce
      description: Include a minimal `pytaskwirecheck.toml` and commands if possible.
      render: shell
    validations:
      required: true
  - type: textarea
    id: logs
    attributes:
      label: Relevant output
      description: Paste the CLI output. Run with `--json` or `-q` as appropriate.
      render: shell
    validations:
      required: false
