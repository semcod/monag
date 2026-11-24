#!/usr/bin/env python3
"""Emit one Reflex check.fact about a Monag continuation snapshot or its Planfile queue."""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
import re
from pathlib import Path
import tempfile
import uuid
from urllib.parse import parse_qs, urlsplit


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


def remember(fact, path):
    """Atomically retain the original event identity while the same evidence persists."""
    with path.with_suffix(path.suffix + ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            previous = json.loads(path.read_bytes())
        except FileNotFoundError:
            previous = None
        identity = ("event_type", "repository", "operation", "task_id", "failure_code", "status", "evidence")
        if isinstance(previous, dict) and all(previous.get(key) == fact[key] for key in identity):
            return previous
        with tempfile.NamedTemporaryFile(dir=path.parent, mode="w", delete=False) as tmp:
            name = Path(tmp.name)
            try:
                json.dump(fact, tmp)
                tmp.flush()
                os.fsync(tmp.fileno())
                name.replace(path)
            finally:
                name.unlink(missing_ok=True)
        return fact


def inspect_queue(url):
    from monag.autonomy_probes import _discovery_failure

    try:
        endpoint = urlsplit(url)
        query = parse_qs(endpoint.query, keep_blank_values=True)
        valid = (
            endpoint.scheme in {"http", "https"} and endpoint.hostname
            and endpoint.username is None and not endpoint.fragment
            and query.get("mode") == ["queue"]
            and query.keys() <= {"mode", "queue", "state", "view", "limit"}
            and all(len(query.get(k, [])) == 1 and re.fullmatch(r"[A-Za-z0-9._-]{1,120}", query[k][0])
                    for k in ("queue", "state"))
        )
    except ValueError:
        valid = False
    if not valid:
        return {"reason": "invalid_queue_binding"}

    failure = _discovery_failure(url, configured=True, timeout=1.5)
    status, reason = failure if failure else (200, "queue_ready")
    return {"queue": query["queue"][0], "state": query["state"][0], "http_status": status, "reason": reason}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    source = cli.add_mutually_exclusive_group(required=True)
    source.add_argument("--snapshot", type=Path)
    source.add_argument("--planfile-queue-url", help="Scoped Planfile discovery URL, requires the Monag package")
    cli.add_argument("--root", type=Path)
    cli.add_argument("--target", required=True, help="Stable check target in this workspace")
    cli.add_argument("--max-age-seconds", type=int)
    cli.add_argument("--last-observation", type=Path, help="Private state file for replay of unchanged evidence")
    args = cli.parse_args()
    if args.snapshot is not None:
        if args.root is None or args.max_age_seconds is None or args.max_age_seconds <= 0:
            cli.error("--snapshot requires --root and positive --max-age-seconds")
        now = datetime.now(timezone.utc)
        proof = inspect_snapshot(args.snapshot, args.root.resolve(), now, args.max_age_seconds)
        reason = proof["state"]
        operation, repository, code = "ops.monag-continuation-snapshot", "semcod/monag", "unusable-snapshot"
        label, prefix, success = "Scheduled Monag snapshot", "monag-snapshot", reason == "fresh"
    else:
        if args.root is not None or args.max_age_seconds is not None:
            cli.error("--root and --max-age-seconds apply only to --snapshot")
        proof = inspect_queue(args.planfile_queue_url)
        now = datetime.now(timezone.utc)
        reason = proof["reason"]
        operation, repository, code = "ops.planfile-queue-discovery", "semcod/planfile", "queue-not-ready"
        label, prefix = "Planfile queue discovery", "monag-queue"
        success = proof.get("http_status") == 200 and reason == "queue_ready"
    invocation = os.environ.get("INVOCATION_ID") or uuid.uuid4().hex
    fact = {"event_type": "check.fact", "operation": operation, "repository": repository,
            "task_id": args.target, "failure_code": code, "failure_category": reason,
            "occurred_at": now.isoformat(), "source_event_id": f"{prefix}-{invocation}-{now.isoformat()}",
            "status": "success" if success else "failure", "summary": f"{label}: {reason}", "evidence": proof}
    print(json.dumps(remember(fact, args.last_observation) if args.last_observation else fact))


if __name__ == "__main__":
    main()
