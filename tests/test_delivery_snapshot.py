import json

import pytest

from monag import delivery_snapshot


def test_snapshot_replaces_previous_contents(tmp_path):
    path = tmp_path / "snapshot.json"
    path.write_text("old data" * 100)
    snapshot = {"schema": "monag.resume/v1", "projects": []}
    delivery_snapshot.save_projection(snapshot, path, reflex=False)
    assert json.loads(path.read_text()) == snapshot
    assert path.stat().st_mode & 0o077 == 0


def test_failed_projection_keeps_last_observations(tmp_path, monkeypatch):
    path = tmp_path / "delivery.jsonl"
    path.write_text("previous scan")

    def incomplete(*args):
        yield {"event_type": "delivery.observation"}
        raise ValueError("incomplete projection")

    monkeypatch.setattr(delivery_snapshot, "_observations", incomplete)
    with pytest.raises(ValueError, match="incomplete"):
        delivery_snapshot.save_projection({}, path, reflex=True)
    assert path.read_text() == "previous scan"
    assert list(tmp_path.iterdir()) == [path]
