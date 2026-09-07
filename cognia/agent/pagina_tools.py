# -*- coding: utf-8 -*-
"""
cognia/agent/pagina_tools.py
============================
Familia `pagina_*` (2026-09-07, pedido del dueno: "mas herramientas para que
Cognia pruebe sus propios resultados"): una SESION PERSISTENTE de Chromium
headless (Playwright) sobre la que el agente hace preguntas y acciones UNA A
UNA, sin repetir la carga en cada paso como hace `renderizar`.

  pagina_abrir       carga fichero/URL (misma preparacion que renderizar)
  pagina_js          evalua JS y devuelve el valor
  pagina_texto       innerText de un selector (o de todos)
  pagina_atributos   tag/id/class/atributos/caja/estilos computados
  pagina_clic / pagina_escribir / pagina_tecla / pagina_scroll / pagina_esperar
                     acciones; cada una dice si la pantalla cambio y si hubo
                     errores de JS nuevos
  pagina_captura     PNG de la pagina, de un elemento o entera
  pagina_consola     mensajes de consola acumulados (errores primero)
  pagina_red         peticiones acumuladas y las fallidas
  pagina_enlaces     enlaces/imagenes/scripts rotos
  pagina_responsive  capturas a varios anchos + desbordamiento horizontal
  pagina_fotogramas  N capturas en el tiempo: anima / estatica / parpadea
  pagina_accesibilidad  alt, labels, contraste, headings, lang, titulo
  pagina_servir      http.server de un directorio (modulos ES, fetch)
  pagina_cerrar / pagina_estado

POR QUE UN HILO PROPIO: run_tool corre CADA llamada en un hilo nuevo
(harness/timeout_tool.correr_con_deadline) y la API sync de Playwright no
admite usar sus objetos desde otro hilo ("cannot switch to a different
thread"). La sesion vive en un worker daemon con cola de comandos: cada tool
le manda una funcion `fn(page)` y espera el resultado. Asi la sesion sobrevive
entre pasos del agente y entre tools del REPL.
"""
from __future__ import annotations

import atexit
import functools
import http.server
import json
import queue
import re
import shutil
import socketserver
import tempfile
import threading
import time
from pathlib import Path

from cognia.agent import pruebas_comun as PC

ANCHO_DEF, ALTO_DEF, ESPERA_DEF_MS = 1100, 720, 800
TIMEOUT_NAV_S = 45
MAX_CONSOLA, MAX_RED = 400, 600
UMBRAL_CAMBIO = 0.002       # fraccion de pixeles (misma que renderizador_guion)
MAX_TEXTO = 2000

_ULTIMO: dict = {"accion": "", "detalle": "", "ts": 0.0, "error": ""}


# ---------------------------------------------------------------------------
# Sesion: un worker con cola, Playwright vive SOLO ahi
# ---------------------------------------------------------------------------

class _Sesion:
    def __init__(self):
        self.cola: "queue.Queue" = queue.Queue()
        self.hilo = None
        self.pw = None
        self.nav = None
        self.pg = None
        self.uri = ""
        self.fuente = ""
        self.consola: list = []       # dicts {tipo, texto, url, linea}
        self.red: list = []           # dicts {metodo, url, status, tipo, bytes, fallo}
        self.errores_pagina: list = []
        self.vistos = 0               # marca para "errores nuevos" entre acciones
        self.tmpdir = None
        self.ancho, self.alto = ANCHO_DEF, ALTO_DEF
        self.lock = threading.Lock()

    # -- worker ------------------------------------------------------------
    def _bucle(self):
        while True:
            fn, caja, listo = self.cola.get()
            if fn is None:
                listo.set()
                break
            try:
                caja["res"] = fn()
            except BaseException as exc:       # viaja al llamador
                caja["exc"] = exc
            listo.set()

    def llamar(self, fn, timeout: float = 90.0):
        with self.lock:
            if self.hilo is None or not self.hilo.is_alive():
                self.hilo = threading.Thread(target=self._bucle, name="pagina-worker", daemon=True)
                self.hilo.start()
        caja: dict = {}
        listo = threading.Event()
        self.cola.put((fn, caja, listo))
        if not listo.wait(timeout):
            raise TimeoutError("la sesion del navegador no respondio en %ds" % int(timeout))
        if "exc" in caja:
            raise caja["exc"]
        return caja.get("res")

    # -- arranque / cierre (SIEMPRE dentro del worker) --------------------
    def _arrancar(self):
        if self.pg is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except Exception:
            raise ValueError("falta Playwright (pip install playwright && playwright install chromium)")
        self.pw = sync_playwright().start()
        self.nav = self.pw.chromium.launch(args=["--enable-unsafe-swiftshader",
                                                 "--use-gl=swiftshader", "--no-sandbox"])
        ctx = self.nav.new_context(viewport={"width": self.ancho, "height": self.alto})
        self.pg = ctx.new_page()
        self.pg.on("console", self._on_consola)
        self.pg.on("pageerror", lambda e: self._push_consola("excepcion", str(e)[:300], "", 0))
        self.pg.on("response", self._on_respuesta)
        self.pg.on("requestfailed", self._on_fallo)

    def _cerrar(self):
        errs = []
        for nombre, fn in (("navegador", lambda: self.nav and self.nav.close()),
                           ("playwright", lambda: self.pw and self.pw.stop())):
            try:
                fn()
            except Exception as exc:
                errs.append("%s: %s" % (nombre, str(exc)[:80]))
        self.pg = self.nav = self.pw = None
        if self.tmpdir:
            shutil.rmtree(self.tmpdir, ignore_errors=True)
            self.tmpdir = None
        return errs

    # -- eventos -----------------------------------------------------------
    def _push_consola(self, tipo, texto, url, linea):
        if "favicon" in (url or "").lower() or "favicon" in (texto or "").lower():
            return          # el 404 del favicon no es un error de la pagina
        if len(self.consola) >= MAX_CONSOLA:
            del self.consola[0]
        self.consola.append({"tipo": tipo, "texto": texto, "url": url, "linea": linea})

    def _on_consola(self, m):
        try:
            loc = m.location or {}
            url, linea = loc.get("url", ""), loc.get("lineNumber", 0)
        except Exception:
            url, linea = "", 0
        self._push_consola(m.type, m.text[:400], url, linea)

    def _on_respuesta(self, r):
        try:
            req = r.request
            tam = 0
            try:
                tam = int((r.headers or {}).get("content-length", "0") or 0)
            except Exception:
                tam = 0
            self._push_red({"metodo": req.method, "url": r.url, "status": r.status,
                            "tipo": req.resource_type, "bytes": tam, "fallo": r.status >= 400})
        except Exception as exc:
            self._push_red({"metodo": "?", "url": "?", "status": 0, "tipo": "?", "bytes": 0,
                            "fallo": True, "detalle": "evento ilegible: %s" % exc})

    def _on_fallo(self, req):
        try:
            det = (req.failure or "")
        except Exception:
            det = ""
        self._push_red({"metodo": req.method, "url": req.url, "status": 0,
                        "tipo": req.resource_type, "bytes": 0, "fallo": True, "detalle": det})

    def _push_red(self, fila):
        if "favicon" in fila.get("url", "").lower():
            return
        if len(self.red) >= MAX_RED:
            del self.red[0]
        self.red.append(fila)

    # -- utilidades dentro del worker -------------------------------------
    def errores_nuevos(self) -> list:
        nuevos = [c for c in self.consola[self.vistos:] if c["tipo"] in ("error", "excepcion")]
        self.vistos = len(self.consola)
        return nuevos

    def captura_bytes(self) -> bytes:
        return self.pg.screenshot(full_page=False)


_S = _Sesion()

# Servidor estatico (pagina_servir)
_SRV: dict = {"srv": None, "hilo": None, "url": "", "dir": ""}


def _cambio(a: bytes, b: bytes):
    """Fraccion de pixeles distintos entre dos PNG en memoria (None si no se pudo)."""
    try:
        from cognia.program_creator.frames_gate import fraccion_pixeles_distintos
        return fraccion_pixeles_distintos(a, b)
    except Exception:
        pass
    try:
        import io
        from PIL import Image, ImageChops
        ia = Image.open(io.BytesIO(a)).convert("RGB")
        ib = Image.open(io.BytesIO(b)).convert("RGB")
        if ia.size != ib.size:
            ib = ib.resize(ia.size)
        d = ImageChops.difference(ia, ib).convert("L").point(lambda v: 255 if v > 24 else 0)
        h = d.histogram()
        return round(h[255] / float(ia.width * ia.height or 1), 4)
    except Exception:
        return None


def _texto_cambio(frac) -> str:
    if frac is None:
        return "cambio de pantalla: no medible"
    if frac < UMBRAL_CAMBIO:
        return "la pantalla NO cambio"
    return "la pantalla cambio (%.1f%% de pixeles)" % (frac * 100)


def _texto_errores(nuevos: list) -> str:
    if not nuevos:
        return "sin errores JS nuevos"
    return "%d error(es) JS nuevos: %s" % (len(nuevos), " | ".join(
        "%s: %s" % (c["tipo"], c["texto"][:160]) for c in nuevos[:3]))


def _tecla(nombre: str) -> str:
    try:
        from cognia.agent.renderizador_guion import _tecla as _t
        return _t(nombre)
    except Exception:
        n = (nombre or "").strip()
        return n if len(n) <= 1 else n[0].upper() + n[1:]


def _selector_o_punto(s: str):
    """'x,y' -> (x, y); cualquier otra cosa -> selector."""
    m = re.match(r"^\s*(-?\d+)\s*,\s*(-?\d+)\s*$", s or "")
    if m:
        return (int(m.group(1)), int(m.group(2)))
    return (s or "").strip().strip("\"'")


def _sellar(accion: str, detalle: str = "", error: str = "") -> None:
    _ULTIMO.update({"accion": accion, "detalle": detalle[:200], "ts": time.time(), "error": error[:200]})


def _requiere_pagina():
    if _S.pg is None:
        raise ValueError("no hay pagina abierta: primero pagina_abrir <ruta o URL>")


def _accion(nombre: str, fn_dentro, timeout: float = 60.0) -> str:
    """Ejecuta `fn_dentro(pg) -> str` en el worker midiendo cambio de
    pantalla y errores nuevos; devuelve el RESULTADO ya formateado."""
    def _run():
        _requiere_pagina()
        pg = _S.pg
        antes = _S.captura_bytes()
        _S.errores_nuevos()          # marca: lo anterior no cuenta como nuevo
        det = fn_dentro(pg)
        pg.wait_for_timeout(150)
        despues = _S.captura_bytes()
        return det, _cambio(antes, despues), _S.errores_nuevos()
    try:
        det, frac, nuevos = _S.llamar(_run, timeout)
    except ValueError as exc:
        _sellar(nombre, error=str(exc))
        return "RESULTADO %s ERROR: %s" % (nombre, exc)
    except Exception as exc:
        _sellar(nombre, error=str(exc))
        return "RESULTADO %s ERROR: %s: %s" % (nombre, type(exc).__name__, str(exc)[:220])
    _sellar(nombre, det)
    return "RESULTADO %s: %s · %s · %s" % (nombre, det, _texto_cambio(frac), _texto_errores(nuevos))


def _json_corto(v, tope: int = MAX_TEXTO) -> str:
    try:
        s = json.dumps(v, ensure_ascii=False, default=str)
    except Exception:
        s = repr(v)
    return s if len(s) <= tope else s[:tope] + "... (%d chars mas)" % (len(s) - tope)


# ---------------------------------------------------------------------------
# JS reutilizable
# ---------------------------------------------------------------------------

_JS_ATRIBUTOS = """(sel) => {
  const el = document.querySelector(sel);
  if (!el) return null;
  const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
  const attrs = {}; for (const a of el.attributes) attrs[a.name] = a.value.slice(0, 120);
  const claves = ['display','position','width','height','color','background-color','font-size',
                  'opacity','z-index','overflow','visibility','font-family','margin','padding'];
  const est = {}; for (const k of claves) est[k] = s.getPropertyValue(k);
  const visible = r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && parseFloat(s.opacity) > 0;
  return {tag: el.tagName.toLowerCase(), id: el.id, clase: el.className, atributos: attrs,
          caja: {x: Math.round(r.x), y: Math.round(r.y), ancho: Math.round(r.width), alto: Math.round(r.height)},
          visible: visible, estilos: est, texto: (el.innerText || el.value || '').trim().slice(0, 200),
          hijos: el.children.length};
}"""

_JS_TEXTO_TODOS = """(sel) => Array.from(document.querySelectorAll(sel)).slice(0, 30)
  .map((el, i) => ({i: i, texto: (el.innerText || el.value || el.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 200)}))"""

_JS_RECURSOS = """() => {
  const out = [];
  const add = (tipo, url, el) => { if (url) out.push({tipo, url, alt: el.getAttribute && el.getAttribute('alt'),
      rota: (tipo === 'img' && el.complete && el.naturalWidth === 0)}); };
  for (const a of document.querySelectorAll('a[href]')) add('a', a.href, a);
  for (const i of document.querySelectorAll('img[src]')) add('img', i.src, i);
  for (const l of document.querySelectorAll('link[href]')) add('link', l.href, l);
  for (const s of document.querySelectorAll('script[src]')) add('script', s.src, s);
  return out.slice(0, 200);
}"""

_JS_DESBORDE = """() => ({sw: document.documentElement.scrollWidth, iw: window.innerWidth,
                        sh: document.documentElement.scrollHeight, ih: window.innerHeight})"""

_JS_ACCESIBILIDAD = """() => {
  const sel = el => { if (el.id) return '#' + el.id; const p = el.parentElement;
    if (!p) return el.tagName.toLowerCase();
    const i = Array.from(p.children).filter(c => c.tagName === el.tagName).indexOf(el) + 1;
    return el.tagName.toLowerCase() + ':nth-of-type(' + i + ')'; };
  const vis = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const prob = {};
  const add = (k, el, extra) => { (prob[k] = prob[k] || []).push(sel(el) + (extra ? ' ' + extra : '')); };
  for (const im of document.querySelectorAll('img')) if (!im.hasAttribute('alt')) add('img_sin_alt', im);
  for (const inp of document.querySelectorAll('input:not([type=hidden]), select, textarea')) {
    const lab = inp.id && document.querySelector('label[for="' + inp.id + '"]');
    if (!lab && !inp.closest('label') && !inp.getAttribute('aria-label') && !inp.getAttribute('aria-labelledby')
        && !inp.getAttribute('placeholder') && !inp.getAttribute('title')) add('input_sin_label', inp);
  }
  for (const b of document.querySelectorAll('button, a[href], [role=button]')) {
    const t = (b.innerText || b.getAttribute('aria-label') || b.getAttribute('title') || '').trim();
    const img = b.querySelector('img[alt]');
    if (!t && !(img && img.getAttribute('alt'))) add('control_sin_texto', b);
  }
  let prev = 0;
  for (const h of document.querySelectorAll('h1,h2,h3,h4,h5,h6')) {
    const n = parseInt(h.tagName[1]); if (prev && n > prev + 1) add('heading_salta_nivel', h, '(h' + prev + ' -> h' + n + ')'); prev = n;
  }
  const lum = c => { const m = c.match(/\\d+(\\.\\d+)?/g); if (!m || m.length < 3) return null;
    const f = v => { v = parseFloat(v) / 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    if (m.length >= 4 && parseFloat(m[3]) === 0) return null;
    return 0.2126 * f(m[0]) + 0.7152 * f(m[1]) + 0.0722 * f(m[2]); };
  const fondo = el => { let e = el; while (e) { const bg = getComputedStyle(e).backgroundColor;
      const l = lum(bg); if (l !== null) return l; e = e.parentElement; } return 1; };
  let n = 0;
  for (const el of document.querySelectorAll('p, span, a, li, td, th, h1, h2, h3, h4, h5, h6, label, button, div')) {
    if (n >= 200) break;
    if (!vis(el)) continue;
    const propio = Array.from(el.childNodes).some(c => c.nodeType === 3 && c.textContent.trim());
    if (!propio) continue;
    n++;
    const lc = lum(getComputedStyle(el).color); if (lc === null) continue;
    const lb = fondo(el);
    const ratio = (Math.max(lc, lb) + 0.05) / (Math.min(lc, lb) + 0.05);
    if (ratio < 4.5) add('contraste_bajo', el, '(' + ratio.toFixed(1) + ':1)');
  }
  const globales = [];
  if (!document.documentElement.getAttribute('lang')) globales.push('html sin atributo lang');
  if (!document.title) globales.push('sin <title>');
  return {problemas: prob, globales: globales, textos_revisados: n};
}"""


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

def _abrir(fuente: str, ancho: int, alto: int, espera_ms: int) -> str:
    from cognia.agent import renderizador as _rz

    def _run():
        _S.ancho, _S.alto = ancho, alto
        if _S.pg is None:
            _S._arrancar()
        else:
            try:
                _S.pg.set_viewport_size({"width": ancho, "height": alto})
            except Exception as exc:
                raise ValueError("no se pudo ajustar el viewport: %s" % exc)
        if _S.tmpdir:
            shutil.rmtree(_S.tmpdir, ignore_errors=True)
        _S.tmpdir = Path(tempfile.mkdtemp(prefix="cognia_pagina_"))
        uri, tec, _ = _rz.preparar_fuente(fuente, _S.tmpdir)
        _S.consola.clear(); _S.red.clear(); _S.vistos = 0
        try:
            _S.pg.goto(uri, wait_until="load", timeout=TIMEOUT_NAV_S * 1000)
        except Exception as exc:
            # cualquier net::ERR_* (conexion rechazada, puerto inseguro, DNS)
            # es "la URL no responde": el consejo accionable es el mismo
            if "net::ERR_" in str(exc):
                raise ValueError(str(_rz.NoAlcanzable(uri, str(exc).splitlines()[0][:160])))
            raise
        _S.pg.wait_for_timeout(espera_ms)
        _S.uri, _S.fuente = uri, fuente
        titulo = _S.pg.title()
        texto = _S.pg.evaluate("() => (document.body && document.body.innerText || '').replace(/\\s+/g, ' ').trim()")
        errs = [c for c in _S.consola if c["tipo"] in ("error", "excepcion")]
        _S.vistos = len(_S.consola)
        return tec, titulo, texto, errs

    tec, titulo, texto, errs = _S.llamar(_run, TIMEOUT_NAV_S + espera_ms / 1000.0 + 20)
    partes = ["%s abierta (%s, %dx%d)" % (fuente, tec, ancho, alto)]
    if titulo:
        partes.append("titulo: %s" % titulo[:80])
    partes.append("texto visible (%d chars): %s" % (len(texto), texto[:400]) if texto else "SIN texto visible")
    if errs:
        partes.append("%d error(es) de consola: %s" % (len(errs), " | ".join(e["texto"][:120] for e in errs[:3])))
    else:
        partes.append("sin errores de consola")
    partes.append("sesion abierta: usa pagina_js / pagina_texto / pagina_clic / pagina_escribir / "
                  "pagina_captura / pagina_consola / pagina_red / pagina_enlaces / pagina_responsive / "
                  "pagina_fotogramas / pagina_accesibilidad; pagina_cerrar al terminar")
    return " · ".join(partes)


def _arrancar_servidor(directorio: Path, puerto: int) -> str:
    if _SRV["srv"] is not None:
        _parar_servidor()

    class _Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a, **k):      # silencio: el REPL no es un access log
            pass

    class _Srv(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True
        allow_reuse_address = True

    handler = functools.partial(_Handler, directory=str(directorio))
    srv = _Srv(("127.0.0.1", puerto), handler)
    hilo = threading.Thread(target=srv.serve_forever, name="pagina-servir", daemon=True)
    hilo.start()
    url = "http://127.0.0.1:%d/" % srv.server_address[1]
    _SRV.update({"srv": srv, "hilo": hilo, "url": url, "dir": str(directorio)})
    return url


def _parar_servidor() -> str:
    srv = _SRV.get("srv")
    if srv is None:
        return ""
    url = _SRV.get("url", "")
    try:
        srv.shutdown()
        srv.server_close()
    except Exception as exc:
        _SRV.update({"srv": None, "hilo": None, "url": "", "dir": ""})
        return "servidor %s (error al parar: %s)" % (url, exc)
    _SRV.update({"srv": None, "hilo": None, "url": "", "dir": ""})
    return "servidor %s" % url


def cerrar_todo() -> list:
    """Cierra navegador y servidor. Devuelve lo que cerro (para la puerta CLI)."""
    cerrado = []
    if _S.pg is not None:
        try:
            errs = _S.llamar(_S._cerrar, 20)
            cerrado.append("navegador" + ((" (avisos: %s)" % "; ".join(errs)) if errs else ""))
        except Exception as exc:
            cerrado.append("navegador (error al cerrar: %s)" % str(exc)[:100])
            _S.pg = _S.nav = _S.pw = None
    s = _parar_servidor()
    if s:
        cerrado.append(s)
    return cerrado


def _comprobar_url(url: str, timeout: float = 5.0) -> tuple:
    """(ok, detalle) para http(s) y file://."""
    if url.lower().startswith("file:"):
        try:
            p = PC.resolver_ruta(url)
            return p.exists(), ("existe" if p.exists() else "no existe")
        except ValueError as exc:
            return False, str(exc)[:80]
    if not re.match(r"^https?://", url, re.I):
        return True, "no comprobable (%s)" % url.split(":", 1)[0]
    try:
        import httpx
        with httpx.Client(timeout=timeout, follow_redirects=True) as c:
            r = c.head(url)
            if r.status_code in (405, 403, 501):
                r = c.get(url)
            return r.status_code < 400, "HTTP %d" % r.status_code
    except Exception as exc:
        return False, "%s: %s" % (type(exc).__name__, str(exc)[:60])


def ultimo() -> dict:
    return dict(_ULTIMO)


def disponibilidad() -> dict:
    try:
        import playwright.sync_api  # noqa: F401  (sondeo: solo importa si esta instalado)
        pw = True
    except Exception:
        pw = False
    return {"playwright": pw, "sesion": _S.pg is not None, "uri": _S.uri,
            "consola": len(_S.consola), "red": len(_S.red), "servidor": _SRV.get("url", "")}


def register(tool) -> None:
    P = lambda nombre, tipo, desc, req=False, clave=True: {   # noqa: E731
        "nombre": nombre, "tipo": tipo, "requerido": req, "descripcion": desc, "clave": clave}

    @tool("pagina_abrir",
          "pagina_abrir <ruta o URL> [| ancho=N] [| alto=N] [| espera=MS]  -- abre la pagina en una sesion "
          "de navegador PERSISTENTE (sin ventana) para inspeccionarla y probarla paso a paso",
          desc="Abre un fichero (HTML, SVG, Markdown, JS, CSS, imagen) o URL en un Chromium headless que "
               "SIGUE ABIERTO entre llamadas: despues puedes preguntar (pagina_js, pagina_texto, "
               "pagina_atributos), actuar (pagina_clic, pagina_escribir, pagina_tecla, pagina_scroll), "
               "capturar (pagina_captura, pagina_responsive, pagina_fotogramas) y auditar (pagina_consola, "
               "pagina_red, pagina_enlaces, pagina_accesibilidad). Una sola pagina activa; abrir otra la "
               "reemplaza. Para un servidor local arrancalo antes o sirve el directorio con pagina_servir. "
               "Cierra con pagina_cerrar.",
          params=[P("fuente", "string", "ruta del fichero o URL", True, False),
                  P("ancho", "integer", "ancho del viewport (default 1100)"),
                  P("alto", "integer", "alto del viewport (default 720)"),
                  P("espera", "integer", "ms a esperar tras cargar (default 800)")],
          timeout_s=TIMEOUT_NAV_S + 45)
    def _pagina_abrir(args, ctx):
        fuente, o = PC.partir_args(args, ["ancho", "alto", "espera"])
        if not fuente:
            return "RESULTADO pagina_abrir ERROR: falta la ruta o URL. Uso: pagina_abrir <ruta o URL>"
        try:
            det = _abrir(fuente, PC.entero(o.get("ancho"), ANCHO_DEF, 200, 4000),
                         PC.entero(o.get("alto"), ALTO_DEF, 150, 4000),
                         PC.entero(o.get("espera"), ESPERA_DEF_MS, 0, 20000))
        except ValueError as exc:
            _sellar("abrir", error=str(exc))
            return "RESULTADO pagina_abrir ERROR: %s" % exc
        except Exception as exc:
            _sellar("abrir", error=str(exc))
            return "RESULTADO pagina_abrir ERROR: %s: %s" % (type(exc).__name__, str(exc)[:220])
        _sellar("abrir", fuente)
        return "RESULTADO pagina_abrir: " + det

    @tool("pagina_js",
          "pagina_js <expresion o codigo JS>  -- evalua JS en la pagina abierta y devuelve el valor",
          desc="Evalua una expresion o codigo JavaScript en la pagina abierta con pagina_abrir y devuelve "
               "el valor serializado (JSON) mas los errores de consola nuevos. Sirve para leer variables "
               "del juego (window.score), contar elementos, disparar funciones o cambiar estado.",
          params=[P("codigo", "string", "expresion o codigo JS", True, False)], timeout_s=60)
    def _pagina_js(args, ctx):
        codigo = (args or "").strip()
        if not codigo:
            return "RESULTADO pagina_js ERROR: falta el codigo JS"

        def _run():
            _requiere_pagina()
            _S.errores_nuevos()
            try:
                val = _S.pg.evaluate(codigo)
            except Exception as exc:
                # una expresion que no es funcion ni sentencia valida: reintento como bloque
                try:
                    val = _S.pg.evaluate("() => { %s }" % codigo)
                except Exception:
                    raise ValueError("JS invalido o lanzo: %s" % str(exc).splitlines()[0][:220])
            return val, _S.errores_nuevos()
        try:
            val, nuevos = _S.llamar(_run, 55)
        except ValueError as exc:
            _sellar("js", error=str(exc))
            return "RESULTADO pagina_js ERROR: %s" % exc
        except Exception as exc:
            _sellar("js", error=str(exc))
            return "RESULTADO pagina_js ERROR: %s: %s" % (type(exc).__name__, str(exc)[:220])
        _sellar("js", codigo)
        return "RESULTADO pagina_js: %s · %s" % (_json_corto(val), _texto_errores(nuevos))

    @tool("pagina_texto",
          "pagina_texto [<selector>] [| todos=1]  -- texto visible del selector (o del body); todos=1 lista cada coincidencia",
          desc="Devuelve el innerText del primer elemento que casa con el selector CSS (o del body si no "
               "se pasa). Con todos=1 lista hasta 30 coincidencias numeradas. Para comprobar que un "
               "texto aparece tras una accion.",
          params=[P("selector", "string", "selector CSS (default body)", False, False),
                  P("todos", "integer", "1 = listar todas las coincidencias")], timeout_s=60)
    def _pagina_texto(args, ctx):
        sel, o = PC.partir_args(args, ["todos"])
        sel = sel or "body"
        todos = str(o.get("todos", "")).strip() in ("1", "si", "true", "on")

        def _run():
            _requiere_pagina()
            if todos:
                return _S.pg.evaluate(_JS_TEXTO_TODOS, sel)
            el = _S.pg.query_selector(sel)
            if el is None:
                raise ValueError("no hay ningun elemento que case con %r" % sel)
            return el.inner_text()
        try:
            r = _S.llamar(_run, 55)
        except ValueError as exc:
            return "RESULTADO pagina_texto ERROR: %s" % exc
        except Exception as exc:
            return "RESULTADO pagina_texto ERROR: %s: %s" % (type(exc).__name__, str(exc)[:220])
        _sellar("texto", sel)
        if todos:
            if not r:
                return "RESULTADO pagina_texto %s: 0 coincidencias" % sel
            return "RESULTADO pagina_texto %s: %d coincidencia(s):\n" % (sel, len(r)) + "\n".join(
                "  [%d] %s" % (f["i"], f["texto"]) for f in r)
        t = re.sub(r"\s+", " ", r or "").strip()
        if not t:
            return "RESULTADO pagina_texto %s: (sin texto visible)" % sel
        return "RESULTADO pagina_texto %s (%d chars): %s" % (sel, len(t), t[:MAX_TEXTO])

    @tool("pagina_atributos",
          "pagina_atributos <selector>  -- tag, id, clases, atributos, caja, visible y estilos computados del elemento",
          desc="Inspecciona el primer elemento que casa con el selector: tag, id, class, atributos, "
               "bounding box (x, y, ancho, alto), si es visible y estilos computados clave (display, "
               "position, width, height, color, background-color, font-size, opacity, z-index, overflow). "
               "Para comprobar que un elemento existe, se ve, tiene el tamano/color esperado.",
          params=[P("selector", "string", "selector CSS", True, False)], timeout_s=60)
    def _pagina_atributos(args, ctx):
        sel = (args or "").strip().strip("\"'")
        if not sel:
            return "RESULTADO pagina_atributos ERROR: falta el selector"

        def _run():
            _requiere_pagina()
            return _S.pg.evaluate(_JS_ATRIBUTOS, sel)
        try:
            r = _S.llamar(_run, 55)
        except ValueError as exc:
            return "RESULTADO pagina_atributos ERROR: %s" % exc
        except Exception as exc:
            return "RESULTADO pagina_atributos ERROR: %s: %s" % (type(exc).__name__, str(exc)[:220])
        if r is None:
            return "RESULTADO pagina_atributos ERROR: no hay ningun elemento que case con %r" % sel
        _sellar("atributos", sel)
        c = r.get("caja") or {}
        est = r.get("estilos") or {}
        partes = ["<%s%s%s>" % (r.get("tag"), ("#" + r["id"]) if r.get("id") else "",
                                ("." + str(r["clase"]).replace(" ", ".")) if r.get("clase") else ""),
                  "%s" % ("VISIBLE" if r.get("visible") else "NO visible"),
                  "caja x=%s y=%s %sx%s" % (c.get("x"), c.get("y"), c.get("ancho"), c.get("alto")),
                  "estilos: " + ", ".join("%s=%s" % (k, v) for k, v in est.items() if v),
                  "atributos: " + _json_corto(r.get("atributos") or {}, 600),
                  "hijos: %s" % r.get("hijos")]
        if r.get("texto"):
            partes.append("texto: %s" % r["texto"][:200])
        return "RESULTADO pagina_atributos %s: " % sel + " · ".join(partes)

    @tool("pagina_clic",
          "pagina_clic <selector|x,y>  -- hace clic y dice si la pantalla cambio y si hubo errores JS",
          desc="Hace clic en un elemento (selector CSS o texto con text=...) o en coordenadas x,y del "
               "viewport de la pagina abierta. Devuelve si la pantalla cambio (fraccion de pixeles) y "
               "los errores JS nuevos. Combina con pagina_texto / pagina_js para comprobar el efecto.",
          params=[P("objetivo", "string", "selector CSS o 'x,y'", True, False)], timeout_s=60)
    def _pagina_clic(args, ctx):
        obj = _selector_o_punto(args)
        if not obj:
            return "RESULTADO pagina_clic ERROR: falta el selector o x,y"

        def _dentro(pg):
            if isinstance(obj, tuple):
                pg.mouse.click(obj[0], obj[1])
                return "clic en %d,%d" % obj
            pg.click(obj, timeout=8000)
            return "clic en %s" % obj
        return _accion("pagina_clic", _dentro)

    @tool("pagina_escribir",
          "pagina_escribir <selector> \"texto\"  -- rellena un input/textarea y dice si la pantalla cambio",
          desc="Escribe texto en un input, textarea o elemento editable (selector CSS): lo enfoca, borra "
               "lo que tenia y teclea el texto. Devuelve si la pantalla cambio y los errores JS nuevos.",
          params=[P("selector", "string", "selector CSS del campo", True, False),
                  P("texto", "string", "texto a escribir (entre comillas)", True, False)], timeout_s=60)
    def _pagina_escribir(args, ctx):
        s = (args or "").strip()
        m = re.match(r"^(\S+)\s+[\"'](.*)[\"']\s*$", s, re.S) or re.match(r"^(\S+)\s+(.*)$", s, re.S)
        if not m:
            return "RESULTADO pagina_escribir ERROR: uso: pagina_escribir <selector> \"texto\""
        sel, texto = m.group(1), m.group(2)

        def _dentro(pg):
            pg.fill(sel, texto, timeout=8000)
            return "escrito %r en %s" % (texto[:60], sel)
        return _accion("pagina_escribir", _dentro)

    @tool("pagina_tecla",
          "pagina_tecla <Tecla>[*N]  -- pulsa una tecla N veces (derecha, espacio, Enter, a, F5...) y mide el cambio",
          desc="Pulsa una tecla (nombres de Playwright o alias en castellano: derecha, izquierda, arriba, "
               "abajo, espacio, intro, escape, tab, retroceso) N veces sobre la pagina abierta. Devuelve si "
               "la pantalla cambio y los errores JS nuevos. Para juegos con teclado y atajos.",
          params=[P("tecla", "string", "tecla, opcionalmente *N (ej: derecha*3)", True, False)],
          timeout_s=60)
    def _pagina_tecla(args, ctx):
        s = (args or "").strip()
        if not s:
            return "RESULTADO pagina_tecla ERROR: falta la tecla"
        m = re.match(r"^(.*?)\s*\*\s*(\d+)$", s)
        nombre, n = (m.group(1), int(m.group(2))) if m else (s, 1)
        n = max(1, min(50, n))
        tecla = _tecla(nombre)

        def _dentro(pg):
            for _ in range(n):
                pg.keyboard.press(tecla)
                pg.wait_for_timeout(40)
            return "tecla %s x%d" % (tecla, n)
        return _accion("pagina_tecla", _dentro)

    @tool("pagina_scroll",
          "pagina_scroll <y>  -- desplaza la pagina y px (negativo = arriba) y mide el cambio",
          desc="Hace scroll vertical de y pixeles (negativo hacia arriba) con la rueda del raton sobre la "
               "pagina abierta. Devuelve si la pantalla cambio y errores JS nuevos.",
          params=[P("y", "integer", "pixeles a desplazar", True, False)], timeout_s=60)
    def _pagina_scroll(args, ctx):
        try:
            y = int((args or "").strip())
        except ValueError:
            return "RESULTADO pagina_scroll ERROR: y tiene que ser un entero"

        def _dentro(pg):
            pg.mouse.wheel(0, y)
            pg.wait_for_timeout(120)
            return "scroll %d" % y
        return _accion("pagina_scroll", _dentro)

    @tool("pagina_esperar",
          "pagina_esperar <selector|\"texto\"|ms>  -- espera a que aparezca un selector o texto, o N ms",
          desc="Espera hasta 15 s a que aparezca un elemento (selector CSS) o un texto (entre comillas) "
               "en la pagina, o simplemente N milisegundos si se pasa un numero. Devuelve si aparecio y "
               "si la pantalla cambio mientras tanto.",
          params=[P("que", "string", "selector, \"texto\" o milisegundos", True, False)], timeout_s=60)
    def _pagina_esperar(args, ctx):
        s = (args or "").strip()
        if not s:
            return "RESULTADO pagina_esperar ERROR: falta que esperar"

        def _dentro(pg):
            if s.isdigit():
                pg.wait_for_timeout(min(int(s), 15000))
                return "esperados %s ms" % s
            if len(s) >= 2 and s[0] in "\"'" and s[-1] == s[0]:
                t = s[1:-1]
                pg.wait_for_function("t => (document.body && document.body.innerText || '').includes(t)",
                                     arg=t, timeout=15000)
                return "aparecio el texto %r" % t[:60]
            pg.wait_for_selector(s, timeout=15000)
            return "aparecio %s" % s
        return _accion("pagina_esperar", _dentro, 40)

    @tool("pagina_captura",
          "pagina_captura [<selector>] [| salida=X.png] [| completa=1]  -- PNG de la pagina, de un elemento o entera",
          desc="Guarda una captura PNG de la pagina abierta (viewport), de un elemento (selector CSS) o de "
               "la pagina completa (completa=1, con scroll) y devuelve la ruta y un resumen visual "
               "(tamano, color dominante, si esta vacia). Para VER lo que hay tras cada accion.",
          params=[P("selector", "string", "selector CSS del elemento (opcional)", False, False),
                  P("salida", "string", "ruta del PNG (default: scratchpad)"),
                  P("completa", "integer", "1 = pagina entera con scroll")], timeout_s=60)
    def _pagina_captura(args, ctx):
        sel, o = PC.partir_args(args, ["salida", "completa"])
        completa = str(o.get("completa", "")).strip() in ("1", "si", "true", "on")
        png = PC.ruta_salida(ctx, "pagina_" + (re.sub(r"\W+", "_", sel)[:20] if sel else "captura"),
                             ".png", o.get("salida", ""))

        def _run():
            _requiere_pagina()
            if sel:
                el = _S.pg.query_selector(sel)
                if el is None:
                    raise ValueError("no hay ningun elemento que case con %r" % sel)
                el.screenshot(path=str(png))
            else:
                _S.pg.screenshot(path=str(png), full_page=completa)
        try:
            _S.llamar(_run, 55)
            info = PC.texto_resumen_imagen(PC.resumen_imagen(png))
        except ValueError as exc:
            return "RESULTADO pagina_captura ERROR: %s" % exc
        except Exception as exc:
            return "RESULTADO pagina_captura ERROR: %s: %s" % (type(exc).__name__, str(exc)[:220])
        _sellar("captura", str(png))
        return "RESULTADO pagina_captura: captura en %s · %s" % (png, info)

    @tool("pagina_consola",
          "pagina_consola [| limpiar=1]  -- mensajes de consola acumulados de la pagina (errores primero)",
          desc="Lista los mensajes de consola y excepciones acumulados desde pagina_abrir (tipo, texto, "
               "url:linea), errores y excepciones primero. limpiar=1 vacia la lista tras mostrarla.",
          params=[P("limpiar", "integer", "1 = vaciar tras mostrar")], timeout_s=30)
    def _pagina_consola(args, ctx):
        _, o = PC.partir_args(args, ["limpiar"])
        if _S.pg is None:
            return "RESULTADO pagina_consola ERROR: no hay pagina abierta: primero pagina_abrir"
        filas = list(_S.consola)
        errs = [c for c in filas if c["tipo"] in ("error", "excepcion")]
        resto = [c for c in filas if c["tipo"] not in ("error", "excepcion")]
        if str(o.get("limpiar", "")).strip() in ("1", "si", "true", "on"):
            _S.consola.clear(); _S.vistos = 0
        if not filas:
            return "RESULTADO pagina_consola: consola vacia (0 mensajes)"
        lineas = ["%d mensaje(s): %d error(es)/excepcion(es), %d otros" % (len(filas), len(errs), len(resto))]
        for c in (errs + resto)[:40]:
            loc = (" [%s:%s]" % (c["url"][-50:], c["linea"])) if c.get("url") else ""
            lineas.append("  %s: %s%s" % (c["tipo"], c["texto"][:220], loc))
        _sellar("consola", lineas[0])
        return "RESULTADO pagina_consola: " + "\n".join(lineas)

    @tool("pagina_red",
          "pagina_red [| fallos=1]  -- peticiones de red acumuladas (metodo, url, status, tipo, bytes); fallos=1 solo las fallidas",
          desc="Lista las peticiones HTTP que hizo la pagina desde pagina_abrir: metodo, URL, status, tipo "
               "de recurso y tamano, con 'N peticiones, M fallidas' delante. fallos=1 muestra solo las "
               "fallidas (status >= 400 o sin respuesta). Para cazar recursos rotos, 404 y CORS.",
          params=[P("fallos", "integer", "1 = solo fallidas")], timeout_s=30)
    def _pagina_red(args, ctx):
        _, o = PC.partir_args(args, ["fallos"])
        if _S.pg is None:
            return "RESULTADO pagina_red ERROR: no hay pagina abierta: primero pagina_abrir"
        filas = list(_S.red)
        fallidas = [f for f in filas if f.get("fallo")]
        solo_fallos = str(o.get("fallos", "")).strip() in ("1", "si", "true", "on")
        cab = "%d peticion(es), %d fallida(s)" % (len(filas), len(fallidas))
        mostrar = fallidas if solo_fallos else (fallidas + [f for f in filas if not f.get("fallo")])
        lineas = [cab]
        for f in mostrar[:50]:
            st = ("HTTP %d" % f["status"]) if f.get("status") else ("FALLO %s" % (f.get("detalle") or "sin respuesta")[:60])
            # la COLA de la URL es la que nombra el fichero: al recortar se conserva
            u = f["url"] if len(f["url"]) <= 120 else ("..." + f["url"][-117:])
            lineas.append("  %s %s %s %s%s" % (f["metodo"], u, st, f["tipo"],
                                              (" %dB" % f["bytes"]) if f.get("bytes") else ""))
        _sellar("red", cab)
        return "RESULTADO pagina_red: " + "\n".join(lineas)

    @tool("pagina_enlaces",
          "pagina_enlaces  -- comprueba enlaces, imagenes, hojas y scripts de la pagina: rotos vs ok, imagenes sin alt",
          desc="Recorre <a href>, <img src>, <link href> y <script src> de la pagina abierta y comprueba "
               "cada URL (HEAD/GET con 5 s de timeout, maximo 60; file:// por existencia). Devuelve los "
               "rotos con su motivo, cuantos estan bien, las imagenes que no cargaron (naturalWidth 0) y "
               "las imagenes sin alt.",
          params=[], timeout_s=120)
    def _pagina_enlaces(args, ctx):
        def _run():
            _requiere_pagina()
            return _S.pg.evaluate(_JS_RECURSOS)
        try:
            recursos = _S.llamar(_run, 55) or []
        except ValueError as exc:
            return "RESULTADO pagina_enlaces ERROR: %s" % exc
        except Exception as exc:
            return "RESULTADO pagina_enlaces ERROR: %s: %s" % (type(exc).__name__, str(exc)[:220])
        vistos, rotos, ok, sin_alt, img_rotas = set(), [], 0, [], []
        for r in recursos:
            url = r.get("url") or ""
            if r.get("tipo") == "img":
                if r.get("alt") is None:
                    sin_alt.append(url[-80:])
                if r.get("rota"):
                    img_rotas.append(url[-80:])
            if url in vistos or url.startswith(("javascript:", "mailto:", "#", "data:", "blob:")):
                continue
            if url.startswith(_S.uri) and "#" in url and url.split("#")[0] == _S.uri:
                continue         # ancla interna
            vistos.add(url)
            if len(vistos) > 60:
                break
            bien, det = _comprobar_url(url)
            if bien:
                ok += 1
            else:
                rotos.append("%s %s (%s)" % (r.get("tipo"), url[-100:], det))
        partes = ["%d recurso(s) comprobado(s): %d ok, %d roto(s)" % (len(vistos), ok, len(rotos))]
        if rotos:
            partes.append("ROTOS: " + " | ".join(rotos[:20]))
        if img_rotas:
            partes.append("imagenes que no cargaron: " + ", ".join(img_rotas[:10]))
        if sin_alt:
            partes.append("%d imagen(es) sin alt: %s" % (len(sin_alt), ", ".join(sin_alt[:6])))
        _sellar("enlaces", partes[0])
        return "RESULTADO pagina_enlaces: " + " · ".join(partes)

    @tool("pagina_responsive",
          "pagina_responsive [| anchos=360,768,1280] [| salida=X.png]  -- captura a varios anchos y detecta desbordamiento horizontal",
          desc="Redimensiona el viewport a cada ancho (default 360, 768 y 1280 px), captura, comprueba si "
               "la pagina desborda horizontalmente (scrollWidth > innerWidth) y devuelve un MOSAICO PNG "
               "con las capturas etiquetadas y el veredicto por ancho. Restaura el ancho original.",
          params=[P("anchos", "string", "anchos separados por coma (default 360,768,1280)"),
                  P("salida", "string", "ruta del mosaico PNG")], timeout_s=120)
    def _pagina_responsive(args, ctx):
        _, o = PC.partir_args(args, ["anchos", "salida"])
        try:
            anchos = [max(200, min(4000, int(a))) for a in re.split(r"[,\s]+", o.get("anchos", "") or "360,768,1280") if a.strip()]
        except ValueError:
            return "RESULTADO pagina_responsive ERROR: anchos tiene que ser una lista de enteros"
        anchos = anchos[:6] or [360, 768, 1280]
        carpeta = PC.carpeta_salida(ctx)
        salida = PC.ruta_salida(ctx, "responsive", ".png", o.get("salida", ""))

        def _run():
            _requiere_pagina()
            pg = _S.pg
            out = []
            for a in anchos:
                pg.set_viewport_size({"width": a, "height": _S.alto})
                pg.wait_for_timeout(250)
                m = pg.evaluate(_JS_DESBORDE)
                p = carpeta / ("responsive_%d_%s.png" % (a, time.strftime("%H%M%S")))
                pg.screenshot(path=str(p), full_page=False)
                out.append((a, m, str(p)))
            pg.set_viewport_size({"width": _S.ancho, "height": _S.alto})
            return out
        try:
            filas = _S.llamar(_run, 110)
            etiquetas = ["%dpx %s" % (a, "DESBORDA" if m["sw"] > m["iw"] + 1 else "ok") for a, m, _ in filas]
            PC.mosaico([p for _, _, p in filas], salida, etiquetas, celda=380)
        except ValueError as exc:
            return "RESULTADO pagina_responsive ERROR: %s" % exc
        except Exception as exc:
            return "RESULTADO pagina_responsive ERROR: %s: %s" % (type(exc).__name__, str(exc)[:220])
        veredictos = []
        for a, m, p in filas:
            desb = m["sw"] > m["iw"] + 1
            veredictos.append("%dpx: %s (scrollWidth %d vs ancho %d)%s" % (
                a, "DESBORDA horizontalmente" if desb else "sin desbordamiento", m["sw"], m["iw"],
                " -> " + Path(p).name))
        _sellar("responsive", str(salida))
        return "RESULTADO pagina_responsive: mosaico en %s · %s" % (salida, " · ".join(veredictos))

    @tool("pagina_fotogramas",
          "pagina_fotogramas [| n=6] [| cada=250] [| salida=X.png]  -- N capturas en el tiempo: dice si la pagina anima, esta estatica o parpadea",
          desc="Toma N capturas separadas `cada` ms de la pagina abierta, mide la fraccion de pixeles que "
               "cambia entre consecutivas y devuelve un mosaico etiquetado t=ms mas el veredicto: ANIMA "
               "(cambio sostenido), ESTATICA (sin cambio) o PARPADEA (cambios grandes alternos). Para "
               "comprobar que un juego/canvas/animacion se mueve de verdad.",
          params=[P("n", "integer", "numero de capturas (2-12, default 6)"),
                  P("cada", "integer", "ms entre capturas (default 250)"),
                  P("salida", "string", "ruta del mosaico PNG")], timeout_s=120)
    def _pagina_fotogramas(args, ctx):
        _, o = PC.partir_args(args, ["n", "cada", "salida"])
        n = PC.entero(o.get("n"), 6, 2, 12)
        cada = PC.entero(o.get("cada"), 250, 30, 5000)
        carpeta = PC.carpeta_salida(ctx)
        salida = PC.ruta_salida(ctx, "fotogramas", ".png", o.get("salida", ""))

        def _run():
            _requiere_pagina()
            pg = _S.pg
            fotos, rutas = [], []
            t0 = time.perf_counter()
            for i in range(n):
                b = pg.screenshot(full_page=False)
                p = carpeta / ("fotograma_%02d_%s.png" % (i, time.strftime("%H%M%S")))
                p.write_bytes(b)
                fotos.append((int((time.perf_counter() - t0) * 1000), b))
                rutas.append(str(p))
                if i < n - 1:
                    pg.wait_for_timeout(cada)
            return fotos, rutas
        try:
            fotos, rutas = _S.llamar(_run, 110)
        except ValueError as exc:
            return "RESULTADO pagina_fotogramas ERROR: %s" % exc
        except Exception as exc:
            return "RESULTADO pagina_fotogramas ERROR: %s: %s" % (type(exc).__name__, str(exc)[:220])
        cambios = []
        for i in range(1, len(fotos)):
            cambios.append(_cambio(fotos[i - 1][1], fotos[i][1]))
        medibles = [c for c in cambios if c is not None]
        if not medibles:
            veredicto = "cambio no medible"
        elif all(c < UMBRAL_CAMBIO for c in medibles):
            veredicto = "ESTATICA (nada cambia entre capturas)"
        elif max(medibles) > 0.5 and sum(1 for c in medibles if c < UMBRAL_CAMBIO) >= 1:
            veredicto = "PARPADEA (cambios grandes alternados con quietud)"
        elif all(c >= UMBRAL_CAMBIO for c in medibles):
            veredicto = "ANIMA (cambio sostenido, media %.1f%% de pixeles)" % (100 * sum(medibles) / len(medibles))
        else:
            veredicto = "se mueve A RATOS (%d de %d intervalos con cambio)" % (
                sum(1 for c in medibles if c >= UMBRAL_CAMBIO), len(medibles))
        try:
            PC.mosaico(rutas, salida, ["t=%dms" % t for t, _ in fotos], celda=300)
        except Exception as exc:
            return "RESULTADO pagina_fotogramas ERROR: mosaico: %s" % exc
        det = ", ".join(("%.1f%%" % (c * 100)) if c is not None else "?" for c in cambios)
        _sellar("fotogramas", veredicto)
        return ("RESULTADO pagina_fotogramas: %s · cambio entre capturas: %s · mosaico en %s"
                % (veredicto, det, salida))

    @tool("pagina_accesibilidad",
          "pagina_accesibilidad  -- imagenes sin alt, inputs sin label, controles sin texto, headings, contraste, lang, titulo",
          desc="Chequeo rapido de accesibilidad de la pagina abierta: imagenes sin alt, inputs sin label ni "
               "aria-label, botones/enlaces sin texto accesible, headings que saltan nivel, textos con "
               "contraste WCAG < 4.5:1 (hasta 200 elementos), html sin lang y pagina sin titulo. Devuelve "
               "el conteo por problema y hasta 5 ejemplos con selector.",
          params=[], timeout_s=60)
    def _pagina_accesibilidad(args, ctx):
        def _run():
            _requiere_pagina()
            return _S.pg.evaluate(_JS_ACCESIBILIDAD)
        try:
            r = _S.llamar(_run, 55) or {}
        except ValueError as exc:
            return "RESULTADO pagina_accesibilidad ERROR: %s" % exc
        except Exception as exc:
            return "RESULTADO pagina_accesibilidad ERROR: %s: %s" % (type(exc).__name__, str(exc)[:220])
        prob = r.get("problemas") or {}
        glob = r.get("globales") or []
        total = sum(len(v) for v in prob.values()) + len(glob)
        partes = ["%d problema(s) (%d textos revisados)" % (total, r.get("textos_revisados", 0))]
        for k, v in prob.items():
            partes.append("%s x%d: %s" % (k, len(v), ", ".join(v[:5])))
        if glob:
            partes.append("globales: " + "; ".join(glob))
        if total == 0:
            partes.append("sin problemas detectados por estos chequeos")
        _sellar("accesibilidad", partes[0])
        return "RESULTADO pagina_accesibilidad: " + " · ".join(partes)

    @tool("pagina_servir",
          "pagina_servir <directorio> [| puerto=0]  -- sirve un directorio por HTTP en 127.0.0.1 y devuelve la URL",
          desc="Arranca un servidor HTTP estatico (en un hilo, sin ventana) que sirve el directorio dado en "
               "127.0.0.1:puerto (0 = puerto libre) y devuelve la URL. Necesario para paginas con modulos "
               "ES (type=module), fetch() o rutas absolutas, que NO funcionan desde file://. Luego "
               "pagina_abrir <URL>/index.html. Se para con pagina_cerrar.",
          params=[P("directorio", "string", "carpeta a servir", True, False),
                  P("puerto", "integer", "puerto (default 0 = libre)")], timeout_s=30)
    def _pagina_servir(args, ctx):
        d, o = PC.partir_args(args, ["puerto"])
        d = d or "."
        try:
            ruta = PC.resolver_ruta(d)
            if not ruta.is_dir():
                return "RESULTADO pagina_servir ERROR: %s no es un directorio" % ruta
            url = _arrancar_servidor(ruta, PC.entero(o.get("puerto"), 0, 0, 65535))
        except ValueError as exc:
            return "RESULTADO pagina_servir ERROR: %s" % exc
        except OSError as exc:
            return "RESULTADO pagina_servir ERROR: no se pudo abrir el puerto: %s" % exc
        _sellar("servir", url)
        return ("RESULTADO pagina_servir: sirviendo %s en %s · abre con pagina_abrir %s<fichero.html>"
                % (ruta, url, url))

    @tool("pagina_cerrar",
          "pagina_cerrar  -- cierra la sesion del navegador y el servidor estatico",
          desc="Cierra el Chromium de la sesion pagina_* y para el servidor de pagina_servir. Llamala al "
               "terminar de probar para liberar memoria.",
          params=[], timeout_s=40)
    def _pagina_cerrar(args, ctx):
        cerrado = cerrar_todo()
        _sellar("cerrar", ", ".join(cerrado))
        if not cerrado:
            return "RESULTADO pagina_cerrar: no habia nada abierto"
        return "RESULTADO pagina_cerrar: cerrado " + ", ".join(cerrado)

    @tool("pagina_estado",
          "pagina_estado  -- hay sesion abierta?, URL, titulo, mensajes de consola, peticiones, servidor",
          desc="Estado de la sesion pagina_*: si hay navegador abierto, que URL y titulo tiene, cuantos "
               "mensajes de consola y peticiones de red lleva, y si hay servidor estatico corriendo.",
          params=[], timeout_s=30)
    def _pagina_estado(args, ctx):
        d = disponibilidad()
        if not d["playwright"]:
            return "RESULTADO pagina_estado: Playwright NO instalado (pip install playwright && playwright install chromium)"
        if not d["sesion"]:
            srv = (" · servidor: %s" % d["servidor"]) if d["servidor"] else ""
            return "RESULTADO pagina_estado: sin sesion abierta (usa pagina_abrir)%s" % srv
        try:
            titulo = _S.llamar(lambda: _S.pg.title(), 15)
        except Exception as exc:
            titulo = "(titulo ilegible: %s)" % str(exc)[:60]
        errs = sum(1 for c in _S.consola if c["tipo"] in ("error", "excepcion"))
        return ("RESULTADO pagina_estado: sesion abierta · %s · titulo: %s · consola: %d mensajes (%d errores) · "
                "red: %d peticiones (%d fallidas)%s" % (
                    _S.fuente or _S.uri, titulo[:80], len(_S.consola), errs, len(_S.red),
                    sum(1 for f in _S.red if f.get("fallo")),
                    (" · servidor: %s" % d["servidor"]) if d["servidor"] else ""))


def _atexit():
    try:
        cerrar_todo()
    except Exception:
        pass        # el proceso ya se va; no hay a quien avisar


atexit.register(_atexit)
