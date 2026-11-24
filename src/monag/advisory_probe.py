"""Read the configured principal's outstanding URTLog fact advisories."""
from __future__ import annotations

from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import time


ROUTE = "subllm://decision/d1_3b/fact-review"
MAX_EPISODES = 32
OPEN_EPISODES = """
    SELECT e.event_id FROM events e
    WHERE e.owner_principal = ? AND e.source = 'reflex-check' AND e.summary = 'opened' AND e.status = 'failed'
      AND NOT EXISTS (
        SELECT 1 FROM events a WHERE a.event_id = 'fact-advice-' || e.event_id AND a.owner_principal = e.owner_principal
          AND a.causation_id = e.event_id AND a.uri_raw = ? AND a.source = 'oqllm-fact-advice' AND a.status = 'succeeded')
      AND NOT EXISTS (
        SELECT 1 FROM events r WHERE r.causation_id = e.event_id AND r.owner_principal = e.owner_principal
          AND r.run_id = e.run_id AND r.source = e.source AND r.summary = 'recovered' AND r.status = 'succeeded')
    ORDER BY e.seq DESC LIMIT ?
"""


def _alert(cause, title, evidence, **fields):
    return {"origin": "operator-alert", "category": "telemetry", "priority": "high", "repo": "oqllm/proxy",
            "cause": cause, "title": title, "evidence": evidence, **fields}


def _metadata(raw):
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    metadata = data.get("metadata") if isinstance(data, dict) else None
    return metadata if isinstance(metadata, dict) else {}


def _episode_alert(conn, principal, episode, now_us):
    start = conn.execute("""
        SELECT at_us, event_id, record_json FROM events
        WHERE run_id = ? AND owner_principal = ? AND uri_raw = ? AND source = 'oqllm-fact-attempt'
          AND status = 'started' AND causation_id = ?
        ORDER BY at_us DESC, seq DESC LIMIT 1
        """, (episode, principal, ROUTE, episode)).fetchone()
    cause = f"oqllm-advice-{episode}"
    if start is None:
        return _alert(cause, "OQLLM advisory attempt unverified", f"Episode {episode} has no recorded start.",
                      episode=episode, advisory_state="incomplete")
    age = now_us - start["at_us"]
    deadline = _metadata(start["record_json"]).get("timeout_seconds")
    if age < 0 or type(deadline) is not int or deadline <= 0:
        return _alert(cause, "OQLLM advisory timing unverified", f"Episode {episode} lacks a usable recorded deadline or clock.",
                      episode=episode, attempt=start["event_id"], advisory_state="incomplete")
    # Retain a confirmed failure while a later attempt is in flight.
    failure = conn.execute("""
        SELECT f.causation_id, f.record_json FROM events f JOIN events s ON s.event_id = f.causation_id
        WHERE f.run_id = ? AND f.owner_principal = ? AND f.uri_raw = ? AND f.source = 'oqllm-fact-attempt'
          AND f.status = 'failed' AND s.run_id = f.run_id AND s.causation_id = f.run_id AND s.uri_raw = f.uri_raw
          AND s.owner_principal = f.owner_principal AND s.source = f.source AND s.status = 'started'
        ORDER BY f.at_us DESC, f.seq DESC LIMIT 1
        """, (episode, principal, ROUTE)).fetchone()
    retry = None
    if failure is not None and failure["causation_id"] == start["event_id"]:
        result = _metadata(failure["record_json"])
        kind = result.get("failure_kind")
        state = kind if isinstance(kind, str) and kind in ("timeout", "http_error", "transport_error", "invalid_response") else "incomplete"
        eligible = result.get("retry_not_before_us")
        if type(eligible) is int:
            retry = "eligible" if now_us >= eligible else "backoff"
    elif age >= deadline * 1_000_000:
        state = "overdue_without_outcome"
    elif failure is not None:
        state = "retry_in_progress"
    else:
        return None
    age_seconds = round(age / 1_000_000, 2)
    title = f"OQLLM fact advisory {state} (age {age_seconds:g}s, deadline {deadline}s"
    evidence = f"Episode {episode}, attempt {start['event_id']}, age {age_seconds}s, recorded deadline {deadline}s."
    if retry:
        title += f", retry {retry}"
        evidence += f" Retry {retry}."
    return _alert(cause, title + ")", evidence, episode=episode, attempt=start["event_id"],
                  advisory_state=state, age_seconds=age_seconds, timeout_seconds=deadline, retry=retry)


def probe_fact_advisories(timeout: float) -> list[dict]:
    principal = os.environ.get("MONAG_OQLLM_FACT_PRINCIPAL", "").strip()
    if not principal:
        return []
    state_dir = os.environ.get("URTLOG_STATE_DIR", "").strip()
    unavailable = _alert("oqllm-advice-journal", "OQLLM fact journal unavailable",
                         "The configured advisory route has no readable native URTLog journal.")
    if not state_dir:
        return [unavailable]
    db = Path(state_dir) / "urilog.sqlite3"
    budget = max(0.01, float(timeout))
    end = time.monotonic() + budget
    try:
        with closing(sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True, timeout=budget)) as conn:
            conn.row_factory = sqlite3.Row
            conn.set_progress_handler(lambda: int(time.monotonic() >= end), 1000)
            conn.execute("BEGIN")
            episodes = conn.execute(OPEN_EPISODES, (principal, ROUTE, MAX_EPISODES + 1)).fetchall()
            if not episodes and not conn.execute(
                "SELECT 1 FROM events WHERE owner_principal = ? AND source = 'reflex-check' LIMIT 1", (principal,)
            ).fetchone():
                return [_alert("oqllm-advice-unobserved", "No Reflex fact observed for the advisory principal",
                               "No source observation is available to assess the configured route.")]
            now = time.time_ns() // 1000
            alerts = []
            for row in episodes[:MAX_EPISODES]:
                alert = _episode_alert(conn, principal, row["event_id"], now)
                if alert:
                    alerts.append(alert)
    except (OSError, sqlite3.Error):
        return [unavailable]
    if len(episodes) > MAX_EPISODES:
        alerts.append(_alert("oqllm-advice-coverage", "OQLLM fact journal partially inspected",
                             f"More than {MAX_EPISODES} unresolved episodes are present."))
    return alerts
