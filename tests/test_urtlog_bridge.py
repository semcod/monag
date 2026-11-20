"""Tests for the opt-in uritime-urtlog bridge in Monag."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from monag.urtlog_bridge import (
    normalize_monag_snapshot,
    record_monag_snapshot,
    resolve_state_dir,
)


class TestMonagUrtlogBridge(unittest.TestCase):
    def _sample_snapshot(self) -> dict:
        return {
            "observed_at": "2026-11-20T20:15:00+00:00",
            "agents": [
                {
                    "pid": 4242,
                    "kind": "codex",
                    "state": "S",
                    "cwd": "/home/tom/github/semcod/monag/.worktrees/ticket-151--pilot",
                    "task": "inferred from worktree: monag ticket-151: urtlog pilot",
                }
            ],
            "repositories": [
                {
                    "path": "/home/tom/github/semcod/monag/.worktrees/ticket-151--pilot",
                    "github": "semcod/monag",
                    "agents": [4242],
                }
            ],
        }

    def test_inactive_when_env_unset(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("URTLOG_STATE_DIR", None)
            self.assertIsNone(resolve_state_dir())
            self.assertEqual(record_monag_snapshot(self._sample_snapshot()), 0)

    def test_normalize_snapshot_resolves_repo_and_ticket(self) -> None:
        normalized = normalize_monag_snapshot(self._sample_snapshot())
        self.assertEqual(normalized["observed_at"], "2026-11-20T20:15:00+00:00")
        self.assertEqual(len(normalized["agents"]), 1)
        agent = normalized["agents"][0]
        self.assertEqual(agent["repository"], "semcod/monag")
        self.assertEqual(agent["ticket"], "ticket-151")
        self.assertEqual(agent["agent"], "codex")
        self.assertEqual(agent["status"], "running")

    def test_graceful_degradation_when_urtlog_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("monag.urtlog_bridge.importlib.import_module", side_effect=ImportError("no urtlog")):
                count = record_monag_snapshot(self._sample_snapshot(), state_dir=tmp)
            self.assertEqual(count, 0)

    @unittest.skipUnless(importlib.util.find_spec("urtlog") is not None, "urtlog not installed")
    def test_records_snapshot_when_urtlog_available(self) -> None:
        from urtlog import AccessContext, UrtClient

        with tempfile.TemporaryDirectory() as tmp:
            count = record_monag_snapshot(self._sample_snapshot(), state_dir=Path(tmp))
            self.assertEqual(count, 1)
            ctx = AccessContext(
                "heyasa",
                roles=frozenset({"assistant"}),
                groups=frozenset({"ops"}),
                max_sensitivity="internal",
            )
            with UrtClient(Path(tmp), source="monag", repository="semcod/monag") as client:
                rows = client.store.query(ctx, source="monag", op_prefix="op/monag/workspace/")
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["repository"], "semcod/monag")
                self.assertEqual(rows[0]["status"], "started")


if __name__ == "__main__":
    unittest.main()
