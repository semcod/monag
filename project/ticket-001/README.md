# ticket-001 — Agent activity CLI

- **Owner**: codex-monag
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT

SESSION_EXECUTION_AUTHORIZATION: the user requested implementation, tests, push, and continuation toward independently verified publication.

Deliver a Python CLI for Linux agent processes, checkout concurrency, changed
files, recent commits, optional GitHub issues/PRs, and explicit task reporting.
Preserve protected publication gates and distinguish observations from attribution.

This slice is the delivery bootstrap: adopt `wellmanifest/new-project` 0.20.31
as one verified installation together with the repository-owned files it
requires (governance manifest, required checks, ticket allocation, `VERSION`,
`CHANGELOG.md`, `README.md`, `pyproject.toml`) and a checkout-scoped
`goal.yaml`. The CLI source and tests, packaging extras with documentation, and
the read-only `resume` inventory follow as dependent tickets stacked on this one.

Acceptance: the managed gate passes against `main`, host files and hooks
activate, and `pyproject.toml` declares the package and its runtime dependency.

Handoff 2026-09-15: the user transferred this ticket from `codex-monag` to
`claude-monag` and authorized rebuilding the branch so the intent is part of the
first material commit, after the gate reported the previous delivery over
budget. The previous head `c7e17ebef8621588f213f20d298d6f84d1ec803b`, its staged
adoption and the uncommitted continuation are preserved in a local bundle
(`sha256:dd50143ba571f2298af9ac242cc3472cac6fd3b261e06e6aa879ffc692fbbf57`).

Delivery: [PR #1](https://github.com/semcod/monag/pull/1). The protected
Validator profile for this repository is missing; merge requires the user's
trusted review.

Handoff 2026-09-15: user confirmed Claude finished and explicitly transferred delivery to Codex. Refresh against main 04228b366f42ddca24e9e66cc0bb07cc0c12f2c9 preserves checkout-scoped Goal configuration.
