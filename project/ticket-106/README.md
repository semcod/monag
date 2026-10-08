# Ticket 106: Feed reflex proposal categories into advise risk matching

- **ID**: ticket-106
- **Owner**: claude-code
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-07

## Goal and scope

`monag advise` read `patterns` from the reflex analysis, but `reflex analyze` returns `proposals`, so advise always reported 0 reflex patterns and priority readings ignored recurring failures. It also used `min_repeat=1`, turning every one-off event into a proposal (595 on the 8-hour transcript corpus). Derive one pattern per proposal category and require at least two repeats. User authorization: investigate the last 8 hours with monag and reflex, propose prevention, then continue (`kontynuuj`).

## Acceptance criteria

- [ ] AC-01: `collect_reflex_patterns` returns one pattern per reflex proposal category with summed frequency, for both the import and CLI runners.
- [ ] AC-02: One-off failures no longer produce reflex proposals in advise (`min_repeat=2`).
- [ ] AC-03: Tests and governance pass.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
