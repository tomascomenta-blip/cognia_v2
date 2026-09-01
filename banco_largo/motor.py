# -*- coding: utf-8 -*-
"""motor.py -- el MOTOR DE PRUEBAS del banco: comprueba el PRODUCTO, no el texto.

POR QUE EXISTE
    Un banco que puntua la respuesta del agente mide prosa. Este motor abre lo que
    el agente dejo en disco y lo EJECUTA: sirve el HTML y lo abre en Chromium real,
    corre el .py, arranca el servidor y le pega peticiones, teclea en el juego y
    mira si el canvas cambia. Lo que diga el agente no entra aqui.

CONTRATO
    Una prueba es un dict {"tipo": ..., ...}. `correr_prueba(spec, ws)` devuelve
    siempre un dict con al menos {ok, tipo, detalle, ms}; NUNCA lanza. Un motor que
    revienta convierte un producto sano en un cero.

TIPOS (genericos: ninguno sabe de que tarea viene)
    fichero        glob + tamano minimo + regex que debe/no debe aparecer
    python         ejecuta el interprete del banco con argumentos
    nodo           ejecuta node
    pytest         corre pytest dentro del workspace
    http_servidor  arranca un proceso servidor, espera al puerto, pega peticiones
    web            sirve el workspace, abre Chromium, actua y afirma
    dos_pasadas    repite otra prueba dos veces (regresion / no determinismo)
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PY_BANCO = str(RAIZ / "venv312" / "Scripts" / "python.exe")
if not Path(PY_BANCO).exists():
    PY_BANCO = sys.executable
NODE = shutil.which("node") or "node"

TOPE_SALIDA = 4000


def _recorta(texto, tope=TOPE_SALIDA):
    texto = texto or ""
    if len(texto) <= tope:
        return texto
    return texto[: tope // 2] + "\n...[recortado]...\n" + texto[-tope // 2:]


def _puerto_libre():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _espera_puerto(puerto, timeout=25.0):
    fin = time.time() + timeout
    while time.time() < fin:
        try:
            with socket.create_connection(("127.0.0.1", puerto), timeout=1.0):
                return True
        except OSError:
            time.sleep(0.25)
    return False


# -- servidor estatico -------------------------------------------------------

class ServidorEstatico:
    """Sirve un directorio en un puerto efimero. Silencioso."""

    def __init__(self, directorio):
        self.dir = str(directorio)
        self.puerto = _puerto_libre()
        self._httpd = None
        self._hilo = None

    def __enter__(self):
        from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

        raiz = self.dir

        class H(SimpleHTTPRequestHandler):
            def __init__(self, *a, **kw):
                super().__init__(*a, directory=raiz, **kw)

            def log_message(self, *a):
                pass

        self._httpd = ThreadingHTTPServer(("127.0.0.1", self.puerto), H)
        self._hilo = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._hilo.start()
        _espera_puerto(self.puerto, 10)
        return self

    def __exit__(self, *a):
        try:
            self._httpd.shutdown()
            self._httpd.server_close()
        except Exception:
            pass
        return False

    @property
    def base(self):
        return "http://127.0.0.1:%d" % self.puerto


# -- utilidades de ficheros --------------------------------------------------

def buscar(ws, patron):
    """glob relativo al workspace; devuelve lista de Path ordenada."""
    ws = Path(ws)
    try:
        return sorted(p for p in ws.glob(patron) if p.is_file())
    except Exception:
        return []


def _leer(p, tope=400000):
    try:
        return Path(p).read_text(encoding="utf-8", errors="replace")[:tope]
    except Exception:
        return ""


# -- ejecucion de procesos ---------------------------------------------------

def _correr(cmd, cwd, timeout, entrada=None, env_extra=None):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    if env_extra:
        env.update(env_extra)
    t0 = time.time()
    try:
        pr = subprocess.run(cmd, cwd=str(cwd), capture_output=True, timeout=timeout,
                            input=entrada, text=True, encoding="utf-8",
                            errors="replace", env=env, shell=False)
        return {"exit": pr.returncode, "out": pr.stdout or "", "err": pr.stderr or "",
                "ms": int((time.time() - t0) * 1000), "timeout": False}
    except subprocess.TimeoutExpired as e:
        salida = e.stdout if isinstance(e.stdout, str) else ""
        return {"exit": -9, "out": salida, "err": "TIMEOUT tras %ss" % timeout,
                "ms": int((time.time() - t0) * 1000), "timeout": True}
    except Exception as e:
        return {"exit": -1, "out": "", "err": "%s: %s" % (type(e).__name__, e),
                "ms": int((time.time() - t0) * 1000), "timeout": False}


# -- pruebas -----------------------------------------------------------------

def _p_fichero(spec, ws):
    patron = spec.get("glob") or spec.get("ruta") or ""
    encontrados = buscar(ws, patron)
    if not encontrados:
        return False, "no existe ningun fichero que case con %s" % patron
    minimo = int(spec.get("min_bytes") or 0)
    grandes = [p for p in encontrados if p.stat().st_size >= minimo]
    if not grandes:
        tam = ", ".join("%s=%dB" % (p.name, p.stat().st_size) for p in encontrados[:5])
        return False, "existe pero por debajo de %d bytes (%s)" % (minimo, tam)
    texto = "\n".join(_leer(p) for p in grandes[:6])
    for pat in spec.get("contiene") or []:
        if not re.search(pat, texto, re.I | re.S):
            return False, "falta el patron %r en %s" % (pat, patron)
    for pat in spec.get("no_contiene") or []:
        if re.search(pat, texto, re.I | re.S):
            return False, "aparece el patron prohibido %r en %s" % (pat, patron)
    minlineas = int(spec.get("min_lineas") or 0)
    if minlineas:
        total = sum(len(_leer(p).splitlines()) for p in grandes)
        if total < minlineas:
            return False, "%d lineas < %d exigidas" % (total, minlineas)
    return True, "%d fichero(s), %d bytes" % (len(grandes),
                                              sum(p.stat().st_size for p in grandes))


def _p_proceso(spec, ws, binario):
    args = [str(a) for a in (spec.get("args") or [])]
    entrada = spec.get("stdin")
    timeout = float(spec.get("timeout") or 90)
    cwd = Path(ws) / (spec.get("cwd") or ".")
    entry = spec.get("entry")
    cmd = [binario]
    if spec.get("modulo"):
        cmd += ["-m", spec["modulo"]]
    elif entry:
        encontrados = buscar(ws, entry)
        if not encontrados:
            alt = buscar(ws, "**/" + entry)
            encontrados = alt
        if not encontrados:
            return False, "no existe el punto de entrada %s" % entry, {}
        cmd += [str(encontrados[0])]
    cmd += args
    r = _correr(cmd, cwd if cwd.exists() else ws, timeout, entrada)
    salida = (r["out"] or "") + "\n" + (r["err"] or "")
    esperado = spec.get("exit")
    esperado = 0 if esperado is None else int(esperado)
    if r["exit"] != esperado:
        return False, "exit=%s (esperado %s)\n%s" % (r["exit"], esperado,
                                                     _recorta(salida, 1200)), r
    for pat in spec.get("stdout_re") or []:
        if not re.search(pat, salida, re.I | re.S):
            return False, "la salida no casa con %r\n%s" % (pat, _recorta(salida, 1200)), r
    for pat in spec.get("no_stdout_re") or []:
        if re.search(pat, salida, re.I | re.S):
            return False, "la salida contiene lo prohibido %r" % pat, r
    return True, "exit=%d en %dms" % (r["exit"], r["ms"]), r


def _p_pytest(spec, ws):
    destino = spec.get("ruta") or "."
    timeout = float(spec.get("timeout") or 300)
    cmd = [PY_BANCO, "-m", "pytest", destino, "-q", "--no-header", "--tb=line", "-p", "no:cacheprovider"]
    r = _correr(cmd, ws, timeout)
    salida = (r["out"] or "") + (r["err"] or "")
    m = re.search(r"(\d+) passed", salida)
    pasados = int(m.group(1)) if m else 0
    m2 = re.search(r"(\d+) failed", salida)
    fallados = int(m2.group(1)) if m2 else 0
    minimo = int(spec.get("min_tests") or 1)
    datos = {"passed": pasados, "failed": fallados}
    if r["exit"] != 0:
        return False, "pytest exit=%s (%d passed, %d failed)\n%s" % (
            r["exit"], pasados, fallados, _recorta(salida, 1500)), datos
    if pasados < minimo:
        return False, "solo %d tests pasados (<%d)" % (pasados, minimo), datos
    return True, "%d tests en verde" % pasados, datos


def _p_http(spec, ws):
    """Arranca un servidor del producto y le pega peticiones reales."""
    import urllib.error
    import urllib.request

    puerto = _puerto_libre()
    binario = {"python": PY_BANCO, "node": NODE}.get(spec.get("binario", "python"), PY_BANCO)
    if spec.get("entry"):
        encontrados = buscar(ws, spec["entry"]) or buscar(ws, "**/" + spec["entry"])
        if not encontrados:
            return False, "no existe el servidor %s" % spec["entry"], {}
        cmd = [binario, str(encontrados[0])]
    elif spec.get("modulo"):
        cmd = [binario, "-m", spec["modulo"]]
    else:
        return False, "prueba http sin entry ni modulo", {}
    cmd += [str(a).replace("{puerto}", str(puerto)) for a in (spec.get("args") or [])]
    env = dict(os.environ)
    env["PORT"] = str(puerto)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    pr = None
    try:
        pr = subprocess.Popen(cmd, cwd=str(ws), stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                              errors="replace", env=env)
        if not _espera_puerto(puerto, float(spec.get("espera") or 25)):
            salida = ""
            try:
                pr.kill()
                salida = pr.stdout.read() if pr.stdout else ""
            except Exception:
                pass
            return False, "el servidor no abrio el puerto %d\n%s" % (
                puerto, _recorta(salida, 1200)), {}
        fallos = []
        hechas = 0
        peticiones = spec.get("peticiones") or []
        for pet in peticiones:
            url = "http://127.0.0.1:%d%s" % (puerto, pet.get("ruta", "/"))
            datos = pet.get("cuerpo")
            if isinstance(datos, (dict, list)):
                cuerpo = json.dumps(datos).encode()
            elif isinstance(datos, str):
                cuerpo = datos.encode()
            else:
                cuerpo = None
            req = urllib.request.Request(url, data=cuerpo, method=pet.get("metodo", "GET"))
            cabeceras = pet.get("cabeceras") or {"Content-Type": "application/json"}
            for k, v in cabeceras.items():
                req.add_header(k, v)
            try:
                with urllib.request.urlopen(req, timeout=float(pet.get("timeout") or 20)) as resp:
                    codigo, texto = resp.status, resp.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as e:
                codigo, texto = e.code, e.read().decode("utf-8", "replace")
            except Exception as e:
                fallos.append("%s %s -> %s" % (pet.get("metodo", "GET"), pet.get("ruta"), e))
                continue
            hechas += 1
            esp = pet.get("status")
            if esp is not None and codigo != int(esp):
                fallos.append("%s -> %s (esperado %s)" % (pet.get("ruta"), codigo, esp))
            for pat in pet.get("re") or []:
                if not re.search(pat, texto, re.I | re.S):
                    fallos.append("%s: sin %r (%s)" % (pet.get("ruta"), pat, _recorta(texto, 200)))
        if fallos:
            return False, "%d fallos de %d peticiones: %s" % (
                len(fallos), len(peticiones), " | ".join(fallos[:6])), {"peticiones": hechas}
        return True, "%d peticiones OK contra el servidor real" % hechas, {"peticiones": hechas}
    finally:
        if pr is not None:
            try:
                pr.terminate()
                pr.wait(timeout=5)
            except Exception:
                try:
                    pr.kill()
                except Exception:
                    pass


# -- web / canvas con Chromium real ------------------------------------------

_JS_CANVAS = """
() => {
  const cs = Array.from(document.querySelectorAll('canvas'));
  if (!cs.length) return {n:0, colores:0, pintado:0};
  let mejor = {n:cs.length, colores:0, pintado:0, firma:0};
  for (const c of cs) {
    try {
      let d = null;
      const ctx = c.getContext('2d');
      if (ctx) {
        d = ctx.getImageData(0,0,c.width,c.height).data;
      } else {
        const g = c.getContext('webgl') || c.getContext('webgl2') || c.getContext('experimental-webgl');
        if (!g) continue;
        d = new Uint8Array(c.width*c.height*4);
        g.readPixels(0,0,c.width,c.height,g.RGBA,g.UNSIGNED_BYTE,d);
      }
      const set = new Set(); let no0 = 0; let firma = 0; let k = 0;
      const paso = Math.max(4, Math.floor(d.length/40000)*4);
      for (let i=0;i<d.length;i+=paso) {
        set.add((d[i]<<16)|(d[i+1]<<8)|d[i+2]);
        if (d[i]|d[i+1]|d[i+2]) no0++;
        // firma posicional: dos imagenes con los mismos colores pero movidos
        // dan firmas distintas. Sin esto, un sprite que se desplaza parecia
        // una imagen estatica (cazado por autotest_motor.py, caso web-sana).
        k++;
        firma = (firma * 31 + (d[i] + 3*d[i+1] + 7*d[i+2]) * (k % 97)) % 2147483647;
      }
      if (set.size > mejor.colores || (set.size === mejor.colores && no0 > mejor.pintado))
        mejor = {n:cs.length, colores:set.size, pintado:no0, firma:firma};
    } catch(e) {}
  }
  return mejor;
}
"""


def _p_web(spec, ws):
    """Sirve el workspace, abre Chromium, ACTUA y afirma sobre DOM/canvas/consola."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        return False, "playwright no disponible: %s" % e, {}

    pagina = spec.get("pagina") or "index.html"
    encontrados = buscar(ws, pagina) or buscar(ws, "**/" + pagina)
    if not encontrados:
        return False, "no existe la pagina %s" % pagina, {}
    relativo = encontrados[0].relative_to(Path(ws)).as_posix()

    errores, avisos, hechos = [], [], []
    datos = {}
    with ServidorEstatico(ws) as srv, sync_playwright() as p:
        nav = p.chromium.launch(args=["--enable-unsafe-swiftshader", "--use-gl=swiftshader",
                                      "--no-sandbox"])
        ctx = nav.new_context(viewport={"width": int(spec.get("ancho") or 1280),
                                        "height": int(spec.get("alto") or 800)})
        pg = ctx.new_page()
        pg.on("console", lambda m: (errores if m.type == "error" else avisos).append(
            "%s: %s" % (m.type, m.text[:300])))
        pg.on("pageerror", lambda e: errores.append("pageerror: %s" % str(e)[:400]))
        try:
            pg.goto(srv.base + "/" + relativo, wait_until="load",
                    timeout=int(spec.get("timeout_carga") or 30000))
            pg.wait_for_timeout(int(spec.get("espera_ms") or 1200))
            for acc in spec.get("acciones") or []:
                t = acc.get("tipo")
                try:
                    if t == "click":
                        pg.click(acc["sel"], timeout=int(acc.get("timeout") or 5000))
                    elif t == "escribir":
                        pg.fill(acc["sel"], acc.get("texto", ""),
                                timeout=int(acc.get("timeout") or 5000))
                    elif t == "tecla":
                        for _ in range(int(acc.get("veces") or 1)):
                            pg.keyboard.press(acc["tecla"])
                            pg.wait_for_timeout(int(acc.get("entre") or 60))
                    elif t == "mantener":
                        pg.keyboard.down(acc["tecla"])
                        pg.wait_for_timeout(int(acc.get("ms") or 600))
                        pg.keyboard.up(acc["tecla"])
                    elif t == "raton":
                        pg.mouse.click(int(acc.get("x", 100)), int(acc.get("y", 100)),
                                       button=acc.get("boton", "left"))
                    elif t == "mover_raton":
                        pg.mouse.move(int(acc.get("x", 100)), int(acc.get("y", 100)))
                    elif t == "esperar":
                        pg.wait_for_timeout(int(acc.get("ms") or 500))
                    elif t == "js":
                        pg.evaluate(acc["codigo"])
                    elif t == "recargar":
                        pg.reload(wait_until="load")
                        pg.wait_for_timeout(int(acc.get("ms") or 1000))
                    hechos.append(t)
                except Exception as e:
                    if acc.get("opcional"):
                        avisos.append("accion opcional fallida %s: %s" % (t, str(e)[:150]))
                    else:
                        return False, "accion %s(%s) fallo: %s" % (
                            t, acc.get("sel") or acc.get("tecla"), str(e)[:250]), {"acciones": hechos}
            fallos = []
            for af in spec.get("afirmaciones") or []:
                t = af.get("tipo")
                try:
                    if t == "selector":
                        n = pg.locator(af["sel"]).count()
                        if n < int(af.get("min") or 1):
                            fallos.append("selector %s: %d < %s" % (af["sel"], n, af.get("min") or 1))
                    elif t == "texto":
                        cuerpo = pg.inner_text("body")
                        if not re.search(af["re"], cuerpo, re.I | re.S):
                            fallos.append("el texto de la pagina no casa con %r" % af["re"])
                    elif t == "js":
                        v = pg.evaluate(af["codigo"])
                        datos[af.get("nombre", "js")] = v
                        if af.get("igual") is not None:
                            if v != af["igual"]:
                                fallos.append("%s = %r != %r" % (af.get("nombre", "js"), v, af["igual"]))
                        elif af.get("min") is not None:
                            if not isinstance(v, (int, float)) or v < af["min"]:
                                fallos.append("%s = %r < %r" % (af.get("nombre", "js"), v, af["min"]))
                        elif not v:
                            fallos.append("%s es falso (%r)" % (af.get("nombre", "js"), v))
                    elif t == "canvas":
                        m = pg.evaluate(_JS_CANVAS)
                        datos["canvas"] = m
                        if m["n"] < 1:
                            fallos.append("no hay canvas en la pagina")
                        elif m["colores"] < int(af.get("min_colores") or 3):
                            fallos.append("el canvas casi no pinta: %d colores" % m["colores"])
                    elif t == "canvas_cambia":
                        a = pg.evaluate(_JS_CANVAS)
                        pg.wait_for_timeout(int(af.get("ms") or 900))
                        b = pg.evaluate(_JS_CANVAS)
                        datos["canvas_antes"], datos["canvas_despues"] = a, b
                        igual = (a.get("firma") == b.get("firma")
                                 and a.get("pintado") == b.get("pintado")
                                 and a.get("colores") == b.get("colores"))
                        if igual:
                            fallos.append("el canvas no cambia con el tiempo (imagen estatica)")
                except Exception as e:
                    fallos.append("afirmacion %s rompio: %s" % (t, str(e)[:200]))
            criticos = [e for e in errores if not re.search(r"favicon", e, re.I)]
            datos["errores_consola"] = criticos[:10]
            tope_err = spec.get("max_errores_consola")
            if tope_err is not None and len(criticos) > int(tope_err):
                fallos.append("%d errores de consola: %s" % (len(criticos), " | ".join(criticos[:3])))
            if spec.get("captura"):
                try:
                    pg.screenshot(path=str(Path(ws) / spec["captura"]))
                except Exception:
                    pass
            if fallos:
                return False, " | ".join(fallos[:8]), datos
            return True, "pagina viva: %d acciones, %d afirmaciones, %d errores de consola" % (
                len(hechos), len(spec.get("afirmaciones") or []), len(criticos)), datos
        finally:
            try:
                ctx.close()
                nav.close()
            except Exception:
                pass


def _p_dos_pasadas(spec, ws):
    interna = dict(spec.get("prueba") or {})
    r1 = correr_prueba(interna, ws)
    r2 = correr_prueba(interna, ws)
    if r1["ok"] and not r2["ok"]:
        return False, "REGRESION en la 2a pasada: %s" % r2["detalle"], {"p1": True, "p2": False}
    if not r1["ok"]:
        return False, "fallo ya en la 1a pasada: %s" % r1["detalle"], {"p1": False, "p2": r2["ok"]}
    return True, "estable en dos pasadas", {"p1": True, "p2": True}


def _envolver2(fn):
    def _f(s, w):
        ok, det = fn(s, w)
        return ok, det, {}
    return _f


_TIPOS = {
    "fichero": _envolver2(_p_fichero),
    "python": lambda s, w: _p_proceso(s, w, PY_BANCO),
    "nodo": lambda s, w: _p_proceso(s, w, NODE),
    "pytest": _p_pytest,
    "http_servidor": _p_http,
    "web": _p_web,
    "dos_pasadas": _p_dos_pasadas,
}

TIPOS_VALIDOS = tuple(_TIPOS)


def correr_prueba(spec, ws):
    """Ejecuta una prueba. NUNCA lanza."""
    t0 = time.time()
    spec = spec or {}
    tipo = spec.get("tipo", "?")
    fn = _TIPOS.get(tipo)
    if fn is None:
        return {"ok": False, "tipo": tipo, "nombre": spec.get("nombre", tipo),
                "capa": spec.get("capa", "funcionalidad"), "peso": 1.0,
                "detalle": "tipo de prueba desconocido", "ms": 0, "datos": {}}
    try:
        ok, detalle, datos = fn(spec, ws)
    except Exception as e:
        ok, detalle, datos = False, "el motor rompio: %s: %s" % (type(e).__name__, e), {}
    return {"ok": bool(ok), "tipo": tipo, "nombre": spec.get("nombre", tipo),
            "capa": spec.get("capa", "funcionalidad"), "peso": float(spec.get("peso") or 1.0),
            "detalle": _recorta(str(detalle), 1500), "ms": int((time.time() - t0) * 1000),
            "datos": datos}


def correr_suite(pruebas, ws):
    return [correr_prueba(p, ws) for p in (pruebas or [])]
