# -*- coding: utf-8 -*-
"""
cognia/agent/flujoteca_view.py
==============================
El lienzo de un flujo CON su linea de tiempo de versiones.

POR QUE NO SE REUSA flow_view.py TAL CUAL
-----------------------------------------
`agent/flow_view.py` ya dibuja un DAG, y su `build_layout()` (profundidad
topologica -> columna) se reusa AQUI sin tocarlo: el calculo de posiciones
esta bien y no hay motivo para reescribirlo.

Lo que cambia es lo que el dueno pidio explicitamente y lo que faltaba:
  1. ASPECTO. flow_view pinta cajas oscuras (fill:#0b0d11) sobre fondo
     oscuro. El pedido es al reves: "nodos rectangulares blancos, bordes
     negros, conectores claros". Los nodos se quedan BLANCOS con borde negro
     en los dos temas, y lo que cambia con el tema es el LIENZO. Un diagrama
     de nodos se lee como un diagrama sobre papel; invertirlo en modo oscuro
     lo convierte en otra cosa.
  2. VERSIONES. flow_view dibuja UN flujo suelto. Aqui el flujo tiene
     historial, y la linea de tiempo es navegable: se pulsa una version y el
     lienzo se redibuja con ella. Las versiones viajan TODAS embebidas, asi
     que moverse por el historial no toca disco ni red.

Como el resto de vistas de la casa: HTML autocontenido, cero CDN, se escribe
a ~/.cognia/ y se abre con webbrowser.
"""
from __future__ import annotations

import json
from pathlib import Path

__all__ = ["build_datos", "render_html", "export"]


def build_datos(nombre: str, *, tope_versiones: int = 40) -> dict:
    """Todas las versiones del flujo con su layout ya calculado."""
    from cognia.agent import flujoteca as _ft
    from cognia.agent import flow_view as _fv

    metas = _ft.versiones(nombre)
    versiones = []
    for m in metas[:tope_versiones]:
        v = int(m.get("v", 0))
        if not m.get("existe"):
            # Una version borrada NO se omite: se muestra en la linea de
            # tiempo marcada como borrada. Omitirla haria que el historial
            # dijera que nunca existio, que es exactamente lo contrario de
            # para que sirve un historial.
            versiones.append({"v": v, "ts": m.get("ts", ""),
                              "nota": m.get("nota", ""), "borrada": True,
                              "actual": m.get("actual", False),
                              "layout": None, "n_nodos": m.get("n_nodos", 0)})
            continue
        try:
            flujo = _ft.cargar(nombre, v)
            layout = _fv.build_layout(flujo)
        except Exception as exc:
            versiones.append({"v": v, "ts": m.get("ts", ""),
                              "nota": m.get("nota", ""), "borrada": False,
                              "error": f"{type(exc).__name__}: {exc}",
                              "actual": m.get("actual", False),
                              "layout": None, "n_nodos": 0})
            continue
        versiones.append({
            "v": v, "ts": m.get("ts", ""), "nota": m.get("nota", ""),
            "actual": bool(m.get("actual")), "borrada": False,
            "n_nodos": len(flujo.get("nodos") or []),
            "layout": layout,
            "nodos": {n.get("id"): n for n in (flujo.get("nodos") or [])},
        })
    return {"nombre": nombre, "descripcion": _ft.descripcion(nombre),
            "versiones": versiones}


_HTML = r"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{
  --lienzo:#eef0f3; --panel:#ffffff; --borde:#d0d7de; --texto:#1f2328;
  --texto2:#59636e; --acento:#0969da; --cable:#57606a; --nodo:#ffffff;
  --nodo-borde:#1f2328;
}
:root[data-tema="oscuro"]{
  --lienzo:#1c2128; --panel:#161b22; --borde:#30363d; --texto:#e6edf3;
  --texto2:#8b949e; --acento:#58a6ff; --cable:#8b949e; --nodo:#ffffff;
  --nodo-borde:#0d1117;
}
*{box-sizing:border-box}
html,body{margin:0;height:100%}
body{background:var(--lienzo);color:var(--texto);display:flex;flex-direction:column;
  font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
header{display:flex;align-items:baseline;gap:14px;padding:13px 20px;background:var(--panel);
  border-bottom:1px solid var(--borde);flex-wrap:wrap}
h1{font-size:16px;font-weight:600;margin:0}
header .desc{color:var(--texto2);font-size:13px;flex:1;min-width:120px}
button{padding:6px 11px;background:var(--panel);color:var(--texto);border:1px solid var(--borde);
  border-radius:6px;font-size:13px;cursor:pointer}
button:hover{border-color:var(--acento)}
main{flex:1;display:flex;min-height:0}
#lienzo{flex:1;overflow:auto;padding:10px}
aside{width:290px;flex:0 0 290px;background:var(--panel);border-left:1px solid var(--borde);
  overflow-y:auto;padding:14px 16px}
aside h2{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--texto2);
  margin:0 0 10px;font-weight:600}
/* LINEA DE TIEMPO: una columna con un punto por version, la mas nueva arriba */
.ver{display:flex;gap:10px;cursor:pointer;padding:5px 6px;border-radius:6px;
  border:1px solid transparent;position:relative}
.ver:hover{background:var(--lienzo)}
.ver[aria-current="true"]{border-color:var(--acento)}
.ver .punto{flex:0 0 11px;height:11px;border-radius:50%;background:var(--acento);
  margin-top:5px;border:2px solid var(--panel);box-shadow:0 0 0 1px var(--acento)}
.ver.borrada .punto{background:transparent;box-shadow:0 0 0 1px var(--texto2)}
.ver::before{content:"";position:absolute;left:11px;top:16px;bottom:-6px;width:1px;
  background:var(--borde)}
.ver:last-child::before{display:none}
.ver .cuerpo{min-width:0;flex:1}
.ver .tit{font-weight:600;font-size:13px}
.ver .meta{color:var(--texto2);font-size:12px;overflow:hidden;text-overflow:ellipsis}
.chip{font-size:10px;padding:0 6px;border-radius:20px;border:1px solid var(--borde);
  color:var(--texto2);margin-left:5px}
/* NODOS: blancos con borde negro, en los DOS temas. Es lo pedido, y es como
   se lee un diagrama de nodos: como tinta sobre papel. */
.caja{fill:var(--nodo);stroke:var(--nodo-borde);stroke-width:2;rx:8}
.n-num{fill:var(--texto2);font-size:11px;font-weight:700}
.n-tool{fill:#1f2328;font-size:13px;font-weight:600}
.n-args{fill:#59636e;font-size:11px}
.cable{stroke:var(--cable);stroke-width:2;fill:none}
.punto-cable{fill:var(--cable)}
#ficha{margin-top:18px;padding-top:14px;border-top:1px solid var(--borde)}
#ficha .k{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--texto2)}
#ficha .v{margin-bottom:9px;word-break:break-word;font-size:13px}
code{background:var(--lienzo);border:1px solid var(--borde);border-radius:4px;padding:1px 5px;
  font-family:ui-monospace,Consolas,monospace;font-size:12px}
#aviso{padding:10px 20px;background:var(--panel);border-bottom:1px solid var(--borde);
  color:var(--texto2)}
footer{padding:7px 20px;background:var(--panel);border-top:1px solid var(--borde);
  color:var(--texto2);font-size:12px}
</style></head><body>
<header>
  <h1 id="titulo"></h1>
  <span class="desc" id="desc"></span>
  <button id="tema" title="Claro / oscuro">&#9788;</button>
</header>
<div id="aviso" hidden></div>
<main>
  <div id="lienzo"></div>
  <aside>
    <h2>Versiones</h2>
    <div id="tl"></div>
    <div id="ficha" hidden></div>
  </aside>
</main>
<footer id="pie"></footer>
<script>
const D = __DATA__;
const $ = s => document.querySelector(s);

(function(){
  let t = null;
  try{ t = localStorage.getItem("cognia_flujo_tema"); }catch(e){}
  if(!t) t = (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) ? "oscuro" : "claro";
  tema(t);
})();
function tema(t){
  document.documentElement.setAttribute("data-tema", t);
  $("#tema").innerHTML = t === "oscuro" ? "&#9788;" : "&#9789;";
}
$("#tema").onclick = () => {
  const n = document.documentElement.getAttribute("data-tema") === "oscuro" ? "claro" : "oscuro";
  tema(n);
  try{ localStorage.setItem("cognia_flujo_tema", n); }catch(e){}
};

$("#titulo").textContent = D.nombre;
$("#desc").textContent = D.descripcion || "";

let activa = D.versiones.find(v => v.actual && v.layout) || D.versiones.find(v => v.layout);

function esc(s){ return String(s == null ? "" : s).replace(/[&<>"]/g, c =>
  ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])); }

function pintarLienzo(v){
  const c = $("#lienzo");
  if(!v || !v.layout){
    c.innerHTML = '<p style="padding:30px;color:var(--texto2)">' +
      (v && v.borrada ? "Esta version fue borrada: no queda cuerpo que dibujar."
                      : "No se pudo cargar esta version.") + '</p>';
    return;
  }
  const L = v.layout;
  let s = '<svg width="' + L.w + '" height="' + L.h + '" viewBox="0 0 ' + L.w + ' ' + L.h + '">';
  s += '<defs><marker id="f" viewBox="0 0 9 7" refX="8" refY="3.5" markerWidth="9" ' +
       'markerHeight="7" orient="auto"><path d="M0,0 L9,3.5 L0,7 Z" fill="var(--cable)"/></marker></defs>';
  /* Conectores en curva: con lineas rectas, dos cables que salen del mismo
     nodo se solapan y no se ve cual va a donde. */
  L.cables.forEach(k => {
    const dx = Math.max(30, (k.x2 - k.x1) / 2);
    s += '<path class="cable" marker-end="url(#f)" d="M' + k.x1 + ',' + k.y1 +
         ' C' + (k.x1 + dx) + ',' + k.y1 + ' ' + (k.x2 - dx) + ',' + k.y2 +
         ' ' + k.x2 + ',' + k.y2 + '"/>';
    s += '<circle class="punto-cable" cx="' + k.x1 + '" cy="' + k.y1 + '" r="3"/>';
  });
  L.cajas.forEach(b => {
    s += '<g class="nodo" data-id="' + esc(b.id) + '" style="cursor:pointer">';
    s += '<rect class="caja" x="' + b.x + '" y="' + b.y + '" width="' + b.w + '" height="' + b.h + '"/>';
    s += '<text class="n-num" x="' + (b.x + 11) + '" y="' + (b.y + 19) + '">' + b.n + '</text>';
    s += '<text class="n-tool" x="' + (b.x + 28) + '" y="' + (b.y + 20) + '">' + esc(b.tool) + '</text>';
    s += '<text class="n-args" x="' + (b.x + 11) + '" y="' + (b.y + 40) + '">' + esc(b.args) + '</text>';
    s += '<text class="n-args" x="' + (b.x + 11) + '" y="' + (b.y + 56) + '">' + esc(b.id) + '</text>';
    s += '</g>';
  });
  s += '</svg>';
  c.innerHTML = s;
  c.querySelectorAll(".nodo").forEach(g => {
    g.onclick = () => ficha(v, g.getAttribute("data-id"));
  });
}

function ficha(v, id){
  const n = (v.nodos || {})[id];
  const f = $("#ficha");
  if(!n){ f.hidden = true; return; }
  f.hidden = false;
  let h = '<h2>Nodo</h2>';
  const filas = [["id", n.id], ["tool", n.tool], ["args", n.args],
                 ["va a", (n.wires || []).join(", ") || "(fin)"],
                 ["saltar si", n.saltar_si], ["reintentos", n.reintentos],
                 ["timeout", n.timeout_s], ["modelo", n.modelo]];
  filas.forEach(([k, val]) => {
    if(val === undefined || val === null || val === "") return;
    h += '<div class="k">' + esc(k) + '</div><div class="v"><code>' + esc(val) + '</code></div>';
  });
  f.innerHTML = h;
}

function pintarTimeline(){
  const tl = $("#tl");
  tl.innerHTML = "";
  D.versiones.forEach(v => {
    const d = document.createElement("div");
    d.className = "ver" + (v.borrada ? " borrada" : "");
    d.setAttribute("aria-current", activa && v.v === activa.v);
    const chips = (v.actual ? '<span class="chip">actual</span>' : "") +
                  (v.borrada ? '<span class="chip">borrada</span>' : "");
    d.innerHTML = '<div class="punto"></div><div class="cuerpo">' +
      '<div class="tit">v' + v.v + chips + '</div>' +
      '<div class="meta">' + esc(v.nota || "sin nota") + '</div>' +
      '<div class="meta">' + esc((v.ts || "").replace("T", " ").slice(0, 16)) +
      '  ·  ' + v.n_nodos + ' nodos</div></div>';
    d.onclick = () => { activa = v; pintarTimeline(); pintarLienzo(v); $("#ficha").hidden = true; };
    tl.appendChild(d);
  });
}

const rotas = D.versiones.filter(v => v.error);
if(rotas.length){
  const a = $("#aviso"); a.hidden = false;
  a.textContent = "No se pudieron leer " + rotas.length + " versiones: " +
    rotas.map(v => "v" + v.v + " (" + v.error + ")").join(", ");
}
$("#pie").textContent = D.versiones.length + " versiones  ·  pulsa una version para verla, " +
  "y un nodo para su ficha  ·  editar: /flujoteca editar " + D.nombre;
pintarTimeline(); pintarLienzo(activa);
</script></body></html>"""


def render_html(datos: dict, title: str = "") -> str:
    crudo = json.dumps(datos, ensure_ascii=False).replace("</", "<\\/")
    titulo = title or f"Cognia · Flujo · {datos.get('nombre', '')}"
    return _HTML.replace("__TITLE__", titulo).replace("__DATA__", crudo)


def export(nombre: str, path: str | None = None, *,
           open_browser: bool = True) -> str:
    datos = build_datos(nombre)
    from cognia.agent import flujoteca as _ft
    destino = (Path(path) if path else
               Path.home() / ".cognia" / f"flujo_{_ft.slugificar(nombre)}.html")
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(render_html(datos), encoding="utf-8")
    if open_browser:
        import webbrowser
        webbrowser.open(destino.as_uri())
    return str(destino)
