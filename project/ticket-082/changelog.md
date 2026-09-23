# Changelog: ticket-082

- feat(monitor): safely validate gitdir references in `discover()` to avoid exit 128 on orphaned worktrees
- feat(doctor): re-audit and prune merged branches freed up by worktree removal in a single `--fix` pass
- test(doctor): add tests for broken gitdir discovery and single-pass branch pruning
