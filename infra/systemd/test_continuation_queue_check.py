import json
import runpy
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


SCRIPT = Path(__file__).with_name("check-continuation-snapshot.py")
URL = "http://planfile.invalid/tickets/discovery?mode=queue&queue=coding-agent&state=ready"
PAGE = {"schema": "planfile.ticket-discovery/v1", "tickets": [],
        "scope": {"mode": "queue", "queue": "coding-agent", "state": "ready"}}


def sample(monkeypatch, capsys, tmp_path, response, url=URL, *, confirm=False):
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--planfile-queue-url", url, "--target", "central-coding-ready",
                                     "--last-observation", str(tmp_path / "ready.json")] + (["--confirm-queue-recovery"] if confirm else []))
    with patch("monag.autonomy_probes._http_probe", return_value=response):
        runpy.run_path(str(SCRIPT), run_name="__main__")
    return json.loads(capsys.readouterr().out)


def test_queue_change_replay_and_healing(monkeypatch, capsys, tmp_path):
    error = (503, {"detail": "ticket_index_stale", "private": "sensitive payload"})
    failed = sample(monkeypatch, capsys, tmp_path, error)
    assert sample(monkeypatch, capsys, tmp_path, error) == failed
    wrong = sample(monkeypatch, capsys, tmp_path, (200, {**PAGE, "scope": {**PAGE["scope"], "state": "pending"}}))
    healthy = sample(monkeypatch, capsys, tmp_path, (200, PAGE))
    assert sample(monkeypatch, capsys, tmp_path, (200, {**PAGE, "tickets": [{"id": "private-ticket"}]})) == healthy
    recurred = sample(monkeypatch, capsys, tmp_path, error)
    assert [x["status"] for x in (failed, wrong, healthy, recurred)] == ["failure", "failure", "success", "failure"]
    assert len({x["source_event_id"] for x in (failed, wrong, healthy, recurred)}) == 4
    assert len({(x["operation"], x["repository"], x["task_id"], x["failure_code"]) for x in (failed, healthy)}) == 1
    assert failed["evidence"] == {"queue": "coding-agent", "state": "ready", "http_status": 503, "reason": "ticket_index_stale"}
    assert wrong["evidence"]["reason"] == "discovery_response_mismatch"
    assert "sensitive payload" not in str(failed) and "private-ticket" not in str(healthy)


@pytest.mark.parametrize("url", ["http://host/health", URL.replace("mode=queue", "mode=other"),
                                  URL + "&state=pending", URL + "&repository=other%2Fproject", URL.replace("state=ready", "state=")])
def test_unqualified_binding_cannot_recover_a_queue(monkeypatch, capsys, tmp_path, url):
    observed = sample(monkeypatch, capsys, tmp_path, (200, PAGE), url)
    assert observed["status"] == "failure"
    assert observed["evidence"]["reason"] == "invalid_queue_binding"


def test_failure_status_cannot_be_labeled_healthy_by_the_backend(monkeypatch, capsys, tmp_path):
    observation = sample(monkeypatch, capsys, tmp_path, (503, {"detail": "queue_ready"}))
    assert observation["status"] == "failure" and observation["evidence"]["http_status"] == 503

def test_flapping_queue_keeps_original_failure_until_two_independent_successes(monkeypatch, capsys, tmp_path):
    failure = (503, {"detail": "ticket_index_stale"})
    success = (200, PAGE)

    def observe(invocation, response):
        monkeypatch.setenv("INVOCATION_ID", invocation)
        return sample(monkeypatch, capsys, tmp_path, response, confirm=True)

    # Start from a flat checkpoint created by the original producer.
    opened = sample(monkeypatch, capsys, tmp_path, failure)
    for invocation, response in [("a", success), ("a", success), ("b", failure), ("c", success), ("c", success)]:
        assert observe(invocation, response) == opened
    recovered = observe("d", success)
    assert recovered["status"] == "success"
    assert observe("e", success) == recovered
    reopened = observe("f", failure)
    assert reopened["status"] == "failure"
    assert reopened["source_event_id"] != opened["source_event_id"]


def test_healthy_start_is_visible_without_waiting_for_a_second_sample(monkeypatch, capsys, tmp_path):
    assert sample(monkeypatch, capsys, tmp_path, (200, PAGE), confirm=True)["status"] == "success"

def test_older_success_does_not_confirm_a_newer_incident(tmp_path):
    remember = runpy.run_path(str(SCRIPT))["remember"]
    state = tmp_path / "ready.json"
    def write(second, outcome):
        at = f"2026-11-25T00:00:{second:02d}+00:00"
        fact = {"event_type": "check.fact", "repository": "semcod/planfile", "operation": "ops.planfile-queue",
                "task_id": "ready", "failure_code": "queue-not-ready", "status": outcome,
                "evidence": {"queue": "coding-agent"}, "occurred_at": at, "source_event_id": f"sample-{second}"}
        return remember(fact, state, recovery_invocation=f"invocation-{second}")
    opened = write(10, "failure")
    assert write(9, "success") == opened
    assert write(11, "success") == opened
    assert write(12, "success")["status"] == "success"
