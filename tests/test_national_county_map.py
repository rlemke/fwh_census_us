"""Tests for the national county choropleth (BuildNationalCountyMap) and the
national ("us") ACS county pull mode."""

from __future__ import annotations

import csv
import json
import os
import zipfile
from unittest.mock import patch

import pytest
import shapefile

from census_us.handlers.vulnerability import svi_handlers
from census_us.tools._lib import downloader
from census_us.tools._lib.maps import build_national_county_map


@pytest.fixture
def out_env(tmp_path, monkeypatch):
    monkeypatch.setenv("FW_CENSUS_OUTPUT_DIR", str(tmp_path / "output"))
    monkeypatch.setenv("FW_CENSUS_CACHE_DIR", str(tmp_path / "cache"))
    return tmp_path


def _write_county_zip(path, counties):
    """Write a minimal TIGER-like county shapefile ZIP: counties is a list of
    (statefp, countyfp, name, lon, lat) — each a 1-degree square."""
    base = path.with_suffix("")
    w = shapefile.Writer(str(base))
    w.field("STATEFP", "C", size=2)
    w.field("COUNTYFP", "C", size=3)
    w.field("GEOID", "C", size=5)
    w.field("NAME", "C", size=100)
    w.field("NAMELSAD", "C", size=100)
    for st, cty, name, lon, lat in counties:
        w.record(st, cty, f"{st}{cty}", name, f"{name} County")
        w.poly([[(lon, lat), (lon + 1, lat), (lon + 1, lat + 1), (lon, lat + 1), (lon, lat)]])
    w.close()
    with zipfile.ZipFile(path, "w") as zf:
        for ext in ("shp", "shx", "dbf"):
            zf.write(f"{base}.{ext}", f"{base.name}.{ext}")
    return path


def _write_acs_csv(path, rows, extra_cols=()):
    with open(path, "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["GEOID", "NAME", "B19013_001E", *extra_cols])
        wr.writerows(rows)
    return path


class TestNationalACSPull:
    def test_us_county_for_clause(self, out_env):
        """state_fips='us' + geo='county' must request every county nationally
        (for=county:* with no in=state clause)."""
        captured = {}

        def fake_api(url, dest, state_fips, geo="county"):
            captured["url"] = url
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "w") as f:
                f.write("GEOID,NAME,B19013_001E\n")
            return 1

        with patch.object(downloader, "_download_acs_api", side_effect=fake_api):
            res = downloader.download_acs(state_fips="us", columns="B19013_001E", tag="t")
        assert "for=county:*" in captured["url"]
        assert "in=state" not in captured["url"]
        assert res["wasInCache"] is False

    def test_state_county_for_clause_unchanged(self, out_env):
        captured = {}

        def fake_api(url, dest, state_fips, geo="county"):
            captured["url"] = url
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "w") as f:
                f.write("GEOID,NAME,B19013_001E\n")
            return 1

        with patch.object(downloader, "_download_acs_api", side_effect=fake_api):
            downloader.download_acs(state_fips="56", columns="B19013_001E", tag="t2")
        assert "for=county:*&in=state:56" in captured["url"]


class TestBuildNationalCountyMap:
    def _build(self, tmp_path, metric="median_income", detail=False):
        acs = _write_acs_csv(
            tmp_path / "acs_us.csv",
            [
                ["0500000US01001", "Autauga County, Alabama", "58000"],
                ["0500000US06001", "Alameda County, California", "112000"],
                ["0500000US48001", "Anderson County, Texas", "-666666666"],  # suppressed
            ],
        )
        detail_path = None
        if detail:
            # B01001: total pop + one 65+ band (male 65-66) per county
            dp = tmp_path / "acs_us_detail.csv"
            with open(dp, "w", newline="") as f:
                wr = csv.writer(f)
                wr.writerow(["GEOID", "NAME", "B01001_001E", "B01001_020E"])
                wr.writerows([
                    ["0500000US01001", "Autauga County, Alabama", "1000", "100"],
                    ["0500000US06001", "Alameda County, California", "1000", "300"],
                ])
            detail_path = str(dp)
        tiger = _write_county_zip(
            tmp_path / "us_county.zip",
            [
                ("01", "001", "Autauga", -86.6, 32.5),
                ("06", "001", "Alameda", -122.3, 37.7),
                ("48", "001", "Anderson", -95.7, 31.8),
                ("66", "010", "Guam", 144.7, 13.4),  # no ACS row at all
            ],
        )
        return build_national_county_map(
            str(acs), str(tiger), detail_path=detail_path, metric=metric
        )

    def test_counts_and_outputs(self, out_env, tmp_path):
        res = self._build(tmp_path)
        assert res.county_count == 4
        assert res.valued_count == 2  # suppressed + territory have no value
        with open(res.output_path) as f:
            fc = json.load(f)
        by_geoid = {ft["properties"]["GEOID"]: ft["properties"] for ft in fc["features"]}
        assert by_geoid["01001"]["val"] == 58000
        assert by_geoid["48001"]["val"] is None
        assert by_geoid["66010"]["val"] is None
        # ACS NAME (fuller "County, State") wins over the TIGER name
        assert by_geoid["06001"]["NAME"] == "Alameda County, California"
        assert by_geoid["66010"]["NAME"] == "Guam County"

    def test_rank_direction_income(self, out_env, tmp_path):
        """median_income is worse=low → rank 1 = highest income."""
        res = self._build(tmp_path)
        with open(res.output_path) as f:
            fc = json.load(f)
        by_geoid = {ft["properties"]["GEOID"]: ft["properties"] for ft in fc["features"]}
        assert by_geoid["06001"]["rank"] == 1
        assert by_geoid["01001"]["rank"] == 2
        assert "rank" not in by_geoid["48001"]

    def test_html_rendered(self, out_env, tmp_path):
        res = self._build(tmp_path)
        with open(res.html_path) as f:
            html = f.read()
        assert "maplibre" in html
        assert "Median household income" in html
        assert res.html_path.endswith("index.html")

    def test_unknown_metric_raises(self, out_env, tmp_path):
        with pytest.raises(ValueError, match="Unknown metric"):
            self._build(tmp_path, metric="nope")

    def test_median_age_years_metric(self, out_env, tmp_path):
        """median_age (B01002, default batch) renders with the years format."""
        acs = _write_acs_csv(
            tmp_path / "acs_ma.csv",
            [
                ["0500000US01001", "Autauga County, Alabama", "58000", "38.6"],
                ["0500000US06001", "Alameda County, California", "112000", "-666666666"],
            ],
            extra_cols=("B01002_001E",),
        )
        tiger = _write_county_zip(
            tmp_path / "ma_county.zip",
            [("01", "001", "Autauga", -86.6, 32.5), ("06", "001", "Alameda", -122.3, 37.7)],
        )
        res = build_national_county_map(str(acs), str(tiger), metric="median_age")
        assert res.valued_count == 1
        with open(res.html_path) as f:
            html = f.read()
        assert " yrs'" in html  # years formatter baked in
        with open(res.output_path) as f:
            fc = json.load(f)
        by_geoid = {ft["properties"]["GEOID"]: ft["properties"] for ft in fc["features"]}
        assert by_geoid["01001"]["val"] == 38.6
        assert by_geoid["06001"]["val"] is None  # sentinel

    def test_detail_merge_age_metric(self, out_env, tmp_path):
        """elderly computes from the merged detailed batch (B01001)."""
        res = self._build(tmp_path, metric="elderly", detail=True)
        assert res.valued_count == 2
        with open(res.output_path) as f:
            fc = json.load(f)
        by_geoid = {ft["properties"]["GEOID"]: ft["properties"] for ft in fc["features"]}
        assert by_geoid["01001"]["val"] == 10.0  # 100/1000
        assert by_geoid["06001"]["val"] == 30.0
        # elderly is worse=high → rank 1 = lowest share
        assert by_geoid["01001"]["rank"] == 1

    def test_rank_side_lists_in_html(self, out_env, tmp_path):
        res = self._build(tmp_path)
        with open(res.html_path) as f:
            html = f.read()
        assert "Highest 20" in html and "Lowest 20" in html
        # RANKS payload: highest-first top list led by Alameda
        import re
        ranks = json.loads(re.search(r"RANKS=(\{.*?\});", html).group(1))
        assert ranks["top"][0]["n"] == "Alameda County, California"
        assert ranks["bottom"][0]["n"] == "Autauga County, Alabama"
        assert len(ranks["top"][0]["c"]) == 2  # centroid for flyTo


class TestHandlerDispatch:
    def test_dispatch_key_present(self):
        assert (
            "census.Vulnerability.BuildNationalCountyMap" in svi_handlers._DISPATCH
        )

    def test_handler_requires_files(self):
        with pytest.raises(ValueError, match="requires acs_file and tiger_file"):
            svi_handlers.handle_build_national_county_map({})
