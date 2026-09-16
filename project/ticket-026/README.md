# Ticket 026: Release monag 0.3.1 with fixed dependency metadata

- **ID**: ticket-026
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-16

## Goal and scope

The published 0.3.0 artifact on PyPI is broken. Its metadata declares
`rich<15,>=14` and no `pyyaml`, although `src/monag/audit.py` imports
`yaml`, so `pip install monag==0.3.0` yields a command that crashes on
`audit`, `resume`, `export` and `panel`:

```
$ pip install monag==0.3.0      # monag==0.3.0, rich==14.3.4
$ monag audit
ModuleNotFoundError: No module named 'yaml'
```

The metadata fix landed on main in ticket-024, but PyPI does not allow
replacing a released version, so it only reaches users through a new
release. This ticket bumps 0.3.0 → 0.3.1 and records the release.

Version bump and changelog only — no source or behaviour change.

## Acceptance criteria

- [x] AC-01: `VERSION`, `pyproject.toml` and `src/monag/__init__.py` all
      read 0.3.1 (the three `versioning.files` targets in `goal.yaml`).
- [x] AC-02: CHANGELOG records 0.3.1 and why it exists.
- [x] AC-03: The 0.3.1 wheel installs into a clean virtualenv and the full
      suite passes against the *installed* package.
- [x] AC-04: After upload, an independent read of PyPI shows 0.3.1 with
      `pyyaml` in `requires_dist`, and `pip install monag==0.3.1` followed
      by `monag audit` runs without the import error.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
