from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

from monag.autonomy_probes import probe_live_autonomy_blockers


QUEUE = "http://planfile.invalid/tickets/discovery?mode=queue&queue=coding-agent&state=pending"
PAGE = {
    "schema": "planfile.ticket-discovery/v1",
    "tickets": [],
    "scope": {"mode": "queue", "queue": "coding-agent", "state": "pending"},
}


def observe(monkeypatch, tmp_path, status, response, *, configured=True):
    monkeypatch.delenv("MONAG_PLANFILE_DISCOVERY_URL", raising=False)
    monkeypatch.delenv("MONAG_PLANFILE_URTLOG_HEALTH_URL", raising=False)
    if configured:
        monkeypatch.setenv("MONAG_PLANFILE_DISCOVERY_URL", QUEUE)

    def probe(url, _timeout):
        return (status, response) if "/tickets/discovery" in url else (200, {})

    with patch("monag.autonomy_probes._http_probe", side_effect=probe), patch(
        "monag.autonomy_probes.probe_fact_advisories", return_value=[]
    ):
        candidates = probe_live_autonomy_blockers(
            include_runtime_probes=True, willman_db=tmp_path / "willman",
            heyasa_plans=tmp_path / "plans", systemctl_runner=lambda argv: CompletedProcess(argv, 1),
        )
    return [item for item in candidates if item["origin"] == "runtime-planfile-health"]


@pytest.mark.parametrize(("status", "body", "reason"), [
    (503, {"detail": "ticket_index_stale"}, "ticket_index_stale"),
    (503, {"detail": "ticket_index_repair_pending"}, "ticket_index_repair_pending"),
    (503, {"detail": {"code": "store_lock_timeout"}}, "store_lock_timeout"),
    (503, {"error": "ticket_index_stale"}, "ticket_index_stale"),
    (502, "<html>Bad Gateway</html>", "http_502"),
    (None, "connection refused", "discovery_unreachable"),
    (200, {"status": "ok"}, "discovery_response_mismatch"),
    (200, {**PAGE, "tickets": {}}, "discovery_response_mismatch"),
    (200, {**PAGE, "scope": {**PAGE["scope"], "state": "ready"}}, "discovery_response_mismatch"),
])
def test_configured_queue_reports_actionable_evidence(monkeypatch, tmp_path, status, body, reason):
    [alert] = observe(monkeypatch, tmp_path, status, body)
    assert (alert["repo"], alert["detail"], alert["http_status"]) == ("semcod/planfile", reason, status)
    assert alert["cause"] == reason
    assert reason in alert["title"] and reason in alert["evidence"]


def test_valid_empty_queue_and_absent_optional_installation(monkeypatch, tmp_path):
    assert observe(monkeypatch, tmp_path, 200, PAGE) == []
    assert observe(monkeypatch, tmp_path, None, "refused", configured=False) == []
