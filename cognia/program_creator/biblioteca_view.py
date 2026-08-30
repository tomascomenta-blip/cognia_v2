# -*- coding: utf-8 -*-
"""
cognia/program_creator/biblioteca_view.py
=========================================
La biblioteca de programas, VISTA: una pagina autocontenida con todos los
productos que hay en disco, y la resolucion de referencias para abrirlos.

POR QUE EXISTE (2026-08-29)
---------------------------
`/biblioteca` listaba 10 lineas de texto y paraba. El dueno tenia mas de un
centenar de productos en disco y ninguna forma de verlos de un vistazo ni de
abrir uno sin recordar su id de 32 hex. Este modulo hace lo que
`memorias_view` hace con las memorias: construye un dict con todo, lo pinta
en un HTML sin dependencias y lo deja en `~/.cognia/biblioteca.html`.

LA FUENTE DE DATOS ES EL DISCO, NO EL INDICE
--------------------------------------------
`index.json` tiene entradas fantasma (apuntan a carpetas que ya no estan) y
hay carpetas huerfanas que el indice no menciona. Medido en esta maquina el
2026-08-29: 137 carpetas en disco, 97 entradas en el indice, 81 que cruzan.
Por eso la fuente es `autoprueba.descubrir_productos()` -que recorre el
disco, resuelve el entrypoint real y ya tiene 30+ tests en
`tests/test_autoprueba.py`- cruzada por id con `storage.list_programs()`
para el titulo, la categoria y el puntaje. `en_index` y `fantasmas` dejan
ver la discrepancia en vez de taparla.

REGLA DE HONESTIDAD DE LA FICHA
-------------------------------
Una pagina `file://` NO puede lanzar un `.py` ni abrir otro `file://` desde
un click: los navegadores modernos lo bloquean sin decir nada. Fingir un
boton "Abrir" que no hace nada es peor que no ponerlo. Cada tarjeta muestra
el comando COPIABLE `/biblioteca abrir <id>`, ya resuelto en Python (mismo
patron que `_ACCIONES` en `memorias_view`: el JS nunca compone comandos).

Y el puntaje se muestra tal como lo da `storage.formatear_puntaje()`, que
solo devuelve un numero si algo se EJECUTO. Aqui no se inventa ninguna nota:
un producto sin sello dice "sin verificar" en la tarjeta, no un 0 ni un
guion que se pueda leer como "malo".

QUIEN ABRE QUE
--------------
`abrir_producto()` vive aqui y no en `cli.py` por dos motivos: se puede
probar sin arrancar el REPL, y la politica de "que ventana se abre" queda en
UN sitio. El reparto por lenguaje:
  - html  -> `webbrowser.open(Path(entrypoint).as_uri())`
  - python-> la app del SO (`os.startfile` en win32, `open`/`xdg-open` en el
             resto), copiado de la tool `abrir` de `cognia/agent/tools.py`.
             `webbrowser.open` sobre un `.py` no sirve: lo descarga.
  - vacio -> la carpeta, que es lo unico que hay.
Bajo `COGNIA_REMOTO` no se abre NADA: una ventana en la maquina servidora no
le sirve a quien esta al otro lado. Se devuelve la ruta y el llamador la
imprime.

REGLAS DE COMPOSICION DEL HTML (no negociables)
-----------------------------------------------
  - Cero CDN: ni `<script src=...>` ni `<link href=...>` a la red.
    Autocontenido: se abre sin red y con el backend caido.
  - El HTML se compone con `.replace()` sobre placeholders, NUNCA con
    `str.format`: las llaves de las expresiones CSS/JS lo revientan (bug
    historico documentado en `flow_view.py`).
  - Todo `json.dumps` que entra en un `<script>` lleva
    `.replace("<", "\\u003c")`: TODOS los "<", no solo el "</". Escapar solo
    el cierre NO basta -- "<!--" y "<script" meten al tokenizador de HTML en
    estado *script data escaped*, y en ese estado el `</script>` de la
    plantilla ya no cierra el bloque. Confirmado en Chromium (revision
    adversarial 2026-08-29): con una `description` que lleve "<!--<script>",
    el `</script></body></html>` del final se traga dentro del script, el JS
    entero muere por error de sintaxis y la biblioteca sale con la barra de
    filtros pintada y CERO tarjetas -- o sea, PARECE VACIA en vez de rota,
    que es el peor de los dos fallos. Y esta biblioteca guarda HTML generado
    por Cognia (muchos productos SON paginas HTML): no es un caso teorico.
    Escapar todos los "<" es seguro sobre JSON: fuera de las cadenas no hay
    ni un "<", y dentro `\\u003c` es la misma cadena para `JSON.parse` y
    para el parser de literales de JS.

CONTRATO (FASE 0 y PEDIDO 2 del plan)
-------------------------------------
    build_biblioteca_data(base=None) -> dict
    render_html(data: dict, title: str = "") -> str
    export(path=None, *, open_browser: bool = True, base=None) -> str
    resolver(ref: str, *, base=None) -> dict | None

Extras (aditivos, no rompen el contrato):
    resolver_detalle(ref, *, base=None) -> dict   # trae el motivo del fallo
    abrir_producto(item, *, open_browser=True) -> dict
    HTML: str                                      # la plantilla

Forma del dict de `build_biblioteca_data()`:

    {"total": int, "fantasmas": int, "lenguajes": [...], "categorias": [...],
     "items": [{"n", "id", "title", "description", "lenguaje",
                "entrypoint", "ruta_corta", "directorio", "puntaje",
                "puntaje_real", "categoria", "en_index", "creado",
                "modificado", "cmd_abrir", "cmd_ver"}, ...]}

El campo `n` es el indice 1-based y viaja EN el dato: la pagina se puede
reordenar por puntaje o por fecha y el numero de la tarjeta sigue siendo el
mismo que acepta `/biblioteca abrir <n>`. Si el numero dependiera de la
posicion en pantalla, ordenar cambiaria en silencio lo que hay que teclear.

Bloque `__main__` con `--no-open`.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from html import escape as _esc
from pathlib import Path

__all__ = [
    "build_biblioteca_data", "render_html", "export", "resolver",
    "resolver_detalle", "abrir_producto", "HTML",
]

# Como se nombra cada lenguaje en la pantalla. "vacio" no es un error: es una
# carpeta con assets, imagenes o notas y ningun ejecutable, y decirlo es mas
# util que esconderla.
_LENGUAJES_UI = {
    "python": "Python",
    "html":   "Web (HTML)",
    "vacio":  "Sin codigo",
}

# Longitud minima de un prefijo de id. Menos de 4 caracteres casa con medio
# catalogo y "abrir a" abriria cualquier cosa: mejor decir que es ambiguo.
_MIN_PREFIJO = 4


# ── Datos ──────────────────────────────────────────────────────────────────────

def _iso(ts) -> str:
    try:
        return datetime.fromtimestamp(float(ts)).isoformat(timespec="seconds")
    except Exception:
        return ""


def _ruta_corta(ruta: str) -> str:
    """`carpeta/fichero`: lo unico que distingue una ruta de otra aqui.

    Las 137 rutas de la biblioteca comparten los mismos ~70 primeros
    caracteres; truncarlas por el final deja 137 tarjetas identicas. La ruta
    absoluta sigue viajando en el dato (y en el tooltip de la pagina).
    """
    if not ruta:
        return ""
    p = Path(ruta)
    padre = p.parent.name
    return (padre + "/" + p.name) if padre else p.name


def _mtime(directorio: str) -> str:
    try:
        return _iso(Path(directorio).stat().st_mtime)
    except Exception:
        return ""


def build_biblioteca_data(base=None) -> dict:
    """Cruza el disco con el indice y devuelve el dict que pinta la pagina.

    Fuente principal: `autoprueba.descubrir_productos()`. Enriquecido por id
    con `storage.list_programs()`. Nunca explota si la biblioteca esta vacia
    o si una carpeta esta corrupta: esa entrada se degrada, no tumba el resto.

    `base` es el directorio `generated_programs` (por defecto el de la casa);
    existe para los tests, que jamas deben tocar la biblioteca real.
    """
    from cognia import autoprueba as _ap
    from cognia.program_creator import storage as _st

    try:
        productos = _ap.descubrir_productos(base)
    except Exception:
        productos = []

    metas = {}
    try:
        for prog in _st.list_programs(Path(base) if base else None):
            metas[prog.id] = prog
    except Exception:
        metas = {}

    items = []
    vistos = set()
    for i, prod in enumerate(productos, 1):
        pid = str(prod.get("id") or "")
        meta = metas.get(pid)
        vistos.add(pid)
        directorio = prod.get("directorio") or ""
        try:
            puntaje = _st.formatear_puntaje(meta) if meta is not None else "sin verificar"
        except Exception:
            puntaje = "sin verificar"
        titulo = (getattr(meta, "title", "") or prod.get("title") or pid or "sin titulo")
        descripcion = (prod.get("description")
                       or getattr(meta, "description", "") or "")
        items.append({
            "n":            i,
            "id":           pid,
            "title":        titulo,
            "description":  descripcion,
            "lenguaje":     prod.get("lenguaje") or "vacio",
            "entrypoint":   prod.get("entrypoint") or "",
            "directorio":   directorio,
            "puntaje":      puntaje,
            # El numero solo viaja si salio de EJECUTAR: es lo unico que se
            # puede ordenar sin mentir. El resto ordena al final.
            "puntaje_real": getattr(meta, "puntaje_real", None),
            "categoria":    (getattr(meta, "category", "") or "sin categoria"),
            "en_index":     bool(prod.get("en_index")),
            "creado":       (getattr(meta, "created_at", "") or ""),
            "modificado":   _mtime(directorio),
            "ruta_corta":   _ruta_corta(prod.get("entrypoint") or directorio),
            "cmd_abrir":    "/biblioteca abrir " + pid,
            "cmd_ver":      "/biblioteca ver " + pid,
        })

    # Entradas del indice cuya carpeta ya no existe. No se pintan como
    # productos (no hay nada que abrir), pero se cuentan: una biblioteca que
    # dice 137 cuando el indice dice 97 tiene que explicar la diferencia.
    fantasmas = sum(1 for pid in metas if pid not in vistos)

    lenguajes = sorted({it["lenguaje"] for it in items})
    categorias = sorted({it["categoria"] for it in items})
    return {
        "total":      len(items),
        "fantasmas":  fantasmas,
        "en_index":   sum(1 for it in items if it["en_index"]),
        "lenguajes":  [{"clave": l, "etiqueta": _LENGUAJES_UI.get(l, l),
                        "n": sum(1 for it in items if it["lenguaje"] == l)}
                       for l in lenguajes],
        "categorias": categorias,
        "items":      items,
    }


# ── Resolucion de referencias ──────────────────────────────────────────────────

def resolver_detalle(ref: str, *, base=None) -> dict:
    """Como `resolver`, pero contando POR QUE cuando no encuentra nada.

    Devuelve `{"item": dict|None, "motivo": str, "candidatos": [ids]}`. Un
    prefijo ambiguo no puede devolver "no existe": el dueno teclearia lo
    mismo otra vez. Devuelve la lista de candidatos para que el CLI la pinte.
    """
    ref = (ref or "").strip()
    vacio = {"item": None, "motivo": "", "candidatos": []}
    if not ref:
        return dict(vacio, motivo="hace falta un id o un numero")

    data = build_biblioteca_data(base)
    items = data["items"]
    if not items:
        return dict(vacio, motivo="la biblioteca esta vacia")

    # 1. Id exacto (o nombre de carpeta exacto: para los huerfanos son lo mismo).
    bajo = ref.casefold()
    for it in items:
        if it["id"].casefold() == bajo:
            return {"item": it, "motivo": "", "candidatos": []}

    # 2. Indice 1..N, el MISMO que pinta la pagina.
    if ref.isdigit():
        n = int(ref)
        if 1 <= n <= len(items):
            return {"item": items[n - 1], "motivo": "", "candidatos": []}
        return dict(vacio, motivo=f"el numero {n} esta fuera de rango (hay "
                                  f"{len(items)} productos)")

    # 3. Prefijo de id.
    if len(ref) < _MIN_PREFIJO:
        return dict(vacio, motivo=f"'{ref}' es demasiado corto para buscar por "
                                  f"prefijo (minimo {_MIN_PREFIJO} caracteres)")
    casan = [it for it in items if it["id"].casefold().startswith(bajo)]
    if len(casan) == 1:
        return {"item": casan[0], "motivo": "", "candidatos": []}
    if len(casan) > 1:
        return {"item": None,
                "motivo": f"'{ref}' es ambiguo: casa con {len(casan)} productos",
                "candidatos": [it["id"] for it in casan[:8]]}
    return dict(vacio, motivo=f"no hay ningun producto con id o prefijo '{ref}'")


def resolver(ref: str, *, base=None) -> dict | None:
    """Encuentra un producto por id exacto, prefijo de id o indice 1..N.

    Devuelve el item de `build_biblioteca_data()["items"]` o None. El indice
    es el de la pagina HTML, no el del resumen recortado a 10 lineas de
    `storage.format_library_summary`. Un prefijo ambiguo devuelve None: usar
    `resolver_detalle` si hace falta saber por que.
    """
    return resolver_detalle(ref, base=base)["item"]


# ── Abrir ──────────────────────────────────────────────────────────────────────

def _abrir_con_el_so(ruta: Path) -> None:
    """Abre un fichero o carpeta con la app del sistema.

    Copiado de la tool `abrir` (`cognia/agent/tools.py:2567-2605`): es el
    unico sitio de la casa que sabe hacer esto en los tres sistemas.
    """
    if sys.platform == "win32":
        os.startfile(str(ruta))          # noqa: S606  (es la API del SO)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(ruta)])
    else:
        subprocess.Popen(["xdg-open", str(ruta)])


def abrir_producto(item: dict, *, open_browser: bool = True) -> dict:
    """Abre el producto y cuenta que hizo.

    Devuelve `{"ok", "que", "ruta", "abierto", "motivo"}`. `ok` es False solo
    si no hay nada que abrir; que no se haya abierto ventana (remoto, o
    `open_browser=False`) NO es un fallo: la ruta se devuelve igual y el
    llamador la imprime.
    """
    item = item or {}
    lenguaje = item.get("lenguaje") or "vacio"
    entrypoint = item.get("entrypoint") or ""
    directorio = item.get("directorio") or ""

    if lenguaje == "html" and entrypoint:
        que, ruta = "html", entrypoint
    elif lenguaje == "python" and entrypoint:
        que, ruta = "programa", entrypoint
    elif directorio:
        # Sin ejecutable no se inventa uno: se abre la carpeta, que es lo que
        # hay. Decirlo es mejor que abrir algo al azar.
        que, ruta = "carpeta", directorio
    else:
        return {"ok": False, "que": "nada", "ruta": "", "abierto": False,
                "motivo": "el producto no tiene ni entrypoint ni carpeta"}

    p = Path(ruta)
    if not p.exists():
        return {"ok": False, "que": que, "ruta": str(p), "abierto": False,
                "motivo": "la ruta ya no existe en disco"}

    if os.environ.get("COGNIA_REMOTO"):
        return {"ok": True, "que": que, "ruta": str(p), "abierto": False,
                "motivo": "en remoto no se abre ventana: aqui tienes la ruta"}
    if not open_browser:
        return {"ok": True, "que": que, "ruta": str(p), "abierto": False,
                "motivo": "apertura desactivada (memorias_abrir_navegador)"}

    try:
        if que == "html":
            import webbrowser
            webbrowser.open(p.as_uri())
        else:
            _abrir_con_el_so(p)
    except Exception as exc:
        return {"ok": False, "que": que, "ruta": str(p), "abierto": False,
                "motivo": f"{type(exc).__name__}: {exc}"}
    return {"ok": True, "que": que, "ruta": str(p), "abierto": True, "motivo": ""}


# ── La pagina ──────────────────────────────────────────────────────────────────

HTML: str = r"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{
  --fondo:#0d1117; --panel:#161b22; --panel2:#1c2128; --borde:#30363d;
  --texto:#e6edf3; --texto2:#8b949e; --acento:#58a6ff;
  --ok:#3fb950; --alerta:#d29922; --neutro:#8b949e;
  --py:#e3b341; --web:#58a6ff; --nada:#6e7681;
  --sombra:0 1px 3px rgba(0,0,0,.4);
}
:root[data-tema="claro"]{
  --fondo:#ffffff; --panel:#f6f8fa; --panel2:#eaeef2; --borde:#d0d7de;
  --texto:#1f2328; --texto2:#59636e; --acento:#0969da;
  --ok:#1a7f37; --alerta:#9a6700; --neutro:#59636e;
  --py:#9a6700; --web:#0969da; --nada:#8c959f;
  --sombra:0 1px 3px rgba(31,35,40,.12);
}
*{box-sizing:border-box}
html,body{margin:0;min-height:100%}
body{
  background:var(--fondo); color:var(--texto);
  font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  display:flex; flex-direction:column; min-height:100vh;
}
header{
  display:flex; align-items:center; gap:14px; padding:13px 22px;
  border-bottom:1px solid var(--borde); background:var(--panel);
  position:sticky; top:0; z-index:10; flex-wrap:wrap;
}
h1{font-size:16px;font-weight:600;margin:0;letter-spacing:-.01em;white-space:nowrap}
h1 span{color:var(--texto2);font-weight:400;margin-left:8px;font-size:13px}
#buscar{
  flex:1; min-width:190px; max-width:420px; padding:7px 12px;
  background:var(--fondo); color:var(--texto);
  border:1px solid var(--borde); border-radius:6px; font-size:14px;
}
#buscar:focus{outline:none;border-color:var(--acento);
  box-shadow:0 0 0 3px color-mix(in srgb,var(--acento) 25%,transparent)}
select,button.btn{
  padding:7px 11px; background:var(--panel2); color:var(--texto);
  border:1px solid var(--borde); border-radius:6px; font-size:13px; cursor:pointer;
}
/* Un <select> se ensancha hasta su opcion mas larga, y las "categorias" de
   esta biblioteca son frases enteras: sin tope, el desplegable de categorias
   media 900 px y la pagina scrolleaba en horizontal. */
select{max-width:190px; min-width:0; text-overflow:ellipsis}
button.btn:hover,select:hover{border-color:var(--acento)}
#tema{width:38px;text-align:center;font-size:15px}
#avisos{
  padding:9px 22px; font-size:13px; color:var(--texto);
  background:color-mix(in srgb,var(--alerta) 14%,var(--fondo));
  border-bottom:1px solid var(--borde);
}
main{flex:1;padding:16px 22px 26px}
#rejilla{
  display:grid; gap:12px;
  grid-template-columns:repeat(auto-fill,minmax(330px,1fr));
}
.tarjeta{
  border:1px solid var(--borde); border-radius:10px; background:var(--panel);
  padding:13px 14px 11px; display:flex; flex-direction:column; gap:8px;
  min-width:0; overflow:hidden;
}
.tarjeta:hover{border-color:var(--acento);box-shadow:var(--sombra)}
.cab{display:flex;align-items:baseline;gap:8px;min-width:0}
.num{
  color:var(--texto2); font-size:12px; font-variant-numeric:tabular-nums;
  flex:0 0 auto; padding-top:1px;
}
.tit{
  font-weight:600; font-size:14.5px; flex:1; min-width:0;
  overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
}
.desc{
  color:var(--texto2); font-size:12.8px; margin:0;
  display:-webkit-box; -webkit-line-clamp:3; -webkit-box-orient:vertical;
  overflow:hidden; min-height:19px;
}
.desc.sin{font-style:italic;opacity:.75}
.chips{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
/* max-width + ellipsis NO es cosmetica: la "categoria" de estos productos
   la escribio un modelo y a veces es una frase entera ("automated pet feeder
   scheduler based on animal needs and feeding habits"). Con nowrap y sin
   tope, ese chip empujaba la columna del grid y la pagina entera scrolleaba
   en horizontal. */
.chip{
  font-size:11px; padding:1px 8px; border-radius:20px;
  border:1px solid var(--borde); color:var(--texto2); white-space:nowrap;
  max-width:100%; min-width:0; overflow:hidden; text-overflow:ellipsis;
}
.chip.lang-python{color:var(--py);border-color:color-mix(in srgb,var(--py) 45%,var(--borde))}
.chip.lang-html{color:var(--web);border-color:color-mix(in srgb,var(--web) 45%,var(--borde))}
.chip.lang-vacio{color:var(--nada)}
.chip.medido{color:var(--ok);border-color:color-mix(in srgb,var(--ok) 45%,var(--borde))}
.chip.huerfano{color:var(--alerta);border-color:color-mix(in srgb,var(--alerta) 45%,var(--borde))}
.ruta{
  font-family:ui-monospace,"Cascadia Code",Consolas,monospace; font-size:11.5px;
  color:var(--texto2); overflow:hidden; text-overflow:ellipsis;
  white-space:nowrap;
}
.cmd{display:flex;gap:6px;align-items:center;margin-top:auto;padding-top:3px}
.cmd code{
  flex:1; min-width:0; background:var(--panel2); border:1px solid var(--borde);
  border-radius:6px; padding:4px 8px; font-size:12px;
  font-family:ui-monospace,"Cascadia Code",Consolas,monospace;
  overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
}
.copiar{
  padding:4px 9px; font-size:12px; border-radius:6px; border:1px solid var(--borde);
  background:var(--panel2); color:var(--texto); cursor:pointer; white-space:nowrap;
}
.copiar:hover{border-color:var(--acento);color:var(--acento)}
#vacio{
  padding:56px 20px; text-align:center; color:var(--texto2);
  border:1px dashed var(--borde); border-radius:10px; line-height:1.7;
}
#vacio b{color:var(--texto);display:block;margin-bottom:6px;font-size:15px}
footer{
  padding:9px 22px; border-top:1px solid var(--borde); color:var(--texto2);
  font-size:12px; background:var(--panel); display:flex; gap:18px; flex-wrap:wrap;
}
footer code{
  background:var(--panel2); border:1px solid var(--borde); border-radius:5px;
  padding:1px 5px; font-family:ui-monospace,Consolas,monospace; font-size:11.5px;
}
@media(max-width:640px){
  header{padding:11px 14px} main{padding:12px 14px 22px}
  #rejilla{grid-template-columns:1fr}
}
</style></head><body>
<header>
  <h1>Biblioteca <span id="sub"></span></h1>
  <input id="buscar" type="search" placeholder="Buscar por titulo, descripcion, id o ruta..." autocomplete="off">
  <select id="flenguaje"><option value="">Todo lenguaje</option></select>
  <select id="fcategoria"><option value="">Toda categoria</option></select>
  <select id="orden">
    <option value="orden">Orden de la biblioteca</option>
    <option value="puntaje">Puntaje medido</option>
    <option value="reciente">Mas reciente</option>
    <option value="antiguo">Mas antiguo</option>
    <option value="nombre">Nombre A-Z</option>
  </select>
  <button class="btn" id="tema" title="Cambiar entre claro y oscuro">&#9788;</button>
</header>
<div id="avisos" hidden></div>
<main><div id="rejilla"></div></main>
<footer>
  <span id="pie"></span>
  <span>Esta pagina ENTIENDE lo que hay; para ABRIRLO: <code>/biblioteca abrir &lt;id&gt;</code> en el CLI</span>
</footer>
<script>
const DATOS = __DATA__;
const ITEMS = DATOS.items || [];
const $ = s => document.querySelector(s);

/* ---- tema: el sistema manda al principio, el usuario manda despues ---- */
(function(){
  const guardado = (function(){ try{ return localStorage.getItem("cognia_biblioteca_tema"); }catch(e){ return null; } })();
  const oscuroSistema = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  aplicarTema(guardado || (oscuroSistema ? "oscuro" : "claro"));
})();
function aplicarTema(t){
  document.documentElement.setAttribute("data-tema", t);
  $("#tema").innerHTML = t === "claro" ? "&#9789;" : "&#9788;";
  $("#tema").title = t === "claro" ? "Cambiar a oscuro" : "Cambiar a claro";
}
$("#tema").onclick = function(){
  const nuevo = document.documentElement.getAttribute("data-tema") === "claro" ? "oscuro" : "claro";
  aplicarTema(nuevo);
  try{ localStorage.setItem("cognia_biblioteca_tema", nuevo); }catch(e){}
};

/* ---- filtros: se llenan con lo que HAY, no con una lista fija ---- */
(DATOS.lenguajes || []).forEach(function(l){
  const o = document.createElement("option");
  o.value = l.clave; o.textContent = l.etiqueta + " (" + l.n + ")";
  $("#flenguaje").appendChild(o);
});
(DATOS.categorias || []).forEach(function(c){
  const o = document.createElement("option");
  o.value = c; o.textContent = c;
  $("#fcategoria").appendChild(o);
});

function fecha(it){ return it.creado || it.modificado || ""; }

function filtrar(){
  const q = $("#buscar").value.trim().toLowerCase();
  const palabras = q ? q.split(/\s+/) : [];
  const fl = $("#flenguaje").value, fc = $("#fcategoria").value;
  let out = ITEMS.filter(function(it){
    if(fl && it.lenguaje !== fl) return false;
    if(fc && it.categoria !== fc) return false;
    return true;
  });
  if(palabras.length){
    out = out.filter(function(it){
      const heno = (it.title + " " + it.description + " " + it.id + " " +
                    it.categoria + " " + it.entrypoint + " " + it.lenguaje).toLowerCase();
      return palabras.every(function(p){ return heno.indexOf(p) >= 0; });
    });
  }
  const o = $("#orden").value;
  out = out.slice();
  out.sort(function(a, b){
    if(o === "nombre")   return a.title.localeCompare(b.title, "es");
    if(o === "antiguo")  return (fecha(a) || "9").localeCompare(fecha(b) || "9");
    if(o === "reciente") return (fecha(b) || "").localeCompare(fecha(a) || "");
    if(o === "puntaje"){
      /* Sin sello NO es cero: es "no se midio". Va detras de todo lo medido,
         nunca mezclado con los suspensos. */
      const pa = (a.puntaje_real === null || a.puntaje_real === undefined) ? -1 : a.puntaje_real;
      const pb = (b.puntaje_real === null || b.puntaje_real === undefined) ? -1 : b.puntaje_real;
      if(pa !== pb) return pb - pa;
      return a.n - b.n;
    }
    return a.n - b.n;
  });
  return out;
}

function chip(texto, clase){
  const s = document.createElement("span");
  s.className = "chip" + (clase ? " " + clase : "");
  s.textContent = texto;
  return s;
}

function botonCopiar(texto){
  const b = document.createElement("button");
  b.className = "copiar"; b.textContent = "copiar";
  b.onclick = function(ev){
    ev.stopPropagation();
    const ok = function(){ b.textContent = "copiado"; setTimeout(function(){ b.textContent = "copiar"; }, 1200); };
    /* file:// sin permiso de portapapeles: se cae a seleccionar el texto, que
       sigue permitiendo Ctrl-C. Un boton que falla en silencio seria peor. */
    if(navigator.clipboard && navigator.clipboard.writeText){
      navigator.clipboard.writeText(texto).then(ok).catch(function(){
        b.textContent = "no pude: copialo a mano";
      });
    } else {
      b.textContent = "no pude: copialo a mano";
    }
  };
  return b;
}

const ETIQ_LENG = {};
(DATOS.lenguajes || []).forEach(function(l){ ETIQ_LENG[l.clave] = l.etiqueta; });

function tarjeta(it){
  const d = document.createElement("div");
  d.className = "tarjeta";

  const cab = document.createElement("div"); cab.className = "cab";
  const num = document.createElement("span"); num.className = "num";
  num.textContent = "#" + it.n;
  const tit = document.createElement("span"); tit.className = "tit";
  tit.textContent = it.title; tit.title = it.title;
  cab.append(num, tit);

  const desc = document.createElement("p");
  desc.className = "desc" + (it.description ? "" : " sin");
  desc.textContent = it.description || "sin descripcion guardada";

  const chips = document.createElement("div"); chips.className = "chips";
  chips.appendChild(chip(ETIQ_LENG[it.lenguaje] || it.lenguaje, "lang-" + it.lenguaje));
  chips.appendChild(chip(it.puntaje, (it.puntaje_real === null || it.puntaje_real === undefined) ? "" : "medido"));
  if(it.categoria){
    const c = chip(it.categoria);
    c.title = it.categoria;      /* la categoria se trunca: entera en el tooltip */
    chips.appendChild(c);
  }
  if(!it.en_index) chips.appendChild(chip("fuera del indice", "huerfano"));

  /* Se pinta la ruta CORTA (carpeta/fichero): la absoluta ocupa media
     pantalla y las 137 tarjetas comparten los mismos 70 primeros chars, asi
     que truncarla por el final las hacia identicas. La entera va en el
     tooltip, que es donde se necesita cuando se necesita. */
  const ruta = document.createElement("div"); ruta.className = "ruta";
  ruta.textContent = it.ruta_corta || "";
  ruta.title = it.entrypoint || it.directorio || "";

  const cmd = document.createElement("div"); cmd.className = "cmd";
  const c = document.createElement("code");
  c.textContent = it.cmd_abrir; c.title = it.cmd_abrir;
  cmd.append(c, botonCopiar(it.cmd_abrir));

  d.append(cab, desc, chips, ruta, cmd);
  return d;
}

function pintar(){
  const filas = filtrar();
  const cont = $("#rejilla");
  cont.innerHTML = "";
  $("#sub").textContent = (DATOS.total === 0)
      ? "vacia"
      : (filas.length === DATOS.total ? DATOS.total + " productos"
                                      : filas.length + " de " + DATOS.total);
  if(!DATOS.total){
    cont.innerHTML = '<div id="vacio"><b>No hay ningun producto en disco</b>' +
      'La carpeta generated_programs esta vacia.<br>' +
      'Cognia guarda aqui lo que construye: proba con <code>/crear</code>.</div>';
    return;
  }
  if(!filas.length){
    const v = document.createElement("div"); v.id = "vacio";
    const b = document.createElement("b"); b.textContent = "Nada coincide con lo que buscas";
    const p = document.createElement("div");
    p.textContent = "Hay " + DATOS.total + " productos, pero ninguno pasa estos filtros.";
    const btn = document.createElement("button");
    btn.className = "btn"; btn.style.marginTop = "12px"; btn.textContent = "limpiar filtros";
    btn.onclick = function(){
      $("#buscar").value = ""; $("#flenguaje").value = ""; $("#fcategoria").value = "";
      pintar();
    };
    v.append(b, p, btn);
    cont.appendChild(v);
    return;
  }
  const frag = document.createDocumentFragment();
  filas.forEach(function(it){ frag.appendChild(tarjeta(it)); });
  cont.appendChild(frag);
}

/* ---- avisos: la diferencia entre el disco y el indice se DICE ---- */
(function(){
  const partes = [];
  const huerfanos = DATOS.total - (DATOS.en_index || 0);
  if(DATOS.fantasmas)
    partes.push(DATOS.fantasmas + " entradas del indice apuntan a carpetas que ya no existen (no se listan: no hay nada que abrir)");
  if(huerfanos > 0)
    partes.push(huerfanos + " carpetas no estan en el indice (se listan igual: la fuente es el disco)");
  if(partes.length){
    const av = $("#avisos"); av.hidden = false;
    av.textContent = partes.join("  ·  ");
  }
})();

$("#buscar").oninput = pintar;
$("#flenguaje").onchange = pintar;
$("#fcategoria").onchange = pintar;
$("#orden").onchange = pintar;
document.addEventListener("keydown", function(e){
  if(e.key === "/" && document.activeElement !== $("#buscar")){ e.preventDefault(); $("#buscar").focus(); }
  if(e.key === "Escape"){ $("#buscar").value = ""; $("#buscar").blur(); pintar(); }
});
$("#pie").textContent = DATOS.total + " productos en disco  ·  el numero de cada tarjeta es el que acepta /biblioteca abrir  ·  tecla / para buscar";
pintar();
</script></body></html>"""


def render_html(data: dict, title: str = "") -> str:
    """Pagina autocontenida a partir del dict. Sin CDN, sin `str.format`.

    El JSON va con TODOS los `<` escapados como `\\u003c`, no solo el `</`.
    Escapar unicamente el cierre dejaba pasar `<!--` y `<script`, que meten
    al tokenizador de HTML en estado *script data escaped*: en ese estado el
    `</script>` de la plantilla no cierra el bloque, se lo come el script, el
    JS muere por sintaxis y la pagina sale con la barra pintada y sin ni una
    tarjeta -- parece vacia, no rota. El dato es la `description` de un
    producto y esta biblioteca guarda paginas HTML generadas por Cognia, asi
    que "<!--" o "<script" ahi dentro es el caso NORMAL, no el rebuscado.
    """
    data = data or {}
    if not title:
        title = "Cognia - Biblioteca (%d productos)" % int(data.get("total") or 0)
    crudo = (json.dumps(data, ensure_ascii=False, default=str)
             .replace("<", "\\u003c"))
    return (HTML
            .replace("__TITLE__", _esc(title))
            .replace("__DATA__", crudo))


def export(path: str | None = None, *, open_browser: bool = True, base=None) -> str:
    """Escribe la pagina y devuelve la ruta. Abre el navegador si se pide.

    Sin `path`, escribe en `~/.cognia/biblioteca.html`. La ruta se devuelve
    SIEMPRE, aunque no se abra nada: bajo `COGNIA_REMOTO` el llamador la
    imprime en vez de abrir una ventana que nadie veria.
    """
    data = build_biblioteca_data(base)
    titulo = "Cognia - Biblioteca (%d productos)" % data["total"]
    out = Path(path) if path else (Path.home() / ".cognia" / "biblioteca.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(data, titulo), encoding="utf-8")
    if open_browser:
        import webbrowser
        webbrowser.open(out.as_uri())
    return str(out)


if __name__ == "__main__":
    ruta = export(open_browser="--no-open" not in sys.argv)
    print(f"biblioteca -> {ruta}")
