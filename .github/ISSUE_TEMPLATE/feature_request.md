name: Feature request
description: Suggest an idea or improvement for PyTaskWireCheck
title: "[feature] "
labels: ["enhancement"]
body:
  - type: markdown
    attributes:
      value: |
        Thanks for the suggestion. Please check the roadmap
        (docs/roadmap.md) and existing issues first.
  - type: textarea
    id: problem
    attributes:
      label: What problem does this solve?
      description: Describe the pain point, not just the proposed solution.
    validations:
      required: true
  - type: textarea
    id: proposal
    attributes:
      label: Proposed solution
      description: How would you like it to work? Sketch config/CLI/API if relevant.
    validations:
      required: true
  - type: textarea
    id: alternatives
    attributes:
      label: Alternatives considered
    validations:
      required: false
