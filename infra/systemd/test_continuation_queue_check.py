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


def sample(monkeypatch, capsys, tmp_path, response, url=URL):
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--planfile-queue-url", url, "--target", "central-coding-ready",
                                     "--last-observation", str(tmp_path / "ready.json")])
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
