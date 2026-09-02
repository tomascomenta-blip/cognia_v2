# -*- coding: utf-8 -*-
"""
cognia/agent/renderizador.py
============================
`renderizar`: abre HTML / SVG / Markdown / JS / imagenes / URLs en un navegador
AISLADO (sin ventana) y devuelve una captura PNG + los errores de consola +
un resumen de lo visible. Pedido del dueno (2026-09-02): "a veces Playwright
no funciona y no puede tomar capturas; un interprete de HTML y de diferentes
tecnologias que tome capturas aisladas sin molestar lo que yo este haciendo".

DOS BACKENDS, por orden:
  1. playwright  Chromium headless de Playwright (errores de consola y
                 excepciones de pagina en vivo, texto del DOM, captura).
  2. edge/chrome El navegador del sistema en modo headless por linea de
                 comandos (`msedge --headless=new --screenshot=...`): NO abre
                 ventana, no roba el foco, no toca la sesion del dueno. Los
                 errores de consola salen del log del propio navegador
                 (`--enable-logging=stderr`), que los vuelca como CONSOLE(...).
Sin ninguno de los dos se dice EXACTAMENTE que falta; nunca "no se pudo".

QUE ACEPTA (la "tecnologia" se decide por extension):
  .html .htm     tal cual
  .svg           envuelto en una pagina blanca (y tambien como <img>)
  .md .markdown  convertido a HTML (markdown si esta instalado; si no, <pre>)
  .js            envuelto en una pagina con <canvas id="lienzo"> + <script src>
  .css           una pagina de muestra con esa hoja aplicada
  .png .jpg ...  envuelto en <img>
  .txt y otros   <pre> con el texto
  http(s)://     la URL

Config (cli): 'renderizador_backend' = auto | playwright | edge | chrome.
Env COGNIA_RENDER_BACKEND manda sobre la config. La captura va por defecto al
scratchpad de la tarea (ctx['_scratchpad']) o, sin el, a `<workspace>/
.cognia_capturas/`.
"""
from __future__ import annotations

import html as _html
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ENV_BACKEND = "COGNIA_RENDER_BACKEND"
ANCHO_DEF, ALTO_DEF, ESPERA_DEF_MS = 1100, 720, 1500
ESPERA_MAX_MS = 20000
TIMEOUT_NAV_S = 45

# Ultimo render del proceso (puerta /renderizar estado).
_ULTIMO: dict = {"backend": "", "fuente": "", "png": "", "errores": 0,
                 "detalle": "", "ts": 0.0}

_RUTAS_NAVEGADOR = {
    "edge": [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        "/usr/bin/microsoft-edge", "/usr/bin/microsoft-edge-stable",
    ],
    "chrome": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome",
                     "Application", "chrome.exe"),
        "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium", "/usr/bin/chromium-browser",
    ],
}


# ---------------------------------------------------------------------------
# Config / disponibilidad
# ---------------------------------------------------------------------------

def backend_pedido() -> str:
    """auto | playwright | edge | chrome (env > config > auto)."""
    v = (os.environ.get(ENV_BACKEND) or "").strip().lower()
    if not v:
        try:
            _cli = sys.modules.get("cognia.cli")
            if _cli is not None:
                v = str((_cli._load_config() or {}).get("renderizador_backend", "")).strip().lower()
        except Exception:
            v = ""
    return v if v in ("playwright", "edge", "chrome") else "auto"


def navegador_sistema(preferido: str = "") -> tuple:
    """(nombre, ruta) del navegador headless disponible, o ("", "")."""
    orden = ["edge", "chrome"]
    if preferido in orden:
        orden = [preferido] + [o for o in orden if o != preferido]
    for nombre in orden:
        for ruta in _RUTAS_NAVEGADOR[nombre]:
            if ruta and os.path.isfile(ruta):
                return nombre, ruta
        exe = shutil.which("msedge" if nombre == "edge" else "chrome") or \
            shutil.which("google-chrome") if nombre == "chrome" else None
        if exe:
            return nombre, exe
    return "", ""


def playwright_disponible() -> bool:
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
        return True
    except Exception:
        return False


def disponibilidad() -> dict:
    nombre, ruta = navegador_sistema()
    return {"playwright": playwright_disponible(),
            "sistema": nombre, "sistema_ruta": ruta,
            "pedido": backend_pedido()}


# ---------------------------------------------------------------------------
# Fuente -> pagina HTML
# ---------------------------------------------------------------------------

def _envolver(cuerpo: str, titulo: str = "cognia", extra_head: str = "") -> str:
    return ("<!doctype html><html><head><meta charset='utf-8'>"
            "<title>%s</title>%s</head><body style='margin:16px;background:#fff;"
            "color:#111;font-family:system-ui,Segoe UI,Arial,sans-serif'>"
            "%s</body></html>" % (_html.escape(titulo), extra_head, cuerpo))


def _md_a_html(texto: str) -> str:
    try:
        import markdown  # type: ignore
        return markdown.markdown(texto, extensions=["tables", "fenced_code"])
    except Exception:
        return "<pre style='white-space:pre-wrap'>%s</pre>" % _html.escape(texto)


def preparar_fuente(fuente: str, tmpdir: Path) -> tuple:
    """(uri, tecnologia, aviso). Escribe una pagina envoltorio en `tmpdir`
    cuando la fuente no es HTML directo. Lanza ValueError si no existe."""
    f = (fuente or "").strip().strip("\"'")
    if not f:
        raise ValueError("uso: renderizar <ruta o URL> [| ancho=N] [| alto=N] "
                         "[| espera=MS] [| salida=captura.png]")
    if re.match(r"^https?://", f, re.I):
        return f, "url", ""
    if re.match(r"^file:", f, re.I):
        # El modelo escribe file:///C:/... con naturalidad (cazado 2026-09-02:
        # "el sandbox no ve mis archivos" era esto). Se vuelve ruta local.
        from urllib.parse import unquote, urlparse
        u = urlparse(f)
        f = unquote(u.path)
        if re.match(r"^/[A-Za-z]:", f):
            f = f[1:]
        if u.netloc and not re.match(r"^[A-Za-z]:", f):
            f = "//" + u.netloc + f
    p = Path(f)
    if not p.is_absolute():
        p = Path(os.getcwd()) / p
    p = p.resolve()
    if not p.exists():
        raise ValueError("no existe: %s" % f)
    ext = p.suffix.lower()
    if ext in (".html", ".htm", ".xhtml"):
        return p.as_uri(), "html", ""
    texto = ""
    if ext not in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"):
        try:
            texto = p.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            raise ValueError("no se pudo leer %s: %s" % (p.name, exc))
    if ext == ".svg":
        cuerpo = texto + "<hr><img src='%s' alt='svg'>" % p.as_uri()
        pagina, tec = _envolver(cuerpo, p.name), "svg"
    elif ext in (".md", ".markdown"):
        pagina, tec = _envolver(_md_a_html(texto), p.name,
                                "<style>pre{background:#f4f4f4;padding:8px}"
                                "table{border-collapse:collapse}td,th{border:1px "
                                "solid #999;padding:4px}</style>"), "markdown"
    elif ext in (".js", ".mjs"):
        cuerpo = ("<canvas id='lienzo' width='%d' height='%d' style='border:1px "
                  "solid #ccc'></canvas><div id='app'></div><div id='root'></div>"
                  "<script src='%s'></script>" % (ANCHO_DEF - 40, ALTO_DEF - 80, p.as_uri()))
        pagina, tec = _envolver(cuerpo, p.name), "js"
    elif ext == ".css":
        cuerpo = ("<link rel='stylesheet' href='%s'><h1>Titulo h1</h1><p>Parrafo con "
                  "<a href='#'>enlace</a> y <strong>negrita</strong>.</p><button>"
                  "Boton</button><ul><li>uno</li><li>dos</li></ul><div class='card "
                  "container box'>div.card.container.box</div>" % p.as_uri())
        pagina, tec = _envolver(cuerpo, p.name), "css"
    elif ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"):
        pagina, tec = _envolver("<img src='%s' style='max-width:100%%'>" % p.as_uri(),
                                p.name), "imagen"
    else:
        pagina, tec = _envolver("<pre style='white-space:pre-wrap'>%s</pre>"
                                % _html.escape(texto[:200000]), p.name), "texto"
    env = tmpdir / ("render_" + re.sub(r"[^A-Za-z0-9_.-]", "_", p.stem) + ".html")
    env.write_text(pagina, encoding="utf-8")
    return env.as_uri(), tec, ""


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------

_JS_RESUMEN = """() => {
  const t = (document.body && document.body.innerText || '').replace(/\\s+/g, ' ').trim();
  const c = document.querySelector('canvas');
  let canvas = null;
  if (c) {
    try {
      const ctx = c.getContext('2d');
      const d = ctx ? ctx.getImageData(0, 0, Math.min(c.width, 200), Math.min(c.height, 200)).data : null;
      const cols = new Set();
      if (d) { for (let i = 0; i < d.length; i += 4 * 37) cols.add(d[i] + ',' + d[i+1] + ',' + d[i+2]); }
      canvas = {ancho: c.width, alto: c.height, colores: cols.size};
    } catch (e) { canvas = {ancho: c.width, alto: c.height, colores: -1}; }
  }
  return {titulo: document.title, texto: t.slice(0, 400), chars: t.length,
          canvas: canvas, imgs: document.images.length};
}"""


def _con_playwright(uri: str, png: Path, ancho: int, alto: int, espera_ms: int) -> dict:
    from playwright.sync_api import sync_playwright
    errores, avisos = [], []
    with sync_playwright() as p:
        nav = p.chromium.launch(args=["--enable-unsafe-swiftshader",
                                      "--use-gl=swiftshader", "--no-sandbox"])
        try:
            pg = nav.new_page(viewport={"width": ancho, "height": alto})
            def _consola(m):
                try:
                    url = (m.location or {}).get("url", "") if hasattr(m, "location") else ""
                except Exception:
                    url = ""
                if "favicon" in (url or "").lower():
                    return      # el 404 del favicon no es un error de la pagina
                (errores if m.type == "error" else avisos).append(
                    ("consola: " if m.type == "error" else "aviso: ") + m.text[:220]
                    + (" [%s]" % url[-60:] if url and m.text.startswith("Failed to load") else ""))
            pg.on("console", _consola)
            pg.on("pageerror", lambda e: errores.append("excepcion: " + str(e)[:300]))
            try:
                pg.goto(uri, wait_until="load", timeout=TIMEOUT_NAV_S * 1000)
            except Exception as exc:
                if "ERR_CONNECTION" in str(exc) or "ERR_NAME" in str(exc):
                    raise NoAlcanzable(uri, str(exc)[:160])
                raise
            pg.wait_for_timeout(espera_ms)
            resumen = pg.evaluate(_JS_RESUMEN)
            pg.screenshot(path=str(png), full_page=False)
        finally:
            nav.close()
    errores = [e for e in errores if "favicon" not in e.lower()]
    return {"errores": errores[:8], "avisos": avisos[:4], "resumen": resumen or {}}


# Edge/Chrome vuelcan al log '[pid:tid:fecha:NIVEL:CONSOLE:linea] "msg", source: url (n)'
# (el formato viejo era CONSOLE(linea)). El NIVEL del prefijo es el que vale:
# ERROR = console.error / excepcion no capturada; INFO = console.log.
_RE_CONSOLE = re.compile(
    r':(INFO|WARNING|ERROR|FATAL|VERBOSE\d*):CONSOLE[:(](\d+)\)?\]\s*"(.*?)",\s*source:\s*(\S+)',
    re.S)
_RE_TAG = re.compile(r"<(script|style)[^>]*>.*?</\1>|<[^>]+>", re.S | re.I)


def _resumen_dom(ruta_exe: str, uri: str, perfil: Path, espera_ms: int) -> dict:
    """Titulo y texto visible via --dump-dom (segunda pasada, ~0,5 s)."""
    cmd = [ruta_exe, "--headless=new", "--disable-gpu", "--no-first-run",
           "--no-default-browser-check", "--mute-audio", "--disable-extensions",
           "--user-data-dir=%s" % perfil, "--virtual-time-budget=%d" % max(0, espera_ms),
           "--dump-dom", uri]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=TIMEOUT_NAV_S + espera_ms / 1000.0,
                           encoding="utf-8", errors="replace")
        dom = r.stdout or ""
    except Exception:
        return {}
    if not dom.strip():
        return {}
    if 'id="main-frame-error"' in dom or "ERR_CONNECTION" in dom or "ERR_NAME_NOT_RESOLVED" in dom:
        return {"error_navegador": True}
    m = re.search(r"<title[^>]*>(.*?)</title>", dom, re.S | re.I)
    titulo = _html.unescape(m.group(1).strip()) if m else ""
    cuerpo = dom.split("<body", 1)[1] if "<body" in dom else dom
    cuerpo = cuerpo.split(">", 1)[1] if ">" in cuerpo[:400] else cuerpo
    texto = _html.unescape(_RE_TAG.sub(" ", cuerpo))
    texto = re.sub(r"\s+", " ", texto).strip()
    canvas = None
    mc = re.search(r"<canvas[^>]*width=['\"]?(\d+)[^>]*height=['\"]?(\d+)", dom, re.I)
    if mc:
        canvas = {"ancho": int(mc.group(1)), "alto": int(mc.group(2)), "colores": "?"}
    return {"titulo": titulo, "texto": texto[:400], "chars": len(texto),
            "canvas": canvas, "imgs": len(re.findall(r"<img\b", dom, re.I))}


def _con_sistema(ruta_exe: str, uri: str, png: Path, ancho: int, alto: int,
                 espera_ms: int) -> dict:
    """Edge/Chrome headless por CLI: sin ventana, sin foco, sin perfil del
    dueno (perfil temporal propio)."""
    perfil = Path(tempfile.mkdtemp(prefix="cognia_render_perfil_"))
    cmd = [ruta_exe, "--headless=new", "--disable-gpu", "--no-first-run",
           "--no-default-browser-check", "--hide-scrollbars", "--mute-audio",
           "--disable-extensions", "--user-data-dir=%s" % perfil,
           "--enable-logging=stderr", "--v=0",
           "--window-size=%d,%d" % (ancho, alto),
           "--virtual-time-budget=%d" % max(0, espera_ms),
           "--screenshot=%s" % png, uri]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=TIMEOUT_NAV_S + espera_ms / 1000.0,
                           encoding="utf-8", errors="replace")
        log = (r.stderr or "") + (r.stdout or "")
    finally:
        shutil.rmtree(perfil, ignore_errors=True)
    errores, avisos = [], []
    for m in _RE_CONSOLE.finditer(log):
        nivel, msg, fuente = m.group(1), m.group(3).strip(), m.group(4)
        if "favicon" in msg.lower() or fuente.startswith("chrome-extension://"):
            continue           # ruido del propio navegador, no de la pagina
        if nivel in ("ERROR", "FATAL") or msg.startswith("Uncaught"):
            errores.append("consola: " + msg[:220])
        elif nivel == "WARNING":
            avisos.append("aviso: " + msg[:220])
    if not png.exists():
        raise RuntimeError("el navegador no dejo la captura (exit %s): %s"
                           % (r.returncode, (log.strip().splitlines() or ["sin log"])[-1][:200]))
    perfil2 = Path(tempfile.mkdtemp(prefix="cognia_render_perfil_"))
    try:
        resumen = _resumen_dom(ruta_exe, uri, perfil2, espera_ms)
    finally:
        shutil.rmtree(perfil2, ignore_errors=True)
    if resumen.get("error_navegador"):
        # Edge fotografio SU pagina de error ("no se puede obtener acceso"):
        # eso no es la pagina del agente y decir "sin errores" mentiria.
        try:
            png.unlink()
        except Exception:
            pass
        raise NoAlcanzable(uri, "el navegador no pudo cargar la URL")
    return {"errores": errores[:8], "avisos": avisos[:4], "resumen": resumen,
            "consola_observada": "CONSOLE" in log}


class NoAlcanzable(Exception):
    """La URL no responde (servidor local no arrancado, puerto equivocado)."""

    def __init__(self, uri: str, detalle: str = ""):
        self.uri, self.detalle = uri, detalle
        super().__init__(
            "no se pudo conectar a %s (%s). Si es tu servidor local: arrancalo "
            "con ejecutar_fondo, espera unos segundos, comprueba el puerto con "
            "ver_salida y vuelve a renderizar. Si es un fichero, pasa su ruta "
            "en vez de la URL." % (uri, detalle or "conexion rechazada"))


def _firma_png(png: Path) -> str:
    """'en blanco' si la imagen es de un solo color; '' si no se puede saber."""
    try:
        from PIL import Image  # type: ignore
        im = Image.open(png).convert("RGB")
        im.thumbnail((64, 64))
        colores = im.getcolors(64 * 64) or []
        if len(colores) <= 1:
            return "la captura es de UN solo color (pagina en blanco o sin pintar)"
        return "%d colores en miniatura" % len(colores)
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def renderizar(fuente: str, salida=None, ancho: int = ANCHO_DEF, alto: int = ALTO_DEF,
               espera_ms: int = ESPERA_DEF_MS, backend: str = "", scratch=None) -> dict:
    """Renderiza `fuente` y devuelve un dict con png, backend, errores, resumen.
    Lanza ValueError con mensaje accionable si nada puede renderizar."""
    ancho = max(200, min(4000, int(ancho or ANCHO_DEF)))
    alto = max(150, min(4000, int(alto or ALTO_DEF)))
    espera_ms = max(0, min(ESPERA_MAX_MS, int(espera_ms or 0)))
    pedido = (backend or backend_pedido()).strip().lower() or "auto"
    tmpdir = Path(tempfile.mkdtemp(prefix="cognia_render_"))
    try:
        uri, tec, _ = preparar_fuente(fuente, tmpdir)
        if salida:
            png = Path(str(salida))
            if not png.is_absolute():
                png = Path(os.getcwd()) / png
        else:
            base = Path(str(scratch)) if scratch else (Path(os.getcwd()) / ".cognia_capturas")
            base.mkdir(parents=True, exist_ok=True)
            nombre = re.sub(r"[^A-Za-z0-9_.-]", "_", Path(fuente.strip().strip("\"'")).name
                            if tec != "url" else "url")[:40]
            png = base / ("captura_%s_%s.png" % (nombre, time.strftime("%H%M%S")))
        png.parent.mkdir(parents=True, exist_ok=True)
        intentos, usado, res = [], "", None
        orden = (["playwright", "sistema"] if pedido in ("auto", "playwright")
                 else ["sistema", "playwright"])
        for b in orden:
            try:
                if b == "playwright":
                    if not playwright_disponible():
                        intentos.append("playwright: no instalado")
                        continue
                    res = _con_playwright(uri, png, ancho, alto, espera_ms)
                    usado = "playwright"
                else:
                    nombre, exe = navegador_sistema(pedido if pedido in ("edge", "chrome") else "")
                    if not exe:
                        intentos.append("edge/chrome: no encontrados en el sistema")
                        continue
                    res = _con_sistema(exe, uri, png, ancho, alto, espera_ms)
                    usado = nombre + "-headless"
                break
            except NoAlcanzable as exc:
                # No se cae al otro backend: el fallo es de la URL, no del
                # navegador, y el segundo solo fotografiaria la pagina de error.
                raise ValueError(str(exc))
            except Exception as exc:
                intentos.append("%s: %s: %s" % (b, type(exc).__name__, str(exc)[:160]))
                if pedido in ("playwright", "edge", "chrome"):
                    # backend forzado: no se cae a otro sin decirlo
                    pass
        if res is None:
            raise ValueError("ningun backend pudo renderizar — " + " | ".join(intentos)
                             + ". Instala Playwright (pip install playwright && playwright "
                               "install chromium) o Edge/Chrome.")
        out = {"png": str(png), "backend": usado, "tecnologia": tec, "uri": uri,
               "consola_observada": bool(res.get("consola_observada", True)),
               "errores": res.get("errores", []), "avisos": res.get("avisos", []),
               "resumen": res.get("resumen", {}), "firma": _firma_png(png),
               "intentos": intentos, "ancho": ancho, "alto": alto}
        _ULTIMO.update({"backend": usado, "fuente": fuente, "png": str(png),
                        "errores": len(out["errores"]), "ts": time.time(),
                        "detalle": out["firma"]})
        return out
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def texto_resultado(r: dict) -> str:
    """El RESULTADO que lee el modelo: captura, backend, errores y lo visible."""
    partes = ["captura en %s (%dx%d, %s, %s)" % (r["png"], r["ancho"], r["alto"],
                                                  r["tecnologia"], r["backend"])]
    if r.get("errores"):
        partes.append("%d error(es) de JS: %s" % (len(r["errores"]), " | ".join(r["errores"][:4])))
    elif r.get("consola_observada", True):
        partes.append("sin errores de consola")
    else:
        # honesto: el log del navegador no trajo NINGUNA linea de consola,
        # asi que "sin errores" seria afirmar lo que no se midio
        partes.append("consola no observable con este backend")
    res = r.get("resumen") or {}
    if res:
        if res.get("titulo"):
            partes.append("titulo: %s" % str(res["titulo"])[:80])
        if res.get("canvas"):
            c = res["canvas"]
            partes.append("canvas %sx%s con %s colores" % (c.get("ancho"), c.get("alto"),
                                                            c.get("colores")))
        if res.get("texto"):
            partes.append("texto visible (%d chars): %s" % (res.get("chars", 0),
                                                            str(res["texto"])[:300]))
        elif res.get("chars", 0) == 0 and not res.get("canvas"):
            partes.append("SIN texto visible")
    if r.get("firma"):
        partes.append(r["firma"])
    if r.get("intentos"):
        partes.append("(backend(s) que fallaron antes: %s)" % "; ".join(r["intentos"]))
    return " · ".join(p for p in partes if p)


def ultimo() -> dict:
    return dict(_ULTIMO)


# ---------------------------------------------------------------------------
# Registro en el catalogo del agente
# ---------------------------------------------------------------------------

_RE_KV = re.compile(r"\|\s*(ancho|alto|espera|salida|backend)\s*=\s*([^|]+)\s*$", re.I)


def partir_args(args: str) -> tuple:
    """(fuente, opciones) desde 'ruta | ancho=N | alto=N | espera=MS | salida=X'."""
    s = (args or "").strip()
    opts = {}
    while True:
        m = _RE_KV.search(s)
        if not m:
            break
        opts[m.group(1).lower()] = m.group(2).strip().strip("\"'")
        s = s[:m.start()].strip()
    return s, opts


def register(tool) -> None:
    @tool("renderizar",
          "renderizar <ruta o URL> [| ancho=N] [| alto=N] [| espera=MS] [| salida=X.png]"
          "  -- abre HTML/SVG/MD/JS/CSS/imagen en un navegador AISLADO (sin ventana), "
          "guarda una captura PNG y devuelve errores de consola y lo visible",
          desc="Renderiza una pagina o fichero (HTML, SVG, Markdown, JS con canvas, "
               "CSS, imagen o URL) en un navegador headless que NO abre ventana ni "
               "toca la sesion del usuario, y devuelve la ruta de la captura PNG, "
               "los errores de consola/JS y un resumen de lo visible (titulo, texto, "
               "canvas). Usa Playwright y, si falla, Edge/Chrome del sistema. Usala "
               "para COMPROBAR que lo que escribiste se ve y no revienta. Acepta "
               "rutas relativas al workspace, absolutas y file://; para una URL "
               "http://localhost:PUERTO el servidor tiene que estar arrancado "
               "antes (ejecutar_fondo) o devuelve 'no se pudo conectar'.",
          params=[
              {"nombre": "fuente", "tipo": "string", "requerido": True,
               "descripcion": "ruta del fichero (html, svg, md, js, css, png…) o URL"},
              {"nombre": "ancho", "tipo": "integer", "requerido": False, "clave": True,
               "descripcion": "ancho del viewport en px (default 1100)"},
              {"nombre": "alto", "tipo": "integer", "requerido": False, "clave": True,
               "descripcion": "alto del viewport en px (default 720)"},
              {"nombre": "espera", "tipo": "integer", "requerido": False, "clave": True,
               "descripcion": "ms a esperar tras cargar antes de capturar (default 1500)"},
              {"nombre": "salida", "tipo": "string", "requerido": False, "clave": True,
               "descripcion": "ruta del PNG (default: el scratchpad de la tarea)"},
          ],
          timeout_s=TIMEOUT_NAV_S + 30)
    def _renderizar(args, ctx):
        fuente, o = partir_args(args)
        try:
            r = renderizar(fuente, salida=o.get("salida"),
                           ancho=int(o.get("ancho") or ANCHO_DEF),
                           alto=int(o.get("alto") or ALTO_DEF),
                           espera_ms=int(o.get("espera") or ESPERA_DEF_MS),
                           backend=o.get("backend", ""),
                           scratch=(ctx or {}).get("_scratchpad") if isinstance(ctx, dict) else None)
        except ValueError as exc:
            return "RESULTADO renderizar ERROR: %s" % exc
        except Exception as exc:
            return "RESULTADO renderizar ERROR: %s: %s" % (type(exc).__name__, str(exc)[:200])
        return "RESULTADO renderizar %s: %s" % (fuente, texto_resultado(r))
