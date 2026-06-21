"""Tests for the composability manifest (``census_us/catalog.yaml``).

Verifies the manifest loads, that every indexed workflow carries an intent
``summary`` + ``tags``, that every ``qualified_name`` (workflows + facets)
resolves to a real declaration in the package's FFL, and that there are no
duplicate qualified names.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from census_us import catalog

CENSUS_SRC = Path(__file__).resolve().parent.parent / "src" / "census_us"


def _ffl_files() -> list[Path]:
    return sorted(
        p
        for p in CENSUS_SRC.rglob("*.ffl")
        if "tests" not in p.parts and "fixtures" not in p.parts
    )


def _declared_qualified_names() -> set[str]:
    """Parse every package FFL and collect <namespace>.<name> for all decls."""
    from facetwork.cli import CompilerInput, FFLParser, FileOrigin, SourceEntry

    ffls = _ffl_files()
    ci = CompilerInput(
        primary_sources=[
            SourceEntry(text=p.read_text(), origin=FileOrigin(path=str(p)), is_library=False)
            for p in ffls
        ],
        library_sources=[],
    )
    program, _ = FFLParser().parse_sources(ci)
    names: set[str] = set()
    for ns in program.namespaces:
        for group in (ns.facets, ns.event_facets, ns.workflows):
            for decl in group:
                names.add(f"{ns.name}.{decl.sig.name}")
    return names


def test_manifest_loads():
    m = catalog.load_manifest()
    assert isinstance(m, dict)
    assert m.get("package") == "census-us"
    assert isinstance(catalog.workflows(), list) and catalog.workflows()
    assert isinstance(catalog.facets(), list) and catalog.facets()


def test_workflows_have_summary_and_tags():
    for wf in catalog.workflows():
        qn = wf.get("qualified_name", "<missing>")
        assert wf.get("entry_point") is True, f"{qn} not marked entry_point"
        assert wf.get("summary", "").strip(), f"{qn} missing summary"
        tags = wf.get("tags")
        assert isinstance(tags, list) and tags, f"{qn} missing tags"
        assert "param_schema" in wf, f"{qn} missing param_schema"


def test_facets_have_effect_and_cost():
    valid_effects = {"pure", "io", "external"}
    valid_costs = {"free", "cheap", "moderate", "expensive"}
    for fac in catalog.facets():
        qn = fac.get("qualified_name", "<missing>")
        assert fac.get("effect") in valid_effects, f"{qn} bad effect {fac.get('effect')!r}"
        assert fac.get("cost") in valid_costs, f"{qn} bad cost {fac.get('cost')!r}"
        assert fac.get("signature", "").strip(), f"{qn} missing signature"
        assert fac.get("purpose", "").strip(), f"{qn} missing purpose"


def test_qualified_names_resolve_to_real_decls():
    declared = _declared_qualified_names()
    manifest_names = [
        entry["qualified_name"]
        for entry in (*catalog.workflows(), *catalog.facets())
    ]
    missing = [qn for qn in manifest_names if qn not in declared]
    assert not missing, f"manifest qualified_names not found in FFL: {missing}"


def test_no_duplicate_qualified_names():
    names = [
        entry["qualified_name"]
        for entry in (*catalog.workflows(), *catalog.facets())
    ]
    dupes = {n for n in names if names.count(n) > 1}
    assert not dupes, f"duplicate qualified_names in manifest: {dupes}"


def test_all_ffl_compile_clean():
    """Every package FFL parses and validates with no errors."""
    from facetwork.cli import (
        CompilerInput,
        FFLParser,
        FileOrigin,
        SourceEntry,
        validate,
    )

    ffls = _ffl_files()
    texts = {p: p.read_text() for p in ffls}
    for primary in ffls:
        libs = [
            SourceEntry(text=texts[o], origin=FileOrigin(path=str(o)), is_library=True)
            for o in ffls
            if o != primary
        ]
        ci = CompilerInput(
            primary_sources=[
                SourceEntry(
                    text=texts[primary],
                    origin=FileOrigin(path=str(primary)),
                    is_library=False,
                )
            ],
            library_sources=libs,
        )
        program, _ = FFLParser().parse_sources(ci)
        result = validate(program)
        assert not result.errors, f"{primary.name}: {result.errors}"
