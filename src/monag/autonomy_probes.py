"""Read-only bounded probes for live Heyasa/Willman/Planfile/systemd autonomy blockers."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

_AUTONOMY_UNIT_PREFIXES = (
    "heyasa",
    "willman",
    "subactor",
    "onedev",
    "planfile",
    "willmux",
    "validator",
)


def _http_probe(url: str, timeout: float) -> tuple[int | None, dict[str, Any] | str | None]:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=max(0.2, float(timeout))) as resp:
            raw = resp.read(32 * 1024).decode("utf-8", errors="replace")
            try:
                return int(getattr(resp, "status", 200)), json.loads(raw)
            except ValueError:
                return int(getattr(resp, "status", 200)), raw[:300]
    except urllib.error.HTTPError as exc:
        raw = ""
        try:
            raw = exc.read(16 * 1024).decode("utf-8", errors="replace")
        except Exception:
            pass
        try:
            return int(exc.code), json.loads(raw)
        except ValueError:
            return int(exc.code), raw[:300] or str(exc)
    except Exception as exc:
        return None, str(exc)[:200]


def _planfile_bridge_alert(url: str, timeout: float) -> dict[str, Any] | None:
    """Check the capability advertised by a central Planfile expected to emit telemetry."""
    try:
        endpoint = urllib.parse.urlsplit(url)
        valid_endpoint = endpoint.scheme in {"http", "https"} and bool(endpoint.hostname)
    except ValueError:
        valid_endpoint = False
    status, body = _http_probe(url, timeout) if valid_endpoint else (None, None)
    fields = ("enabled", "state_dir_configured", "urtlog_importable")
    bridge = body.get("urtlog_bridge") if status == 200 and isinstance(body, dict) else None
    flags = (
        {key: bridge[key] for key in fields if isinstance(bridge.get(key), bool)}
        if isinstance(bridge, dict) else {}
    )
    if len(flags) == len(fields) and all(flags.values()):
        return None
    missing = [key for key in fields if flags.get(key) is False]
    if missing:
        cause = "planfile-urtlog-unready"
        detail = "Reported false: " + ", ".join(missing)
    else:
        cause = "planfile-urtlog-unverified"
        detail = f"HTTP {status} returned no complete set of bridge readiness flags" if status else "Health endpoint unavailable"
        if not valid_endpoint:
            detail = "Bridge health URL must name an HTTP or HTTPS host"
    return {
        "origin": "operator-alert",
        "category": "telemetry",
        "priority": "high",
        "cause": cause,
        "repo": "subactor/platform",
        "title": f"Central Planfile URTLog bridge: {cause.removeprefix('planfile-urtlog-')}",
        "evidence": detail,
        "http_status": status,
        "bridge": flags,
    }


def probe_live_autonomy_blockers(
    *,
    timeout: float = 1.5,
    include_runtime_probes: bool | None = None,
    endpoint_urls: dict[str, str] | None = None,
    willman_db: Path | None = None,
    heyasa_plans: Path | None = None,
    systemctl_runner: Callable[[list[str]], subprocess.CompletedProcess[str]] | None = None,
) -> list[dict[str, Any]]:
    """Return P0/FLOOR candidates describing live local autonomy blockers."""
    in_pytest = bool(os.environ.get("PYTEST_CURRENT_TEST"))
    if include_runtime_probes is False or (include_runtime_probes is None and in_pytest):
        return []

    blockers: list[dict[str, Any]] = []
    urls = endpoint_urls or {}
    willman_url = urls.get("willman") or os.environ.get("MONAG_WILLMAN_HEALTH_URL", "http://127.0.0.1:7655/v1/health?readiness=1")
    planfile_url = urls.get("planfile") or os.environ.get("MONAG_PLANFILE_DISCOVERY_URL", "http://127.0.0.1:8765/tickets/discovery")
    heyasa_url = urls.get("heyasa") or os.environ.get("MONAG_HEYASA_HEALTH_URL", "http://127.0.0.1:8787/health")

    # 1. Willman readiness probe
    w_status, w_body = _http_probe(willman_url, timeout)
    if w_status == 503 or (isinstance(w_body, dict) and w_body.get("ready") is False):
        reason = w_body.get("reason") if isinstance(w_body, dict) else "HTTP 503"
        blockers.append({
            "origin": "runtime-willman-health",
            "category": "autonomy-blocker",
            "priority": "critical",
            "tier": "floor",
            "score": 5200,
            "unblock_impact": 5200,
            "suggested_command": f"curl -fsS {willman_url}",
            "repo": "heyasa/willman",
            "title": f"P0 Autonomy Blocker: Willman /v1/health unready ({w_status or 'err'}: {reason})",
            "detail": w_body if isinstance(w_body, dict) else str(w_body),
        })

    # 2. Central Planfile /tickets/discovery probe
    p_status, p_body = _http_probe(planfile_url, timeout)
    if p_status == 503 or (isinstance(p_body, dict) and p_body.get("error") == "ticket_index_stale"):
        detail = p_body.get("error") if isinstance(p_body, dict) else str(p_body)
        blockers.append({
            "origin": "runtime-planfile-health",
            "category": "autonomy-blocker",
            "priority": "critical",
            "tier": "floor",
            "score": 5150,
            "unblock_impact": 5150,
            "suggested_command": f"curl -fsS {planfile_url}",
            "repo": "wellmanifest/new-project",
            "title": f"P0 Autonomy Blocker: Planfile /tickets/discovery unhealthy ({p_status or 'err'}: {detail})",
            "detail": detail,
        })

    # Setting the health URL declares that this installation should emit URTLog events.
    bridge_url = urls.get("planfile_urtlog") or os.environ.get("MONAG_PLANFILE_URTLOG_HEALTH_URL")
    if bridge_url:
        alert = _planfile_bridge_alert(bridge_url, timeout)
        if alert is not None:
            blockers.append(alert)

    # 3. Heyasa /health & paused cyclic plans
    h_status, h_body = _http_probe(heyasa_url, timeout)
    if h_status == 503 or (isinstance(h_body, dict) and str(h_body.get("status", "")).lower() in {"degraded", "blocked", "unhealthy"}):
        blockers.append({
            "origin": "runtime-heyasa-health",
            "category": "autonomy-blocker",
            "priority": "critical",
            "tier": "floor",
            "score": 5100,
            "unblock_impact": 5100,
            "suggested_command": f"curl -fsS {heyasa_url}",
            "repo": "heyasa/heyasa",
            "title": f"P0 Autonomy Blocker: Heyasa /health unhealthy ({h_status or 'err'})",
            "detail": h_body if isinstance(h_body, dict) else str(h_body),
        })

    xdg_state = Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state"))
    w_db = Path(willman_db) if willman_db is not None else (xdg_state / "subactor" / "willman-project-jobs" / "projects.sqlite")
    if w_db.is_file():
        try:
            conn = sqlite3.connect(f"file:{w_db}?mode=ro", uri=True, timeout=1.0)
            uncertain_cnt = int(conn.execute("SELECT count(*) FROM jobs WHERE phase='uncertain'").fetchone()[0])
            conn.close()
            if uncertain_cnt > 0:
                blockers.append({
                    "origin": "runtime-willman-uncertain-jobs",
                    "category": "autonomy-blocker",
                    "priority": "critical",
                    "tier": "floor",
                    "score": 5180,
                    "unblock_impact": 5180,
                    "suggested_command": f"sqlite3 -readonly {w_db} \"SELECT id,phase FROM jobs WHERE phase='uncertain' LIMIT 10;\"",
                    "repo": "heyasa/willman",
                    "title": f"P0 Autonomy Blocker: {uncertain_cnt} stuck Willman job(s) in phase='uncertain'",
                    "uncertain_jobs": uncertain_cnt,
                })
        except Exception:
            pass

    h_plans = Path(heyasa_plans) if heyasa_plans is not None else (xdg_state / "heyasa" / "plans.json")
    if h_plans.is_file():
        try:
            pdata = json.loads(h_plans.read_text(encoding="utf-8"))
            plans = pdata.get("plans", pdata) if isinstance(pdata, dict) else pdata
            if isinstance(plans, list):
                paused = [p for p in plans if isinstance(p, dict) and str(p.get("status", "")).lower() in {"paused", "blocked"}]
                if paused:
                    blockers.append({
                        "origin": "runtime-heyasa-paused-plans",
                        "category": "autonomy-blocker",
                        "priority": "critical",
                        "tier": "floor",
                        "score": 5120,
                        "unblock_impact": 5120,
                        "suggested_command": f"jq '.plans[] | select(.status==\"paused\" or .status==\"blocked\") | .id' {h_plans}",
                        "repo": "heyasa/heyasa",
                        "title": f"P0 Autonomy Blocker: {len(paused)} paused/blocked Heyasa self-healing plan(s)",
                        "paused_plans": len(paused),
                    })
        except Exception:
            pass

    # 4. Failed user systemd autonomy units
    try:
        runner = systemctl_runner or (
            lambda argv: subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        )
        proc = runner(["systemctl", "--user", "--failed", "--no-legend", "--plain"])
        if proc.returncode == 0 and proc.stdout:
            failed_units = []
            for line in proc.stdout.splitlines():
                unit = (line.split() or [""])[0]
                if unit and any(unit.startswith(pref) for pref in _AUTONOMY_UNIT_PREFIXES):
                    failed_units.append(unit)
            if failed_units:
                blockers.append({
                    "origin": "runtime-systemd-failed",
                    "category": "autonomy-blocker",
                    "priority": "critical",
                    "tier": "floor",
                    "score": 5300,
                    "unblock_impact": 5300,
                    "suggested_command": f"systemctl --user status {' '.join(failed_units[:3])}",
                    "repo": "heyasa/heyasa",
                    "title": f"P0 Autonomy Blocker: failed systemd user unit(s): {', '.join(failed_units[:5])}",
                    "failed_units": failed_units,
                })
    except Exception:
        pass

    return blockers
