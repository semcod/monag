# ticket-004 — Planfile/GitHub coverage audit report

- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-15

## Goal and scope

Add a `monag audit` subcommand that reports how well a repository's local
Planfile tickets are covered by, and in sync with, its GitHub Issues — for
one repository, or across every repository under `--root` when run outside
a specific repository (the same mode `resume`/`status` already use for a
multi-repository workspace).

This is an independent, application-workstream ticket, deliberately kept
separate from `ticket-003` (`semcod/monag#6`, workstream `governance`),
which only bootstraps the repository-local `.planfile/` store itself. Mixing
the two under one ticket is what made `ticket-003` fail this repository's own
`project/governance-check.sh` (`GOV-WORKSTREAM-003`: no declared workstream
owns both `.planfile/**` and `src/monag/**`).

## Acceptance criteria

- [x] AC-01: `monag audit` reports, for a single repository (root is that
      repository's checkout), total GitHub issues, Planfile-tracked tickets,
      untracked issues, and any drift between a ticket's own GitHub mapping
      and the repository's `.planfile/sync/github.state.yaml` index.
- [x] AC-02: `monag audit --root <workspace>` (root is not itself a Git
      checkout) produces the same audit for every discovered repository with
      a GitHub remote, without requiring the caller to `cd` into each one.
- [x] AC-03: JSON and Markdown output follow the existing `resume`/`status`
      conventions (`--json`, `--markdown`, `--format`).
- [x] AC-04: Regression tests cover single-repo and multi-repo (org) modes,
      missing/duplicate mappings, and a repository with no `gh` access.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant
prose and raw command logs are not required delivery output.
