# -*- coding: utf-8 -*-
"""
cognia/knowledge/graph_view.py — vista del knowledge graph estilo Obsidian
==========================================================================
Mandato del dueño (2026-07-13): ver los grafos de conocimiento conectados y
relacionados, como una memoria de Obsidian pero NATIVA. Cognia ya tiene el
KG (graph.py: tripletas sujeto-predicado-objeto en sqlite + networkx). Esto
lo hace VISIBLE: genera un HTML autocontenido con un force-graph en canvas
vanilla — cero dependencias JS, offline, privado (nada sale de la máquina).

Aspecto Obsidian: nodos-ESFERA con glow, tamaño por grado (los hubs se ven
grandes), layout orgánico force-directed, hover ilumina vecinos, zoom/pan,
búsqueda, color de arista por tipo de relación.
"""
from __future__ import annotations

import html
import json

_REL_COLORS = {
    "is_a": "#4B8AF0", "instance_of": "#4B8AF0",
    "part_of": "#2FB37A", "located_in": "#2FB37A",
    "causes": "#E0574B", "used_for": "#E08A2E",
    "capable_of": "#7B4FD4", "has_property": "#D4AF37",
    "opposite_of": "#C94FD4", "related_to": "#8A8F98",
}
_DEFAULT_COLOR = "#8A8F98"


def build_graph_data(kg, limit: int = 600, project: str | None = None) -> dict:
    """{nodes, links, rels} desde el KG. val de cada nodo = grado (tamaño)."""
    triples = kg.get_all_triples(limit=limit)
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


# Front vanilla: force-graph en canvas. Placeholders __TITLE__/__DATA__/__SUB__
# se sustituyen con .replace() — NADA de llaves dobles (bug histórico: el
# template usaba {{ }} de str.format pero se renderizaba con replace, dejando
# el CSS/JS con llaves dobles literales y el canvas en blanco).
_HTML = r"""<!doctype html><html><head><meta charset="utf-8">
<title>__TITLE__</title>
<style>
 html,body{margin:0;height:100%;background:#12141a;color:#c9d1d9;
   font:13px/1.4 system-ui,sans-serif;overflow:hidden}
 #hud{position:fixed;top:12px;left:14px;z-index:2;max-width:300px}
 #hud h1{font-size:15px;margin:0 0 6px;color:#e6edf3}
 #q{width:210px;background:#1c1f28;border:1px solid #2a2f3a;color:#c9d1d9;
   padding:6px 9px;border-radius:7px;outline:none}
 #legend{margin-top:9px;font-size:11px;opacity:.85}
 #legend span{display:inline-flex;align-items:center;margin:2px 9px 2px 0}
 #legend i{width:9px;height:9px;border-radius:50%;margin-right:4px;display:inline-block}
 #tip{position:fixed;padding:5px 9px;background:#1c1f28;border:1px solid #2a2f3a;
   border-radius:7px;pointer-events:none;display:none;z-index:3;max-width:260px}
 #info{position:fixed;bottom:12px;left:14px;font-size:11px;opacity:.55}
</style></head><body>
<div id="hud"><h1>__TITLE__</h1>
 <input id="q" placeholder="buscar nodo..." autocomplete="off">
 <div id="legend"></div></div>
<div id="tip"></div><div id="info">__SUB__</div>
<canvas id="c"></canvas>
<script>
const DATA = __DATA__;
const cv=document.getElementById('c'),ctx=cv.getContext('2d');
let W,H;function resize(){W=cv.width=innerWidth;H=cv.height=innerHeight;}
addEventListener('resize',resize);resize();
const N=DATA.nodes, L=DATA.links;
const byId={};N.forEach(n=>{byId[n.id]=n;n.x=W/2+(Math.random()-.5)*Math.min(W,900);
  n.y=H/2+(Math.random()-.5)*Math.min(H,700);n.vx=0;n.vy=0;});
const adj={};N.forEach(n=>adj[n.id]=new Set());
L.forEach(l=>{l.s=byId[l.source];l.t=byId[l.target];
  if(l.s&&l.t){adj[l.source].add(l.target);adj[l.target].add(l.source);}});
let cam={x:0,y:0,z:1},hover=null,drag=null,pan=null,query='';
const lg=document.getElementById('legend');
DATA.rels.slice(0,10).forEach(r=>{const s=document.createElement('span');
  s.innerHTML='<i style="background:'+r.color+'"></i>'+r.rel+' ('+r.n+')';lg.appendChild(s);});
function radio(n){return 5+Math.sqrt(n.val)*3.4;}
function step(){
 for(let i=0;i<N.length;i++){const a=N[i];
  for(let j=i+1;j<N.length;j++){const b=N[j];let dx=a.x-b.x,dy=a.y-b.y;
   let d2=dx*dx+dy*dy+.01,d=Math.sqrt(d2);let f=2800/d2;
   let fx=dx/d*f,fy=dy/d*f;a.vx+=fx;a.vy+=fy;b.vx-=fx;b.vy-=fy;}
  a.vx+=(W/2-a.x)*.0005;a.vy+=(H/2-a.y)*.0005;}
 L.forEach(l=>{if(!l.s||!l.t)return;let dx=l.t.x-l.s.x,dy=l.t.y-l.s.y;
  let d=Math.sqrt(dx*dx+dy*dy)||1;let f=(d-130)*.018;
  let fx=dx/d*f,fy=dy/d*f;l.s.vx+=fx;l.s.vy+=fy;l.t.vx-=fx;l.t.vy-=fy;});
 N.forEach(n=>{if(n===drag)return;n.vx*=.86;n.vy*=.86;n.x+=n.vx;n.y+=n.vy;});
}
function sx(n){return (n.x-cam.x)*cam.z+W/2;}
function sy(n){return (n.y-cam.y)*cam.z+H/2;}
function draw(){ctx.clearRect(0,0,W,H);
 const hl=hover?adj[hover.id]:null;
 L.forEach(l=>{if(!l.s||!l.t)return;
  const on=hover&&(l.source===hover.id||l.target===hover.id);
  ctx.globalAlpha=hover?(on?.95:.05):.30;ctx.strokeStyle=l.color;
  ctx.lineWidth=(on?2:1)*Math.min(cam.z,1.5);ctx.beginPath();
  ctx.moveTo(sx(l.s),sy(l.s));ctx.lineTo(sx(l.t),sy(l.t));ctx.stroke();});
 ctx.globalAlpha=1;
 N.forEach(n=>{const on=!hover||n===hover||(hl&&hl.has(n.id));
  const match=query&&n.label.toLowerCase().includes(query);
  const r=radio(n)*cam.z;const X=sx(n),Y=sy(n);
  if(X<-40||X>W+40||Y<-40||Y>H+40)return;
  ctx.globalAlpha=on?1:.14;
  const base=match?'#ffd24a':(n===hover?'#ffffff':'#7aa2f7');
  const g=ctx.createRadialGradient(X-r*0.3,Y-r*0.3,r*0.2,X,Y,r);
  g.addColorStop(0,'#dbe7ff');g.addColorStop(0.55,base);g.addColorStop(1,base);
  ctx.beginPath();ctx.arc(X,Y,r,0,7);ctx.fillStyle=g;ctx.fill();
  ctx.lineWidth=1;ctx.strokeStyle='rgba(180,205,255,.45)';ctx.stroke();
  if(match||n===hover||(hl&&hl.has(n.id))||n.val>=3||cam.z>1.3){
   ctx.globalAlpha=on?.96:.25;ctx.fillStyle='#dfe7f2';
   ctx.font=(Math.max(10,11*Math.min(cam.z,1.6)))+'px system-ui';
   ctx.textAlign='center';ctx.fillText(n.label,X,Y+r+13);ctx.textAlign='left';}
 });ctx.globalAlpha=1;}
// auto-fit: durante el asentamiento inicial, encuadra TODO el grafo en la
// vista (asi no se escapa de pantalla). Tras unos segundos deja de forzar y
// el usuario puede pan/zoom libre.
let t0=performance.now(),autofit=true;
function fit(){
 if(!N.length)return;
 let minx=1e9,miny=1e9,maxx=-1e9,maxy=-1e9;
 N.forEach(n=>{minx=Math.min(minx,n.x);miny=Math.min(miny,n.y);
   maxx=Math.max(maxx,n.x);maxy=Math.max(maxy,n.y);});
 const cx=(minx+maxx)/2,cy=(miny+maxy)/2;
 const zx=(W-120)/Math.max(maxx-minx,1),zy=(H-120)/Math.max(maxy-miny,1);
 const z=Math.max(.1,Math.min(3,Math.min(zx,zy)));
 cam.x+=(cx-cam.x)*.1;cam.y+=(cy-cam.y)*.1;cam.z+=(z-cam.z)*.1;
}
function loop(){step();
 if(autofit){fit();if(performance.now()-t0>6000)autofit=false;}
 draw();requestAnimationFrame(loop);}loop();
// cualquier interaccion del usuario corta el auto-fit
['wheel','mousedown'].forEach(ev=>cv.addEventListener(ev,()=>autofit=false));
function pick(mx,my){let best=null,bd=1e9;N.forEach(n=>{
  let d=Math.hypot(sx(n)-mx,sy(n)-my);let r=radio(n)*cam.z+6;
  if(d<r&&d<bd){bd=d;best=n;}});return best;}
cv.addEventListener('mousemove',e=>{const mx=e.clientX,my=e.clientY;
 if(drag){drag.x=(mx-W/2)/cam.z+cam.x;drag.y=(my-H/2)/cam.z+cam.y;drag.vx=drag.vy=0;return;}
 if(pan){cam.x-=(mx-pan.x)/cam.z;cam.y-=(my-pan.y)/cam.z;pan={x:mx,y:my};return;}
 hover=pick(mx,my);const tip=document.getElementById('tip');
 if(hover){tip.style.display='block';tip.style.left=(mx+12)+'px';tip.style.top=(my+12)+'px';
  tip.textContent=hover.label+'  ·  '+hover.val+' conexiones';cv.style.cursor='pointer';}
 else{tip.style.display='none';cv.style.cursor=pan?'grabbing':'grab';}});
cv.addEventListener('mousedown',e=>{const n=pick(e.clientX,e.clientY);
 if(n)drag=n;else pan={x:e.clientX,y:e.clientY};});
addEventListener('mouseup',()=>{drag=null;pan=null;});
cv.addEventListener('wheel',e=>{e.preventDefault();
 const f=e.deltaY<0?1.1:.9;cam.z=Math.max(.15,Math.min(6,cam.z*f));},{passive:false});
document.getElementById('q').addEventListener('input',e=>{query=e.target.value.toLowerCase();});
</script></body></html>"""


def render_html(data: dict, title: str = "Cognia · Grafo de conocimiento") -> str:
    sub = f"{len(data.get('nodes', []))} nodos · {len(data.get('links', []))} relaciones"
    return (_HTML.replace("__TITLE__", html.escape(title))
            .replace("__SUB__", sub)
            .replace("__DATA__", json.dumps(data, ensure_ascii=False)))


def export(kg=None, path: str | None = None, limit: int = 220,
           project: str | None = None, open_browser: bool = True) -> str:
    from pathlib import Path
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
