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

Running `monag` in a terminal starts interactive watch immediately. Exit with Ctrl-C.
Use `monag status` for one snapshot. Pipes, `--json`, and `--markdown` default
to one snapshot unless `watch` is explicit.

Shows agent process count, working directories, concurrent agents in a checkout,
process trees and their working directories, changed files, recent commits,
reported tasks, searchable local history, and optional GitHub issues/PRs.
Custom agents: `--agent LABEL=EXECUTABLE` or `run --agent-kind LABEL`.
Open descriptor paths: `--open-files`. Watch records observations by default;
use `watch --no-record` to disable recording.
Put global options before `status`, `watch`, or `run`.

[Usage, interpretation and limitations](docs/information/usage.md) ·
[Documentation](docs/README.md)

Governance checks are available through `./project.sh` on Linux/macOS and
`project.bat` on Windows; both entry points execute the repository's pinned
governance validator before optional analysis tooling.
