import sqlite3
import tempfile
from pathlib import Path
import unittest

from monag import autodiag_store


class TestAutodiagStore(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_diag.sqlite3"
        self.db = autodiag_store.connect(db_path=self.db_path)

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def test_database_initialization(self):
        cursor = self.db.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}
        self.assertIn("repo_snapshots", tables)
        self.assertIn("dispatched_tasks", tables)

    def test_save_and_retrieve_cached_diagnosis(self):
        repo = "/path/to/demo_repo"
        head_sha = "abc123456789"
        dirty = "dirty-hash-111"
        anomalies = [{"code": "NO_LICENSE", "target": "demo_repo", "tier": "hygiene"}]
        tickets = [{"title": "[demo_repo] fix(no-license)", "target_repo": "demo_repo"}]

        # Before saving -> cache miss
        self.assertIsNone(autodiag_store.get_cached_diagnosis(self.db, repo, head_sha, dirty))

        # Save diagnosis
        autodiag_store.save_cached_diagnosis(self.db, repo, head_sha, dirty, anomalies, tickets)

        # After saving with exact fingerprint -> cache hit
        cached = autodiag_store.get_cached_diagnosis(self.db, repo, head_sha, dirty)
        self.assertIsNotNone(cached)
        cached_anoms, cached_tkts = cached
        self.assertEqual(len(cached_anoms), 1)
        self.assertEqual(cached_anoms[0]["code"], "NO_LICENSE")
        self.assertEqual(len(cached_tkts), 1)
        self.assertEqual(cached_tkts[0]["title"], "[demo_repo] fix(no-license)")

        # With changed HEAD -> cache miss
        self.assertIsNone(autodiag_store.get_cached_diagnosis(self.db, repo, "different_sha", dirty))

        # With changed dirty state -> cache miss
        self.assertIsNone(autodiag_store.get_cached_diagnosis(self.db, repo, head_sha, "new_dirty"))

    def test_dispatched_task_tracking(self):
        repo = "org/repo"
        code = "NO_README"
        fingerprint = "fp_123"
        task = {"id": "task_1", "title": "Add README"}

        self.assertFalse(autodiag_store.is_task_already_dispatched(self.db, repo, code, fingerprint))
        autodiag_store.record_dispatched_task(self.db, "task_1", repo, code, fingerprint, task)
        self.assertTrue(autodiag_store.is_task_already_dispatched(self.db, repo, code, fingerprint))

        # Different fingerprint is not considered dispatched
        self.assertFalse(autodiag_store.is_task_already_dispatched(self.db, repo, code, "fp_new"))


if __name__ == "__main__":
    unittest.main()
