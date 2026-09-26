import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import urllib.request
import urllib.error

import pytest
from monag import panel


def test_page_contains_live_autorefresh_and_koru_buttons():
    assert "autorefresh" in panel.PAGE
    assert "pulse-dot" in panel.PAGE
    assert "toast" in panel.PAGE
    assert "dispatchToKoru" in panel.PAGE
    assert "dispatchSingleToKoru" in panel.PAGE
    assert "btn-koru" in panel.PAGE


def test_state_dispatch_koru(tmp_path: Path):
    state = panel.State(root=tmp_path, state_dir=tmp_path / "state")
    state.snapshot = {
        "agents": [
            {"pid": 12345, "kind": "koru", "command": "koru autonomous up"},
            {"pid": 67890, "kind": "other", "command": "other tool"},
        ]
    }

    mock_tickets = [
        {"target_repo": "semcod/monag", "ticket_id": "T-1", "title": "Fix conflict"},
        {"target_repo": "semcod/koru", "ticket_id": "T-2", "title": "Fix venv"},
    ]

    with patch.object(state, "autodiagnosis_run") as mock_run, \
         patch("monag.autodiagnosis.dispatch_tickets_to_planfile") as mock_dispatch:
        mock_run.return_value = {"tickets": mock_tickets}
        mock_dispatch.return_value = {"dispatched": 2, "tickets": mock_tickets}

        # 1. Dispatch all
        res = state.autodiagnosis_dispatch_koru()
        assert res["status"] == "ok"
        assert res["dispatched_count"] == 2
        assert res["koru_active"] is True
        assert res["koru_pids"] == [12345]

        # 2. Dispatch single target_repo
        mock_dispatch.return_value = {"dispatched": 1, "tickets": [mock_tickets[0]]}
        res_single = state.autodiagnosis_dispatch_koru(target_repo="semcod/monag")
        assert res_single["status"] == "ok"
        assert res_single["target_repo"] == "semcod/monag"
        mock_dispatch.assert_called_with([mock_tickets[0]], root=tmp_path, sync_github=True)


def test_http_dispatch_koru_endpoints(tmp_path: Path):
    import http.server
    import threading

    state = panel.State(root=tmp_path, state_dir=tmp_path / "state", bind="127.0.0.1", port=0)
    state.snapshot = {"agents": []}

    with patch.object(state, "autodiagnosis_dispatch_koru") as mock_dispatch:
        mock_dispatch.return_value = {
            "status": "ok",
            "action": "dispatch_to_koru",
            "dispatched_count": 1,
            "koru_active": False,
            "koru_pids": [],
        }

        handler_cls = panel.make_handler(state)
        server = http.server.HTTPServer(("127.0.0.1", 0), handler_cls)
        port = server.server_address[1]

        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            # Test GET
            url_get = f"http://127.0.0.1:{port}/api/autodiagnosis/dispatch-koru.json?repo=semcod/monag"
            req_get = urllib.request.Request(url_get, method="GET")
            with urllib.request.urlopen(req_get, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                assert data["status"] == "ok"
                assert data["dispatched_count"] == 1
                mock_dispatch.assert_called_with(target_repo="semcod/monag", ticket_id=None)

            # Test POST
            url_post = f"http://127.0.0.1:{port}/api/autodiagnosis/dispatch-koru.json"
            post_body = json.dumps({"repo": "semcod/koru", "title": "Fix bug"}).encode("utf-8")
            req_post = urllib.request.Request(url_post, data=post_body, headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req_post, timeout=5) as resp:
                data = json.loads(resp.read().decode())
                assert data["status"] == "ok"
                mock_dispatch.assert_called_with(target_repo="semcod/koru", ticket_id="Fix bug")
        finally:
            server.shutdown()
            server.server_close()
