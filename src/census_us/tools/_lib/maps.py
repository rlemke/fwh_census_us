"""Multi-metric county choropleth + national state rankings/choropleths.

Built on the metric registry (``_lib.metrics``):

- ``build_metrics_map(joined_path, region)`` — one per-state county choropleth
  with a dropdown over all 13 metrics + the SVI; "dark = worse" regardless of a
  metric's direction (high income/grad-degree shade light). Also writes a
  ``metrics-summary.json`` with the state-level value for each metric (for the
  national rankings).
- ``build_national_rankings()`` — reads every state's ``metrics-summary.json``,
  fills median-income + Gini from a ``for=state:*`` pull (they can't be
  aggregated from counties), and writes a sortable rankings table + a national
  state choropleth per metric (US states shaded, dropdown).

Storage-aware via ``_lib.storage`` → MinIO on the fleet.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from census_us.tools._lib import downloader
from census_us.tools._lib import metrics
from census_us.tools._lib import storage as cstore
from census_us.tools._lib import svi as svi_lib

# state name → 2-digit FIPS (the 50 states + DC)
STATE_FIPS = {
    "Alabama": "01", "Alaska": "02", "Arizona": "04", "Arkansas": "05",
    "California": "06", "Colorado": "08", "Connecticut": "09", "Delaware": "10",
    "District of Columbia": "11", "Florida": "12", "Georgia": "13", "Hawaii": "15",
    "Idaho": "16", "Illinois": "17", "Indiana": "18", "Iowa": "19", "Kansas": "20",
    "Kentucky": "21", "Louisiana": "22", "Maine": "23", "Maryland": "24",
    "Massachusetts": "25", "Michigan": "26", "Minnesota": "27", "Mississippi": "28",
    "Missouri": "29", "Montana": "30", "Nebraska": "31", "Nevada": "32",
    "New Hampshire": "33", "New Jersey": "34", "New Mexico": "35", "New York": "36",
    "North Carolina": "37", "North Dakota": "38", "Ohio": "39", "Oklahoma": "40",
    "Oregon": "41", "Pennsylvania": "42", "Rhode Island": "44", "South Carolina": "45",
    "South Dakota": "46", "Tennessee": "47", "Texas": "48", "Utah": "49",
    "Vermont": "50", "Virginia": "51", "Washington": "53", "West Virginia": "54",
    "Wisconsin": "55", "Wyoming": "56",
}
_FIPS_NAME = {v: k for k, v in STATE_FIPS.items()}

_RAMP = svi_lib._RAMP
_NODATA = svi_lib._NODATA_COLOR


@dataclass
class MetricsMapResult:
    output_path: str  # enriched county GeoJSON
    html_path: str  # multi-metric choropleth
    summary_path: str  # state-level metric summary
    county_count: int


@dataclass
class RankingsResult:
    html_path: str
    state_count: int
    metric_count: int


def _num(props: dict[str, Any], key: str) -> float | None:
    v = props.get(key)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _state_aggregate(features: list[dict]) -> dict[str, float | None]:
    """State-level value per metric: ratio metrics aggregate Σnum/Σden across
    counties; raw metrics (median income, Gini) can't be aggregated → None."""
    summed: dict[str, float] = {}
    for feat in features:
        for k, v in (feat.get("properties") or {}).items():
            if isinstance(k, str) and k.startswith("B"):
                fv = _num(feat["properties"], k)
                if fv is not None and fv > -1e8:
                    summed[k] = summed.get(k, 0.0) + fv
    out: dict[str, float | None] = {}
    for m in metrics.METRICS:
        out[m.key] = None if m.raw is not None else metrics.compute_metric(summed, m)
    return out


# ---------------------------------------------------------------------------
# Per-state multi-metric county choropleth.
# ---------------------------------------------------------------------------


def build_metrics_map(
    joined_path: str,
    *,
    region: str = "state",
    title: str = "Census metrics",
    storage=None,
) -> MetricsMapResult:
    with cstore.open_read(joined_path) as f:
        fc = json.load(f)
    features = fc.get("features") or []

    # per-county metric values + SVI (percentile-ranked within the state)
    svi_comps = [svi_lib._indicators(ft.get("properties") or {}) for ft in features]
    svi_ranks = {
        m.key: svi_lib._percentile_ranks([c[m.key] for c in svi_comps])
        for m in metrics.SVI_METRICS
    }
    for idx, feat in enumerate(features):
        props = feat.setdefault("properties", {})
        vals = metrics.compute_metrics(props)
        for k, v in vals.items():
            props[f"m_{k}"] = v
        rs = [svi_ranks[m.key][idx] for m in metrics.SVI_METRICS if svi_ranks[m.key][idx] is not None]
        props["m_svi"] = round(sum(rs) / len(rs), 4) if rs else None

    out_dir = cstore.join(cstore.output_root(), "metrics", region or "state")
    geo_path = cstore.join(out_dir, "metrics.geojson")
    with cstore.open_write(geo_path, "w") as f:
        f.write(json.dumps(fc, separators=(",", ":")))

    html = _render_metrics_html(fc, title=title, region=region or "state")
    html_path = cstore.join(out_dir, "index.html")
    with cstore.open_write(html_path, "w") as f:
        f.write(html)

    # state-level summary for the national rankings
    summary = {"region": region, "county_count": len(features), "values": _state_aggregate(features)}
    summary_path = cstore.join(out_dir, "metrics-summary.json")
    with cstore.open_write(summary_path, "w") as f:
        f.write(json.dumps(summary))

    return MetricsMapResult(geo_path, html_path, summary_path, len(features))


def _metric_js() -> str:
    """JS array describing each selectable layer (13 metrics + SVI)."""
    items = []
    for m in metrics.METRICS:
        items.append({"key": f"m_{m.key}", "label": m.label, "fmt": m.fmt, "worse": m.worse})
    items.append({"key": "m_svi", "label": "Social Vulnerability Index", "fmt": "svi", "worse": "high"})
    return json.dumps(items)


def _render_metrics_html(fc: dict, *, title: str, region: str) -> str:
    bbox = svi_lib._bbox(fc)
    data_js = json.dumps(fc, separators=(",", ":"))
    ramp_js = json.dumps(_RAMP)
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{title} - {region}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css" rel="stylesheet">
<script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
<style>
  html,body,#map{{margin:0;height:100%;width:100%;font-family:system-ui,sans-serif}}
  .panel{{position:absolute;z-index:1;background:rgba(255,255,255,.93);padding:10px 12px;
    border-radius:6px;box-shadow:0 1px 4px rgba(0,0,0,.3);font-size:12px}}
  #ctl{{top:10px;left:10px;max-width:340px}}
  #ctl h3{{margin:0 0 6px;font-size:14px}} #ctl select{{font-size:13px;padding:3px;width:100%}}
  #legend{{bottom:18px;left:10px}} #legend .scale{{display:flex;margin-top:4px}}
  #legend .scale div{{display:flex;flex-direction:column;align-items:center;font-size:10px}}
  #legend .scale span{{width:30px;height:12px}}
  .maplibregl-popup-content{{max-width:320px;font-size:12px}}
  .maplibregl-popup-content h4{{margin:0 0 4px;font-size:13px}}
  table.m{{border-collapse:collapse;margin-top:4px}} table.m td{{padding:1px 6px 1px 0}}
  table.m td.v{{text-align:right}} tr.sel td{{font-weight:700}}
</style></head>
<body>
<div id="map"></div>
<div id="ctl" class="panel">
  <h3>{title} &middot; {region}</h3>
  <select id="metric"></select>
  <div style="margin-top:5px;color:#555">Counties shaded <b>dark = worse</b>. Click a county for all
  metrics. SVI = percentile-ranked composite within this state. Data: US Census ACS 2023 + TIGER.</div>
</div>
<div id="legend" class="panel"><b id="lgttl"></b><div class="scale" id="lgscale"></div></div>
<script>
const DATA={data_js}, METRICS={_metric_js()}, RAMP={ramp_js};
const fmt=(v,f)=>{{ if(v===null||v===undefined||v==='') return '—';
  if(f==='dollar') return '$'+Math.round(v).toLocaleString();
  if(f==='index') return (Math.round(v*1000)/1000).toString();
  if(f==='svi') return Math.round(v*100)+' pctile';
  return (Math.round(v*10)/10)+'%'; }};
const vals=k=>DATA.features.map(f=>f.properties[k]).filter(v=>typeof v==='number');
function colorExpr(m){{
  const a=vals(m.key); if(!a.length) return '{_NODATA}';
  let lo=Math.min(...a), hi=Math.max(...a); if(lo===hi) hi=lo+1;
  // "dark = worse": build ascending value→color stops; for worse-low metrics
  // (income, grad) reverse the ramp so high values shade light.
  const expr=['interpolate',['linear'],['get',m.key]];
  const pairs=[];
  for(let i=0;i<RAMP.length;i++){{
    const v=lo+(hi-lo)*RAMP[i][0];
    const c = m.worse==='low' ? RAMP[RAMP.length-1-i][1] : RAMP[i][1];
    pairs.push([v,c]);
  }}
  pairs.sort((x,y)=>x[0]-y[0]);
  for(const [v,c] of pairs) expr.push(v,c);
  return ['case',['==',['get',m.key],null],'{_NODATA}',expr];
}}
function legend(m){{
  document.getElementById('lgttl').textContent=m.label;
  const a=vals(m.key); const sc=document.getElementById('lgscale'); sc.innerHTML='';
  if(!a.length){{return;}} let lo=Math.min(...a),hi=Math.max(...a);
  const order = m.worse==='low' ? [...RAMP].reverse() : RAMP;
  order.forEach(([t,c],i)=>{{ const d=document.createElement('div');
    const val = m.worse==='low' ? hi-(hi-lo)*t : lo+(hi-lo)*t;
    d.innerHTML=`<span style="background:${{c}}"></span>${{fmt(val,m.fmt)}}`; sc.appendChild(d); }});
}}
const map=new maplibregl.Map({{container:'map',style:{{version:8,
  sources:{{bm:{{type:'raster',tiles:['https://a.basemaps.cartocdn.com/rastertiles/voyager/{{z}}/{{x}}/{{y}}.png','https://b.basemaps.cartocdn.com/rastertiles/voyager/{{z}}/{{x}}/{{y}}.png'],tileSize:256,attribution:'&copy; OpenStreetMap &copy; CARTO &middot; US Census Bureau'}}}},
  layers:[{{id:'bm',type:'raster',source:'bm'}}]}}}});
map.addControl(new maplibregl.NavigationControl());
const sel=document.getElementById('metric');
METRICS.forEach((m,i)=>{{const o=document.createElement('option');o.value=i;o.textContent=m.label;sel.appendChild(o);}});
let cur=METRICS[0];
map.on('load',()=>{{
  map.addSource('c',{{type:'geojson',data:DATA}});
  map.addLayer({{id:'fill',type:'fill',source:'c',paint:{{'fill-color':colorExpr(cur),'fill-opacity':0.8}}}});
  map.addLayer({{id:'line',type:'line',source:'c',paint:{{'line-color':'#555','line-width':0.4}}}});
  map.fitBounds([[{bbox[0]},{bbox[1]}],[{bbox[2]},{bbox[3]}]],{{padding:30,duration:0}});
  legend(cur);
  sel.onchange=()=>{{cur=METRICS[+sel.value];map.setPaintProperty('fill','fill-color',colorExpr(cur));legend(cur);}};
  map.on('click','fill',e=>{{const p=e.features[0].properties||{{}};
    let rows=''; for(const m of METRICS){{ const v=p[m.key];
      rows+=`<tr class="${{m.key===cur.key?'sel':''}}"><td>${{m.label}}</td><td class="v">${{fmt(v,m.fmt)}}</td></tr>`; }}
    new maplibregl.Popup({{closeButton:true,maxWidth:'340px'}}).setLngLat(e.lngLat)
      .setHTML(`<h4>${{p.NAME||'County'}}</h4><table class="m">${{rows}}</table>`).addTo(map);}});
  map.on('mouseenter','fill',()=>map.getCanvas().style.cursor='pointer');
  map.on('mouseleave','fill',()=>map.getCanvas().style.cursor='');
}});
</script></body></html>"""


# ---------------------------------------------------------------------------
# National state rankings + choropleths.
# ---------------------------------------------------------------------------


def _state_income_gini(year: str = "2023") -> dict[str, dict[str, float | None]]:
    """One for=state:* pull → {fips: {median_income, gini}} (can't be county-
    aggregated). Best-effort: returns {} if the pull fails."""
    out: dict[str, dict[str, float | None]] = {}
    try:
        res = downloader.download_acs(
            state_fips="us", columns="B19013_001E,B19083_001E", tag="states_incgini",
            geo="state", year=year,
        )
    except Exception:
        return out
    import csv as _csv

    with cstore.open_read(res["path"], newline="") as f:
        for row in _csv.DictReader(f):
            fips = (row.get("GEOID", "") or "").rsplit("US", 1)[-1]
            out[fips] = {
                "median_income": metrics.compute_metric(row, metrics.BY_KEY["median_income"]),
                "gini": metrics.compute_metric(row, metrics.BY_KEY["gini"]),
            }
    return out


def build_national_rankings(
    *, year: str = "2023", title: str = "US state rankings", storage=None,
) -> RankingsResult:
    """Assemble per-state metric values (county-aggregated summaries + a
    state-level income/Gini pull), join onto TIGER state geometry, and write a
    national choropleth + rankings table to output/rankings/index.html."""
    metrics_root = cstore.join(cstore.output_root(), "metrics")
    incgini = _state_income_gini(year)

    # gather {fips: {metric_key: value}}
    state_vals: dict[str, dict[str, float | None]] = {}
    for name, fips in STATE_FIPS.items():
        vals: dict[str, float | None] = {}
        sp = cstore.join(metrics_root, name, "metrics-summary.json")
        if cstore.exists(sp):
            try:
                with cstore.open_read(sp) as f:
                    vals = (json.load(f).get("values") or {})
            except Exception:
                vals = {}
        ig = incgini.get(fips, {})
        vals["median_income"] = ig.get("median_income")
        vals["gini"] = ig.get("gini")
        state_vals[fips] = vals

    # attach values onto state geometry (TIGER state extract: output/tiger/state/us_state.geojson)
    geo_path = cstore.join(cstore.output_root(), "tiger", "state", "us_state.geojson")
    fc = {"type": "FeatureCollection", "features": []}
    if cstore.exists(geo_path):
        with cstore.open_read(geo_path) as f:
            fc = json.load(f)
    for feat in fc.get("features") or []:
        p = feat.setdefault("properties", {})
        fips = p.get("STATEFP") or (p.get("GEOID", "") or "").rsplit("US", 1)[-1]
        vals = state_vals.get(fips, {})
        p["state_name"] = _FIPS_NAME.get(fips, p.get("NAME", ""))
        for m in metrics.METRICS:
            p[f"m_{m.key}"] = vals.get(m.key)

    html = _render_national_html(fc, state_vals, title=title)
    out_dir = cstore.join(cstore.output_root(), "rankings")
    html_path = cstore.join(out_dir, "index.html")
    with cstore.open_write(html_path, "w") as f:
        f.write(html)
    return RankingsResult(html_path, len([v for v in state_vals.values() if v]), len(metrics.METRICS))


def _render_national_html(fc: dict, state_vals: dict, *, title: str) -> str:
    data_js = json.dumps(fc, separators=(",", ":"))
    ramp_js = json.dumps(_RAMP)
    # rankings rows source: {fips: {key: val}} + names
    rank_src = json.dumps({_FIPS_NAME.get(f, f): v for f, v in state_vals.items()})
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css" rel="stylesheet">
<script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
<style>
  html,body{{margin:0;height:100%;font-family:system-ui,sans-serif}}
  #wrap{{display:flex;height:100vh}} #map{{flex:1}} #side{{width:300px;overflow:auto;border-left:1px solid #ddd;padding:10px 14px}}
  h3{{margin:0 0 6px;font-size:15px}} select{{font-size:13px;padding:3px;width:100%;margin-bottom:8px}}
  table{{border-collapse:collapse;width:100%;font-size:12px}} th,td{{padding:3px 6px;border-bottom:1px solid #eee;text-align:left}}
  td.v,th.v{{text-align:right}} .mut{{color:#999}}
  .maplibregl-popup-content{{font-size:12px}}
</style></head>
<body><div id="wrap">
<div id="map"></div>
<div id="side">
  <h3>{title}</h3>
  <select id="metric"></select>
  <div class="mut" id="note" style="margin-bottom:6px"></div>
  <table><thead><tr><th>#</th><th>State</th><th class="v" id="vh">Value</th></tr></thead><tbody id="rk"></tbody></table>
</div></div>
<script>
const DATA={data_js}, RANK={rank_src}, RAMP={ramp_js};
const METRICS={_metric_js_national()};
const fmt=(v,f)=>{{ if(v===null||v===undefined||v==='') return '—';
  if(f==='dollar') return '$'+Math.round(v).toLocaleString();
  if(f==='index') return (Math.round(v*1000)/1000).toString();
  return (Math.round(v*10)/10)+'%'; }};
const vals=k=>DATA.features.map(f=>f.properties[k]).filter(v=>typeof v==='number');
function colorExpr(m){{ const a=vals(m.key); if(!a.length) return '#ccc';
  let lo=Math.min(...a),hi=Math.max(...a); if(lo===hi) hi=lo+1;
  const pairs=[]; for(let i=0;i<RAMP.length;i++){{ const v=lo+(hi-lo)*RAMP[i][0];
    const c=m.worse==='low'?RAMP[RAMP.length-1-i][1]:RAMP[i][1]; pairs.push([v,c]); }}
  pairs.sort((x,y)=>x[0]-y[0]); const e=['interpolate',['linear'],['get',m.key]];
  for(const [v,c] of pairs) e.push(v,c); return ['case',['==',['get',m.key],null],'#ccc',e]; }}
function rankTable(m){{
  document.getElementById('vh').textContent=m.label;
  const rows=Object.entries(RANK).map(([s,v])=>[s,v[m.key.slice(2)]]).filter(r=>typeof r[1]==='number');
  rows.sort((a,b)=> m.worse==='low' ? a[1]-b[1] : b[1]-a[1]);   // worst first
  const tb=document.getElementById('rk'); tb.innerHTML='';
  rows.forEach(([s,v],i)=>{{ const tr=document.createElement('tr');
    tr.innerHTML=`<td>${{i+1}}</td><td>${{s}}</td><td class="v">${{fmt(v,m.fmt)}}</td>`; tb.appendChild(tr); }});
  document.getElementById('note').textContent = m.worse==='low' ? 'ranked worst→best (lower = worse)' : 'ranked worst→best (higher = worse)';
}}
const map=new maplibregl.Map({{container:'map',style:{{version:8,
  sources:{{bm:{{type:'raster',tiles:['https://a.basemaps.cartocdn.com/rastertiles/voyager/{{z}}/{{x}}/{{y}}.png'],tileSize:256,attribution:'&copy; OpenStreetMap &copy; CARTO &middot; US Census Bureau'}}}},
  layers:[{{id:'bm',type:'raster',source:'bm'}}]}},center:[-96,38],zoom:3}});
map.addControl(new maplibregl.NavigationControl());
const sel=document.getElementById('metric');
METRICS.forEach((m,i)=>{{const o=document.createElement('option');o.value=i;o.textContent=m.label;sel.appendChild(o);}});
let cur=METRICS[0];
map.on('load',()=>{{
  map.addSource('s',{{type:'geojson',data:DATA}});
  map.addLayer({{id:'fill',type:'fill',source:'s',paint:{{'fill-color':colorExpr(cur),'fill-opacity':0.82}}}});
  map.addLayer({{id:'line',type:'line',source:'s',paint:{{'line-color':'#666','line-width':0.4}}}});
  rankTable(cur);
  sel.onchange=()=>{{cur=METRICS[+sel.value];map.setPaintProperty('fill','fill-color',colorExpr(cur));rankTable(cur);}};
  map.on('click','fill',e=>{{const p=e.features[0].properties||{{}};
    let rows=''; for(const m of METRICS){{ rows+=`<tr><td>${{m.label}}</td><td class="v">${{fmt(p[m.key],m.fmt)}}</td></tr>`; }}
    new maplibregl.Popup({{closeButton:true,maxWidth:'320px'}}).setLngLat(e.lngLat)
      .setHTML(`<h4>${{p.state_name||p.NAME}}</h4><table>${{rows}}</table>`).addTo(map);}});
}});
</script></body></html>"""


def _metric_js_national() -> str:
    items = [{"key": f"m_{m.key}", "label": m.label, "fmt": m.fmt, "worse": m.worse} for m in metrics.METRICS]
    return json.dumps(items)
