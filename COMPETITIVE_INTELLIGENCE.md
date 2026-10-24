# Competitive intelligence in roadmap and upgrade work

**Policy date:** 2026-10-19

Competitive findings are an input to product decisions, not a one-off report.
Every pending roadmap item, new feature, and routine dependency upgrade should
check the repository's [`AUDIT_FINDINGS.md`](AUDIT_FINDINGS.md) before work
starts, and record the decision in the PR or changelog.

## Required check before building

1. **Read `AUDIT_FINDINGS.md`.** Find the relevant competitor row and the
   ranked next actions. If the finding is stale, update it with a dated source.
2. **Name the competitor and the user problem.** A feature is not justified by
   "competitor has it". State the workflow it unlocks, who needs it, and how
   often. Mark unverified demand as a hypothesis.
3. **Prefer reuse over new code.** Check whether an existing Mullassery repo
   already provides the capability (see `BUNDLES.md` in the profile repo and
   the bundle role file in this repo, when present). Typical reuse:
   - crawling/fetching/robots/SSRF → **MudFish**
   - architecture maps / PR diffs → **CodeAtlas**
   - data-quality contracts / validation → **StatGuardian**
   - token counting / cost tables → **PyTokenCalc**
   - dependency graph / advisories / SBOM → **PyDeepMesh**
   - segmentation / CLV / churn → **ClusterAudienceKit**
   - activation / lineage / PII → **PyReverseETL**
   - fleet state sync → **SyncFleet** (only after conflict resolution)
4. **Choose one disposition:** build, integrate, defer, or reject. Write it
   down. A rejection with a reason is a successful outcome.
5. **For routine upgrades**, check whether the upgrade closes a known
   competitor gap or breaks a differentiated capability. Run the tests that
   cover the affected path; do not merge a green build that silently changes a
   user-visible contract.

## PR / changelog checklist

- [ ] Competitor and source URL/date recorded (or "no direct competitor").
- [ ] User impact and frequency stated; unverified demand labelled.
- [ ] Reuse check done against sibling repos/bundles.
- [ ] Failure mode and rollback considered (especially auth, PII, cost).
- [ ] Docs/roadmap status updated honestly.
- [ ] Tests or a manual verification command included.

## Review cadence

- Refresh the competitor row when a release changes the capability.
- Re-check the full `AUDIT_FINDINGS.md` at least quarterly and before a major
  release.
- If a finding is wrong or stale, correct it in the same PR that relies on it.

## Non-goals

- Copying features for parity.
- Adding a dependency just because a competitor uses it.
- Treating star counts or download counts as proof of user need.

## OSS gap analysis — 2026-10-24

**What matters most here:** keep local-only, but add Python-native dynamic DAGs. Distributed execution is a deliberate rejection; the gap that matters is generating tasks from data without pre-writing TOML, plus per-task environment isolation.

Scope: PyTaskWireCheck 0.3.0 compared with four actively maintained OSS task runners and workflow orchestrators on DAG execution, up-to-date/caching behaviour, environment isolation, and operational surface. Features were checked against each project's repository documentation; PyPI distribution status was checked against this repo's own status notes.

### Comparable OSS projects

| Project | GitHub | License | Last activity | Why it is the comparison |
| --- | --- | --- | --- | --- |
| just | https://github.com/casey/just | CC0-1.0 | pushed 2026-10-19 (~36.4k stars) | Closest ergonomics: a command runner with recipe prerequisites and no server |
| doit | https://github.com/pydoit/doit | MIT | pushed 2026-09-21 (~2.1k stars) | Python task runner with a dependency DAG and up-to-date checks |
| Snakemake | https://github.com/snakemake/snakemake | MIT | pushed 2026-10-23 (~2.9k stars) | File-driven reproducible workflows with container and cluster execution |
| Prefect | https://github.com/PrefectHQ/prefect | Apache-2.0 | pushed 2026-10-24 (~24.1k stars) | Python orchestration with retries, a server/UI, and managed execution |

### Capability comparison

| Capability | Ours | just | doit | Snakemake | Prefect | Gap |
| --- | --- | --- | --- | --- | --- | --- |
| Dependency DAG | Yes | Partial | Yes | Yes | Yes | None; recipe prerequisites are not a full DAG |
| Parallel independent branches | Yes | No | Yes | Yes | Yes | None |
| Content-addressed artifact cache | Yes | No | Partial | Partial | Partial | We are ahead; others use timestamps or task-result caches |
| Restore declared outputs on a hit | Yes | No | No | No | Partial | We are ahead |
| Fingerprint environment variables | Yes | No | Partial | Partial | Partial | We hash values; rivals mostly do not track env |
| Explain why a task re-ran | Yes | No | Partial | Partial | Partial | We are ahead with component-level diffs |
| Retries with backoff | Yes | No | Partial | Partial | Yes | Prefect has richer retry policies |
| Per-task container or conda env | No | No | No | Yes | Partial | Real gap |
| Remote or distributed execution | No | No | No | Yes | Yes | Real gap; local-only is deliberate |
| Schedules and event triggers | No | No | No | Partial | Yes | Real gap |
| UI and run lineage | Partial | No | No | Partial | Yes | TUI and local history only |
| Python-native dynamic DAG | No | No | Yes | Yes | Yes | TOML-only config is a real gap |
| Zero runtime dependencies | Yes | Yes | Yes | No | No | We are ahead |

Nuance: "Partial" for doit/Snakemake caching means they decide staleness from declared file inputs and timestamps or rerun triggers; they do not store and restore declared output files by content hash the way PyTaskWireCheck does. Prefect's "Partial" cache is task-result caching rather than file restore and was not re-tested in this pass. Prefect's trigger and UI claims are supported by its README's server/Cloud description; its exact retry policy surface was not independently exercised.

### Gaps that matter (ranked)

1. **No distributed or remote execution.** Every competitor with scale ambitions (Snakemake, Prefect) can dispatch work to clusters or remote workers; PyTaskWireCheck only launches local subprocesses. This blocks teams whose build or data job outgrows one machine. Effort L, and a deliberate scope choice rather than an oversight.
2. **No Python-native task definition or dynamic DAG generation.** doit, Snakemake, and Prefect define tasks in Python, so task lists can be generated from data at runtime. PyTaskWireCheck requires a static `pytaskwirecheck.toml`, which forces users to pre-generate configuration for parameter sweeps or per-directory tasks. Effort M.
3. **No per-task environment isolation.** Snakemake can run a rule inside a container or conda environment; Prefect can target work pools with their own runtime. PyTaskWireCheck runs every command in the caller's environment, so two tasks needing conflicting Python versions cannot coexist in one DAG. Effort L.
4. **No scheduler or trigger layer.** Prefect provides schedules and event-driven runs; Snakemake integrates with cluster job submission. PyTaskWireCheck is invoke-and-exit, so recurring or event-triggered work needs an external cron/Airflow/CI caller. Effort L.
5. **Distribution is incomplete.** This repository records Linux and Windows wheels as blocked. A macOS-only or source-build-only install limits adoption for CI runners, which are predominantly Linux. Effort M, and mostly packaging work rather than product design.
6. **The shared remote cache is best-effort and unauthenticated by design.** It is documented as off by default and never changing a task result, but there is no described authentication/authorization model for a cache shared across machines or a team. That is acceptable for a trusted LAN cache and insufficient for a public endpoint. Effort S-M.

### Where we are differentiated

- **Correctness-first caching:** sha256-verified restores, atomic commits, corrupt-entry recovery, hashed (never plaintext) environment values, and `explain --against` showing exactly which fingerprint component changed.
- **Narrow, dependency-free footprint:** zero runtime dependencies on modern Python and no server, daemon, account, or telemetry, which is materially simpler than Prefect or Snakemake deployment.
- **Honest execution semantics:** an explicit state machine, distinguishably blocked dependents, and a guarantee that cancelled, timed-out, or failed tasks are never cached.
- **Single-package operator experience:** DAG view, plan, TUI, watch mode, local history, and JSON output in one small CLI.

### Disposition

- **Build:** Python-native/dynamic task definitions (M); per-task environment or container isolation (M); authentication for the shared remote cache (S-M); Linux and Windows wheels (M).
- **Integrate/reuse:** keep the existing HTTP remote-cache contract and document integration with CI-native caches rather than inventing a scheduler; reuse MudFish only if remote input fetching becomes a requirement.
- **Defer/reject:** a server/daemon, distributed scheduler, hosted UI, and multi-tenant control plane. Those are already rejected in this repo and should stay rejected; the product's value is the local, inspectable slice.

### Sources

- https://github.com/casey/just (CC0-1.0, pushed 2026-10-19, accessed 2026-10-24)
- https://github.com/pydoit/doit (MIT, pushed 2026-09-21, accessed 2026-10-24)
- https://github.com/snakemake/snakemake (MIT, pushed 2026-10-23, accessed 2026-10-24)
- https://github.com/PrefectHQ/prefect (Apache-2.0, pushed 2026-10-24, accessed 2026-10-24)
- Repo files inspected: `README.md`, `COMPETITIVE_INTELLIGENCE.md`, `docs/caching.md`, `docs/execution.md`, `docs/roadmap.md`, `QUEUE_STATUS.md`
