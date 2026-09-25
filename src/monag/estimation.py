"""Integration with semcod/estimation for empirical process resource modeling.

Reads empirical process measurements from semcod-estimation store to predict
duration, peak memory, and CPU utilization for test verification commands.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import re
from typing import Any, Dict, List, Optional

DEFAULT_SAMPLES_STORE = Path.home() / ".local" / "state" / "semcod-estimation" / "process-samples.jsonl"


def _percentile(values: List[float], quantile: float) -> float:
    ordered = sorted(float(v) for v in values)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * quantile
    lower = math.floor(pos)
    upper = math.ceil(pos)
    if lower == upper:
        return ordered[lower]
    weight = pos - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _confidence(count: int) -> str:
    if count == 0:
        return "none"
    if count < 3:
        return "low"
    if count < 10:
        return "medium"
    return "high"


def derive_process_uri(command: str, target_repo: str) -> str:
    """Derive canonical Process URI from command semantics."""
    clean_repo = target_repo.strip("/").replace(" ", "-")
    cmd_lower = command.lower()
    if "pytest" in cmd_lower or "test" in cmd_lower or "testql" in cmd_lower:
        return f"testql://{clean_repo}/query/tests"
    if "status" in cmd_lower or "audit" in cmd_lower or "check" in cmd_lower:
        return f"artifact://{clean_repo}/registry/query/check"
    if "fix" in cmd_lower or "repair" in cmd_lower:
        return f"control://{clean_repo}/remediation/execute"
    return f"process://{clean_repo}/command/run"


def estimate_verification(
    command: str,
    target_repo: str,
    store_path: Optional[Path] = None
) -> Dict[str, Any]:
    """Calculate empirical resource estimation for a verification command using semcod/estimation."""
    target_store = store_path or DEFAULT_SAMPLES_STORE
    process_uri = derive_process_uri(command, target_repo)

    # 1. Try importing semcod/estimation directly
    samples_data = []
    try:
        from estimation.store import load_samples
        from estimation.stats import aggregate_samples
        if target_store.is_file():
            raw_samples = load_samples(target_store)
            if raw_samples:
                report = aggregate_samples(raw_samples)
                processes = report.get("processes", {})
                # Look for exact match or generic matching scheme
                matched_process = processes.get(process_uri)
                if not matched_process:
                    # Match by scheme or program
                    scheme = process_uri.split(":")[0]
                    for key, val in processes.items():
                        if key.startswith(f"{scheme}://"):
                            matched_process = val
                            break

                # If still no match, take any successful testql or overall baseline
                if not matched_process and processes:
                    for key, val in processes.items():
                        if "testql" in key or "tests" in key:
                            matched_process = val
                            break

                if matched_process and matched_process.get("successful_samples", 0) > 0:
                    metrics = matched_process.get("metrics", {})
                    dur_metrics = metrics.get("duration_seconds", {})
                    rss_metrics = metrics.get("peak_rss_bytes", {})
                    cpu_metrics = metrics.get("effective_cpu_cores", {})
                    succ_count = matched_process.get("successful_samples", 0)

                    p50_dur = dur_metrics.get("p50", 2.5)
                    p90_dur = dur_metrics.get("p90", 4.0)
                    peak_rss_bytes = rss_metrics.get("p90", 128 * 1024 * 1024)
                    effective_cores = cpu_metrics.get("p90", 0.8)

                    return {
                        "duration_p50_seconds": round(float(p50_dur), 2),
                        "duration_p90_seconds": round(float(p90_dur), 2),
                        "peak_rss_mb": round(float(peak_rss_bytes) / (1024 * 1024), 1),
                        "effective_cpu_cores": round(float(effective_cores), 2),
                        "confidence": matched_process.get("confidence", _confidence(succ_count)),
                        "samples_count": succ_count,
                        "process_uri": process_uri,
                        "source": "semcod.estimation",
                    }
    except Exception:
        pass

    # 2. Standalone file parsing fallback
    if target_store.is_file():
        try:
            durations, rss_values, cores_values = [], [], []
            for line in target_store.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                if row.get("outcome") in {"succeeded", "observed"}:
                    if "duration_seconds" in row:
                        durations.append(float(row["duration_seconds"]))
                    if "peak_rss_bytes" in row:
                        rss_values.append(float(row["peak_rss_bytes"]))
                    if "effective_cpu_cores" in row:
                        cores_values.append(float(row["effective_cpu_cores"]))

            if durations:
                p50_dur = _percentile(durations, 0.50)
                p90_dur = _percentile(durations, 0.90)
                p90_rss = _percentile(rss_values, 0.90) if rss_values else (128 * 1024 * 1024)
                p90_cores = _percentile(cores_values, 0.90) if cores_values else 0.8
                count = len(durations)

                return {
                    "duration_p50_seconds": round(p50_dur, 2),
                    "duration_p90_seconds": round(p90_dur, 2),
                    "peak_rss_mb": round(p90_rss / (1024 * 1024), 1),
                    "effective_cpu_cores": round(p90_cores, 2),
                    "confidence": _confidence(count),
                    "samples_count": count,
                    "process_uri": process_uri,
                    "source": "semcod.estimation",
                }
        except Exception:
            pass

    # 3. Conservative default envelope
    return {
        "duration_p50_seconds": 2.5,
        "duration_p90_seconds": 4.5,
        "peak_rss_mb": 128.0,
        "effective_cpu_cores": 0.8,
        "confidence": "none",
        "samples_count": 0,
        "process_uri": process_uri,
        "source": "default_envelope",
    }


def format_estimation_markdown(est: Dict[str, Any]) -> str:
    """Format estimation dictionary into GitHub markdown section."""
    conf = est.get("confidence", "none")
    samples = est.get("samples_count", 0)
    samples_note = f" ({samples} historical samples)" if samples > 0 else " (no prior samples recorded)"

    return f"""## Empirical Resource Estimation (semcod/estimation)
- **Process URI**: `{est.get('process_uri', 'process://unknown')}`
- **Expected Duration**: {est.get('duration_p50_seconds', 0)}s (p50) / **{est.get('duration_p90_seconds', 0)}s** (p90)
- **Peak RSS Memory**: {est.get('peak_rss_mb', 0)} MB
- **Effective CPU Cores**: ~{est.get('effective_cpu_cores', 0)}
- **Confidence**: `{conf}`{samples_note}
"""
