#!/usr/bin/env python3
"""Emit one Reflex check.fact about an existing Monag continuation snapshot."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import uuid


def inspect_snapshot(path, root, now, max_age):
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return {"state": "missing" if isinstance(exc, FileNotFoundError) else "unreadable"}
    proof = {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    try:
        report = json.loads(raw)
        if not isinstance(report, dict) or report.get("schema") != "monag.resume/v1":
            return dict(proof, state="wrong-schema")
        if report.get("root") != str(root) or not isinstance(report.get("projects"), list):
            return dict(proof, state="wrong-workspace-or-projects")
        timestamp = report["observed_at"]
        observed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if observed.utcoffset() is None:
            raise ValueError("timezone required")
    except (ValueError, KeyError, AttributeError, TypeError, OverflowError, RecursionError):
        return dict(proof, state="invalid-document")
    age = (now - observed).total_seconds()
    if age < 0:
        return dict(proof, state="future-timestamp")
    return dict(proof, state="stale" if age > max_age else "fresh", observed_at=timestamp,
                projects=len(report["projects"]))


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--snapshot", type=Path, required=True)
    cli.add_argument("--root", type=Path, required=True)
    cli.add_argument("--target", required=True, help="Stable check target in this workspace")
    cli.add_argument("--max-age-seconds", type=int, required=True)
    args = cli.parse_args()
    if args.max_age_seconds <= 0:
        cli.error("--max-age-seconds must be positive")
    now = datetime.now(timezone.utc)
    proof = inspect_snapshot(args.snapshot, args.root.resolve(), now, args.max_age_seconds)
    invocation = os.environ.get("INVOCATION_ID") or uuid.uuid4().hex
    fact = {"event_type": "check.fact", "operation": "ops.monag-continuation-snapshot",
            "repository": "semcod/monag", "task_id": args.target, "failure_code": "unusable-snapshot",
            "failure_category": proof["state"], "occurred_at": now.isoformat(),
            "source_event_id": "monag-snapshot-" + invocation,
            "status": "success" if proof["state"] == "fresh" else "failure",
            "summary": "Scheduled Monag snapshot: " + proof["state"], "evidence": proof}
    print(json.dumps(fact))


if __name__ == "__main__":
    main()
