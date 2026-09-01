# -*- coding: utf-8 -*-
"""lazo_corto.py -- el arnes CORRE lo que el agente acaba de escribir, en el acto.

QUE RESUELVE (2026-09-01, medido con el banco de tareas largas)
    El harness ya sabia arrancar un producto (autoprueba, revision_profunda),
    pero esa fase vive en el CIERRE del turno. En una tarea larga el cierre no
    llega: el reloj o el presupuesto matan la tarea antes. Resultado tipico: un
    tablero kanban de 30 KB con README impecable y `window.KANBAN` sin definir,
    porque el agente escribio todo y no abrio la pagina ni una vez.

    Este modulo mueve la comprobacion al momento en que se escribe: cada vez que
    el agente escribe o edita un fichero ARRANCABLE, se ejecuta y el error real
    -- con su linea -- vuelve pegado al resultado de la tool. El modelo lo ve en
    el mismo turno y arregla mientras el contexto todavia esta caliente. Es el
    lazo "escribe -> corre -> mira el error -> arregla" que hace un humano.

    Y comprueba el CONTRATO que el usuario escribio en el encargo: si pidio
    `window.JUEGO.iniciarOleada()`, se mira si existe tras cargar. Nada
    especifico de juegos: cualquier encargo que declare una interfaz.

QUE HACE POR FAMILIA
    .html/.htm   abre la pagina en Chromium (Playwright): errores de consola,
                 excepciones, y los identificadores del contrato.
    .py          compila y lo IMPORTA como modulo con timeout (los scripts con
                 guarda __main__ no corren; los modulos ejecutan su nivel
                 superior, que es donde vive el 90% de los NameError/ImportError).
    .js/.mjs     `node --check` (sintaxis). Sin node, se dice.

LO QUE **NO** HACE
    No decide nada: devuelve TEXTO para el modelo. No corta el turno, no
    penaliza, no repite. Si no se puede comprobar (sin Playwright, sin node),
    lo DICE en vez de callar: "no se pudo comprobar" es un estado distinto de
    "comprobado".

COSTE
    Un arranque de Chromium son ~1,5-3 s; un import de Python, decimas. Hay un
    intervalo minimo por fichero para que una rafaga de ediciones no pague un
    navegador cada vez. COGNIA_LAZO_CORTO=0 lo apaga.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

ENV = "COGNIA_LAZO_CORTO"
INTERVALO_MIN_S = 12.0          # entre dos comprobaciones del MISMO fichero
TIMEOUT_IMPORT_S = 12.0
TIMEOUT_NAV_MS = 15000
ESPERA_CARGA_MS = 900
TOPE_TEXTO = 700

_ultima = {}                    # ruta -> monotonic de la ultima comprobacion


def activo() -> bool:
    return os.environ.get(ENV, "1").strip().lower() not in ("0", "off", "false", "no")


def _tope(s, n=TOPE_TEXTO):
    s = str(s or "")
    return s if len(s) <= n else s[:n] + "…"


# -- que ficheros merecen el lazo ---------------------------------------------

def es_arrancable(ruta) -> str:
    """'html' | 'py' | 'js' | '' segun la extension. Los tests de Python no:
    para eso esta la fase de tests, y correrlos aqui duplicaria."""
    try:
        p = Path(str(ruta))
    except Exception:
        return ""
    ext = p.suffix.lower()
    nombre = p.name.lower()
    if ext in (".html", ".htm"):
        return "html"
    if ext == ".py":
        if nombre.startswith("test_") or nombre.endswith("_test.py") or nombre == "conftest.py":
            return ""
        return "py"
    if ext in (".js", ".mjs"):
        return "js"
    return ""


def _reciente(ruta) -> bool:
    ahora = time.monotonic()
    t = _ultima.get(str(ruta))
    if t is not None and ahora - t < INTERVALO_MIN_S:
        return True
    _ultima[str(ruta)] = ahora
    return False


# -- HTML: navegador real -----------------------------------------------------

_JS_SONDA = """
(ids) => {
  const out = {globales_faltan: [], metodos_faltan: [], ids_faltan: [], canvas: null};
  for (const g of ids.globales) {
    if (typeof window[g] === 'undefined') out.globales_faltan.push(g);
  }
  for (const [obj, ms] of Object.entries(ids.metodos)) {
    const o = window[obj];
    if (typeof o === 'undefined') continue;   // ya contado arriba
    for (const m of ms) {
      if (typeof o[m] === 'undefined') out.metodos_faltan.push(obj + '.' + m);
    }
  }
  for (const id of ids.dom_ids) {
    if (!document.getElementById(id)) out.ids_faltan.push(id);
  }
  const c = document.querySelector('canvas');
  if (c) {
    try {
      const g = c.getContext('2d');
      if (g) {
        const d = g.getImageData(0, 0, c.width, c.height).data;
        const set = new Set();
        const paso = Math.max(4, Math.floor(d.length / 20000) * 4);
        for (let i = 0; i < d.length; i += paso) set.add((d[i] << 16) | (d[i+1] << 8) | d[i+2]);
        out.canvas = {colores: set.size, ancho: c.width, alto: c.height};
      } else {
        out.canvas = {colores: -1, ancho: c.width, alto: c.height};   // webgl: no se lee aqui
      }
    } catch (e) { out.canvas = {colores: -2}; }
  }
  return out;
}
"""


def comprobar_html(ruta, contrato=None) -> dict:
    """Abre la pagina en Chromium. Devuelve {ok, corrio, detalle, errores, faltan}."""
    res = {"ok": None, "corrio": False, "detalle": "", "errores": [], "faltan": []}
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        res["detalle"] = ("no se pudo comprobar en navegador (sin Playwright: %s)"
                          % type(exc).__name__)
        return res
    ids = contrato or {"globales": [], "metodos": {}, "dom_ids": []}
    errores = []
    try:
        with sync_playwright() as p:
            nav = p.chromium.launch(args=["--enable-unsafe-swiftshader",
                                          "--use-gl=swiftshader", "--no-sandbox"])
            try:
                pg = nav.new_page(viewport={"width": 1100, "height": 720})
                pg.on("console", lambda m: errores.append("consola: " + m.text[:220])
                      if m.type == "error" else None)
                pg.on("pageerror", lambda e: errores.append("excepcion: " + str(e)[:300]))
                pg.goto(Path(str(ruta)).resolve().as_uri(), wait_until="load",
                        timeout=TIMEOUT_NAV_MS)
                pg.wait_for_timeout(ESPERA_CARGA_MS)
                sonda = pg.evaluate(_JS_SONDA, ids)
            finally:
                nav.close()
    except Exception as exc:
        res["detalle"] = "no se pudo abrir la pagina: %s: %s" % (type(exc).__name__, _tope(exc, 200))
        return res
    res["corrio"] = True
    errores = [e for e in errores if "favicon" not in e.lower()]
    faltan = (["window." + g for g in sonda.get("globales_faltan", [])]
              + list(sonda.get("metodos_faltan", []))
              + ["#" + i for i in sonda.get("ids_faltan", [])])
    res["errores"] = errores[:6]
    res["faltan"] = faltan[:12]
    partes = []
    if errores:
        partes.append("%d error(es) de JS al cargar: %s" % (len(errores), " | ".join(errores[:3])))
    if faltan:
        partes.append("del contrato del encargo NO existen tras cargar: %s" % ", ".join(faltan[:8]))
    canvas = sonda.get("canvas")
    if canvas and canvas.get("colores", 0) == 1:
        partes.append("el canvas esta en blanco (un solo color)")
    res["ok"] = not partes
    res["detalle"] = " · ".join(partes) if partes else "abre sin errores de JS"
    if not partes and ids.get("globales"):
        res["detalle"] += " y el contrato (%s) esta expuesto" % ", ".join(
            "window." + g for g in ids["globales"][:4])
    return res


# -- Python: compila e importa ------------------------------------------------

_SONDA_PY = r'''
import importlib.util, sys, traceback, io
ruta = sys.argv[1]
sys.path.insert(0, sys.argv[2])
try:
    spec = importlib.util.spec_from_file_location("_lazo_corto_mod", ruta)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_lazo_corto_mod"] = mod
    spec.loader.exec_module(mod)
except SystemExit as e:
    print("LAZO_OK exit=%s" % e.code)
except BaseException:
    tb = traceback.format_exc().strip().splitlines()
    print("LAZO_ERR " + " || ".join(tb[-4:]))
else:
    print("LAZO_OK")
'''


def comprobar_py(ruta, raiz=None, contrato=None) -> dict:
    res = {"ok": None, "corrio": False, "detalle": "", "errores": [], "faltan": []}
    ruta = Path(str(ruta))
    try:
        import py_compile
        py_compile.compile(str(ruta), doraise=True)
    except Exception as exc:
        res["corrio"] = True
        res["ok"] = False
        msg = _tope(str(exc).replace("\n", " "), 300)
        res["errores"] = [msg]
        res["detalle"] = "NO compila: " + msg
        return res
    # Un fichero que arranca un servidor o un bucle en el nivel superior se
    # quedaria colgado: el timeout lo corta y se declara indeterminado.
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        pr = subprocess.run([sys.executable, "-c", _SONDA_PY, str(ruta),
                             str(raiz or ruta.parent)],
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=TIMEOUT_IMPORT_S,
                            cwd=str(raiz or ruta.parent), env=env, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        res["detalle"] = ("importar %s tardo mas de %ds: ¿arranca algo en el nivel "
                          "superior? Ponlo bajo if __name__ == '__main__'"
                          % (ruta.name, int(TIMEOUT_IMPORT_S)))
        return res
    except Exception as exc:
        res["detalle"] = "no se pudo importar: %s" % type(exc).__name__
        return res
    res["corrio"] = True
    salida = (pr.stdout or "") + (pr.stderr or "")
    m = re.search(r"LAZO_ERR (.+)", salida)
    if m:
        res["ok"] = False
        res["errores"] = [_tope(m.group(1), 400)]
        res["detalle"] = "al importar: " + res["errores"][0]
        return res
    res["ok"] = True
    res["detalle"] = "compila e importa sin errores"
    faltan = []
    for nombre in (contrato or {}).get("funciones", [])[:12]:
        try:
            texto = ruta.read_text(encoding="utf-8", errors="replace")
        except Exception:
            break
        if not re.search(r"^\s*(def|class|async def)\s+%s\b" % re.escape(nombre), texto, re.M):
            faltan.append(nombre)
    if faltan and len(faltan) < len((contrato or {}).get("funciones", [])):
        # solo se avisa si el fichero define ALGUNA del contrato: si no define
        # ninguna, probablemente el contrato vive en otro fichero
        res["faltan"] = faltan[:8]
        res["detalle"] += " · del contrato no estan aqui: " + ", ".join(faltan[:6])
    return res


# -- JS: sintaxis con node ----------------------------------------------------

def comprobar_js(ruta) -> dict:
    res = {"ok": None, "corrio": False, "detalle": "", "errores": [], "faltan": []}
    import shutil
    node = shutil.which("node")
    if not node:
        res["detalle"] = "no se pudo comprobar la sintaxis (sin node)"
        return res
    try:
        pr = subprocess.run([node, "--check", str(ruta)], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=10)
    except Exception as exc:
        res["detalle"] = "node --check no corrio: %s" % type(exc).__name__
        return res
    res["corrio"] = True
    if pr.returncode != 0:
        err = (pr.stderr or pr.stdout or "").strip().splitlines()
        res["ok"] = False
        res["errores"] = [_tope(" | ".join(err[:4]), 400)]
        res["detalle"] = "error de sintaxis: " + res["errores"][0]
    else:
        res["ok"] = True
        res["detalle"] = "sintaxis OK"
    return res


# -- la PAGINA es la unidad de verificacion, no el fragmento -------------------

def pagina_de(ruta, raiz=None):
    """El .html que carga este .js/.css, si lo hay. None si no.

    MEDIDO (A/B 20 min, 2026-09-01): el agente escribio index.html una vez y
    game.js doce veces. El lazo abrio la pagina UNA vez (al escribir el html) y
    las otras doce solo paso `node --check` sobre game.js, que dice "sintaxis
    OK" a un juego que no pinta nada. Para un producto web el fichero que hay
    que correr es la PAGINA: es la que ejecuta el script y expone el contrato.
    Se busca un .html en el mismo directorio (o en la raiz) que referencie el
    nombre del fichero; si no hay referencia, index.html del mismo directorio.
    """
    try:
        p = Path(str(ruta))
        nombre = p.name
        candidatos = []
        for base in ([p.parent] + ([Path(str(raiz))] if raiz else [])):
            try:
                candidatos.extend(sorted(base.glob("*.html")) + sorted(base.glob("*.htm")))
            except Exception:
                continue
        vistos, refer, indice = set(), None, None
        for h in candidatos:
            if h in vistos:
                continue
            vistos.add(h)
            try:
                if nombre in h.read_text(encoding="utf-8", errors="replace"):
                    refer = refer or h
            except Exception:
                continue
            if h.name.lower() == "index.html" and indice is None:
                indice = h
        return refer or indice
    except Exception:
        return None


# -- punto de entrada para el bucle ------------------------------------------

def tras_escritura(ruta, raiz=None, contrato=None, forzar=False) -> "str | None":
    """Comprueba `ruta` si es arrancable. Devuelve el texto para el modelo o None.

    NUNCA lanza: un lazo que revienta mata la escritura que venia a comprobar.
    """
    try:
        if not activo():
            return None
        familia = es_arrancable(ruta)
        if not familia:
            return None
        p = Path(str(ruta))
        if not p.exists():
            return None
        if not forzar and _reciente(p.resolve()):
            return None
        if familia == "html":
            r = comprobar_html(p, contrato)
        elif familia == "py":
            r = comprobar_py(p, raiz, contrato)
        else:
            r = comprobar_js(p)
            # Un .js que carga una pagina se comprueba EN la pagina: la
            # sintaxis limpia no dice si el juego pinta ni si el contrato
            # esta expuesto. Si el script no compila, con eso basta.
            if r.get("ok"):
                pag = pagina_de(p, raiz)
                if pag is not None and (forzar or not _reciente(pag.resolve())):
                    rp = comprobar_html(pag, contrato)
                    if rp.get("corrio"):
                        marca = "OK" if rp.get("ok") else "FALLA"
                        return "[LAZO CORTO %s] %s (abierta tras escribir %s): %s" % (
                            marca, pag.name, p.name, rp.get("detalle", ""))
        if not r.get("corrio"):
            return "[LAZO CORTO] %s" % r.get("detalle", "no se pudo comprobar")
        marca = "OK" if r.get("ok") else "FALLA"
        return "[LAZO CORTO %s] %s: %s" % (marca, p.name, r.get("detalle", ""))
    except Exception as exc:
        return "[LAZO CORTO] no se pudo comprobar %s (%s)" % (
            Path(str(ruta)).name, type(exc).__name__)
