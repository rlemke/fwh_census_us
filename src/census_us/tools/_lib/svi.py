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

from census_us.tools._lib import metrics
from census_us.tools._lib import storage as cstore

NAMESPACE = "census"
CACHE_TYPE = "svi"

# The SVI indicator set is the registry's in_svi metrics (all oriented so
# higher value → more vulnerable). (key, label) pairs, in registry order.
INDICATORS = [(m.key, m.label) for m in metrics.SVI_METRICS]

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
    """Compute the SVI indicator values for one county, via the metric registry
    (all in_svi metrics, keyed by metric key — e.g. poverty, less_than_hs, gini)."""
    return {m.key: metrics.compute_metric(props, m) for m in metrics.SVI_METRICS}


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

    # 6) tiny summary sidecar — lets build_national_index assemble the national
    #    page from KB-sized files instead of re-downloading every 1+ MB geojson.
    top = max(
        (ft for ft in features if isinstance(ft["properties"].get("svi"), (int, float))),
        key=lambda x: x["properties"]["svi"],
        default=None,
    )
    povs = sorted(
        ft["properties"]["poverty_pct"]
        for ft in features
        if isinstance(ft["properties"].get("poverty_pct"), (int, float))
    )
    summary = {
        "region": region_key,
        "county_count": len(features),
        "scored_count": scored,
        "mean_svi": mean_svi,
        "top_county": (top["properties"].get("NAME", "") if top else "").replace(" County", ""),
        "top_pct": top["properties"].get("svi_percentile") if top else None,
        "median_poverty": (povs[len(povs) // 2] if povs else None),
    }
    with cstore.open_write(cstore.join(out_dir, "svi-summary.json"), "w") as f:
        f.write(json.dumps(summary))

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


US_STATE_NAMES = [
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado",
    "Connecticut", "Delaware", "District of Columbia", "Florida", "Georgia",
    "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky",
    "Louisiana", "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota",
    "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada", "New Hampshire",
    "New Jersey", "New Mexico", "New York", "North Carolina", "North Dakota",
    "Ohio", "Oklahoma", "Oregon", "Pennsylvania", "Rhode Island",
    "South Carolina", "South Dakota", "Tennessee", "Texas", "Utah", "Vermont",
    "Virginia", "Washington", "West Virginia", "Wisconsin", "Wyoming",
]


def _state_summary(svi_root: str, name: str) -> dict[str, Any] | None:
    """Return a state's SVI summary — from the tiny svi-summary.json sidecar if
    present (fast), else computed from the full svi.geojson and backfilled."""
    sum_path = cstore.join(svi_root, name, "svi-summary.json")
    if cstore.exists(sum_path):
        try:
            with cstore.open_read(sum_path) as f:
                return json.load(f)
        except Exception:
            pass
    gj_path = cstore.join(svi_root, name, "svi.geojson")
    if not cstore.exists(gj_path):
        return None
    try:
        with cstore.open_read(gj_path) as f:
            fc = json.load(f)
    except Exception:
        return None
    feats = fc.get("features") or []
    scored = [ft for ft in feats if isinstance(ft["properties"].get("svi"), (int, float))]
    top = max(scored, key=lambda x: x["properties"]["svi"], default=None)
    povs = sorted(
        ft["properties"]["poverty_pct"]
        for ft in feats
        if isinstance(ft["properties"].get("poverty_pct"), (int, float))
    )
    summary = {
        "region": name,
        "county_count": len(feats),
        "scored_count": len(scored),
        "top_county": (top["properties"].get("NAME", "") if top else "").replace(" County", ""),
        "top_pct": top["properties"].get("svi_percentile") if top else None,
        "median_poverty": (povs[len(povs) // 2] if povs else None),
    }
    try:  # backfill the sidecar so the next index build is fast
        with cstore.open_write(sum_path, "w") as f:
            f.write(json.dumps(summary))
    except Exception:
        pass
    return summary


def build_national_index(
    regions: list[str] | None = None,
    *,
    title: str = "United States - Social Vulnerability Index",
    storage=None,
) -> tuple[str, int]:
    """Build a national index page linking every per-state SVI map.

    Reads each state's ``svi-summary.json`` sidecar (KB; written by BuildSVIMap)
    — falling back to the full ``svi.geojson`` + backfilling the sidecar when
    absent — and writes ``output/svi/index.html``: a sortable table linking each
    state's choropleth (``./<state>/index.html``).

    Per-state columns: county count, the most-vulnerable county (by within-state
    SVI), and the **median county poverty rate** — a nationally-comparable raw
    rate (the SVI percentile itself is ranked WITHIN each state, so it isn't
    comparable across states; poverty % is).
    """
    svi_root = cstore.join(cstore.output_root(), "svi")
    names = regions if regions is not None else US_STATE_NAMES

    rows: list[dict[str, Any]] = []
    for name in names:
        s = _state_summary(svi_root, name)
        if s is None:
            continue
        rows.append(
            {
                "name": name,
                "counties": s.get("county_count", 0),
                "top_county": s.get("top_county", ""),
                "top_pct": s.get("top_pct"),
                "median_poverty": s.get("median_poverty"),
            }
        )

    html = _render_index_html(rows, title=title)
    index_path = cstore.join(svi_root, "index.html")
    with cstore.open_write(index_path, "w") as f:
        f.write(html)
    return index_path, len(rows)


def _render_index_html(rows: list[dict[str, Any]], *, title: str) -> str:
    # nationally-comparable poverty scale (light → dark) for the mini bar
    def pov_color(p):
        if p is None:
            return _NODATA_COLOR
        for v, c in reversed(_RAMP):
            if p >= v * 35:  # ~0..35% poverty mapped onto the ramp
                return c
        return _RAMP[0][1]

    body_rows = ""
    for r in sorted(rows, key=lambda x: x["name"]):
        mp = r["median_poverty"]
        mp_txt = "—" if mp is None else f"{mp:.1f}%"
        tp = r["top_pct"]
        tp_txt = "—" if tp is None else str(tp)
        body_rows += (
            f"<tr>"
            f"<td><a href='./{r['name']}/index.html'>{r['name']}</a></td>"
            f"<td class='n'>{r['counties']}</td>"
            f"<td>{r['top_county']} <span class='mut'>({tp_txt})</span></td>"
            f"<td class='n' data-v='{mp if mp is not None else -1}'>"
            f"<span class='bar' style='background:{pov_color(mp)}'></span>{mp_txt}</td>"
            f"</tr>\n"
        )
    legend = "".join(
        f"<span style='background:{c}'>&nbsp;</span>" for _v, c in _RAMP
    )
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  body {{ font-family:system-ui,sans-serif; margin:0; background:#fafafa; color:#222; }}
  header {{ background:#800026; color:#fff; padding:18px 24px; }}
  header h1 {{ margin:0 0 4px; font-size:20px; }}
  header p {{ margin:0; font-size:13px; opacity:.92; max-width:760px; }}
  .wrap {{ padding:18px 24px; }}
  table {{ border-collapse:collapse; width:100%; max-width:820px; background:#fff;
           box-shadow:0 1px 3px rgba(0,0,0,.12); }}
  th,td {{ padding:7px 12px; border-bottom:1px solid #eee; font-size:13px; text-align:left; }}
  th {{ background:#f3f3f3; cursor:pointer; user-select:none; position:sticky; top:0; }}
  td.n {{ text-align:right; }}
  a {{ color:#0645ad; text-decoration:none; }} a:hover {{ text-decoration:underline; }}
  .mut {{ color:#999; }}
  .bar {{ display:inline-block; width:12px; height:12px; border-radius:2px; margin-right:6px;
          vertical-align:-1px; }}
  .lg {{ font-size:11px; color:#666; margin-top:10px; }}
  .lg span {{ display:inline-block; width:18px; height:11px; }}
</style></head>
<body>
<header>
  <h1>{title}</h1>
  <p>Social Vulnerability Index choropleths for all 50 states + DC, by county.
  Click a state to open its map. Each county's SVI is the mean of six
  percentile-ranked indicators (poverty, unemployment, education, age 65+,
  no-vehicle, renter) — ranked <b>within that state</b>, so SVI percentiles are
  not comparable across states. The <b>median poverty</b> column is a raw rate
  and <b>is</b> nationally comparable. Data: US Census Bureau ACS 2023 + TIGER.</p>
</header>
<div class="wrap">
<table id="t">
  <thead><tr>
    <th onclick="sortBy(0,'s')">State &#x25B4;&#x25BE;</th>
    <th onclick="sortBy(1,'n')">Counties</th>
    <th onclick="sortBy(2,'s')">Most-vulnerable county (SVI pctile)</th>
    <th onclick="sortBy(3,'v')">Median county poverty</th>
  </tr></thead>
  <tbody>
{body_rows}  </tbody>
</table>
<div class="lg">poverty scale (low&nbsp;{legend}&nbsp;high) &middot; {len(rows)} maps</div>
</div>
<script>
function sortBy(col, kind) {{
  const tb=document.querySelector('#t tbody');
  const rows=[...tb.rows];
  const dir = tb.dataset.col==String(col) && tb.dataset.dir=='1' ? -1 : 1;
  rows.sort((a,b)=>{{
    let x,y;
    if(kind=='n'){{ x=+a.cells[col].textContent; y=+b.cells[col].textContent; }}
    else if(kind=='v'){{ x=+a.cells[col].dataset.v; y=+b.cells[col].dataset.v; }}
    else {{ x=a.cells[col].textContent.trim(); y=b.cells[col].textContent.trim();
            return dir*x.localeCompare(y); }}
    return dir*(x-y);
  }});
  rows.forEach(r=>tb.appendChild(r));
  tb.dataset.col=col; tb.dataset.dir=dir==1?'1':'0';
}}
</script>
</body></html>"""


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
