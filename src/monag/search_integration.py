"""Integration bridge between monag and subactor_search / Liquid D1 JEV.

Provides AST-based code intent extraction (integrating code2llm map.toon.yaml
and code2logic function.toon) and fast Liquid D1 decision reranking for
monag triage and advisory recommendations.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SEARCH_CANDIDATE_PATHS = [
    Path.home() / "github" / "semcod" / "search" / "src",
    Path(__file__).resolve().parent.parent.parent.parent / "semcod" / "search" / "src",
]


def _find_subactor_search() -> Any:
    """Discover and import subactor_search from environment or workspace."""
    try:
        import subactor_search  # type: ignore
        return subactor_search
    except ImportError:
        pass

    for candidate in SEARCH_CANDIDATE_PATHS:
        if candidate.is_dir() and (candidate / "subactor_search").is_dir():
            candidate_str = str(candidate)
            if candidate_str not in sys.path:
                sys.path.insert(0, candidate_str)
            try:
                import subactor_search  # type: ignore
                return subactor_search
            except ImportError:
                continue
    return None


def discover_code_intents(
    root: Path | str,
    role: str | None = None,
    stage: str | None = None,
    max_modules: int = 32,
    max_functions: int = 128,
) -> list[dict[str, Any]]:
    """Extract code intent records and functions from repository AST or toon files."""
    root_path = Path(root).resolve()
    search_mod = _find_subactor_search()
    if search_mod is None:
        return []

    try:
        from subactor_search.intent_code import (  # type: ignore
            extract_project_code_intents,
        )
        from subactor_search.intent_adapters import (  # type: ignore
            adapt_code_intents_to_records,
        )

        schema_ir = extract_project_code_intents(root_path, max_modules=max_modules, max_functions=max_functions)
        if not schema_ir:
            return []

        records = adapt_code_intents_to_records(schema_ir, root_path.name)
        if role:
            role_tag = f"cqrs.{role.strip().lower()}"
            records = [r for r in records if role_tag in r.get("capabilities", [])]
        if stage:
            stage_lower = stage.strip().lower()
            records = [r for r in records if r.get("stage", "").lower() == stage_lower]
        return records
    except Exception as exc:
        logger.debug("Failed to extract code intents via subactor_search: %s", exc)
        return []


def rerank_recommendations_with_d1(
    query: str,
    recommendations: list[dict[str, Any]],
    model: str = "d1:3b",
    timeout_s: float = 15.0,
) -> list[dict[str, Any]]:
    """Rerank recommendations using fast local Liquid D1 (d1:3b) decision routing.

    Gracefully falls back to original ordering if inference is unreachable.
    """
    if not recommendations or len(recommendations) <= 1:
        return recommendations

    search_mod = _find_subactor_search()
    if search_mod is None:
        return recommendations

    try:
        from subactor_search.decision_adapter import d1_reranker  # type: ignore

        candidates = []
        for i, rec in enumerate(recommendations):
            cid = str(rec.get("id") or rec.get("ticket") or f"rec-{i}")
            desc = rec.get("title") or rec.get("description") or rec.get("summary") or ""
            caps = rec.get("tags") or rec.get("capabilities") or []
            candidates.append({
                "id": cid,
                "description": desc,
                "project": rec.get("repo") or rec.get("project") or "",
                "capabilities": caps,
            })

        rankings = d1_reranker(query, candidates, model=model, timeout_s=timeout_s)
        score_by_id = {r["id"]: r.get("score", 0.0) for r in rankings}
        reason_by_id = {r["id"]: r.get("reason", "") for r in rankings}

        ranked_recs = []
        for i, rec in enumerate(recommendations):
            cid = str(rec.get("id") or rec.get("ticket") or f"rec-{i}")
            new_rec = dict(rec)
            new_rec["_d1_score"] = score_by_id.get(cid, 0.0)
            new_rec["_d1_reason"] = reason_by_id.get(cid, "")
            ranked_recs.append(new_rec)

        ranked_recs.sort(key=lambda r: float(r.get("_d1_score", 0.0)), reverse=True)
        return ranked_recs
    except Exception as exc:
        logger.debug("Liquid D1 decision reranking unavailable: %s", exc)
        return recommendations
