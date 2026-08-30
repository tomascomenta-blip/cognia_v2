# -*- coding: utf-8 -*-
"""
cognia/memory/memorias_view.py
==============================
El dashboard MEMORIAS: la vista navegable de todo lo que Cognia produjo.

Sigue el patron de vista HTML de la casa (cognia/knowledge/graph_view.py y
cognia/agent/flow_view.py): un template con placeholders __X__, sustitucion
por .replace(), datos embebidos como JSON, CERO CDN y cero dependencias. Se
escribe a ~/.cognia/memorias.html y se abre con webbrowser. Funciona sin red
y sin servidor, que es lo que hace que se pueda abrir dentro de un avion o
con el backend caido.

QUE PUEDE Y QUE NO PUEDE ESTA PAGINA (limitacion declarada, no escondida)
------------------------------------------------------------------------
Un HTML estatico servido por file:// NO puede escribir en disco: no hay
manera de que un boton de esta pagina borre un fichero o renombre una skill,
por mucho que el boton exista. Inventar botones que no hacen nada seria peor
producto que no ponerlos.

Asi que el reparto es explicito y se DICE en la propia pagina:
  - Aqui: buscar, filtrar, ordenar, categorizar, ver el detalle, las fechas,
    el tamano, las relaciones y el estado. O sea, ENTENDER que hay.
  - En el CLI (`/memorias ...`): abrir, editar, renombrar, duplicar y borrar.
    O sea, CAMBIAR lo que hay.
El detalle de cada artefacto trae el comando exacto con un boton de copiar,
de modo que la distancia entre "lo veo" y "lo cambio" es un pegado.

MODO OSCURO Y CLARO
-------------------
Los dos son reales, no un filtro de colores. Cada color es un token en
:root y el tema claro REDEFINE los tokens (no los invierte), asi que los
contrastes se eligieron uno a uno en los dos modos. Arranca respetando
`prefers-color-scheme` del sistema y recuerda la eleccion del usuario en
localStorage. El patron viene de cognia/remoto/static/index.html, que es el
unico sitio del repo donde el conmutador ya estaba resuelto.
"""
from __future__ import annotations

import json
from pathlib import Path

__all__ = ["build_memorias_data", "render_html", "export"]


# Etiqueta legible y glifo por familia. El dueno no tiene por que saber que
# es una "corrida" del motor de workflows: la UI le dice "Ejecuciones".
_FAMILIAS_UI = {
    "programa":   ("Programas",   "Codigo que Cognia escribio y guardo"),
    "flujo":      ("Recetas",     "Flujos aprendidos y reutilizables"),
    "corrida":    ("Ejecuciones", "Corridas del motor de workflows"),
    "skill":      ("Skills",      "Instrucciones que el agente sabe seguir"),
    "documento":  ("Documentos",  "HTML, markdown y exports generados"),
    "sesion":     ("Sesiones",    "Conversaciones guardadas"),
    "memoria":    ("Memorias",    "Episodios y conceptos aprendidos"),
    "checkpoint": ("Puntos de retorno", "Estados a los que se puede volver"),
    "papelera":   ("Papelera",    "Borrados recuperables"),
    "nota":       ("Notas",       "Apuntes sueltos"),
}

# El comando del CLI que ACTUA sobre cada familia.
#
# REGLA DURA: aqui solo entra un comando que EXISTE y acepta ese argumento.
# Un dashboard que sugiere `/workflow ver <id>` cuando /workflow es "repartir
# subtareas en paralelo" no ayuda: manda al dueno a teclear algo que falla y
# le hace dudar de todo lo demas que ve en la pantalla. La primera version de
# esta tabla tenia CUATRO comandos inventados (/programs borrar, /receta ver,
# /receta borrar, /workflow ver); los caza `tests/test_memorias_view.py::
# test_todas_las_acciones_existen_en_el_cli`, que compara contra el dispatch
# REAL de cli.py. Si una familia no tiene comando, no se le inventa uno: se
# queda sin acciones y la ficha lo dice.
#
# Punto de extension: anadir una familia es anadir su fila, y el test obliga
# a que el comando exista antes de que llegue a la pantalla.
_ACCIONES = {
    # /programs ver <id>            el codigo, en el terminal
    # /biblioteca abrir <id>        EL PRODUCTO (la web en el navegador, el
    #                               .py con la app del sistema, la carpeta si
    #                               no hay entrypoint) -- _slash_biblioteca
    "programa":  {"ver": "/programs ver {id}",
                  "abrir": "/biblioteca abrir {id}"},
    # /receta correr|examinar <n>   (subcomandos: lista aprender examinar correr cuarentena)
    "flujo":     {"correr": "/receta correr {id}",
                  "examinar": "/receta examinar {id}"},
    # sin comando propio: el journal de una corrida se lee con /ver
    "corrida":   {"ver el journal": "/ver {ruta}/journal.jsonl"},
    "skill":     {"aplicar": "/skill {id}", "editar": "/editar {ruta}"},
    "documento": {"ver": "/ver {ruta}", "editar": "/editar {ruta}"},
    "sesion":    {"ver": "/sesion-ver {id}"},
    "memoria":   {"buscar": "/buscar-memoria {titulo}"},
    # /deshacer [n | lista | diff | hasta <n>] -> el n del checkpoint
    "checkpoint": {"deshacer": "/deshacer {id}"},
    # /deshacer-borrado [lista | <lote>]
    "papelera":  {"restaurar": "/deshacer-borrado {id}"},
}


def build_memorias_data(cat=None, *, familias=None) -> dict:
    """El dict que se embebe en la pagina. `cat` es un catalogo.Catalogo ya
    construido (para no leerlo dos veces cuando el CLI ya lo tiene)."""
    from cognia.memory import catalogo as _cat
    if cat is None:
        cat = _cat.construir(familias=familias)
    filas = [f.a_dict() for f in cat.filas]
    # La accion viaja YA resuelta: que el JS componga comandos con plantillas
    # invita a que el dia que cambie un comando la pagina mienta en silencio.
    for f in filas:
        acciones = []
        for etiqueta, plantilla in (_ACCIONES.get(f["familia"]) or {}).items():
            try:
                cmd = plantilla.format(id=f["id"], ruta=f["ruta"],
                                       titulo=f["titulo"])
            except Exception:
                continue
            acciones.append({"etiqueta": etiqueta, "cmd": cmd})
        f["acciones"] = acciones
    conteo = cat.conteo()
    familias_ui = []
    for fam, (etiqueta, ayuda) in _FAMILIAS_UI.items():
        if conteo.get(fam):
            familias_ui.append({"clave": fam, "etiqueta": etiqueta,
                                "ayuda": ayuda, "n": conteo[fam]})
    return {
        "filas": filas,
        "familias": familias_ui,
        "total": len(filas),
        "avisos": list(cat.avisos),
        "familias_fallidas": list(cat.familias_fallidas),
        "ms": cat.ms,
    }


_HTML = r"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{
  --fondo:#0d1117; --panel:#161b22; --panel2:#1c2128; --borde:#30363d;
  --texto:#e6edf3; --texto2:#8b949e; --acento:#58a6ff; --acento2:#1f6feb;
  --ok:#3fb950; --alerta:#d29922; --error:#f85149;
  --sombra:0 1px 3px rgba(0,0,0,.4);
}
:root[data-tema="claro"]{
  --fondo:#ffffff; --panel:#f6f8fa; --panel2:#eaeef2; --borde:#d0d7de;
  --texto:#1f2328; --texto2:#59636e; --acento:#0969da; --acento2:#0550ae;
  --ok:#1a7f37; --alerta:#9a6700; --error:#cf222e;
  --sombra:0 1px 3px rgba(31,35,40,.12);
}
*{box-sizing:border-box}
html,body{margin:0;height:100%}
body{
  background:var(--fondo); color:var(--texto);
  font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  display:flex; flex-direction:column;
}
header{
  display:flex; align-items:center; gap:14px; padding:14px 20px;
  border-bottom:1px solid var(--borde); background:var(--panel);
  position:sticky; top:0; z-index:10; flex-wrap:wrap;
}
h1{font-size:16px;font-weight:600;margin:0;letter-spacing:-.01em}
h1 span{color:var(--texto2);font-weight:400;margin-left:8px;font-size:13px}
#buscar{
  flex:1; min-width:200px; max-width:460px; padding:7px 12px;
  background:var(--fondo); color:var(--texto);
  border:1px solid var(--borde); border-radius:6px; font-size:14px;
}
#buscar:focus{outline:none;border-color:var(--acento);box-shadow:0 0 0 3px color-mix(in srgb,var(--acento) 25%,transparent)}
select,button.btn{
  padding:7px 12px; background:var(--panel2); color:var(--texto);
  border:1px solid var(--borde); border-radius:6px; font-size:13px; cursor:pointer;
}
button.btn:hover,select:hover{border-color:var(--acento)}
#tema{width:38px;text-align:center;font-size:15px}
main{flex:1;display:flex;min-height:0}
nav{
  width:210px; flex:0 0 210px; border-right:1px solid var(--borde);
  padding:14px 10px; overflow-y:auto; background:var(--panel);
}
nav h2{font-size:11px;text-transform:uppercase;letter-spacing:.06em;
  color:var(--texto2);margin:0 0 8px 8px;font-weight:600}
.fam{
  display:flex;justify-content:space-between;align-items:center;gap:6px;
  padding:6px 10px;border-radius:6px;cursor:pointer;margin-bottom:2px;
  border:1px solid transparent;
}
.fam:hover{background:var(--panel2)}
.fam[aria-pressed="true"]{background:var(--panel2);border-color:var(--acento);color:var(--acento)}
.fam .n{color:var(--texto2);font-size:12px;font-variant-numeric:tabular-nums}
#lista{flex:1;overflow-y:auto;padding:10px 14px}
/* GRID y no flex: con flex cada fila repartia el ancho segun SU propio
   contenido, asi que las columnas no se alineaban entre filas y el titulo
   —lo unico que el dueno lee para reconocer algo— se colapsaba a "se...".
   Con grid las cuatro columnas mandan igual en todas las filas, y el
   titulo tiene un minimo que ninguna descripcion larga le puede quitar. */
.item{
  padding:9px 12px;border:1px solid var(--borde);border-radius:8px;
  margin-bottom:6px;cursor:pointer;background:var(--panel);
  display:grid;gap:12px;align-items:baseline;
  grid-template-columns:104px minmax(170px,1.5fr) minmax(0,2fr) 118px;
}
.item:hover{border-color:var(--acento)}
.item[aria-selected="true"]{border-color:var(--acento);box-shadow:var(--sombra)}
.item>*{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.item .tit{font-weight:500}
.item .res{color:var(--texto2);font-size:12.5px}
.item .badge{justify-self:start}
.item .fecha{text-align:right}
@media(max-width:1150px){
  .item{grid-template-columns:104px minmax(150px,1fr) 118px}
  .item .res{display:none}   /* antes de apretar el titulo, se va la descripcion */
}
.badge{
  font-size:11px;padding:1px 7px;border-radius:20px;border:1px solid var(--borde);
  color:var(--texto2);white-space:nowrap;
}
.fecha{color:var(--texto2);font-size:12px;font-variant-numeric:tabular-nums;white-space:nowrap}
aside{
  width:380px;flex:0 0 380px;border-left:1px solid var(--borde);
  padding:16px 18px;overflow-y:auto;background:var(--panel);
}
aside.vacio{display:flex;align-items:center;justify-content:center;color:var(--texto2);text-align:center}
aside h3{margin:0 0 4px;font-size:15px;word-break:break-word}
.campo{margin:12px 0}
.campo .k{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--texto2);margin-bottom:3px}
.campo .v{word-break:break-word;font-size:13px}
code{
  background:var(--panel2);border:1px solid var(--borde);border-radius:5px;
  padding:2px 6px;font-family:ui-monospace,"Cascadia Code",Consolas,monospace;font-size:12.5px;
}
.accion{display:flex;gap:8px;align-items:center;margin-bottom:6px}
.accion code{flex:1;overflow-x:auto;white-space:nowrap}
.copiar{padding:3px 9px;font-size:12px;border-radius:5px;border:1px solid var(--borde);
  background:var(--panel2);color:var(--texto);cursor:pointer}
.copiar:hover{border-color:var(--acento);color:var(--acento)}
.tags{display:flex;flex-wrap:wrap;gap:4px}
#avisos{
  padding:8px 20px;background:color-mix(in srgb,var(--alerta) 14%,var(--fondo));
  border-bottom:1px solid var(--borde);color:var(--texto);font-size:13px;
}
#vacio{padding:40px;text-align:center;color:var(--texto2)}
footer{padding:7px 20px;border-top:1px solid var(--borde);color:var(--texto2);
  font-size:12px;background:var(--panel);display:flex;gap:16px;flex-wrap:wrap}
@media(max-width:900px){
  main{flex-direction:column} nav{width:auto;flex:0 0 auto;border-right:none;
  border-bottom:1px solid var(--borde);display:flex;flex-wrap:wrap;gap:4px}
  nav h2{display:none} aside{width:auto;flex:0 0 auto;border-left:none;
  border-top:1px solid var(--borde);max-height:44vh}
}
</style></head><body>
<header>
  <h1>Memorias <span id="sub"></span></h1>
  <input id="buscar" type="search" placeholder="Buscar por nombre, contenido o etiqueta..." autocomplete="off">
  <select id="orden">
    <option value="reciente">Mas reciente</option>
    <option value="antiguo">Mas antiguo</option>
    <option value="nombre">Nombre A-Z</option>
    <option value="tamano">Mas grande</option>
    <option value="familia">Por categoria</option>
  </select>
  <button class="btn" id="tema" title="Cambiar entre claro y oscuro">&#9788;</button>
</header>
<div id="avisos" hidden></div>
<main>
  <nav id="familias"><h2>Categorias</h2></nav>
  <div id="lista"></div>
  <aside id="detalle" class="vacio"><div>Elegi algo de la lista<br>para ver su ficha</div></aside>
</main>
<footer>
  <span id="pie"></span>
  <span>Para abrir, editar o borrar: <code>/memorias</code> en el CLI</span>
</footer>
<script>
const DATOS = __DATA__;
const $ = s => document.querySelector(s);

/* ---- tema: el sistema manda al principio, el usuario manda despues ---- */
(function(){
  const guardado = (()=>{ try{ return localStorage.getItem("cognia_memorias_tema"); }catch(e){ return null; } })();
  const oscuroSistema = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  aplicarTema(guardado || (oscuroSistema ? "oscuro" : "claro"));
})();
function aplicarTema(t){
  document.documentElement.setAttribute("data-tema", t);
  $("#tema").innerHTML = t === "claro" ? "&#9789;" : "&#9788;";
  $("#tema").title = t === "claro" ? "Cambiar a oscuro" : "Cambiar a claro";
}
$("#tema").onclick = () => {
  const nuevo = document.documentElement.getAttribute("data-tema") === "claro" ? "oscuro" : "claro";
  aplicarTema(nuevo);
  try{ localStorage.setItem("cognia_memorias_tema", nuevo); }catch(e){}
};

/* ---- estado ---- */
let familiaActiva = null, seleccionada = null;
const ETIQ = {};
DATOS.familias.forEach(f => ETIQ[f.clave] = f.etiqueta);

/* ---- barra lateral de categorias ---- */
const nav = $("#familias");
function pintarFamilias(){
  nav.querySelectorAll(".fam").forEach(n => n.remove());
  const todas = document.createElement("div");
  todas.className = "fam"; todas.setAttribute("aria-pressed", familiaActiva === null);
  todas.innerHTML = '<span>Todo</span><span class="n">' + DATOS.total + '</span>';
  todas.onclick = () => { familiaActiva = null; pintarFamilias(); pintar(); };
  nav.appendChild(todas);
  DATOS.familias.forEach(f => {
    const d = document.createElement("div");
    d.className = "fam"; d.title = f.ayuda;
    d.setAttribute("aria-pressed", familiaActiva === f.clave);
    d.innerHTML = '<span>' + f.etiqueta + '</span><span class="n">' + f.n + '</span>';
    d.onclick = () => { familiaActiva = (familiaActiva === f.clave ? null : f.clave); pintarFamilias(); pintar(); };
    nav.appendChild(d);
  });
}

/* ---- filtro + orden ---- */
function fecha(f){ return f.modificado || f.creado || ""; }
function filtrar(){
  const q = $("#buscar").value.trim().toLowerCase();
  const palabras = q ? q.split(/\s+/) : [];
  let out = DATOS.filas.filter(f => !familiaActiva || f.familia === familiaActiva);
  if(palabras.length){
    out = out.filter(f => {
      const heno = (f.titulo + " " + f.resumen + " " + (f.etiquetas||[]).join(" ")
                    + " " + f.familia + " " + (ETIQ[f.familia]||"") + " " + f.ruta).toLowerCase();
      return palabras.every(p => heno.includes(p));
    });
  }
  const o = $("#orden").value;
  out.sort((a,b) => {
    if(o === "nombre")  return a.titulo.localeCompare(b.titulo, "es");
    if(o === "tamano")  return (b.bytes||0) - (a.bytes||0);
    if(o === "antiguo") return (fecha(a)||"9").localeCompare(fecha(b)||"9");
    if(o === "familia") return a.familia.localeCompare(b.familia) || a.titulo.localeCompare(b.titulo,"es");
    return (fecha(b)||"").localeCompare(fecha(a)||"");
  });
  return out;
}

function humanBytes(n){
  if(!n) return "";
  if(n < 1024) return n + " B";
  if(n < 1048576) return (n/1024).toFixed(1) + " KB";
  return (n/1048576).toFixed(1) + " MB";
}
function humanFecha(s){ return s ? s.replace("T", " ").slice(0,16) : "sin fecha"; }

/* ---- lista ---- */
function pintar(){
  const filas = filtrar();
  const cont = $("#lista");
  cont.innerHTML = "";
  $("#sub").textContent = filas.length === DATOS.total
      ? DATOS.total + " artefactos"
      : filas.length + " de " + DATOS.total;
  if(!filas.length){
    cont.innerHTML = '<div id="vacio">Nada coincide con lo que buscas.</div>';
    return;
  }
  const frag = document.createDocumentFragment();
  filas.forEach(f => {
    const d = document.createElement("div");
    d.className = "item";
    d.setAttribute("aria-selected", seleccionada === f);
    const tit = document.createElement("span"); tit.className = "tit"; tit.textContent = f.titulo;
    const bad = document.createElement("span"); bad.className = "badge";
    bad.textContent = ETIQ[f.familia] || f.familia;
    const res = document.createElement("span"); res.className = "res"; res.textContent = f.resumen || "";
    const fec = document.createElement("span"); fec.className = "fecha"; fec.textContent = humanFecha(fecha(f));
    d.append(bad, tit, res, fec);
    d.onclick = () => { seleccionada = f; pintar(); detalle(f); };
    frag.appendChild(d);
  });
  cont.appendChild(frag);
}

/* ---- ficha ---- */
function campo(k, v){
  if(!v) return "";
  const d = document.createElement("div"); d.className = "campo";
  const kk = document.createElement("div"); kk.className = "k"; kk.textContent = k;
  const vv = document.createElement("div"); vv.className = "v"; vv.textContent = v;
  d.append(kk, vv);
  return d;
}
function detalle(f){
  const a = $("#detalle");
  a.className = ""; a.innerHTML = "";
  const h = document.createElement("h3"); h.textContent = f.titulo;
  const b = document.createElement("span"); b.className = "badge";
  b.textContent = ETIQ[f.familia] || f.familia;
  a.append(h, b);
  if(f.resumen) a.append(campo("Que es", f.resumen));
  if(f.estado)  a.append(campo("Estado", f.estado));
  a.append(campo("Creado", humanFecha(f.creado) !== "sin fecha" ? humanFecha(f.creado) : ""));
  a.append(campo("Modificado", humanFecha(f.modificado) !== "sin fecha" ? humanFecha(f.modificado) : ""));
  if(f.bytes) a.append(campo("Tamano", humanBytes(f.bytes)));
  if(f.ruta)  a.append(campo("Donde vive", f.ruta));
  if((f.etiquetas||[]).length){
    const d = document.createElement("div"); d.className = "campo";
    d.innerHTML = '<div class="k">Etiquetas</div>';
    const t = document.createElement("div"); t.className = "tags";
    f.etiquetas.forEach(e => { const s = document.createElement("span");
      s.className = "badge"; s.textContent = e; t.appendChild(s); });
    d.appendChild(t); a.appendChild(d);
  }
  if((f.relaciones||[]).length){
    a.append(campo("Relacionado con",
      f.relaciones.map(r => (ETIQ[r.familia]||r.familia) + " " + r.id).join(", ")));
  }
  if((f.acciones||[]).length){
    const d = document.createElement("div"); d.className = "campo";
    d.innerHTML = '<div class="k">Que puedo hacer con esto (pegalo en el CLI)</div>';
    f.acciones.forEach(ac => {
      const fila = document.createElement("div"); fila.className = "accion";
      const c = document.createElement("code"); c.textContent = ac.cmd;
      const btn = document.createElement("button"); btn.className = "copiar"; btn.textContent = "copiar";
      btn.onclick = ev => {
        ev.stopPropagation();
        const ok = () => { btn.textContent = "copiado"; setTimeout(()=>btn.textContent="copiar", 1200); };
        /* file:// sin permiso de portapapeles: se cae a seleccionar el texto,
           que sigue permitiendo Ctrl-C. Un boton que falla en silencio seria
           peor que no tenerlo. */
        if(navigator.clipboard && navigator.clipboard.writeText){
          navigator.clipboard.writeText(ac.cmd).then(ok).catch(() => { seleccionar(c); btn.textContent="selecciona y Ctrl-C"; });
        } else { seleccionar(c); btn.textContent = "selecciona y Ctrl-C"; }
      };
      fila.append(c, btn); d.appendChild(fila);
    });
    a.appendChild(d);
  }
  a.append(campo("De donde sale este dato", f.fuente));
}
function seleccionar(nodo){
  const r = document.createRange(); r.selectNodeContents(nodo);
  const s = window.getSelection(); s.removeAllRanges(); s.addRange(r);
}

/* ---- avisos: una familia rota NO puede parecer una familia vacia ---- */
if((DATOS.avisos||[]).length || (DATOS.familias_fallidas||[]).length){
  const av = $("#avisos"); av.hidden = false;
  const partes = [];
  if((DATOS.familias_fallidas||[]).length)
    partes.push("No pude leer: " + DATOS.familias_fallidas.join(", "));
  /* Los avisos se AGRUPAN por su forma: dos conceptos con el mismo problema
     de datos son un aviso con un contador, no dos parrafos que tapan la
     mitad de la pantalla. Se sigue pudiendo ver el detalle entero. */
  const porTipo = {};
  (DATOS.avisos||[]).forEach(a => {
    const clave = a.replace(/'[^']*'/g, "'...'");
    (porTipo[clave] = porTipo[clave] || []).push(a);
  });
  Object.keys(porTipo).forEach(k => {
    partes.push(porTipo[k].length > 1 ? k + "  (x" + porTipo[k].length + ")" : porTipo[k][0]);
  });
  const resumen = document.createElement("span");
  resumen.textContent = partes.join("  ·  ");
  av.appendChild(resumen);
  if((DATOS.avisos||[]).length > 1){
    const b = document.createElement("button");
    b.className = "copiar"; b.style.marginLeft = "10px"; b.textContent = "ver los " + DATOS.avisos.length;
    b.onclick = () => {
      const d = document.createElement("ul");
      d.style.margin = "8px 0 0"; d.style.paddingLeft = "20px";
      DATOS.avisos.forEach(a => { const li = document.createElement("li"); li.textContent = a; d.appendChild(li); });
      av.appendChild(d); b.remove();
    };
    av.appendChild(b);
  }
}

$("#buscar").oninput = pintar;
$("#orden").onchange = pintar;
document.addEventListener("keydown", e => {
  if(e.key === "/" && document.activeElement !== $("#buscar")){ e.preventDefault(); $("#buscar").focus(); }
  if(e.key === "Escape"){ $("#buscar").value = ""; $("#buscar").blur(); pintar(); }
});
$("#pie").textContent = DATOS.total + " artefactos leidos en " + DATOS.ms + " ms  ·  tecla / para buscar";
pintarFamilias(); pintar();
</script></body></html>"""


def render_html(data: dict, title: str = "Cognia · Memorias") -> str:
    """Sustituye los placeholders. El JSON va con `</` escapado: un resumen de
    artefacto que contenga la cadena de cierre de script romperia la pagina
    entera, y este catalogo lee texto que Cognia misma genero (HTML incluido).
    """
    crudo = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return (_HTML
            .replace("__TITLE__", title)
            .replace("__DATA__", crudo))


def export(cat=None, path: str | None = None, *, familias=None,
           open_browser: bool = True) -> str:
    """Escribe el dashboard y (por defecto) lo abre. Devuelve la ruta."""
    data = build_memorias_data(cat, familias=familias)
    titulo = f"Cognia · Memorias ({data['total']} artefactos)"
    out = Path(path) if path else (Path.home() / ".cognia" / "memorias.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(data, titulo), encoding="utf-8")
    if open_browser:
        import webbrowser
        webbrowser.open(out.as_uri())
    return str(out)


if __name__ == "__main__":
    import sys
    ruta = export(open_browser="--no-open" not in sys.argv)
    print(f"memorias -> {ruta}")
