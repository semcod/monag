# Ticket 016: Naprawić importer GitHub: zachować id i priorytet w rekordzie Planfile

- **ID**: ticket-016
- **Owner**: codex (executing under the user's explicit continuation, push and merge authorization)
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-15

## Goal and scope

Make Monag's Planfile reader faithfully expose GitHub-imported ticket identity,
priority and labels, and report incomplete imported records instead of silently
normalizing them into apparently complete backlog entries. The importer itself
belongs to Planfile; this ticket covers Monag's read-only compatibility and
diagnostic boundary.

## Acceptance criteria

- [ ] AC-01: A GitHub-imported record with inline `id`, priority, labels and
  `sync.github` mapping is returned with all four values intact.
- [ ] AC-02: A record that only has a `GITHUB-*` mapping key, or omits priority
  or its GitHub mapping, remains visible and carries explicit incompleteness
  evidence.
- [ ] AC-03: Re-reading the same Planfile twice is deterministic and leaves the
  source unchanged.

## Execution authority

The user explicitly authorized continuation, implementation, push and protected
merge in this session. Publication remains subject to exact-head OneDev,
independent Validator approval and the protected delivery controller.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
