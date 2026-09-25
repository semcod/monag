"""SQLite persistent store for fleet autodiagnosis and incremental caching.

Ensures that repositories whose Git state (HEAD commit SHA and working tree status)
has not changed since the last diagnostic pass are not redundantly rescanned or
synthesized, eliminating duplicate ticket records and unnecessary compute.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple


def default_db_path(state_dir: Optional[Path] = None) -> Path:
    if state_dir is not None:
        return state_dir / "autodiagnosis.sqlite3"
    local_state = Path.home() / ".local" / "state" / "monag"
    return local_state / "autodiagnosis.sqlite3"


def connect(state_dir: Optional[Path] = None, db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Connect to autodiagnosis SQLite database and ensure schema is initialized."""
    target = db_path or default_db_path(state_dir)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    # Secure file permissions before sqlite3 opens it
    if not target.exists():
        fd = os.open(target, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)

    db = sqlite3.connect(target, timeout=15)
    db.row_factory = sqlite3.Row

    with db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS repo_snapshots (
                repo_path TEXT PRIMARY KEY,
                head_sha TEXT NOT NULL,
                dirty_digest TEXT NOT NULL,
                scanned_at REAL NOT NULL,
                anomalies_json TEXT NOT NULL,
                tickets_json TEXT NOT NULL
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS dispatched_tasks (
                task_id TEXT PRIMARY KEY,
                repo_path TEXT NOT NULL,
                anomaly_code TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                task_json TEXT NOT NULL,
                dispatched_at REAL NOT NULL
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_repo_snapshots_scanned ON repo_snapshots(scanned_at)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_dispatched_repo ON dispatched_tasks(repo_path, anomaly_code)")

    return db


def compute_repo_fingerprint(repo_path: Path) -> Tuple[str, str]:
    """Compute (head_sha, dirty_digest) for a repository checkout."""
    if not (repo_path / ".git").exists():
        # Fallback for non-git directory: hash directory mtime
        try:
            mtime = repo_path.stat().st_mtime
            return f"nongit-{mtime}", ""
        except OSError:
            return "unknown", ""

    # 1. Resolve HEAD commit SHA
    head_sha = "empty"
    try:
        res = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5, check=False
        )
        if res.returncode == 0 and res.stdout.strip():
            head_sha = res.stdout.strip()
    except Exception:
        pass

    # 2. Check dirty working tree state
    dirty_digest = ""
    try:
        res = subprocess.run(
            ["git", "-C", str(repo_path), "status", "--porcelain"],
            capture_output=True, text=True, timeout=5, check=False
        )
        if res.returncode == 0:
            porcelain = res.stdout.strip()
            if porcelain:
                dirty_digest = hashlib.sha256(porcelain.encode("utf-8")).hexdigest()
    except Exception:
        pass

    return head_sha, dirty_digest


def get_cached_diagnosis(
    db: sqlite3.Connection,
    repo_path: str,
    head_sha: str,
    dirty_digest: str,
    max_age_seconds: Optional[float] = None
) -> Optional[Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]]:
    """Retrieve cached anomalies and tickets if the repository fingerprint matches."""
    cursor = db.cursor()
    cursor.execute(
        "SELECT head_sha, dirty_digest, scanned_at, anomalies_json, tickets_json "
        "FROM repo_snapshots WHERE repo_path = ?",
        (repo_path,)
    )
    row = cursor.fetchone()
    if not row:
        return None

    if row["head_sha"] != head_sha or row["dirty_digest"] != dirty_digest:
        return None

    if max_age_seconds is not None:
        if (time.time() - row["scanned_at"]) > max_age_seconds:
            return None

    try:
        anomalies = json.loads(row["anomalies_json"])
        tickets = json.loads(row["tickets_json"])
        return anomalies, tickets
    except (json.JSONDecodeError, TypeError):
        return None


def save_cached_diagnosis(
    db: sqlite3.Connection,
    repo_path: str,
    head_sha: str,
    dirty_digest: str,
    anomalies: List[Dict[str, Any]],
    tickets: List[Dict[str, Any]]
) -> None:
    """Save or update diagnosis results and state fingerprint in SQLite."""
    with db:
        db.execute(
            """
            INSERT INTO repo_snapshots (repo_path, head_sha, dirty_digest, scanned_at, anomalies_json, tickets_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(repo_path) DO UPDATE SET
                head_sha = excluded.head_sha,
                dirty_digest = excluded.dirty_digest,
                scanned_at = excluded.scanned_at,
                anomalies_json = excluded.anomalies_json,
                tickets_json = excluded.tickets_json
            """,
            (
                repo_path,
                head_sha,
                dirty_digest,
                time.time(),
                json.dumps(anomalies, ensure_ascii=True),
                json.dumps(tickets, ensure_ascii=True),
            )
        )


def record_dispatched_task(
    db: sqlite3.Connection,
    task_id: str,
    repo_path: str,
    anomaly_code: str,
    fingerprint: str,
    task_data: Dict[str, Any]
) -> None:
    """Record that a task has been dispatched to Planfile for a given defect fingerprint."""
    with db:
        db.execute(
            """
            INSERT OR REPLACE INTO dispatched_tasks
            (task_id, repo_path, anomaly_code, fingerprint, task_json, dispatched_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                repo_path,
                anomaly_code,
                fingerprint,
                json.dumps(task_data, ensure_ascii=True),
                time.time(),
            )
        )


def is_task_already_dispatched(
    db: sqlite3.Connection,
    repo_path: str,
    anomaly_code: str,
    fingerprint: str
) -> bool:
    """Check if a task for this defect fingerprint has already been dispatched."""
    cursor = db.cursor()
    cursor.execute(
        "SELECT 1 FROM dispatched_tasks WHERE repo_path = ? AND anomaly_code = ? AND fingerprint = ?",
        (repo_path, anomaly_code, fingerprint)
    )
    return cursor.fetchone() is not None


def get_all_cached_tickets(db: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Retrieve all tickets from current repository snapshots in the database."""
    cursor = db.cursor()
    cursor.execute("SELECT tickets_json FROM repo_snapshots")
    all_tickets = []
    for row in cursor.fetchall():
        try:
            tickets = json.loads(row["tickets_json"])
            if isinstance(tickets, list):
                all_tickets.extend(tickets)
        except Exception:
            continue
    return all_tickets
