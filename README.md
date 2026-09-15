# monag

A terminal view of agents working across your GitHub workspace. Linux, Python
3.10+, Git; Rich renders Markdown in the terminal. Optional GitHub integration uses `gh`.

```sh
python3 -m pip install .
monag
monag status
monag --machine --agents-only watch
monag --machine --agents-only --view tree watch
monag --root ~/github --markdown status > activity.md
monag --root ~/github watch
monag --root ~/github --github status
monag --root ~/github --json status
monag history --search ticket-001
monag doctor
monag run --task "Fix issue #42" --issue 42 -- claude
./project.sh --help
```

Running `monag` in a terminal opens the interactive shell and immediately prints
the agent dashboard plus the restart/backlog inventory. Use `refresh` to repeat
both reports, `resume` for worktrees and Planfile tickets, `audit` for the
Planfile/GitHub comparison, and `quit` or Ctrl-D to exit. `monag watch` remains
available for an always-refreshing dashboard; Ctrl-C exits it.
Use `monag status` for one snapshot. Pipes, `--json`, and `--markdown` default
to one snapshot unless `watch` is explicit.

Shows agent process count, working directories, concurrent agents in a checkout,
process trees and their working directories, changed files, recent commits,
reported tasks, searchable local history, and optional GitHub issues/PRs.
Custom agents: `--agent LABEL=EXECUTABLE` or `run --agent-kind LABEL`.
Open descriptor paths: `--open-files`. Watch records observations by default;
use `watch --no-record` to disable recording.
Put global options before `status`, `watch`, or `run`.

Planfile tickets are stored per sprint. `planfile ticket list` shows only the
`current` sprint; inspect the backlog explicitly with `planfile ticket list
--sprint backlog` (or use `monag resume`, which reads every local sprint and
legacy keyed records). To reconcile local tickets with GitHub, run the
read-only preview first:

```sh
planfile sync github --dry-run --direction both
planfile sync github --direction both
```

[Usage, interpretation and limitations](docs/information/usage.md) ·
[Documentation](docs/README.md)

Governance checks are available through `./project.sh` on Linux/macOS and
`project.bat` on Windows; both entry points execute the repository's pinned
governance validator before optional analysis tooling.
