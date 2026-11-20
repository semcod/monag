# Ticket 153: Give cached gh reads an explicit keyring identity via procache github_env

- **ID**: ticket-153
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-20

## Goal and scope

To be completed from human-owned input.

monag already routes `gh` reads through procache (ticket-072), but on hosts
where `gh` authenticates through the system keyring procache correctly refuses
to share any read, so the cache stayed empty while the workstation exhausted
its GitHub budget on 2026-11-20 (~7,300 `gh` calls per hour).
dockuri/procache#18 added `github_env`, which reads the keyring token locally
(`gh auth token`) and pins `GH_HOST` only when that host is configured.

`with_github_identity` applies it to cached reads when
`MONAG_GITHUB_IDENTITY=1`. Default behaviour is unchanged, explicit tokens are
never replaced, an existing `GH_HOST` is respected, and an older procache or a
failed resolution leaves the environment untouched. The resolved identity is
reused for five minutes.

Out of scope: the root-owned native observer bundle
(`/usr/local/lib/subactor-native-observer/327c8196-f1548ef4`) pins an older
monag/procache and sets `MONAG_DISABLE_PROCACHE=1`; adopting this requires its
operator-owned redeployment.

The owner asked why procache does not reduce GitHub API load and instructed
"kolejno wykonuj i testuj, scalaj" for the resulting work in this session.

## Acceptance criteria

- [x] AC-01: Scope is approved by a human owner.
- [x] AC-02: With the opt-in, cached reads receive the keyring identity and
      procache shares them; without it the previous guarantee holds.
- [x] AC-03: Explicit tokens, existing `GH_HOST`, older procache and failures
      are handled without changing the request target.
- [x] AC-04: Full suite passes with the installed and the new procache.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.

<!-- ticket-radar:start -->
## Ticket Radar

Initial planned-scope estimate; advisory only, not execution or merge approval.

| Measure | Initial assessment |
| --- | --- |
| Impact score | 52/100 |
| Complexity | M |
| Estimated effort | 51 min |
| Planning budget | 30 min |
| Split recommended | yes |

Diagnostics: RADAR-ACCEPTANCE-MISSING, RADAR-BUDGET-EXCEEDED.
<!-- ticket-radar:end -->
