# ticket-005 — Local project catalog and HTTP dashboard

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
- [x] AC-05: `monag panel` serves a local-only HTTP dashboard (default
      `127.0.0.1:8090`) over the existing agent/repository snapshot and
      Planfile backlog (background-refreshed), plus the `audit`/`catalog`
      reports computed lazily and cached on first request. No new data
      source, no authentication, binds to localhost by default.

**Known operational note:** on this host, TCP port 8090 is already bound by
an existing nginx service serving `taskand-glm53`'s own live-context page
(`index.html`, title "taskand · kontekst i stan live"). `monag panel`
defaults to 8090 per the request but will fail to bind there until that
conflict is resolved (stop the other service, or start the panel with
`--port <free-port>`). Not resolved here — needs an owner decision about
which service actually owns 8090.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant
prose and raw command logs are not required delivery output.
