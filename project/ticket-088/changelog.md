# Changelog: ticket-088

- feat(autodiagnosis): implement Wellmanifest Priority lexicographic tier sorting (floor > mission > hygiene > backlog)
- feat(todo2code): enrich autodiagnosis tickets and Planfile sprint tasks with todo2code inputs (verify_command, contract, expect_files_changed) and defect labels
- feat(planfile): ensure Planfile sprint tasks are deterministically sorted by tier, priority, and creation timestamp
- test(autodiagnosis): add comprehensive unit and integration tests for priority sorting and todo2code verification
