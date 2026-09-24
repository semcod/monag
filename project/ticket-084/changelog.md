# Changelog: ticket-084

- fix(monitor): report observation error for invalid `.git` directories missing HEAD while continuing traversal into descendant repositories
- feat(cli): propagate common options (`--limit`, `--hours`, `--github`, `--open-files`, `--agents-only`, `--machine`) across all CLI subparsers
- test(startup,doctor): add test coverage for subcommand option propagation and broken gitdir handling
