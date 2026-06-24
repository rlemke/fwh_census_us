"""Social Vulnerability Index (SVI) — compute + choropleth map.

Given the county-level GeoJSON produced by ``census.Summary.JoinGeo`` (TIGER
county geometry enriched with ACS attributes), compute a CDC/ATSDR-style Social
Vulnerability Index per county and render a MapLibre choropleth.

Methodology (a 6-indicator SES/demographic variant of the CDC SVI):

  1. poverty_pct      — % of people below the poverty line   (B17001)
  2. unemployment_pct — civilian unemployed / civilian labor force (B23025)
  3. no_bachelors_pct — % of adults WITHOUT a bachelor's degree (100 - B15003 bach+)
  4. elderly_pct      — % of people aged 65+                   (B01001)
  5. no_vehicle_pct   — % of households with no vehicle         (B25044)
  6. renter_pct       — % renter-occupied housing units         (B25003)

Each indicator is "higher = more vulnerable". Per the CDC method, counties are
**percentile-ranked** on each indicator across the dataset (the counties in this
run — i.e. within-state ranks for a single state), ties get the average rank, and
the overall SVI is the **mean of the available indicator percentiles** in [0, 1]
(1 = most vulnerable). Counties missing an indicator use the remaining ones;
counties missing everything render grey.

The CDC SVI's 4th theme (racial/ethnic minority status) is intentionally omitted
here; race data is available in the join if a future variant wants the full
4-theme index.

Storage-aware: reads the joined GeoJSON and writes the SVI GeoJSON + HTML through
the census ``_lib.storage`` wrapper, so on the fleet everything lands in MinIO.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from census_us.tools._lib import storage as cstore

NAMESPACE = "census"
CACHE_TYPE = "svi"

# Indicator keys in vulnerability order (all: higher value → more vulnerable).
INDICATORS = [
    ("poverty_pct", "Below poverty"),
    ("unemployment_pct", "Unemployment"),
    ("no_bachelors_pct", "No bachelor's degree"),
    ("elderly_pct", "Aged 65+"),
    ("no_vehicle_pct", "No vehicle"),
    ("renter_pct", "Renter-occupied"),
]

# YlOrRd sequential ramp for the choropleth (low → high vulnerability).
_RAMP = [
    (0.0, "#ffffcc"),
    (0.2, "#ffeda0"),
    (0.4, "#fed976"),
    (0.6, "#fd8d3c"),
    (0.8, "#e31a1c"),
    (1.0, "#800026"),
]
_NODATA_COLOR = "#cccccc"


@dataclass
class SVIResult:
    output_path: str  # SVI GeoJSON (geometry + svi + components)
    html_path: str  # MapLibre choropleth
    county_count: int
    scored_count: int  # counties with a computable SVI
    mean_svi: float  # mean SVI across scored counties (0-1)


# ---------------------------------------------------------------------------
# Indicator extraction.
# ---------------------------------------------------------------------------


def _num(props: dict[str, Any], key: str) -> float | None:
    v = props.get(key)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _rate(num: float | None, den: float | None, scale: float = 100.0) -> float | None:
    if num is None or den is None or den == 0:
        return None
    return round(num / den * scale, 2)


def _indicators(props: dict[str, Any]) -> dict[str, float | None]:
    """Compute the 6 raw indicator percentages for one county."""
    out: dict[str, float | None] = {}

    out["poverty_pct"] = props.get("pct_below_poverty")
    if out["poverty_pct"] is None:
        out["poverty_pct"] = _rate(_num(props, "B17001_002E"), _num(props, "B17001_001E"))

    # unemployed (B23025_005E) / civilian labor force (B23025_003E)
    out["unemployment_pct"] = _rate(_num(props, "B23025_005E"), _num(props, "B23025_003E"))

    bach = props.get("pct_bachelors_plus")
    out["no_bachelors_pct"] = round(100.0 - bach, 2) if isinstance(bach, (int, float)) else None

    # 65+ = male bands B01001_020E..025E + female B01001_044E..049E over total _001E
    male65 = [_num(props, f"B01001_{i:03d}E") for i in range(20, 26)]
    fem65 = [_num(props, f"B01001_{i:03d}E") for i in range(44, 50)]
    elders = sum(v for v in male65 + fem65 if v is not None)
    out["elderly_pct"] = _rate(elders, _num(props, "B01001_001E"))

    # no-vehicle households: owner-0 (B25044_003E) + renter-0 (B25044_010E) over total (_001E)
    no_veh = (_num(props, "B25044_003E") or 0.0) + (_num(props, "B25044_010E") or 0.0)
    out["no_vehicle_pct"] = _rate(no_veh, _num(props, "B25044_001E"))

    out["renter_pct"] = props.get("pct_renter_occupied")
    if out["renter_pct"] is None:
        out["renter_pct"] = _rate(_num(props, "B25003_003E"), _num(props, "B25003_001E"))

    return out


def _percentile_ranks(values: list[float | None]) -> list[float | None]:
    """Average-rank percentile in [0,1] (1 = highest value). None passes through."""
    present = [(i, v) for i, v in enumerate(values) if v is not None]
    out: list[float | None] = [None] * len(values)
    if len(present) < 2:
        for i, _ in present:
            out[i] = 0.5  # single county: neutral
        return out
    present.sort(key=lambda t: t[1])
    n = len(present)
    i = 0
    while i < n:
        j = i
        while j + 1 < n and present[j + 1][1] == present[i][1]:
            j += 1
        pct = ((i + j) / 2.0) / (n - 1)
        for k in range(i, j + 1):
            out[present[k][0]] = round(pct, 4)
        i = j + 1
    return out


# ---------------------------------------------------------------------------
# Public API.
# ---------------------------------------------------------------------------


def build_svi_map(
    joined_path: str,
    *,
    region: str = "state",
    title: str = "Social Vulnerability Index",
    storage=None,
) -> SVIResult:
    """Compute the SVI from a joined county GeoJSON and render a choropleth."""
    s = storage or cstore  # cstore exposes open_read/open_write/join/output_root

    with cstore.open_read(joined_path) as f:
        fc = json.load(f)
    features = fc.get("features") or []

    # 1) raw indicators per county
    comps = [_indicators(feat.get("properties") or {}) for feat in features]

    # 2) percentile-rank each indicator across all counties
    ranks: dict[str, list[float | None]] = {}
    for key, _label in INDICATORS:
        ranks[key] = _percentile_ranks([c[key] for c in comps])

    # 3) SVI = mean of available indicator percentiles
    scored = 0
    svi_sum = 0.0
    for idx, feat in enumerate(features):
        props = feat.setdefault("properties", {})
        rs = [ranks[key][idx] for key, _ in INDICATORS if ranks[key][idx] is not None]
        # carry the raw component values + their percentile ranks for the popup
        for key, _ in INDICATORS:
            props[key] = comps[idx][key]
            props[f"{key}_rank"] = ranks[key][idx]
        if rs:
            svi = round(sum(rs) / len(rs), 4)
            props["svi"] = svi
            props["svi_percentile"] = round(svi * 100)
            scored += 1
            svi_sum += svi
        else:
            props["svi"] = None
            props["svi_percentile"] = None

    mean_svi = round(svi_sum / scored, 4) if scored else 0.0

    # 4) persist the SVI GeoJSON
    region_key = region or "state"
    out_dir = cstore.join(cstore.output_root(), "svi", region_key)
    svi_path = cstore.join(out_dir, "svi.geojson")
    body = json.dumps(fc, separators=(",", ":"))
    with cstore.open_write(svi_path, "w") as f:
        f.write(body)

    # 5) render the choropleth
    html = _render_html(fc, title=title, region=region_key)
    html_path = cstore.join(out_dir, "index.html")
    with cstore.open_write(html_path, "w") as f:
        f.write(html)

    return SVIResult(
        output_path=svi_path,
        html_path=html_path,
        county_count=len(features),
        scored_count=scored,
        mean_svi=mean_svi,
    )


# ---------------------------------------------------------------------------
# Choropleth HTML.
# ---------------------------------------------------------------------------


def _bbox(fc: dict[str, Any]) -> list[float]:
    minx = miny = float("inf")
    maxx = maxy = float("-inf")

    def walk(coords):
        nonlocal minx, miny, maxx, maxy
        if not coords:
            return
        if isinstance(coords[0], (int, float)):
            x, y = coords[0], coords[1]
            minx, miny, maxx, maxy = min(minx, x), min(miny, y), max(maxx, x), max(maxy, y)
        else:
            for c in coords:
                walk(c)

    for feat in fc.get("features") or []:
        geom = feat.get("geometry") or {}
        walk(geom.get("coordinates"))
    if minx == float("inf"):
        return [-125.0, 24.0, -66.0, 50.0]  # CONUS fallback
    return [minx, miny, maxx, maxy]


def _render_html(fc: dict[str, Any], *, title: str, region: str) -> str:
    bbox = _bbox(fc)
    data_js = json.dumps(fc, separators=(",", ":"))
    # MapLibre data-driven fill: grey for no-data (svi < 0 sentinel), else YlOrRd ramp.
    ramp_stops = ", ".join(f"{v}, '{c}'" for v, c in _RAMP)
    legend_rows = "".join(
        f"<div><span style=\"background:{c}\"></span>{int(v * 100)}</div>" for v, c in _RAMP
    )
    indicator_js = json.dumps([[k, lbl] for k, lbl in INDICATORS])
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{title} — {region}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css" rel="stylesheet">
<script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
<style>
  html,body,#map {{ margin:0; height:100%; width:100%; font-family:system-ui,sans-serif; }}
  .panel {{ position:absolute; z-index:1; background:rgba(255,255,255,.92); padding:10px 12px;
            border-radius:6px; box-shadow:0 1px 4px rgba(0,0,0,.3); font-size:12px; }}
  #title {{ top:10px; left:10px; max-width:320px; }}
  #title h3 {{ margin:0 0 2px; font-size:14px; }}
  #legend {{ bottom:18px; left:10px; }}
  #legend .scale {{ display:flex; align-items:center; gap:0; margin-top:4px; }}
  #legend .scale div {{ display:flex; flex-direction:column; align-items:center; font-size:10px; }}
  #legend .scale span {{ width:26px; height:12px; display:block; }}
  .maplibregl-popup-content {{ max-width:300px; font-size:12px; }}
  .maplibregl-popup-content h4 {{ margin:0 0 4px; font-size:13px; }}
  table.svi {{ border-collapse:collapse; margin-top:4px; }}
  table.svi td {{ padding:1px 6px 1px 0; }} table.svi td.v {{ text-align:right; }}
</style></head>
<body>
<div id="map"></div>
<div id="title" class="panel">
  <h3>{title}</h3>
  <div>{region} &middot; counties shaded by SVI percentile (0 = least, 100 = most vulnerable,
  ranked within this view). Click a county for the breakdown.</div>
</div>
<div id="legend" class="panel"><b>SVI percentile</b><div class="scale">{legend_rows}</div></div>
<script>
const DATA = {data_js};
const INDICATORS = {indicator_js};
const map = new maplibregl.Map({{
  container:'map',
  style:{{ version:8,
    sources:{{ basemap:{{ type:'raster', tiles:[
      'https://a.basemaps.cartocdn.com/rastertiles/voyager/{{z}}/{{x}}/{{y}}.png',
      'https://b.basemaps.cartocdn.com/rastertiles/voyager/{{z}}/{{x}}/{{y}}.png'],
      tileSize:256, attribution:'&copy; OpenStreetMap &copy; CARTO &middot; Data: US Census Bureau (ACS/TIGER)' }} }},
    layers:[{{ id:'basemap', type:'raster', source:'basemap' }}] }}
}});
map.addControl(new maplibregl.NavigationControl());
map.on('load', () => {{
  map.addSource('counties', {{ type:'geojson', data:DATA }});
  map.addLayer({{ id:'svi-fill', type:'fill', source:'counties',
    paint:{{
      'fill-color':[ 'case', ['==',['get','svi'],null], '{_NODATA_COLOR}',
        ['interpolate',['linear'],['get','svi'], {ramp_stops} ] ],
      'fill-opacity':0.78 }} }});
  map.addLayer({{ id:'svi-line', type:'line', source:'counties',
    paint:{{ 'line-color':'#555', 'line-width':0.4 }} }});
  map.fitBounds([[{bbox[0]},{bbox[1]}],[{bbox[2]},{bbox[3]}]], {{ padding:30, duration:0 }});

  map.on('click','svi-fill',(e)=>{{
    const p = e.features[0].properties || {{}};
    const pct = (p.svi_percentile===undefined||p.svi_percentile===null||p.svi_percentile==='')
      ? 'n/a' : p.svi_percentile;
    let rows='';
    for (const [k,lbl] of INDICATORS) {{
      const val = p[k]; const rk = p[k+'_rank'];
      const v = (val===undefined||val===null||val==='') ? '—' : (Math.round(val*10)/10)+'%';
      const r = (rk===undefined||rk===null||rk==='') ? '' : ' ('+Math.round(rk*100)+'th)';
      rows += `<tr><td>${{lbl}}</td><td class="v">${{v}}${{r}}</td></tr>`;
    }}
    new maplibregl.Popup({{ closeButton:true, maxWidth:'320px' }})
      .setLngLat(e.lngLat)
      .setHTML(`<h4>${{p.NAME||'County'}}</h4>`+
        `<div><b>SVI percentile: ${{pct}}</b></div>`+
        `<table class="svi">${{rows}}</table>`)
      .addTo(map);
  }});
  map.on('mouseenter','svi-fill',()=>map.getCanvas().style.cursor='pointer');
  map.on('mouseleave','svi-fill',()=>map.getCanvas().style.cursor='');
}});
</script></body></html>"""
