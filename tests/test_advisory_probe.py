from contextlib import closing
import json
import sqlite3
import subprocess

import pytest

from monag import advisory_probe as probe
from monag import autonomy_probes, triage


@pytest.fixture
def journal(tmp_path, monkeypatch):
    monkeypatch.setenv("MONAG_OQLLM_FACT_PRINCIPAL", "ops")
    monkeypatch.setenv("URTLOG_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(probe.time, "time_ns", lambda: 100_000_000_000)
    with closing(sqlite3.connect(tmp_path / "urilog.sqlite3")) as conn:
        conn.execute("""CREATE TABLE events(seq INTEGER PRIMARY KEY, event_id TEXT UNIQUE, at_us INTEGER,
            source TEXT, status TEXT, summary TEXT, run_id TEXT, causation_id TEXT, owner_principal TEXT,
            uri_raw TEXT, record_json TEXT)""")

        def append(eid, status, *, cause=None, run="episode", at=50, owner="ops", source="oqllm-fact-attempt",
                   summary="", route=probe.ROUTE, **metadata):
            conn.execute("INSERT INTO events VALUES(NULL,?,?,?,?,?,?,?,?,?,?)",
                         (eid, int(at * 1_000_000), source, status, summary, run, cause, owner, route,
                          json.dumps({"metadata": metadata})))
            conn.commit()
        append("episode", "failed", run="scope", source="reflex-check", summary="opened", route="check://reflex/ci/example")
        yield append


def test_missing_attempt_and_inflight_deadline(journal, monkeypatch):
    unknown, = probe.probe_fact_advisories(1)
    assert unknown["advisory_state"] == "incomplete"
    journal("s1", "started", cause="episode", at=65, timeout_seconds=35)
    monkeypatch.setattr(probe.time, "time_ns", lambda: 99_999_999_000)
    assert probe.probe_fact_advisories(1) == []
    monkeypatch.setattr(probe.time, "time_ns", lambda: 100_000_000_000)
    overdue, = probe.probe_fact_advisories(1)
    assert (overdue["cause"], overdue["advisory_state"], overdue["age_seconds"]) == (unknown["cause"], "overdue_without_outcome", 35)
    journal("repeat", "failed", run="scope", cause="episode", source="reflex-check", summary="repeat")
    assert probe.probe_fact_advisories(1) == [overdue]


def test_failure_backoff_retry_and_receipt(journal, monkeypatch):
    journal("s1", "started", cause="episode", timeout_seconds=35)
    journal("failure1", "failed", cause="s1", at=85, failure_kind="timeout", retry_not_before_us=110_000_000)
    first, = probe.probe_fact_advisories(1)
    assert (first["advisory_state"], first["retry"]) == ("timeout", "backoff")
    monkeypatch.setattr(probe.time, "time_ns", lambda: 110_000_000_000)
    eligible, = probe.probe_fact_advisories(1)
    assert eligible["retry"] == "eligible"
    journal("s2", "started", cause="episode", at=110, timeout_seconds=35)
    retry, = probe.probe_fact_advisories(1)
    assert (retry["cause"], retry["advisory_state"], retry["attempt"]) == (first["cause"], "retry_in_progress", "s2")
    journal("fact-advice-episode", "succeeded", source="oqllm-fact-advice", cause="episode", run=None, at=111)
    assert probe.probe_fact_advisories(1) == []  # older receipts can lack run_id


def test_scoped_recovery_and_operator_triage(journal, monkeypatch, tmp_path):
    journal("s1", "started", cause="episode", timeout_seconds=35)
    journal("foreign", "succeeded", source="reflex-check", summary="recovered", run="scope", cause="episode", owner="other")
    journal("other-scope", "succeeded", source="reflex-check", summary="recovered", run="other", cause="episode")
    journal("other-episode", "succeeded", source="reflex-check", summary="recovered", run="scope", cause="another")
    monkeypatch.setattr(autonomy_probes, "_http_probe", lambda *args: (200, {}))
    rows = autonomy_probes.probe_live_autonomy_blockers(
        include_runtime_probes=True, willman_db=tmp_path / "absent", heyasa_plans=tmp_path / "absent",
        systemctl_runner=lambda args: subprocess.CompletedProcess(args, 0, "", ""),
    )
    report = triage.run_holistic_triage(tmp_path, extra_candidates=rows, include_runtime_probes=False)
    step, = [s for s in report["guidance_steps"] if s["cause"] == "oqllm-advice-episode"]
    assert "age 50s, deadline 35s" in step["title"]
    journal("good", "succeeded", source="reflex-check", summary="recovered", run="scope", cause="episode")
    assert probe.probe_fact_advisories(1) == []


def test_unverified_old_probe_and_wrong_route(journal):
    journal("foreign-start", "started", cause="episode", owner="other", timeout_seconds=5)
    journal("wrong-route", "started", cause="episode", route="subllm://other", timeout_seconds=5)
    alert, = probe.probe_fact_advisories(1)
    assert alert["advisory_state"] == "incomplete" and "attempt" not in alert
    journal("legacy", "started", cause="episode")
    alert, = probe.probe_fact_advisories(1)
    assert alert["advisory_state"] == "incomplete" and alert["attempt"] == "legacy"


def test_opt_in_absent_invalid_and_partial_journal(journal, monkeypatch, tmp_path):
    monkeypatch.setenv("MONAG_OQLLM_FACT_PRINCIPAL", "")
    assert probe.probe_fact_advisories(1) == []
    monkeypatch.setenv("MONAG_OQLLM_FACT_PRINCIPAL", "unobserved")
    assert probe.probe_fact_advisories(1)[0]["cause"] == "oqllm-advice-unobserved"
    monkeypatch.setenv("MONAG_OQLLM_FACT_PRINCIPAL", "ops")
    monkeypatch.setattr(probe, "MAX_EPISODES", 1)
    journal("next", "failed", run="different", source="reflex-check", summary="opened")
    assert {a["cause"] for a in probe.probe_fact_advisories(1)} == {"oqllm-advice-next", "oqllm-advice-coverage"}
    monkeypatch.setenv("URTLOG_STATE_DIR", str(tmp_path / "missing"))
    assert probe.probe_fact_advisories(1)[0]["cause"] == "oqllm-advice-journal"
    assert not (tmp_path / "missing").exists()
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "urilog.sqlite3").write_bytes(b"unreadable")
    monkeypatch.setenv("URTLOG_STATE_DIR", str(broken))
    assert probe.probe_fact_advisories(1)[0]["cause"] == "oqllm-advice-journal"
