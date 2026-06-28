"""Offline test for incremental-safe landing publish.

The publish landing/section pages are rebuilt from the dests passed to one
``publish_bundles`` call. To avoid clobbering the gallery down to just that
call's bundles, ``_harvest_existing`` reads the bundles + descriptions already
in the cloned repo so they can be merged back in. This round-trips the harvest
against the exact generators that wrote the landing.
"""

from __future__ import annotations

import os


def test_harvest_round_trips_landing(tmp_path):
    from census_us.tools._lib import publish as P

    sections = {
        "world": [("Nuclear power sites (world)", "world/nuclear"),
                  ("Volcanoes (world)", "world/volcanoes")],
        "census": [("Metrics", "census/metrics")],
    }
    repo = str(tmp_path)
    with open(os.path.join(repo, "index.html"), "w", encoding="utf-8") as f:
        f.write(P._grouped_landing_html("Facetwork maps", sections, description="Root intro."))
    for sec, items in sections.items():
        os.makedirs(os.path.join(repo, sec), exist_ok=True)
        rel = [(P._strip_section_suffix(l), dst.split("/", 1)[1]) for l, dst in items]
        with open(os.path.join(repo, sec, "index.html"), "w", encoding="utf-8") as f:
            f.write(P._landing_html(f"{sec} maps", rel, description=f"{sec} desc"))

    links, descs = P._harvest_existing(repo)

    assert ("Nuclear power sites (world)", "world/nuclear") in links
    assert ("Volcanoes (world)", "world/volcanoes") in links
    assert ("Metrics", "census/metrics") in links
    assert descs[""] == "Root intro."
    assert descs["world"] == "world desc"
    assert descs["census"] == "census desc"


def test_harvest_empty_repo(tmp_path):
    from census_us.tools._lib import publish as P
    links, descs = P._harvest_existing(str(tmp_path))
    assert links == []
    assert descs == {}


def test_merge_keeps_existing_and_overrides_collision(tmp_path):
    """Simulate the merge step: a new publish of one dest must keep the others and
    replace only its own dest's label."""
    from census_us.tools._lib import publish as P

    sections = {"world": [("Old Nuclear", "world/nuclear"), ("Volcanoes", "world/volcanoes")]}
    repo = str(tmp_path)
    with open(os.path.join(repo, "index.html"), "w", encoding="utf-8") as f:
        f.write(P._grouped_landing_html("Maps", sections))
    existing_links, _ = P._harvest_existing(repo)

    # this call republishes world/nuclear + adds world/renewable-siting
    links = [("Nuclear power sites (world)", "world/nuclear"),
             ("Renewable-energy siting (world)", "world/renewable-siting")]
    published = {d for _, d in links}
    for lbl, dst in existing_links:
        if dst not in published:
            links.append((lbl, dst))

    dests = {d for _, d in links}
    assert dests == {"world/nuclear", "world/volcanoes", "world/renewable-siting"}
    # collision: the new label wins, the old "Old Nuclear" is gone
    assert ("Nuclear power sites (world)", "world/nuclear") in links
    assert ("Old Nuclear", "world/nuclear") not in links
    # untouched bundle preserved
    assert ("Volcanoes", "world/volcanoes") in links
