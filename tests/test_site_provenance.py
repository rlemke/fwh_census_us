"""Offline tests for the publisher's FFL-link stamping (site_provenance)."""

from __future__ import annotations

import os

from census_us.tools._lib import publish as P
from census_us.tools._lib import site_provenance as SP

REG = {
    "low-zoom-roads": ("osm.lz.BuildLowZoom", "https://github.com/o/r/blob/main/a.ffl"),
    "world/gibraltar-tunnels": ("gib.workflows.Map", "https://github.com/o/g/blob/main/g.ffl"),
    "amr": ("amr.workflows.Map", "https://github.com/o/amr/blob/main/amr.ffl"),
}
PAGE = "<html><head><title>x</title></head><body><div id=map></div></body></html>"


def _write(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def _read(root, rel):
    with open(os.path.join(root, rel), encoding="utf-8") as f:
        return f.read()


def test_lookup_takes_the_longest_whole_segment_prefix():
    assert SP.lookup("low-zoom-roads/alaska", REG)[0] == "osm.lz.BuildLowZoom"
    assert SP.lookup("world/gibraltar-tunnels", REG)[0] == "gib.workflows.Map"
    assert SP.lookup("world/gibraltar", REG) is None          # not a segment match
    assert SP.lookup("world", REG) is None


def test_inject_adds_one_footer_before_body_and_is_idempotent():
    out = SP.inject(PAGE, "a.B", "https://github.com/o/r/blob/main/x.ffl")
    assert out.count("view FFL") == 1
    assert out.index("view FFL") < out.index("</body>")
    assert 'href="https://github.com/o/r"' in out               # source repo link
    assert SP.inject(out, "a.B", "https://github.com/o/r/blob/main/x.ffl") is None
    # No </body> (legal HTML): before </html>, else appended.
    assert SP.inject("<html>x</html>", "a.B", "u").endswith("</div>\n</html>")
    assert SP.inject("<div>x</div>", "a.B", "u").rstrip().endswith("</div>")
    assert "view FFL" in SP.inject("<div>x</div>", "a.B", "u")


def test_stamp_tree_stamps_registered_pages_and_reports_the_rest(tmp_path):
    root = str(tmp_path)
    _write(root, "low-zoom-roads/alaska/index.html", PAGE)
    _write(root, "world/gibraltar-tunnels/index.html", PAGE)
    _write(root, "world/mystery/index.html", PAGE)
    _write(root, "world/has-one/index.html", PAGE.replace("</body>", "view FFL</body>"))
    _write(root, "amr/index.html", PAGE)                         # a MAP at depth 1

    stamped, unknown = SP.stamp_tree(root, REG)

    assert sorted(stamped) == ["amr/index.html", "low-zoom-roads/alaska/index.html",
                               "world/gibraltar-tunnels/index.html"]
    assert unknown == ["world/mystery/index.html"]
    assert "gib.workflows.Map" in _read(root, "world/gibraltar-tunnels/index.html")
    assert _read(root, "world/mystery/index.html") == PAGE       # never guessed
    assert SP.stamp_tree(root, REG) == ([], ["world/mystery/index.html"])


def test_gallery_indexes_written_by_the_publisher_are_never_stamped(tmp_path):
    root = str(tmp_path)
    sections = {"low-zoom-roads": [("Alaska", "low-zoom-roads/alaska")]}
    _write(root, "index.html", P._grouped_landing_html("Facetwork maps", sections))
    _write(root, "low-zoom-roads/index.html",
           P._landing_html("Low Zoom Roads maps", [("Alaska", "alaska")]))

    assert SP.stamp_tree(root, REG) == ([], [])
    assert "view FFL" not in _read(root, "low-zoom-roads/index.html")


def test_every_registry_entry_is_well_formed():
    for key, (wf, url) in SP.REGISTRY.items():
        assert key == key.strip("/") and key, key
        assert "." in wf, (key, wf)
        assert url.startswith("https://github.com/") and "/blob/" in url and url.endswith(".ffl"), url


def test_redirect_stubs_at_a_moved_pages_old_path_are_not_maps(tmp_path):
    root = str(tmp_path)
    stub = ('<!doctype html><meta charset="utf-8">'
            '<meta http-equiv="refresh" content="0; url=../health/amr/index.html">'
            '<a href="../health/amr/index.html">Moved</a>')
    _write(root, "old/index.html", stub)

    assert SP.stamp_tree(root, REG) == ([], [])
    assert _read(root, "old/index.html") == stub
