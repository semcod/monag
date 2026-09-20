# ticket-074 — Reliable packaged GitHub cache

- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Owner**: codex:monag-triage-cache-20260919

SESSION_EXECUTION_AUTHORIZATION: user requested execution of cache recommendations. Planfile PLF-025 / GitHub Issue88.

- [x] AC-01: Installed package includes immutable procache dependency; integration tests cannot silently skip.
- [x] AC-02: Invalid TTL is handled deterministically; timeout/cooldown/cache errors never trigger a duplicate external request.
- [x] AC-03: Installed smoke, full tests and governance pass.
- [ ] AC-04: Protected publication and installed runtime verified. Upstream procache PR2 merged at ca5dc2733ea9999572d654ab1fe9297a738c392c under explicit session Test-Driven Auto-Merge authorization; no Validator App approval claimed.

Validation: 11 cache regressions passed; full pytest suite passed with installed dependency; clean installation resolves immutable upstream Git dependency. No cache test skip.

Dependency now binds merged procache f1548ef488c133617b181005e8fd083eba2cc84b, including PyGithub identity/header correction from PR3. Command cache behavior is unchanged from tested PR2.
