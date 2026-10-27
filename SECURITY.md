# Security Policy

## Supported versions

PyTaskWireCheck is pre-1.0. Security fixes are made against the latest release.

| Version | Supported |
| --- | --- |
| 0.1.x | ✅ |
| < 0.1 | ❌ |

## Reporting a vulnerability

Please **do not** open a public issue for security problems.

Report privately in either of these ways:

- GitHub [Security Advisories](../PyTaskWireCheck/security/advisories/new)
- Email the maintainer (see the repository profile)

Include:

- the affected version,
- a minimal reproduction,
- the impact you believe it has, and
- any suggested fix.

We aim to acknowledge reports within a few days and to provide a remediation
timeline after triage.

## Scope and trust model

PyTaskWireCheck runs the commands you put in `pytaskwirecheck.toml`. Treat that
file as code, and treat anyone who can edit it as able to run programs with your
privileges. PyTaskWireCheck is an orchestrator, not a sandbox.

Defensive measures in place include path containment for `cwd`/`inputs`/`outputs`,
sha256-verified cache restores confined to the workspace root, atomic cache
commits, hashed (never plaintext) environment values, a per-task output budget,
and network access only via an explicitly configured webhook.

See [docs/security.md](docs/security.md) for details.
