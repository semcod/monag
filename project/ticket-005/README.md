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
- [x] AC-05: `monag panel` serves a local-only HTTP dashboard (preferred
      port `8090`) over the existing agent/repository snapshot and Planfile
      backlog (background-refreshed), plus the `audit`/`catalog` reports
      computed lazily and cached on first request. No new data source, no
      authentication, binds to localhost by default.
- [x] AC-06: the preferred port is never required to be free. `bind_server`
      tries it, then up to `--port-attempts` (default 20) ports after it,
      then falls back to any OS-assigned free port; the actually bound
      `host:port` is always printed on startup and recorded in
      `<state-dir>/panel.json` (mode 0600), so a caller never has to guess
      which port a dynamically-reassigned panel ended up on.

**Resolved operational note:** on this host, TCP port 8090 (and 8091) are
already bound by unrelated existing services (an nginx dashboard for
`taskand-glm53`, and a separate "Subactor Platform"). With AC-06, `monag
panel` no longer needs that conflict resolved by a human first — it tried
8090/8091/8092, found 8093 free, and started there automatically
(`MONAG: panel serving http://127.0.0.1:8093/ (requested 8090 was
unavailable)`). No change was made to either pre-existing service.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant
prose and raw command logs are not required delivery output.
