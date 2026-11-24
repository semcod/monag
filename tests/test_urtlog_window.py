from contextlib import closing
from datetime import datetime, timezone
import sqlite3

import pytest

from monag.summary import _read_urtlog_window, format_markdown, gather_summary


def journal(path, schema, insert=None, rows=()):
    with closing(sqlite3.connect(path)) as conn:
        conn.execute(schema)
        if insert:
            conn.executemany(insert, rows)
        conn.commit()


def test_native_window_and_daily_configuration(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    state = tmp_path / "ops #1?"
    state.mkdir()
    db = state / "urilog.sqlite3"
    monkeypatch.setenv("URTLOG_STATE_DIR", str(state))
    end = int(datetime.now(timezone.utc).timestamp()) * 1_000_000 - 10_000_000
    start = end - 86_400_000_000
    journal(db, "CREATE TABLE events (at_us INTEGER, status TEXT, created_at TEXT)",
            "INSERT INTO events VALUES (?, ?, '1970-01-01')",
            [(start - 1, "failed"), (start, "ERROR"), (end, "success"), (end + 1, "failed")])
    assert _read_urtlog_window(db, start, end) == (2, 1, "observed")
    day = gather_summary(tmp_path, github=False, mode="day", telemetry_paths={})
    coverage = day["delta_24h"]["runtime_telemetry_24h"]
    assert (coverage["urtlog_events_24h"], coverage["urtlog_failed_events_24h"], coverage["urtlog_read_status"]) == (
        2, 1, "observed"
    )
    assert "Zdarzenia ogółem 2, w tym błędne 1." in format_markdown(day)
    absent = tmp_path / "missing"
    day = gather_summary(tmp_path, github=False, mode="day", telemetry_paths={"urtlog_db": absent})
    assert day["delta_24h"]["runtime_telemetry_24h"]["urtlog_read_status"] == "missing"
    assert "Brak pliku dziennika." in format_markdown(day)
    assert not absent.exists()


@pytest.mark.parametrize("column", ["created_at", "occurred_at", "timestamp", "ts"])
def test_legacy_epoch_and_iso_windows(tmp_path, column):
    db = tmp_path / "legacy.sqlite"
    end = 1_790_000_000
    def iso(seconds):
        return datetime.fromtimestamp(seconds, timezone.utc).isoformat()

    journal(db, f"CREATE TABLE runs ({column}, outcome TEXT)", "INSERT INTO runs VALUES (?, ?)", [
        (end - 4000, "failed"), (iso(end - 4000), "timeout"), (iso(end + 60), "error"),
        (end - 60, "success"), (iso(end - 120), "TIMEOUT"), (str(end - 30), "error"), ("invalid", "failed"),
    ])
    assert _read_urtlog_window(db, (end - 3600) * 1_000_000, end * 1_000_000) == (3, 2, "observed")


def test_distinguishes_empty_partial_unreadable_and_unknown(tmp_path):
    db = tmp_path / "journal"
    assert _read_urtlog_window(db, 0, 10) == (0, 0, "missing")
    db.write_bytes(b"invalid sqlite")
    assert _read_urtlog_window(db, 0, 10) == (0, 0, "unreadable")
    db.unlink()
    journal(db, "CREATE TABLE unrelated (status TEXT)")
    assert _read_urtlog_window(db, 0, 10) == (0, 0, "unsupported_schema")
    journal(db, "CREATE TABLE runs (at_us INTEGER)", "INSERT INTO runs VALUES (?)", [(10,)])
    assert _read_urtlog_window(db, 0, 10) == (1, 0, "status_unavailable")
    journal(db, "CREATE TABLE events (at_us INTEGER, status TEXT)")
    assert _read_urtlog_window(db, 0, 10) == (0, 0, "observed")
