import json
from pathlib import Path
from unittest.mock import patch
import urllib.request

import pytest
from monag import panel, triage


def test_page_contains_triage_and_collision_elements():
    assert "Holistic Triage & Agent Worktree Collision Monitor" in panel.PAGE
    assert "triage-summary" in panel.PAGE
    assert 'id="triage"' in panel.PAGE
    assert "loadTriage" in panel.PAGE
    assert "dispatchTriageToKoru" in panel.PAGE
    assert "badge-collision" in panel.PAGE
    assert "badge-safe" in panel.PAGE


def test_state_get_triage_and_collisions(tmp_path: Path):
    state = panel.State(root=tmp_path, state_dir=tmp_path / "state")
    fake_triage = {
        "discovered_repos_count": 5,
        "total_candidates": 10,
        "active_agents_count": 2,
        "active_agent_pids": [101, 102],
        "dirty_worktrees_count": 1,
        "collision_count": 2,
        "recommendations": [
            {
                "repo": "semcod/monag",
                "collision": {"has_collision": True, "blocking": True},
            },
            {
                "repo": "semcod/koru",
                "collision": {"has_collision": False, "blocking": False},
            },
        ],
        "guidance_steps": [
            {
                "step": 1,
                "category": triage.CATEGORY_CORE_FOUNDATION,
                "repo": "semcod/koru",
                "title": "Clean worktree",
                "action": "Inspect clean worktree",
                "command": "git status",
                "collision_safe": True,
                "guardrails": ["Follow v5"],
            },
            {
                "step": 2,
                "category": triage.CATEGORY_STRATEGIC_ARCHITECTURE,
                "repo": "semcod/monag",
                "title": "Blocked task",
                "action": "Inspect collision",
                "command": "git status",
                "collision_safe": False,
                "guardrails": ["Agent running"],
            },
        ],
    }

    with patch("monag.triage.run_holistic_triage", return_value=fake_triage):
        res = state.get_triage()
        assert res["total_candidates"] == 10
        assert res["collision_count"] == 2

        collisions = state.get_collisions()
        assert collisions["active_agents_count"] == 2
        assert collisions["active_agent_pids"] == [101, 102]
        assert collisions["dirty_worktrees_count"] == 1
        assert collisions["collision_count"] == 2
        assert len(collisions["colliding_items"]) == 1


def test_state_triage_dispatch_koru(tmp_path: Path):
    state = panel.State(root=tmp_path, state_dir=tmp_path / "state")
    state.snapshot = {
        "agents": [
            {"pid": 2544975, "kind": "koru", "command": "koru autonomous up"}
        ]
    }

    fake_triage = {
        "guidance_steps": [
            {
                "step": 1,
                "category": triage.CATEGORY_CORE_FOUNDATION,
                "repo": "semcod/koru",
                "title": "Clean worktree",
                "action": "Inspect clean worktree",
                "command": "git status",
                "collision_safe": True,
                "guardrails": ["Follow v5"],
            },
            {
                "step": 2,
                "category": triage.CATEGORY_STRATEGIC_ARCHITECTURE,
                "repo": "semcod/monag",
                "title": "Blocked task",
                "action": "Inspect collision",
                "command": "git status",
                "collision_safe": False,
                "guardrails": ["Agent running"],
            },
        ],
    }

    with patch.object(state, "get_triage", return_value=fake_triage), \
         patch("monag.autodiagnosis.dispatch_tickets_to_planfile") as mock_dispatch:
        mock_dispatch.return_value = {"dispatched": 1, "tickets": []}

        # Safe dispatch should filter out collision_safe == False
        res = state.triage_dispatch_koru()
        assert res["status"] == "ok"
        assert res["dispatched_count"] == 1
        assert res["koru_active"] is True
        assert res["koru_pids"] == [2544975]
        # Only the first step (collision_safe == True) was dispatched
        dispatched_tickets = mock_dispatch.call_args[0][0]
        assert len(dispatched_tickets) == 1
        assert dispatched_tickets[0]["target_repo"] == "semcod/koru"


def test_http_triage_and_collision_endpoints(tmp_path: Path):
    import http.server
    import threading

    state = panel.State(root=tmp_path, state_dir=tmp_path / "state", bind="127.0.0.1", port=0)
    fake_triage = {
        "discovered_repos_count": 2,
        "total_candidates": 3,
        "active_agents_count": 1,
        "active_agent_pids": [555],
        "dirty_worktrees_count": 0,
        "collision_count": 0,
        "recommendations": [],
        "guidance_steps": [],
    }

    server = panel.bind_server(panel.make_handler(state), "127.0.0.1", 0)
    actual_port = server.server_address[1]

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        with patch("monag.triage.run_holistic_triage", return_value=fake_triage):
            # GET /api/triage.json
            url_triage = f"http://127.0.0.1:{actual_port}/api/triage.json"
            with urllib.request.urlopen(url_triage) as resp:
                assert resp.status == 200
                data = json.loads(resp.read().decode("utf-8"))
                assert data["discovered_repos_count"] == 2
                assert data["total_candidates"] == 3

            # GET /api/collisions.json
            url_collisions = f"http://127.0.0.1:{actual_port}/api/collisions.json"
            with urllib.request.urlopen(url_collisions) as resp:
                assert resp.status == 200
                col_data = json.loads(resp.read().decode("utf-8"))
                assert col_data["active_agents_count"] == 1
                assert col_data["active_agent_pids"] == [555]

            # POST /api/triage/dispatch-koru.json
            with patch.object(state, "triage_dispatch_koru", return_value={"status": "ok", "dispatched_count": 1}):
                url_dispatch = f"http://127.0.0.1:{actual_port}/api/triage/dispatch-koru.json"
                req = urllib.request.Request(url_dispatch, data=b"{}", headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req) as resp:
                    assert resp.status == 200
                    disp_data = json.loads(resp.read().decode("utf-8"))
                    assert disp_data["status"] == "ok"
                    assert disp_data["dispatched_count"] == 1
    finally:
        server.shutdown()
        server.server_close()
