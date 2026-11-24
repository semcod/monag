import subprocess

import pytest

from monag import autonomy_probes, triage


def run_probe(monkeypatch, tmp_path, response, *, expected=True):
    url = "http://127.0.0.1:18769/health"
    monkeypatch.delenv("MONAG_PLANFILE_URTLOG_HEALTH_URL", raising=False)
    if expected:
        monkeypatch.setenv("MONAG_PLANFILE_URTLOG_HEALTH_URL", url)
    calls = []

    def http(endpoint, timeout):
        calls.append(endpoint)
        return response if endpoint == url else (200, {"status": "ok"})

    monkeypatch.setattr(autonomy_probes, "_http_probe", http)
    rows = autonomy_probes.probe_live_autonomy_blockers(
        include_runtime_probes=True, willman_db=tmp_path / "absent.db", heyasa_plans=tmp_path / "absent.json",
        systemctl_runner=lambda argv: subprocess.CompletedProcess(argv, 0, "", ""),
    )
    assert calls.count(url) == int(expected)
    return [row for row in rows if row.get("category") == "telemetry"]


def test_http_ok_and_disabled_bridge_reaches_operator_triage(monkeypatch, tmp_path):
    bridge = {"enabled": False, "state_dir_configured": False, "urtlog_importable": False,
              "execution_allowed": False, "advisory_only": True}
    alerts = run_probe(monkeypatch, tmp_path, (200, {"status": "ok", "urtlog_bridge": bridge}))
    alert, = alerts
    assert alert["cause"] == "planfile-urtlog-unready"
    assert alert["bridge"] == {key: False for key in ("enabled", "state_dir_configured", "urtlog_importable")}
    report = triage.run_holistic_triage(tmp_path, extra_candidates=alerts, include_runtime_probes=False)
    assert any(step["repo"] == "subactor/platform" for step in report["guidance_steps"])


@pytest.mark.parametrize("response", [
    (None, "connection refused"), (503, {}), (200, {"status": "ok"}),
    (200, {"urtlog_bridge": {"enabled": "false"}}),
])
def test_unknown_health_keeps_uncertainty(monkeypatch, tmp_path, response):
    alert, = run_probe(monkeypatch, tmp_path, response)
    assert alert["cause"] == "planfile-urtlog-unverified"


def test_healthy_advisory_bridge_and_intentionally_unmonitored_instance(monkeypatch, tmp_path):
    body = {"urtlog_bridge": {"enabled": True, "state_dir_configured": True,
                              "urtlog_importable": True, "execution_allowed": False}}
    assert run_probe(monkeypatch, tmp_path, (200, body)) == []
    assert run_probe(monkeypatch, tmp_path, (200, {}), expected=False) == []


@pytest.mark.parametrize("url", ["not-a-url", "http://[", "file:///var/log/planfile"])
def test_invalid_bridge_endpoint_preserves_triage(monkeypatch, url):
    def unexpected_request(*args):
        pytest.fail("unexpected health request")

    monkeypatch.setattr(autonomy_probes, "_http_probe", unexpected_request)
    alert = autonomy_probes._planfile_bridge_alert(url, 0.2)
    assert alert["cause"] == "planfile-urtlog-unverified"
