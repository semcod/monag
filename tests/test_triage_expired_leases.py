"""Triage surfaces expired claimed change leases as immediate blockers.

A stranded claim (owner gone, ``phase: claimed``, ``expiresAt`` in the past)
kept a project blocked for hours on 2026-11-19 while triage only listed
worktree counts.
"""
import json
from pathlib import Path

from monag import triage
from monag.fleet import lease_observation


def _lease(path: Path, **fields) -> dict:
    document = {"schema": "wellmanifest.change-lease/v1", "ticketId": "ticket-920", "phase": "claimed",
                "ownerActor": "agent:codex", "leaseRevision": 11, "fencingToken": 11,
                "heartbeatAt": "2026-11-18T14:45:12Z", "expiresAt": "2026-11-18T16:45:12Z", **fields}
    path.write_text(json.dumps(document))
    return dict(lease_observation(path, now=1_795_100_000.0), path=str(path))


def test_expired_claim_becomes_an_immediate_blocker(tmp_path):
    row = _lease(tmp_path / "ticket-920--job.json")
    found = triage.expired_claim_candidates("subactor/onedev-agent", {"lease_evidence": [row], "repo_path": "/r/onedev"})
    assert len(found) == 1
    candidate = found[0]
    assert candidate["cause"] == "expired_claimed_lease" and candidate["lease_owner"] == "agent:codex"
    category, _ = triage.classify_candidate(candidate, "subactor/onedev-agent", {})
    assert category == triage.CATEGORY_IMMEDIATE_BLOCKER
    action = triage.synthesize_triage_action(candidate, category, "subactor/onedev-agent", {})
    assert "agent:codex" in action["action"] and "ticket-920" in action["action"]
    assert action["suggested_command"] == "python3 .governance/idle_takeover.py --root /r/onedev observe"
    assert any("never authorizes takeover" in g for g in action["guardrails"])


def test_live_released_and_unexpired_leases_are_not_blockers(tmp_path):
    rows = [
        _lease(tmp_path / "a.json", expiresAt="2026-11-30T00:00:00Z"),
        _lease(tmp_path / "b.json", phase="released"),
        _lease(tmp_path / "c.json", expiresAt=None),
    ]
    assert triage.expired_claim_candidates("x/y", {"lease_evidence": rows}) == []


def test_expired_claims_deduplicate_per_repository(tmp_path):
    rows = [_lease(tmp_path / "ticket-1.json", ticketId="ticket-1"), _lease(tmp_path / "ticket-2.json", ticketId="ticket-2")]
    candidates = triage.expired_claim_candidates("x/y", {"lease_evidence": rows})
    ranked = triage.deduplicate_and_rank_candidates(candidates, collisions_by_repo={"x/y": {}})
    assert len(ranked) == 1
    assert ranked[0]["category"] == triage.CATEGORY_IMMEDIATE_BLOCKER
