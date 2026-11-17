---
{
  "schema": "wellmanifest.docs/document/v1",
  "id": "agent-tooling-12h-review-20261117",
  "kind": "analysis",
  "version": 1,
  "title": "Twelve-hour review of Monag, Diagit and Reflex observations (2026-11-17)",
  "status": "accepted",
  "owner": "semcod/monag",
  "created": "2026-11-17",
  "updated": "2026-11-17",
  "review_after": "2026-12-17",
  "source_revision": "da450683dbccd7c5c7882ab23a5f78c93246218a",
  "affected_repositories": [
    "semcod/monag",
    "semcod/diagit",
    "subactor/reflex"
  ],
  "evidence": [
    "repo://semcod/monag/src/monag/summary.py",
    "repo://semcod/diagit/src/diagit/application/service.py",
    "repo://semcod/diagit/src/diagit/infrastructure/projection.py",
    "repo://subactor/reflex/src/reflex/model.py",
    "repo://semcod/monag/tests/test_day_window.py",
    "repo://semcod/diagit/tests/test_audit_coverage_counts.py",
    "repo://semcod/diagit/tests/test_window_baseline_scope.py",
    "repo://subactor/reflex/tests/test_repository_inference.py"
  ]
}
---

# Twelve-hour review of Monag, Diagit and Reflex observations

<!-- docs:section question -->
## Question

What did the three observation tools report for the workspace between
2026-11-17 08:49Z and 20:49Z, which of their own defects distort that picture,
and what should be fixed first?

<!-- docs:section scope -->
## Scope

Read-only runs of `monag` (`status`, `doctor`, `day`, `summary`, `history`,
`autodiagnose`, `triage`) over `/home/tom/github`, a fresh read-only
`diagit audit` of the same root and `diagit query window` for the 12-hour
window, and `reflex analyze --transcripts --since-hours 12` over the 24 Claude
Code and Codex transcripts modified in the window. Code fixes are limited to
defects in the three tools; fleet findings they report are recommendations.

<!-- docs:section method -->
## Method

1. Run each tool with its documented 12-hour selector and compare counts that
   should agree across commands and tools.
2. Trace every implausible value to source and reproduce it with a unit test.
3. Fix each confirmed defect on its own ticket branch and re-run the tool
   against the same live evidence.

<!-- docs:section evidence -->
## Evidence

- Monag: 21 agent processes, 0 inaccessible; `doctor` 908 repositories,
  125 stale worktrees, 289 merged branches, `agent_storage` phase timed out at
  the 60 s budget; `autodiagnose` 1700 anomalies including a failed
  `subactor-coding-agent.service`, Heyasa admission at 0 eligible projects
  with 56 blocked candidates, and 643 zombie processes.
- Diagit audit `bc60e266…`: 942 repositories in 181 s, 4876 findings
  (3093 errors); `WORKTREE_OVERLAP` 3014, of which 3013 in `semcod/prefact`;
  `DIRTY_WORKTREE` 606, `NO_LICENSE` 404, `STASHED_CHANGES` 180,
  `PACKAGE_UNRELEASED_SOURCE_COMMITS` 129, `ORPHAN_LOCAL_BRANCH` 128.
- Reflex: 746 failed tool calls, 581 unique, 66 recurring groups —
  operational-failure 50 groups (193 events), governance-friction 7 (47),
  test-feedback 6 (14), dependency-drift 2 (4), worktree-scope-overlap 1 (3).
  Most frequent failing commands: `rg` 62, `python3` 58, `sed` 54, `cat` 47,
  `wellman run` 30. Eight failures came from `gh pr view` hitting the GraphQL
  "Projects (classic) is being deprecated" error with gh 2.46.0.

<!-- docs:section facts -->
## Facts

Four tool defects were confirmed and fixed:

| Tool | Defect | Effect on the 12-hour picture | Fix |
| :--- | :--- | :--- | :--- |
| Monag | `day --hours 12` queried PRs from local midnight and labelled every section "24h" | 72 merged PRs reported instead of 47 in the real 12-hour window | `semcod/monag` ticket-140 |
| Diagit | receipts counted synthetic desired-inventory observations as scanned | daily audit reported `scanned` 81 > `total` 80 | `semcod/diagit` ticket-081 |
| Diagit | window comparison always used the newest pre-window run as baseline | a 5-repository run hid the fleet baseline; all 4883 findings `unknown` | `semcod/diagit` ticket-081 |
| Reflex | free-text repository fallback took the first `owner/name`-shaped token | 213 of 581 events had repositories such as `github.blog/changelog`, `app/data`, `refs/heads`, `dev/urandom`; after the fix 42 remain, all plausible | `subactor/reflex` ticket-047 |

The diagit baseline fix is conservative: no earlier run has exactly the
942-repository scope, so this window still reports `scope_changed`. A
comparable result needs a recurring audit with a stable scope.

<!-- docs:section hypotheses -->
## Hypotheses

- Monag `history` and `day` report 0 agent runs and "Task telemetry missing"
  because agents are not launched through `monag run`; process observation
  works, task telemetry does not.
- The 3013 `WORKTREE_OVERLAP` findings in `semcod/prefact` (138 registered
  worktrees) dominate diagit's error count and hide other signals.
- Repository counts disagree between `status` (1420), `doctor` (908),
  `triage` (882) and diagit (942) because each counts worktrees and nested
  checkouts differently; no command states which definition it uses.

<!-- docs:section limitations -->
## Limitations

- The user journal held only about 40 minutes (18 765 lines from 21:07 local),
  mostly `koru-lane-nxdo`, `validator-publication-watchdog` and
  `c2004-koru-autonomous`, so service logs could not cover the 12 hours.
- The last scheduled diagit audit (00:12 local) predates the window; the
  in-window observation is the ad-hoc audit from this review.
- `tests/test_procache_integration.py` in monag fails on untouched
  `origin/main` in this environment; it was not investigated.

<!-- docs:section recommendations -->
## Recommendations

1. Publish the three ticket branches through each repository's protected
   delivery process.
2. Reconcile or prune the `semcod/prefact` worktrees, then re-audit; most
   diagit errors should disappear.
3. Run a stable-scope diagit audit on a schedule so window comparisons become
   comparable, or add an explicit intersection mode that keeps
   `resolved` limited to repositories observed in both runs.
4. Make `diagit query findings --limit` above 1000 a usage error instead of a
   traceback.
5. Upgrade `gh` or use `gh pr view --json …` in agent scripts to stop the
   classic-Projects GraphQL failures.
6. Raise the user journal size or reduce the chattiest units so a 12-hour
   review has service evidence.
7. Investigate the failed `subactor-coding-agent.service` and the Heyasa
   admission stall reported by `monag autodiagnose`.
8. Correct the `willmux-reflex.timer` description, which says hourly while
   its drop-in runs every 300 s.
