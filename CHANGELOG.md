# Changelog

## 0.3.1 — 2026-09-16

Fixed packaging metadata. 0.3.0 declared `rich>=14,<15` and never declared
`pyyaml`, although `monag.audit` imports it, so a clean `pip install monag`
produced a command that crashed with `ModuleNotFoundError: No module named
'yaml'` on `audit`, `resume`, `export` and `panel`. Dependencies are now
`rich>=14,<16` and `pyyaml>=6,<7`, verified by running the full suite against
the installed wheel in a clean environment.

No source or behaviour change relative to 0.3.0.

## 0.3.0 — 2026-09-15

Interactive terminal agent monitoring, Markdown reports, local history, and governed publication preparation.
