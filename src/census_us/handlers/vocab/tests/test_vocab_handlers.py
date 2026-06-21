"""Tests for the census.Vocab NL -> ACS variable resolver."""

from __future__ import annotations

import json

from census_us.handlers.vocab import vocab_handlers as vh


def test_resolve_median_income():
    out = vh.handle({"_facet_name": "census.Vocab.ResolveVariable", "term": "median income"})
    res = out["result"]
    assert res["table_id"] == "B19013"
    assert res["confidence"] > 0.0
    assert "B19013_001E" in json.loads(res["columns"])
    assert isinstance(json.loads(res["alternatives"]), list)


def test_resolve_population():
    out = vh.handle({"_facet_name": "census.Vocab.ResolveVariable", "term": "total population"})
    assert out["result"]["table_id"] == "B01003"


def test_resolve_unknown_term_zero_confidence():
    out = vh.handle({"_facet_name": "census.Vocab.ResolveVariable", "term": "zzqq nonexistent"})
    res = out["result"]
    assert res["table_id"] == ""
    assert res["confidence"] == 0.0


def test_list_variables():
    out = vh.handle({"_facet_name": "census.Vocab.ListVariables"})
    variables = json.loads(out["variables"])
    assert out["count"] == len(variables) >= 12
    assert all({"table_id", "label", "columns"} <= set(v) for v in variables)


def test_dispatch_unknown_facet():
    import pytest

    with pytest.raises(ValueError):
        vh.handle({"_facet_name": "census.Vocab.Nope"})
