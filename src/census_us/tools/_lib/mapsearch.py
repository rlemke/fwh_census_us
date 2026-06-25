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
