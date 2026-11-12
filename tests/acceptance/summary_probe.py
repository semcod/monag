"""Frozen acceptance probe for `monag.summary.gather_planfile_daily` (PLF-25993).

Reads one JSON request on stdin, builds the described Planfile sprint files in a private
temporary directory, calls the function under test and prints one JSON object. Standard
library only, so it runs under `python -I -S -B`. An external evaluator keeps this file
outside the paths a candidate change may touch; it expects the package at `<repository>/src`.

Request: {"date": "YYYY-MM-DD", "view": "counts" | "times", "sprints": {file name: JSON document}}
"""
import datetime
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from monag.summary import gather_planfile_daily  # noqa: E402

ALLOWED = ("current.yaml.fast.json",)


def main():
    request = json.load(sys.stdin)
    day = datetime.date.fromisoformat(request["date"])
    with tempfile.TemporaryDirectory() as temp:
        sprints = Path(temp) / ".planfile" / "sprints"
        sprints.mkdir(parents=True)
        for name, document in request["sprints"].items():
            if name not in ALLOWED and name != f"history-{request['date']}.yaml.fast.json":
                raise SystemExit(f"unsupported sprint file: {name}")
            (sprints / name).write_text(json.dumps(document), encoding="utf-8")
        result = gather_planfile_daily(Path(temp), day, depth=0)
    completed = sorted(result["completed_tickets"], key=lambda row: row["id"])
    if request["view"] == "counts":
        output = {"completed_count": result["completed_count"], "completed_ids": [row["id"] for row in completed],
                  "queued_count": result["queued_count"]}
    elif request["view"] == "times":
        output = {"finished_at": {row["id"]: row["finished_at"] for row in completed}}
    else:
        raise SystemExit("unsupported view")
    print(json.dumps(output, sort_keys=True))


if __name__ == "__main__":
    main()
