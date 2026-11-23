"""File projections of the current resume scan for unattended consumers."""
from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile


def _observations(snapshot, directory):
    try:
        from bottlenecks.delivery import analyze_delivery
    except ImportError as exc:
        raise ValueError("--reflex-output requires Bottlenecks with delivery.planfile support") from exc

    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory) as source:
        json.dump(snapshot, source)
        source.flush()
        report = analyze_delivery(source.name)
    for item in report.items:
        yield dict(item.metrics["reflex"], occurred_at=snapshot["observed_at"])


def save_projection(snapshot: dict, destination: Path, *, reflex: bool) -> None:
    """Replace the last export only after serialization and analysis succeed."""
    staged = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=destination.parent,
                                prefix=f".{destination.name}.", delete=False) as output:
            staged = Path(output.name)
            rows = _observations(snapshot, destination.parent) if reflex else (snapshot,)
            for row in rows:
                json.dump(row, output, ensure_ascii=False)
                output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        staged.replace(destination)
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)
