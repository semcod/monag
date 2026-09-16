# ticket-024 — Declare PyYAML and widen the Rich range

- **ID**: ticket-024
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-16

## Goal and scope

`src/monag/audit.py` imports `yaml`, but `pyyaml` was never declared in
`pyproject.toml`. A clean `pip install monag` therefore produced a broken
command: `monag audit` (and `resume`/`export`/`panel`) crashed with
`ModuleNotFoundError: No module named 'yaml'`. Tests never caught it
because every development environment already had PyYAML present.

The same pass closes the other half of GitHub #3: `rich` was pinned
`>=14,<15`, excluding rich 15, which is what the CI executor environment
resolves. The suite passes against rich 15.0.0, so the range widens to
`>=14,<16`.

Packaging metadata only — no source or behaviour change.

## Acceptance criteria

- [x] AC-01: `pyproject.toml` declares `pyyaml>=6,<7`.
- [x] AC-02: `rich` accepts 15.x (`rich>=14,<16`).
- [x] AC-03: The wheel installs into a clean virtualenv and the full
      suite (111/111) passes against the *installed* package, with
      rich 15.0.0 and PyYAML 6.0.3.

## Evidence

Pre-fix dependency set (`--no-deps` + `rich>=14,<15`) reproduces the bug:

```
  File ".../site-packages/monag/audit.py", line 20, in <module>
    import yaml
ModuleNotFoundError: No module named 'yaml'
```

Post-fix clean install: `rich==15.0.0`, `PyYAML==6.0.3`, `monag --help`
works, `python -m unittest discover -s tests -t tests` → `Ran 111 tests
... OK`.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant
prose and raw command logs are not required delivery output.
