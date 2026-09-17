# Ticket 037: open agent session from usage list

- **ID**: ticket-037
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-17

SESSION_EXECUTION_AUTHORIZATION: the user asked whether a numbered row (or
cursor selection) of `monag usage` can open that agent in a terminal or
browser to keep working on it.

## Goal and scope

- `usage` output gains a `#` row-number column (plain and markdown tables).
- New `monag open N` subcommand (also `open N` in `monag shell`) resolves the
  row — or an explicit `pid:NNNN` — against a fresh scan and launches the
  agent's resume command in a detached terminal at its working directory:
  `agy --continue`, `claude --continue`, `cursor-agent --continue`,
  `codex resume`, `opencode`; `devin` opens `devin desktop`.
- `--browser` uses a web route where one exists (`opencode web`,
  `devin desktop`); `--print` shows the launch command without spawning.
- IDE-managed ACP adapters (`*-acp`, `*-agent-acp`) are reported with their
  owning IDE and never respawned.
- Terminal discovery: `MONAG_TERMINAL` override, then the first available of
  `xdg-terminal-exec`, `gnome-terminal`, `konsole`, `kgx`, `alacritty`,
  `kitty`, `wezterm`, `xterm`, `x-terminal-emulator`.

Non-goals: no writes to agent state, no TTY hijacking of running processes,
no cloud-session linking.

## Acceptance criteria

- [ ] AC-01: `usage` prints a stable `#` number per agent row.
- [ ] AC-02: `monag open N` / `open pid:NNNN` resolves the row, launches the
      correct recipe, and `--print` is a no-spawn preview.
- [ ] AC-03: unknown rows, missing cwd, ACP adapters and absent terminals
      fail with a named reason, never a guessed effect.
- [ ] AC-04: focused and full test suites plus the governance gate pass.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
