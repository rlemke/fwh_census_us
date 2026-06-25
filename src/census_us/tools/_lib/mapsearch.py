"""Reusable name-search snippet for the choropleth maps.

Returns plain strings (single braces) to interpolate into a renderer's f-string
template — the f-string evaluates these to values, so their `{ }` are NOT
re-parsed. The JS must be embedded INSIDE the renderer's own ``<script>`` (so it
shares the ``map`` and ``DATA`` consts); the CSS goes in ``<style>`` and the box
in ``<body>``. Typing matches a region's ``name_field`` (substring); clicking a
result fits the map to that feature's bounds and drops a label popup.
"""

from __future__ import annotations


def search_css_rules() -> str:
    return (
        ".rsearch{position:absolute;top:10px;left:50%;transform:translateX(-50%);"
        "z-index:6;width:300px;max-width:70%}"
        ".rsearch input{width:100%;box-sizing:border-box;padding:7px 11px;border:1px solid #aaa;"
        "border-radius:6px;font-size:13px;box-shadow:0 2px 6px rgba(0,0,0,.2)}"
        ".rsearch .res{background:#fff;border-radius:0 0 6px 6px;box-shadow:0 2px 6px rgba(0,0,0,.2);"
        "max-height:240px;overflow:auto}"
        ".rsearch .res div{padding:6px 11px;cursor:pointer;font-size:12px;border-top:1px solid #f0f0f0}"
        ".rsearch .res div:hover{background:#f3f3f3}"
    )


def search_html(placeholder: str) -> str:
    return (
        f'<div class="rsearch"><input id="rsin" placeholder="{placeholder}" autocomplete="off">'
        '<div class="res" id="rsres"></div></div>'
    )


def search_js(name_field: str = "NAME") -> str:
    """JS to embed at the END of the renderer's <script> (needs ``map`` + ``DATA``)."""
    return (
        "(function(){"
        "function fbbox(g){let a=[180,90,-180,-90];const w=c=>{if(typeof c[0]==='number'){"
        "a[0]=Math.min(a[0],c[0]);a[1]=Math.min(a[1],c[1]);a[2]=Math.max(a[2],c[0]);a[3]=Math.max(a[3],c[1]);}"
        "else c.forEach(w);};w(g.coordinates);return a;}"
        "const idx=DATA.features.map(f=>({n:String((f.properties||{})['" + name_field + "']||''),f}))"
        ".filter(x=>x.n);"
        "const inp=document.getElementById('rsin'),res=document.getElementById('rsres');if(!inp)return;"
        "inp.addEventListener('input',()=>{const q=inp.value.trim().toLowerCase();res.innerHTML='';"
        "if(q.length<2)return;"
        "idx.filter(x=>x.n.toLowerCase().includes(q)).slice(0,12).forEach(x=>{"
        "const d=document.createElement('div');d.textContent=x.n;"
        "d.addEventListener('click',()=>{const b=fbbox(x.f.geometry);"
        "map.fitBounds([[b[0],b[1]],[b[2],b[3]]],{padding:40,maxZoom:9,duration:700});"
        "res.innerHTML='';inp.value=x.n;"
        "new maplibregl.Popup().setLngLat([(b[0]+b[2])/2,(b[1]+b[3])/2])"
        ".setHTML('<h4>'+x.n+'</h4>').addTo(map);});res.appendChild(d);});});"
        "document.addEventListener('click',e=>{if(!e.target.closest('.rsearch'))res.innerHTML='';});"
        "})();"
    )


# ---------------------------------------------------------------------------
# Table row-filter — for the index/listing pages (a table of links per state).
# Hides rows whose name cell doesn't match the typed text; updates a count el.
# ---------------------------------------------------------------------------

def table_filter_css() -> str:
    return (
        ".tfilter{margin:0 0 12px;padding:7px 11px;border:1px solid #aaa;border-radius:6px;"
        "font-size:13px;width:300px;max-width:90%;box-sizing:border-box;"
        "box-shadow:0 1px 3px rgba(0,0,0,.1)}"
    )


def table_filter_html(placeholder: str = "Filter by name…", input_id: str = "tfilter") -> str:
    return f'<input id="{input_id}" class="tfilter" placeholder="{placeholder}" autocomplete="off">'


def table_filter_js(table_id: str = "t", name_col: int = 0,
                    input_id: str = "tfilter", count_id: str = "") -> str:
    """JS to filter a table's rows by the text of cell ``name_col``. If
    ``count_id`` names an element, its ``data-count`` template (or text) is
    updated to the visible-row count."""
    cnt = (
        "var c=document.getElementById('" + count_id + "');"
        "if(c){var t=c.getAttribute('data-tpl')||c.textContent;"
        "if(!c.getAttribute('data-tpl'))c.setAttribute('data-tpl',t);"
        "c.textContent=(c.getAttribute('data-tpl')).replace(/\\d+/,String(v));}"
    ) if count_id else ""
    return (
        "(function(){"
        "var inp=document.getElementById('" + input_id + "');if(!inp)return;"
        "var tb=document.querySelector('#" + table_id + " tbody');if(!tb)return;"
        "inp.addEventListener('input',function(){"
        "var q=inp.value.trim().toLowerCase(),v=0;"
        "[].forEach.call(tb.rows,function(r){"
        "var cell=r.cells[" + str(name_col) + "];"
        "var n=(cell?cell.textContent:'').toLowerCase();"
        "var show=(!q||n.indexOf(q)>=0);r.style.display=show?'':'none';if(show)v++;});"
        + cnt +
        "});})();"
    )
