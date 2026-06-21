"""Event-facet handlers for the ``census.Vocab`` namespace.

Wires ResolveVariable / ListVariables (census_vocab.ffl) to the ACS variable
catalogue in ``census_us.tools._lib.acs_extractor.ACS_TABLES``. Pure in-process
lookups (no network, no cache) that turn a natural-language indicator into the
ACS table + estimate columns it denotes — the deterministic NL->variable step
that lets a composer build "median income by county" as B19013 ->
ExtractIncome without memorising the Census variable catalogue.

``Json``-typed returns (columns, alternatives, variables) are emitted as JSON
strings, matching the convention used elsewhere in the fleet (e.g. osm.Vocab).
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from ..shared.census_utils import ACS_TABLES

log = logging.getLogger(__name__)

NAMESPACE = "census.Vocab"


# Hand-curated synonym phrases mapped to ACS table IDs, on top of matching the
# canonical ACS_TABLES labels. Purely additive vocabulary — no behavior change
# to extraction; this only resolves NL -> table_id.
_SYNONYMS: dict[str, list[str]] = {
    "B01003": ["population", "total population", "people", "residents", "headcount"],
    "B19013": ["income", "median income", "median household income", "household income", "earnings"],
    "B25001": ["housing", "housing units", "homes", "dwellings"],
    "B15003": ["education", "educational attainment", "schooling", "degrees", "college"],
    "B08301": ["commute", "commuting", "transportation", "means of transportation", "travel to work"],
    "B25003": ["tenure", "housing tenure", "owner vs renter", "ownership", "renters", "owners"],
    "B11001": ["households", "household type", "household composition", "families"],
    "B01001": ["age", "sex by age", "age distribution", "demographics", "ages"],
    "B25044": ["vehicles", "vehicles available", "cars", "car ownership"],
    "B02001": ["race", "racial composition", "ethnicity"],
    "B17001": ["poverty", "poverty status", "poverty rate", "poor"],
    "B23025": ["employment", "labor force", "jobs", "unemployment", "workers"],
}

_WORD = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def _variable_record(table_id: str) -> dict[str, Any]:
    """Build the {table_id, label, columns} record for an ACS table."""
    meta = ACS_TABLES.get(table_id, {})
    return {
        "table_id": table_id,
        "label": meta.get("label", ""),
        "columns": list(meta.get("columns", [])),
    }


def _score(term_tokens: set[str], candidate_text: str) -> float:
    """Jaccard-ish overlap of term tokens against a candidate phrase."""
    cand = _tokens(candidate_text)
    if not cand or not term_tokens:
        return 0.0
    overlap = term_tokens & cand
    if not overlap:
        return 0.0
    # Reward fraction of the term explained, with an exact-phrase bonus.
    frac = len(overlap) / len(term_tokens)
    if term_tokens == cand:
        return 1.0
    return min(0.95, 0.5 + 0.45 * frac)


def _resolve(term: str) -> list[dict[str, Any]]:
    """Rank ACS tables by how well they match the NL term. Best first."""
    term_tokens = _tokens(term)
    scored: list[tuple[float, str]] = []
    for table_id, meta in ACS_TABLES.items():
        candidates = [meta.get("label", "")] + _SYNONYMS.get(table_id, [])
        best = max((_score(term_tokens, c) for c in candidates), default=0.0)
        if best > 0.0:
            scored.append((best, table_id))
    scored.sort(key=lambda x: (-x[0], x[1]))
    out: list[dict[str, Any]] = []
    for confidence, table_id in scored:
        rec = _variable_record(table_id)
        rec["confidence"] = round(confidence, 3)
        rec["matched_term"] = term
        out.append(rec)
    return out


def handle_resolve_variable(params: dict[str, Any]) -> dict[str, Any]:
    """Resolve a natural-language indicator to the best ACS table + columns."""
    term = (params.get("term") or "").strip()
    step_log = params.get("_step_log")
    if not term:
        raise ValueError("ResolveVariable: term is required")

    matches = _resolve(term)
    best = matches[0] if matches else None
    alternatives = matches[1:]

    if step_log:
        if best:
            step_log(
                f"ResolveVariable: {term!r} -> {best['table_id']} "
                f"({best['label']}, conf {best['confidence']:.2f}, +{len(alternatives)} alt)",
                level="success",
            )
        else:
            step_log(f"ResolveVariable: {term!r} -> no known ACS variable", level="warning")

    return {
        "result": {
            "table_id": best["table_id"] if best else "",
            "label": best["label"] if best else "",
            "columns": json.dumps(best["columns"] if best else []),
            "confidence": best["confidence"] if best else 0.0,
            "matched_term": term,
            "alternatives": json.dumps(alternatives),
        }
    }


def handle_list_variables(params: dict[str, Any]) -> dict[str, Any]:
    """List every ACS table the vocabulary covers."""
    step_log = params.get("_step_log")
    variables = [_variable_record(tid) for tid in ACS_TABLES]
    if step_log:
        step_log(f"ListVariables: {len(variables)} ACS tables", level="success")
    return {"variables": json.dumps(variables), "count": len(variables)}


VOCAB_FACETS = [
    ("ResolveVariable", handle_resolve_variable),
    ("ListVariables", handle_list_variables),
]


_DISPATCH: dict[str, Any] = {}


def _build_dispatch() -> None:
    for facet_name, fn in VOCAB_FACETS:
        _DISPATCH[f"{NAMESPACE}.{facet_name}"] = fn


_build_dispatch()


def handle(payload: dict[str, Any]) -> dict[str, Any]:
    """RegistryRunner dispatch entrypoint."""
    facet_name = payload["_facet_name"]
    handler = _DISPATCH.get(facet_name)
    if handler is None:
        raise ValueError(f"Unknown facet: {facet_name}")
    return handler(payload)


def register_handlers(runner) -> None:
    """Register all census.Vocab facets with a RegistryRunner."""
    for facet_name in _DISPATCH:
        runner.register_handler(
            facet_name=facet_name,
            module_uri=f"file://{os.path.abspath(__file__)}",
            entrypoint="handle",
        )


def register_vocab_handlers(poller) -> None:
    """Register all census.Vocab event facet handlers with an AgentPoller."""
    for facet_name, fn in VOCAB_FACETS:
        qualified_name = f"{NAMESPACE}.{facet_name}"
        poller.register(qualified_name, fn)
        log.debug("Registered vocab handler: %s", qualified_name)
