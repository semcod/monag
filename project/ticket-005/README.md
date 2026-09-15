# ticket-005 — Local project catalog report

- **ID**: ticket-005
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-15

## Goal and scope

Add a `monag catalog` subcommand that reports, for one repository or every
repository under `--root`, what each project declares itself to be —
description, detected stack, declared entry points, docs/tests/changelog
presence, last commit — read verbatim from its own `pyproject.toml`,
`package.json` or `README.md`. No network calls, no LLM-generated summary:
a repository with no declared description is reported as unknown, never
guessed.

Deliberately excludes any form of credential access (browser, password
manager, open sessions, self-issued tokens) — this catalog only reads files
the project already ships in its own checkout.

## Acceptance criteria

- [x] AC-01: `monag catalog` reports, for a single repository (root is that
      repository's checkout), its description/source, detected stack,
      declared entry points, docs/tests/changelog presence, and last commit.
- [x] AC-02: `monag catalog --root <workspace>` (root is not itself a Git
      checkout) produces the same catalog for every discovered repository.
- [x] AC-03: JSON and Markdown output follow the existing `resume`/`audit`
      conventions (`--json`, `--markdown`, `--format`).
- [x] AC-04: Regression tests cover pyproject.toml/package.json/README
      fallback order, blockquote/badge/heading skipping in README parsing,
      entry-point extraction, and an undeclared-description repository.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant
prose and raw command logs are not required delivery output.
