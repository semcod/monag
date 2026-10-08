"""An agent without a reported task is labelled by the ticket worktree it works in (ticket-107)."""
import json
import tempfile
import unittest
from pathlib import Path

from monag.monitor import UNKNOWN_TASK, inferred_task, processes


class TaskInferenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def worktree(self, repo, ticket, slug, summary=None):
        path = self.root / repo / '.worktrees' / f'{ticket}--{slug}'
        (path / 'project' / ticket).mkdir(parents=True)
        if summary is not None:
            (path / 'project' / ticket / 'intent.json').write_text(json.dumps({'summary': summary}))
        return path

    def fake_process(self, proc, pid, parent, argv, cwd):
        p = proc / str(pid)
        p.mkdir(parents=True)
        (p / 'stat').write_text(f'{pid} (x) ' + ' '.join(['S', str(parent)] + ['0'] * 17 + ['123']))
        (p / 'cmdline').write_bytes('\0'.join(argv).encode() + b'\0')
        (p / 'cwd').symlink_to(cwd)

    def test_ticket_and_summary_are_named(self):
        wt = self.worktree('org/repo', 'ticket-042', 'fix-thing', 'Fix   the\nthing')
        self.assertEqual(inferred_task([str(wt / 'src')]),
                         'inferred from worktree: repo ticket-042: Fix the thing')

    def test_missing_intent_still_names_ticket(self):
        wt = self.worktree('org/repo', 'ticket-007', 'x')
        self.assertEqual(inferred_task([str(wt)]), 'inferred from worktree: repo ticket-007')

    def test_plain_directories_give_nothing(self):
        self.assertIsNone(inferred_task([str(self.root / 'org/repo'), '/tmp']))

    def test_unreadable_intent_is_tolerated(self):
        wt = self.worktree('org/repo', 'ticket-009', 'x')
        (wt / 'project' / 'ticket-009' / 'intent.json').write_text('{not json')
        self.assertEqual(inferred_task([str(wt)]), 'inferred from worktree: repo ticket-009')

    def test_agent_rows_use_child_worktree_and_keep_unknown_otherwise(self):
        proc = self.root / 'proc'
        workspace = self.root / 'org'
        wt = self.worktree('org/repo', 'ticket-100', 'feature', 'Add feature')
        self.fake_process(proc, 10, 1, ['/x/codex'], workspace)
        self.fake_process(proc, 11, 10, ['bash'], wt)
        self.fake_process(proc, 20, 1, ['/x/claude'], workspace)
        rows, _ = processes(workspace, proc)
        tasks = {r['pid']: r['task'] for r in rows}
        self.assertEqual(tasks[10], 'inferred from worktree: repo ticket-100: Add feature')
        self.assertEqual(tasks[20], UNKNOWN_TASK)


if __name__ == '__main__':
    unittest.main()
