"""Machine consumers must receive public diagnosis data, not live cache handles."""
import json
import sqlite3
from unittest.mock import patch

import pytest

from monag.cli import main


def report(connection):
    return {"schema": "monag.autodiagnosis/v1", "timestamp": "2026-10-14T18:00:00+00:00",
            "root": "/workspace", "repositories_checked": 1, "repositories_cached": 1,
            "anomalies_count": 0, "anomalies": [], "_database": connection,
            "_repo_fingerprints": {"/workspace": ["head", "dirty"]}}


@pytest.mark.parametrize("cached", [False, True])
def test_json_diagnosis_has_only_public_fields_and_releases_owned_cache(capsys, cached):
    connection = sqlite3.connect(":memory:") if cached else None
    diagnosis = report(connection)
    def synthesize(value, **kwargs):
        if cached:
            assert value["_database"].execute("select 1").fetchone() == (1,)
        return []
    with patch("monag.autoupdate.check_for_updates"), patch("monag.autodiagnosis.diagnose_fleet", return_value=diagnosis), \
            patch("monag.autodiagnosis.synthesize_tickets_with_subllm", side_effect=synthesize):
        assert main(["--json", "autodiagnose", "--no-subllm"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["diagnosis"]["repositories_cached"] == 1
    assert not any(key.startswith("_") for key in output["diagnosis"])
    assert output["tickets"] == []
    if cached:
        with pytest.raises(sqlite3.ProgrammingError): connection.execute("select 1")


def test_synthesis_exception_still_closes_cli_owned_connection():
    connection = sqlite3.connect(":memory:")
    with patch("monag.autoupdate.check_for_updates"), patch("monag.autodiagnosis.diagnose_fleet", return_value=report(connection)), \
            patch("monag.autodiagnosis.synthesize_tickets_with_subllm", side_effect=RuntimeError("synthesis failed")):
        with pytest.raises(RuntimeError): main(["--json", "autodiagnose", "--no-subllm"])
    with pytest.raises(sqlite3.ProgrammingError): connection.execute("select 1")


def test_emit_planfile_keeps_existing_payload_contract_and_closes_cache(capsys):
    connection = sqlite3.connect(":memory:")
    tickets = [{"title": "sample", "priority": "high"}]
    with patch("monag.autoupdate.check_for_updates"), patch("monag.autodiagnosis.diagnose_fleet", return_value=report(connection)), \
            patch("monag.autodiagnosis.synthesize_tickets_with_subllm", return_value=tickets):
        assert main(["autodiagnose", "--no-subllm", "--emit-planfile"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["schema"] == "planfile.tickets/v1" and result["tickets"] == tickets
    with pytest.raises(sqlite3.ProgrammingError): connection.execute("select 1")


def test_fresh_machine_observation_bypasses_cache_and_honors_state_dir(tmp_path, capsys):
    with patch("monag.autoupdate.check_for_updates"), patch("monag.autodiagnosis.diagnose_fleet", return_value=report(None)) as diagnose, \
            patch("monag.autodiagnosis.synthesize_tickets_with_subllm", return_value=[]):
        assert main(["--root", str(tmp_path), "--state-dir", str(tmp_path / "state"), "--json", "autodiagnose", "--no-subllm", "--no-cache"]) == 0
    assert diagnose.call_args.kwargs == {"depth": 2, "use_cache": False, "state_dir": tmp_path / "state"}
    assert json.loads(capsys.readouterr().out)["tickets"] == []
