# -*- coding: utf-8 -*-
"""
cognia/agent/renderizador_guion.py
==================================
`renderizar ... | guion=...`: la captura deja de ser una foto y pasa a ser una
PRUEBA. Pedido del dueno (2026-09-04): "chequear incluso despues de input o
acciones que usualmente necesitan interaccion humana, renderizar despues de
ciertas teclas, mostrar ciertas variables antes y despues de las teclas".

Un guion es una lista de PASOS separados por ';' o saltos de linea:

    tecla <Tecla>[*N]          pulsa una tecla N veces (ArrowRight*5, Space, Enter, a)
    teclas a,b,c               varias teclas seguidas
    mantener <Tecla> <ms>      keydown, espera, keyup (un salto largo, correr)
    clic <selector> | clic x,y  clic en un elemento o en coordenadas del viewport
    dobleclic <selector>
    escribir <selector> "txt"  rellena un input/textarea (fill)
    tipear "texto"             teclea texto donde este el foco
    raton x,y                  mueve el puntero
    arrastrar x1,y1 x2,y2
    scroll <y>                 window.scrollTo(0, y)
    espera <ms>                pausa
    esperar <selector>         hasta que exista (o esperar "texto" hasta que aparezca)
    captura [nombre]           guarda un PNG en ese punto
    var <expr JS>              vigilar una expresion: se lee ANTES y DESPUES de cada accion
    js <codigo>                ejecutar JS en la pagina (util para leer estado o simular)
    assert <expr JS>           la expresion debe ser verdadera (o: assert texto contiene "x",
                               assert canvas cambia, assert sin errores)
    recargar

Que devuelve cada paso: que hizo, cuanto tardo, si la PANTALLA cambio (fraccion
de pixeles distintos frente a la captura anterior, reutilizando
program_creator.frames_gate), el valor ANTES -> DESPUES de cada variable
vigilada, los errores de consola NUEVOS que provoco y las capturas guardadas.
Al final: resumen del DOM y el MAPA DE INTERACCION (botones, enlaces, inputs con
un selector utilizable), para que el modelo sepa que puede tocar sin adivinar.

Solo Playwright (el backend de sistema no puede interactuar); si no esta, se
dice exactamente eso. Nunca lanza hacia la tool: devuelve `error` en el dict.
"""
from __future__ import annotations

import json
import re
import shlex
import time
from pathlib import Path

TIMEOUT_PASO_MS = 8000
MAX_PASOS = 60
MAX_VARS = 12
MAX_CAPTURAS = 12
UMBRAL_CAMBIO = 0.002       # fraccion de pixeles: por debajo, "la pantalla no cambio"

# Alias de teclas en castellano y variantes comunes -> nombres de Playwright.
_TECLAS = {
    "derecha": "ArrowRight", "izquierda": "ArrowLeft", "arriba": "ArrowUp", "abajo": "ArrowDown",
    "right": "ArrowRight", "left": "ArrowLeft", "up": "ArrowUp", "down": "ArrowDown",
    "espacio": "Space", "space": " ", "enter": "Enter", "intro": "Enter", "escape": "Escape",
    "esc": "Escape", "tab": "Tab", "retroceso": "Backspace", "backspace": "Backspace",
    "suprimir": "Delete", "delete": "Delete", "inicio": "Home", "fin": "End",
    "pagarriba": "PageUp", "pagabajo": "PageDown", "shift": "Shift", "ctrl": "Control",
    "control": "Control", "alt": "Alt",
}

_JS_MAPA = """() => {
  const sel = 'button, a[href], input, select, textarea, [role=button], [onclick], summary, [tabindex]';
  const vis = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const selectorDe = el => {
    if (el.id) return '#' + el.id;
    if (el.name) return el.tagName.toLowerCase() + '[name="' + el.name + '"]';
    const t = (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().slice(0, 30);
    if (t && el.tagName !== 'INPUT') return 'text=' + JSON.stringify(t);
    const p = el.parentElement; if (!p) return el.tagName.toLowerCase();
    const i = Array.from(p.children).filter(c => c.tagName === el.tagName).indexOf(el) + 1;
    return el.tagName.toLowerCase() + ':nth-of-type(' + i + ')';
  };
  const out = [];
  for (const el of document.querySelectorAll(sel)) {
    if (!vis(el)) continue;
    const r = el.getBoundingClientRect();
    out.push({tag: el.tagName.toLowerCase(), tipo: el.type || '', selector: selectorDe(el),
              texto: (el.innerText || el.value || el.placeholder || el.getAttribute('aria-label') || '').trim().slice(0, 40),
              x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2)});
    if (out.length >= 25) break;
  }
  const canvas = document.querySelector('canvas');
  const teclado = !!(window.onkeydown || document.onkeydown || document.body && document.body.onkeydown);
  return {controles: out, canvas: !!canvas, focos: document.activeElement ? document.activeElement.tagName.toLowerCase() : '',
          teclado_global: teclado, titulo: document.title,
          texto: (document.body && document.body.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 400)};
}"""


class Paso:
    __slots__ = ("op", "args", "crudo")

    def __init__(self, op: str, args: list, crudo: str):
        self.op, self.args, self.crudo = op, args, crudo

    def __repr__(self) -> str:
        return f"Paso({self.op}, {self.args})"


def _tecla(nombre: str) -> str:
    n = (nombre or "").strip().strip("'\"")
    if not n:
        return "Enter"
    bajo = n.lower()
    if bajo in _TECLAS:
        return _TECLAS[bajo]
    if len(n) > 1 and bajo.startswith("arrow"):
        return "Arrow" + n[5:].capitalize()
    if len(n) > 1 and n[0].upper() == "F" and n[1:].isdigit():
        return n.upper()
    return n if len(n) == 1 else n[0].upper() + n[1:]


def parsear_guion(texto: str) -> list:
    """Texto -> lista de Paso. Lineas vacias y '#' se ignoran. Lanza ValueError con la linea mala."""
    pasos: list = []
    for crudo in re.split(r"[;\n]+", texto or ""):
        linea = crudo.strip()
        if not linea or linea.startswith("#"):
            continue
        op, _, resto = linea.partition(" ")
        op = op.lower()
        resto = resto.strip()
        if op in ("tecla", "key", "pulsar"):
            m = re.match(r"^(\S+?)(?:\s*[*x]\s*(\d+))?$", resto)
            if not m:
                raise ValueError(f"tecla: '{resto}' no es <Tecla>[*N]")
            pasos.append(Paso("tecla", [_tecla(m.group(1)), int(m.group(2) or 1)], linea))
        elif op == "teclas":
            pasos.append(Paso("teclas", [_tecla(t) for t in re.split(r"[,\s]+", resto) if t], linea))
        elif op in ("mantener", "hold"):
            partes = resto.split()
            if len(partes) < 2 or not partes[1].isdigit():
                raise ValueError(f"mantener: '{resto}' no es <Tecla> <ms>")
            pasos.append(Paso("mantener", [_tecla(partes[0]), int(partes[1])], linea))
        elif op in ("clic", "click", "dobleclic", "dblclick"):
            m = re.match(r"^(-?\d+)\s*,\s*(-?\d+)$", resto)
            args = [int(m.group(1)), int(m.group(2))] if m else [resto.strip("\"'")]
            pasos.append(Paso("dobleclic" if op in ("dobleclic", "dblclick") else "clic", args, linea))
        elif op in ("escribir", "fill", "rellenar"):
            try:
                partes = shlex.split(resto)
            except ValueError:
                partes = resto.split(None, 1)
            if len(partes) < 2:
                raise ValueError(f"escribir: '{resto}' no es <selector> \"texto\"")
            pasos.append(Paso("escribir", [partes[0], " ".join(partes[1:])], linea))
        elif op in ("tipear", "type", "teclear"):
            pasos.append(Paso("tipear", [resto.strip().strip("\"'")], linea))
        elif op in ("raton", "mouse"):
            m = re.match(r"^(-?\d+)\s*,\s*(-?\d+)$", resto)
            if not m:
                raise ValueError(f"raton: '{resto}' no es x,y")
            pasos.append(Paso("raton", [int(m.group(1)), int(m.group(2))], linea))
        elif op in ("arrastrar", "drag"):
            m = re.match(r"^(-?\d+)\s*,\s*(-?\d+)\s+(-?\d+)\s*,\s*(-?\d+)$", resto)
            if not m:
                raise ValueError(f"arrastrar: '{resto}' no es x1,y1 x2,y2")
            pasos.append(Paso("arrastrar", [int(g) for g in m.groups()], linea))
        elif op == "scroll":
            pasos.append(Paso("scroll", [int(resto or 0)], linea))
        elif op in ("espera", "wait", "dormir"):
            if not resto.isdigit():
                raise ValueError(f"espera: '{resto}' no es un numero de ms")
            pasos.append(Paso("espera", [min(int(resto), 20000)], linea))
        elif op in ("esperar", "waitfor"):
            pasos.append(Paso("esperar", [resto.strip()], linea))
        elif op in ("captura", "screenshot", "foto"):
            pasos.append(Paso("captura", [re.sub(r"[^A-Za-z0-9_.-]", "_", resto)[:30]], linea))
        elif op in ("var", "vigilar", "watch"):
            pasos.append(Paso("var", [resto], linea))
        elif op in ("js", "eval"):
            pasos.append(Paso("js", [resto], linea))
        elif op in ("assert", "afirmar", "comprobar"):
            pasos.append(Paso("assert", [resto], linea))
        elif op in ("recargar", "reload"):
            pasos.append(Paso("recargar", [], linea))
        else:
            raise ValueError(f"paso desconocido: '{linea}' (ops: tecla, teclas, mantener, clic, dobleclic, "
                             f"escribir, tipear, raton, arrastrar, scroll, espera, esperar, captura, var, js, assert, recargar)")
        if len(pasos) > MAX_PASOS:
            raise ValueError(f"el guion tiene mas de {MAX_PASOS} pasos")
    return pasos


def _fraccion_cambio(a: bytes, b: bytes):
    try:
        from cognia.program_creator.frames_gate import fraccion_pixeles_distintos
        return fraccion_pixeles_distintos(a, b)
    except Exception:
        return None


def _leer_vars(pg, exprs: list) -> dict:
    out = {}
    for e in exprs:
        try:
            v = pg.evaluate(f"() => {{ try {{ return JSON.stringify(({e})); }} catch (err) {{ return 'ERROR ' + err.message; }} }}")
            out[e] = (v if isinstance(v, str) else json.dumps(v))[:160] if v is not None else "undefined"
        except Exception as exc:
            out[e] = f"ERROR {type(exc).__name__}"
    return out


def _es_assert(pg, texto: str, texto_dom: str, cambio, errores_nuevos: int) -> tuple:
    """(ok, detalle) de un assert: JS, 'texto contiene "x"', 'canvas cambia', 'sin errores'."""
    t = texto.strip()
    bajo = t.lower()
    m = re.match(r'^texto\s+(contiene|no contiene)\s+"?(.+?)"?$', t, re.I)
    if m:
        esta = m.group(2).lower() in (texto_dom or "").lower()
        ok = esta if m.group(1).lower() == "contiene" else not esta
        return ok, f"texto {m.group(1)} {m.group(2)!r}: {'si' if esta else 'no'} esta"
    if bajo in ("canvas cambia", "pantalla cambia", "cambia"):
        return (cambio is not None and cambio >= UMBRAL_CAMBIO), f"cambio de pantalla = {cambio}"
    if bajo in ("canvas no cambia", "pantalla no cambia", "no cambia"):
        return (cambio is not None and cambio < UMBRAL_CAMBIO), f"cambio de pantalla = {cambio}"
    if bajo in ("sin errores", "no errores"):
        return errores_nuevos == 0, f"errores de consola hasta aqui = {errores_nuevos}"
    try:
        v = pg.evaluate(f"() => {{ try {{ return !!({t}); }} catch (err) {{ return 'ERROR ' + err.message; }} }}")
    except Exception as exc:
        return False, f"assert no evaluable: {type(exc).__name__}"
    if isinstance(v, str) and v.startswith("ERROR"):
        return False, v[:160]
    return bool(v), f"{t} -> {v}"


def correr_guion(uri: str, guion: str, *, vars_iniciales=(), ancho: int = 1100, alto: int = 720,
                 espera_ms: int = 800, salida_base=None, prefijo: str = "captura",
                 mapa: bool = True, captura_final: bool = True) -> dict:
    """Ejecuta el guion sobre `uri` con Playwright y devuelve un dict serializable.

    Claves: pasos [ {n, paso, ms, cambio, vars_antes, vars_despues, errores_nuevos,
    captura, assert_ok, detalle} ], capturas [rutas], errores [todos], vars_final,
    asserts {ok, fallidos}, mapa {...}, resumen {...}, error (si no pudo correr).
    """
    try:
        pasos = parsear_guion(guion or "")
    except ValueError as exc:
        return {"error": f"guion invalido: {exc}", "pasos": [], "capturas": []}
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        return {"error": f"un guion interactivo necesita Playwright (pip install playwright && playwright install "
                         f"chromium): {type(exc).__name__}", "pasos": [], "capturas": []}
    vars_exprs = [v for v in (vars_iniciales or ()) if v][:MAX_VARS]
    base = Path(str(salida_base)) if salida_base else Path.cwd() / ".cognia_capturas"
    base.mkdir(parents=True, exist_ok=True)
    errores: list = []
    resultados: list = []
    capturas: list = []
    asserts_fallidos: list = []
    n_asserts = 0
    t_total = time.perf_counter()
    with sync_playwright() as p:
        nav = p.chromium.launch(args=["--enable-unsafe-swiftshader", "--use-gl=swiftshader", "--no-sandbox"])
        try:
            pg = nav.new_page(viewport={"width": ancho, "height": alto})
            pg.set_default_timeout(TIMEOUT_PASO_MS)

            def _consola(m):
                try:
                    url = (m.location or {}).get("url", "") if hasattr(m, "location") else ""
                except Exception:
                    url = ""
                if "favicon" in (url or "").lower():
                    return
                if m.type == "error":
                    errores.append("consola: " + m.text[:220])
            pg.on("console", _consola)
            pg.on("pageerror", lambda e: errores.append("excepcion: " + str(e)[:300]))
            try:
                pg.goto(uri, wait_until="load", timeout=45000)
            except Exception as exc:
                return {"error": f"no se pudo abrir {uri}: {type(exc).__name__}: {str(exc)[:160]}",
                        "pasos": [], "capturas": [], "errores": errores}
            pg.wait_for_timeout(max(0, int(espera_ms)))
            # foco en el canvas o en el body para que las teclas lleguen al juego
            try:
                pg.evaluate("() => { const c = document.querySelector('canvas'); if (c) { c.setAttribute('tabindex','0'); c.focus(); } else if (document.body) { document.body.focus(); } }")
            except Exception:
                pass
            anterior_png = pg.screenshot(type="png")
            vars_ahora = _leer_vars(pg, vars_exprs)
            n_err = len(errores)
            texto_dom = ""
            for i, paso in enumerate(pasos, 1):
                t0 = time.perf_counter()
                detalle = ""
                assert_ok = None
                captura_ruta = ""
                cambio = None
                antes = dict(vars_ahora)
                accion = paso.op in ("tecla", "teclas", "mantener", "clic", "dobleclic", "escribir", "tipear",
                                     "raton", "arrastrar", "scroll", "js", "recargar", "esperar")
                try:
                    if paso.op == "tecla":
                        for _ in range(int(paso.args[1])):
                            pg.keyboard.press(paso.args[0])
                            pg.wait_for_timeout(40)
                        detalle = f"{paso.args[0]} x{paso.args[1]}"
                    elif paso.op == "teclas":
                        for k in paso.args:
                            pg.keyboard.press(k)
                            pg.wait_for_timeout(40)
                        detalle = ",".join(paso.args)
                    elif paso.op == "mantener":
                        pg.keyboard.down(paso.args[0])
                        pg.wait_for_timeout(int(paso.args[1]))
                        pg.keyboard.up(paso.args[0])
                        detalle = f"{paso.args[0]} {paso.args[1]} ms"
                    elif paso.op in ("clic", "dobleclic"):
                        if len(paso.args) == 2:
                            (pg.mouse.dblclick if paso.op == "dobleclic" else pg.mouse.click)(paso.args[0], paso.args[1])
                            detalle = f"en {paso.args[0]},{paso.args[1]}"
                        else:
                            loc = pg.locator(paso.args[0]).first
                            (loc.dblclick if paso.op == "dobleclic" else loc.click)(timeout=TIMEOUT_PASO_MS)
                            detalle = f"en {paso.args[0]}"
                    elif paso.op == "escribir":
                        pg.locator(paso.args[0]).first.fill(paso.args[1], timeout=TIMEOUT_PASO_MS)
                        detalle = f"{paso.args[0]} <- {paso.args[1][:40]!r}"
                    elif paso.op == "tipear":
                        pg.keyboard.type(paso.args[0], delay=20)
                        detalle = repr(paso.args[0][:40])
                    elif paso.op == "raton":
                        pg.mouse.move(paso.args[0], paso.args[1])
                        detalle = f"{paso.args[0]},{paso.args[1]}"
                    elif paso.op == "arrastrar":
                        x1, y1, x2, y2 = paso.args
                        pg.mouse.move(x1, y1)
                        pg.mouse.down()
                        pg.mouse.move(x2, y2, steps=8)
                        pg.mouse.up()
                        detalle = f"{x1},{y1} -> {x2},{y2}"
                    elif paso.op == "scroll":
                        pg.evaluate(f"() => window.scrollTo(0, {int(paso.args[0])})")
                        detalle = f"y={paso.args[0]}"
                    elif paso.op == "espera":
                        pg.wait_for_timeout(int(paso.args[0]))
                        detalle = f"{paso.args[0]} ms"
                    elif paso.op == "esperar":
                        obj = paso.args[0].strip()
                        if obj.startswith(("\"", "'")):
                            txt = obj.strip("\"'")
                            pg.wait_for_function("t => (document.body && document.body.innerText || '').includes(t)",
                                                 arg=txt, timeout=TIMEOUT_PASO_MS)
                            detalle = f"texto {txt!r} aparecio"
                        else:
                            pg.wait_for_selector(obj, timeout=TIMEOUT_PASO_MS)
                            detalle = f"{obj} existe"
                    elif paso.op == "captura":
                        if len(capturas) >= MAX_CAPTURAS:
                            detalle = "tope de capturas alcanzado"
                        else:
                            nombre = paso.args[0] or f"paso{i}"
                            ruta = base / f"{prefijo}_{nombre}_{time.strftime('%H%M%S')}_{i}.png"
                            pg.screenshot(path=str(ruta), full_page=False)
                            capturas.append(str(ruta))
                            captura_ruta = str(ruta)
                            detalle = str(ruta)
                    elif paso.op == "var":
                        if paso.args[0] not in vars_exprs and len(vars_exprs) < MAX_VARS:
                            vars_exprs.append(paso.args[0])
                        vars_ahora = _leer_vars(pg, vars_exprs)
                        detalle = f"{paso.args[0]} = {vars_ahora.get(paso.args[0])}"
                    elif paso.op == "js":
                        v = pg.evaluate(f"() => {{ try {{ return JSON.stringify(eval({json.dumps(paso.args[0])})); }} catch (err) {{ return 'ERROR ' + err.message; }} }}")
                        detalle = f"-> {str(v)[:160]}"
                    elif paso.op == "recargar":
                        pg.reload(wait_until="load")
                        pg.wait_for_timeout(int(espera_ms))
                        detalle = "recargada"
                    elif paso.op == "assert":
                        pass   # se evalua abajo con el cambio y las vars ya medidos
                except Exception as exc:
                    detalle = f"FALLO: {type(exc).__name__}: {str(exc).splitlines()[0][:160]}"
                # medicion tras el paso
                if accion:
                    pg.wait_for_timeout(60)
                    try:
                        ahora_png = pg.screenshot(type="png")
                        cambio = _fraccion_cambio(anterior_png, ahora_png)
                        anterior_png = ahora_png
                    except Exception:
                        cambio = None
                    vars_ahora = _leer_vars(pg, vars_exprs)
                errores_nuevos = len(errores) - n_err
                n_err = len(errores)
                if paso.op == "assert":
                    try:
                        texto_dom = pg.evaluate("() => (document.body && document.body.innerText || '').replace(/\\s+/g,' ').trim()")
                    except Exception:
                        texto_dom = ""
                    ultimo_cambio = next((r["cambio"] for r in reversed(resultados) if r.get("cambio") is not None), None)
                    # 'sin errores' mira el TOTAL acumulado: el error suele caer en la
                    # accion anterior, no en el paso del assert.
                    assert_ok, detalle = _es_assert(pg, paso.args[0], texto_dom, ultimo_cambio, len(errores))
                    n_asserts += 1
                    if not assert_ok:
                        asserts_fallidos.append(f"paso {i} {paso.crudo}: {detalle}")
                cambios_vars = {k: (antes.get(k), vars_ahora.get(k)) for k in vars_exprs
                                if accion and antes.get(k) != vars_ahora.get(k)}
                resultados.append({"n": i, "paso": paso.crudo, "ms": round((time.perf_counter() - t0) * 1000),
                                   "cambio": None if cambio is None else round(cambio, 4),
                                   "vars_antes": antes if accion else {}, "vars_despues": dict(vars_ahora) if accion else {},
                                   "vars_cambiadas": cambios_vars, "errores_nuevos": errores_nuevos,
                                   "captura": captura_ruta, "assert_ok": assert_ok, "detalle": detalle})
            final = {}
            if captura_final and len(capturas) < MAX_CAPTURAS:
                ruta = base / f"{prefijo}_final_{time.strftime('%H%M%S')}.png"
                pg.screenshot(path=str(ruta), full_page=False)
                capturas.append(str(ruta))
                final["captura_final"] = str(ruta)
            mapa_dict = {}
            if mapa:
                try:
                    mapa_dict = pg.evaluate(_JS_MAPA) or {}
                except Exception as exc:
                    mapa_dict = {"error": f"{type(exc).__name__}"}
            vars_final = _leer_vars(pg, vars_exprs)
        finally:
            nav.close()
    return {"pasos": resultados, "capturas": capturas, "errores": errores[:12], "vars_final": vars_final,
            "asserts": {"total": n_asserts, "fallidos": asserts_fallidos}, "mapa": mapa_dict,
            "ms": round((time.perf_counter() - t_total) * 1000), **final}


def texto_guion(r: dict) -> str:
    """El informe que lee el modelo: un renglon por paso + asserts + mapa de interaccion."""
    if r.get("error"):
        return "ERROR del guion: " + r["error"]
    lineas = []
    for p in r.get("pasos", []):
        partes = [f"[{p['n']}] {p['paso']}"]
        if p.get("detalle"):
            partes.append(p["detalle"])
        if p.get("cambio") is not None:
            partes.append("pantalla %s (%.1f %%)" % ("CAMBIO" if p["cambio"] >= UMBRAL_CAMBIO else "igual", p["cambio"] * 100))
        if p.get("vars_cambiadas"):
            partes.append("vars: " + "; ".join(f"{k}: {a} -> {b}" for k, (a, b) in p["vars_cambiadas"].items()))
        elif p.get("vars_despues") and p.get("paso", "").split(" ")[0] not in ("var",):
            partes.append("vars sin cambio")
        if p.get("errores_nuevos"):
            partes.append(f"{p['errores_nuevos']} error(es) de JS NUEVOS")
        if p.get("assert_ok") is not None:
            partes.insert(1, "OK" if p["assert_ok"] else "FALLA")
        lineas.append(" · ".join(partes))
    a = r.get("asserts") or {}
    if a.get("total"):
        lineas.append(f"asserts: {a['total'] - len(a.get('fallidos', []))}/{a['total']} OK"
                      + ("" if not a.get("fallidos") else " · FALLAN: " + " | ".join(a["fallidos"][:4])))
    if r.get("vars_final"):
        lineas.append("vars al final: " + "; ".join(f"{k} = {v}" for k, v in r["vars_final"].items()))
    if r.get("errores"):
        lineas.append(f"{len(r['errores'])} error(es) de consola/JS en total: " + " | ".join(r["errores"][:4]))
    else:
        lineas.append("sin errores de consola durante el guion")
    m = r.get("mapa") or {}
    if m and not m.get("error"):
        ctrl = m.get("controles") or []
        if ctrl:
            lineas.append("mapa de interaccion (%d controles visibles): " % len(ctrl) + "; ".join(
                f"{c['tag']}{'[' + c['tipo'] + ']' if c.get('tipo') else ''} {c['selector']}"
                + (f" {c['texto']!r}" if c.get("texto") else "") for c in ctrl[:12]))
        else:
            lineas.append("mapa de interaccion: sin controles visibles"
                          + (" · hay canvas" if m.get("canvas") else "")
                          + (" · escucha teclado global" if m.get("teclado_global") else ""))
        if m.get("texto"):
            lineas.append("texto visible: " + str(m["texto"])[:300])
    if r.get("capturas"):
        lineas.append("capturas: " + ", ".join(r["capturas"]))
    lineas.append("duracion %d ms" % r.get("ms", 0))
    return "\n".join(lineas)


__all__ = ["parsear_guion", "correr_guion", "texto_guion", "Paso", "UMBRAL_CAMBIO"]
