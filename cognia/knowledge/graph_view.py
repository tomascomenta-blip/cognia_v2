# -*- coding: utf-8 -*-
"""
cognia/knowledge/graph_view.py — vista del knowledge graph estilo Obsidian
==========================================================================
Mandato del dueño (2026-07-13): ver los grafos de conocimiento conectados y
relacionados, como una memoria de Obsidian pero NATIVA. Cognia ya tiene el
KG (graph.py: tripletas sujeto-predicado-objeto en sqlite + networkx). Esto
lo hace VISIBLE: genera un HTML autocontenido con un force-graph en canvas
vanilla — cero dependencias JS, offline, privado (nada sale de la máquina).

Reutiliza `KnowledgeGraph.get_all_triples`. Filtro opcional por proyecto
(convención source="project:<nombre>"). Sirve para:
  - comando `python -m cognia.knowledge.graph_view [proyecto]` → abre el HTML.
  - endpoint de la oficina /api/kg (JSON) y /grafo (HTML embebido).

Colores por TIPO DE RELACIÓN (is_a, part_of, causes, ...) para leer la
estructura de un vistazo, como Obsidian colorea por carpeta/tag.
"""
from __future__ import annotations

import html
import json
from pathlib import Path

# Paleta por tipo de relación (VALID_RELATIONS de graph.py + fallback).
_REL_COLORS = {
    "is_a": "#4B8AF0", "instance_of": "#4B8AF0",
    "part_of": "#2FB37A", "located_in": "#2FB37A",
    "causes": "#E0574B", "used_for": "#E08A2E",
    "capable_of": "#7B4FD4", "has_property": "#D4AF37",
    "opposite_of": "#C94FD4", "related_to": "#8A8F98",
}
_DEFAULT_COLOR = "#8A8F98"


def build_graph_data(kg, limit: int = 600, project: str | None = None) -> dict:
    """{nodes, links, rels} desde el KG. project filtra por source
    'project:<nombre>' si el KG lo trae; si no, devuelve el grafo global.
    val de cada nodo = grado (tamaño); color de arista = tipo de relación."""
    triples = kg.get_all_triples(limit=limit)
    # get_all_triples devuelve (subject, predicate, object, weight). El
    # filtro por proyecto necesita la columna source: si el KG lo expone,
    # se usa; si no, no filtra (grafo global) y se declara en el título.
    nodes: dict[str, dict] = {}
    links = []
    rels_vistos: dict[str, int] = {}
    for row in triples:
        s, p, o, w = row[0], row[1], row[2], (row[3] if len(row) > 3 else 1.0)
        if not s or not o:
            continue
        for n in (s, o):
            if n not in nodes:
                nodes[n] = {"id": n, "label": n, "val": 0}
            nodes[n]["val"] += 1
        color = _REL_COLORS.get(p, _DEFAULT_COLOR)
        links.append({"source": s, "target": o, "rel": p,
                      "weight": round(float(w or 1.0), 2), "color": color})
        rels_vistos[p] = rels_vistos.get(p, 0) + 1
    rels = [{"rel": r, "n": n, "color": _REL_COLORS.get(r, _DEFAULT_COLOR)}
            for r, n in sorted(rels_vistos.items(), key=lambda x: -x[1])]
    return {"nodes": list(nodes.values()), "links": links, "rels": rels,
            "project": project}


# ── Front vanilla: force-graph en canvas, sin dependencias ──────────────────
_HTML = r"""<!doctype html><html><head><meta charset="utf-8">
<title>{title}</title>
<style>
 html,body{{margin:0;height:100%;background:#12141a;color:#c9d1d9;
   font:13px/1.4 system-ui,sans-serif;overflow:hidden}}
 #hud{{position:fixed;top:10px;left:10px;z-index:2;max-width:280px}}
 #hud h1{{font-size:15px;margin:0 0 6px}}
 #q{{width:200px;background:#1c1f28;border:1px solid #2a2f3a;color:#c9d1d9;
   padding:5px 8px;border-radius:6px;outline:none}}
 #legend{{margin-top:8px;font-size:11px;opacity:.85}}
 #legend span{{display:inline-flex;align-items:center;margin:2px 8px 2px 0}}
 #legend i{{width:9px;height:9px;border-radius:50%;margin-right:4px;display:inline-block}}
 #tip{{position:fixed;padding:4px 8px;background:#1c1f28;border:1px solid #2a2f3a;
   border-radius:6px;pointer-events:none;display:none;z-index:3;max-width:260px}}
 #info{{position:fixed;bottom:10px;left:10px;font-size:11px;opacity:.6}}
</style></head><body>
<div id="hud"><h1>{title}</h1>
 <input id="q" placeholder="buscar nodo..." autocomplete="off">
 <div id="legend"></div></div>
<div id="tip"></div><div id="info"></div>
<canvas id="c"></canvas>
<script>
const DATA = {data};
const cv=document.getElementById('c'),ctx=cv.getContext('2d');
let W,H;function resize(){{W=cv.width=innerWidth;H=cv.height=innerHeight;}}
addEventListener('resize',resize);resize();
const N=DATA.nodes, L=DATA.links;
const byId={{}};N.forEach(n=>{{byId[n.id]=n;n.x=W/2+(Math.random()-.5)*400;
  n.y=H/2+(Math.random()-.5)*400;n.vx=0;n.vy=0;}});
const adj={{}};N.forEach(n=>adj[n.id]=new Set());
L.forEach(l=>{{l.s=byId[l.source];l.t=byId[l.target];
  if(l.s&&l.t){{adj[l.source].add(l.target);adj[l.target].add(l.source);}}}});
let cam={{x:0,y:0,z:1}},hover=null,drag=null,pan=null,query='';
// leyenda
const lg=document.getElementById('legend');
DATA.rels.slice(0,10).forEach(r=>{{const s=document.createElement('span');
  s.innerHTML='<i style="background:'+r.color+'"></i>'+r.rel+' ('+r.n+')';lg.appendChild(s);}});
document.getElementById('info').textContent=N.length+' nodos · '+L.length+' relaciones';
// física (O(n^2), ok para <600 nodos)
function step(){{
 for(let i=0;i<N.length;i++){{const a=N[i];
  for(let j=i+1;j<N.length;j++){{const b=N[j];let dx=a.x-b.x,dy=a.y-b.y;
   let d2=dx*dx+dy*dy+.01,d=Math.sqrt(d2);let f=1400/d2;
   let fx=dx/d*f,fy=dy/d*f;a.vx+=fx;a.vy+=fy;b.vx-=fx;b.vy-=fy;}}
  a.vx+=(W/2-a.x)*.0006;a.vy+=(H/2-a.y)*.0006;}}
 L.forEach(l=>{{if(!l.s||!l.t)return;let dx=l.t.x-l.s.x,dy=l.t.y-l.s.y;
  let d=Math.sqrt(dx*dx+dy*dy)||1;let f=(d-90)*.02;
  let fx=dx/d*f,fy=dy/d*f;l.s.vx+=fx;l.s.vy+=fy;l.t.vx-=fx;l.t.vy-=fy;}});
 N.forEach(n=>{{if(n===drag)return;n.vx*=.85;n.vy*=.85;n.x+=n.vx;n.y+=n.vy;}});
}}
function sx(n){{return (n.x-cam.x)*cam.z+W/2;}}
function sy(n){{return (n.y-cam.y)*cam.z+H/2;}}
function draw(){{ctx.clearRect(0,0,W,H);
 const hl=hover?adj[hover.id]:null;
 L.forEach(l=>{{if(!l.s||!l.t)return;
  const on=hover&&(l.source===hover.id||l.target===hover.id);
  ctx.globalAlpha=hover?(on?.9:.06):.28;ctx.strokeStyle=l.color;
  ctx.lineWidth=on?1.6:.7;ctx.beginPath();
  ctx.moveTo(sx(l.s),sy(l.s));ctx.lineTo(sx(l.t),sy(l.t));ctx.stroke();}});
 ctx.globalAlpha=1;
 N.forEach(n=>{{const on=!hover||n===hover||(hl&&hl.has(n.id));
  const match=query&&n.label.toLowerCase().includes(query);
  const r=Math.min(3+Math.sqrt(n.val)*1.6,14)*cam.z;
  ctx.globalAlpha=on?1:.12;
  ctx.beginPath();ctx.arc(sx(n),sy(n),r,0,7);
  ctx.fillStyle=match?'#ffd24a':(n===hover?'#fff':'#6b93e0');ctx.fill();
  if(match||n===hover||(hl&&hl.has(n.id))||(cam.z>1.4&&n.val>1)){{
   ctx.globalAlpha=on?.95:.2;ctx.fillStyle='#c9d1d9';
   ctx.font=(11)+'px system-ui';ctx.fillText(n.label,sx(n)+r+2,sy(n)+3);}}
 }});ctx.globalAlpha=1;}}
function loop(){{step();draw();requestAnimationFrame(loop);}}loop();
// interacción
function pick(mx,my){{let best=null,bd=16;N.forEach(n=>{{
  let d=Math.hypot(sx(n)-mx,sy(n)-my);if(d<bd){{bd=d;best=n;}}}});return best;}}
cv.addEventListener('mousemove',e=>{{const mx=e.clientX,my=e.clientY;
 if(drag){{drag.x=(mx-W/2)/cam.z+cam.x;drag.y=(my-H/2)/cam.z+cam.y;drag.vx=drag.vy=0;return;}}
 if(pan){{cam.x-=(mx-pan.x)/cam.z;cam.y-=(my-pan.y)/cam.z;pan={{x:mx,y:my}};return;}}
 hover=pick(mx,my);const tip=document.getElementById('tip');
 if(hover){{tip.style.display='block';tip.style.left=(mx+12)+'px';tip.style.top=(my+12)+'px';
  tip.textContent=hover.label+'  ·  '+hover.val+' conexiones';cv.style.cursor='pointer';}}
 else{{tip.style.display='none';cv.style.cursor=pan?'grabbing':'grab';}}}});
cv.addEventListener('mousedown',e=>{{const n=pick(e.clientX,e.clientY);
 if(n)drag=n;else pan={{x:e.clientX,y:e.clientY}};}});
addEventListener('mouseup',()=>{{drag=null;pan=null;}});
cv.addEventListener('wheel',e=>{{e.preventDefault();
 const f=e.deltaY<0?1.1:.9;cam.z=Math.max(.15,Math.min(6,cam.z*f));}},{{passive:false}});
document.getElementById('q').addEventListener('input',e=>{{query=e.target.value.toLowerCase();}});
</script></body></html>"""


def render_html(data: dict, title: str = "Cognia · Grafo de conocimiento") -> str:
    return _HTML.replace("{title}", html.escape(title)).replace(
        "{data}", json.dumps(data, ensure_ascii=False))


def export(kg=None, path: str | None = None, limit: int = 600,
           project: str | None = None, open_browser: bool = True) -> str:
    """Genera el HTML del grafo y (por defecto) lo abre. Devuelve la ruta."""
    if kg is None:
        from cognia.knowledge.graph import KnowledgeGraph
        kg = KnowledgeGraph()
    data = build_graph_data(kg, limit=limit, project=project)
    titulo = ("Cognia · Grafo" + (f" · {project}" if project else " · global")
              + f" ({len(data['nodes'])} nodos)")
    out = Path(path) if path else (Path.home() / ".cognia" / "grafo.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(data, titulo), encoding="utf-8")
    if open_browser:
        import webbrowser
        webbrowser.open(out.as_uri())
    return str(out)


if __name__ == "__main__":
    import sys
    proj = sys.argv[1] if len(sys.argv) > 1 else None
    ruta = export(project=proj, open_browser="--no-open" not in sys.argv)
    print(f"grafo -> {ruta}")
