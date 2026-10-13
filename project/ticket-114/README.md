# Ticket 114: fix: prevent horizontal viewport overflow in panel on tablet and mobile

- **ID**: ticket-114
- **Owner**: agent:antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-10-13

## Goal and scope

Prevent horizontal viewport overflow in Monag web panel on tablet and mobile viewports (`TW-VIEWPORT-OVERFLOW`). Ensure tables have horizontal scroll wrappers, button groups/headers wrap gracefully, form and option pill containers stay bounded within viewport width, and touch targets meet accessibility minimums.

SESSION_EXECUTION_AUTHORIZATION: user explicitly authorized autonomous execution, testing with digital twin and semcod/testwins, and fixing UX bugs and regressions across ~/github/*/*.

## Acceptance criteria

- [x] AC-01: Table containers in Monag panel allow horizontal scrolling without overflowing parent document width on mobile (<500px) and tablet (<900px) viewports.
- [x] AC-02: Header action button clusters (`h2`) wrap gracefully without blowing out document width.
- [x] AC-03: Responsive styles and minimum touch target sizes satisfy testwins accessibility criteria.
- [x] AC-04: Existing tests pass, new responsive panel tests pass, and governance checks pass.

## Bounds

maxActiveMinutes: 60; checkpointMinutes: 15. Only `src/monag/panel.py` and `tests/test_panel.py` are implementation scope.
