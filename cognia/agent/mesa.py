# -*- coding: utf-8 -*-
"""
cognia/agent/mesa.py
====================
La MESA (segundo puesto de Cognia, 2026-09-08). Pedido del dueno: "dale un raton
individual a su monitor propio, que lo maneje al 100% sin ser una VM, en paralelo
a lo que yo hago, y que yo lo vea en una pantallita en tiempo real".

Lo MEDIDO en este Windows 11 (build 26200) antes de escribir esto (sondas reales,
ver la nota de memoria mesa-segundo-puesto-limites-input):

  - Un cursor de HARDWARE propio en paralelo, sin VM ni SwitchDesktop (que roba
    TODA la pantalla), es IMPOSIBLE en una sesion unica: `SendInput` solo lo
    recibe el *input desktop* activo. En un desktop de fondo el Entry quedo vacio.
  - Lo que SI cruza a un escritorio de fondo son los MENSAJES de ventana
    (PostMessage teclado escribio de verdad) y UI Automation (Invoke). Los clics
    por mensajes NO valen en Tk/pygame/juegos (leen el cursor real): para clicar
    de verdad, UIA Invoke; si no hay, cae a message-click.

Por eso la MESA es un OPERADOR de alto nivel sobre el ESCRITORIO PROPIO ya
existente (`escritorio_propio`, el escritorio virtual 'Cognia' donde `app_*`
lanza las apps): NO roba el raton ni el teclado del dueno NUNCA. El "raton" es un
PUNTERO VIRTUAL: la mesa guarda un (x,y) logico en coordenadas de pantalla; al
mover se anima, al clicar resuelve el elemento UIA bajo el punto y lo Invoca (o
manda el clic por mensajes al control hijo). La PANTALLITA (mesa_pantalla.py)
compone las ventanas de la mesa, dibuja el puntero y refresca en vivo en el
escritorio del dueno.

Limite honesto: apps que leen input hardware/raw (juegos) NO se pueden manejar
aqui; para esas queda el MODO FOCO de escritorio_propio (interrumpe un instante).
Para web, `pagina_*` (Playwright) es paralelo y real.
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from cognia.agent import escritorio_propio as EP

_ESTADO = Path.home() / ".cognia" / "mesa_estado.json"
_ULTIMO: dict = {"accion": "", "detalle": "", "ts": 0.0, "error": ""}

# Puntero e "activa" en memoria (se persiste para la pantallita)
_PUNTERO = {"x": None, "y": None}
_ACTIVA = {"hwnd": 0}


def _anotar(accion: str, detalle: str = "", error: str = "") -> None:
    _ULTIMO.update({"accion": accion, "detalle": str(detalle)[:300], "ts": time.time(), "error": str(error)[:300]})


# ---------------------------------------------------------------------------
# DPI / tamano de pantalla
# ---------------------------------------------------------------------------

def _dpi_aware() -> None:
    if os.name != "nt":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def pantalla_tam() -> tuple:
    """(ancho, alto) del escritorio virtual (todos los monitores)."""
    if os.name != "nt":
        return (1920, 1080)
    _dpi_aware()
    u = ctypes.windll.user32
    # SM_CXVIRTUALSCREEN / SM_CYVIRTUALSCREEN
    w = u.GetSystemMetrics(78) or u.GetSystemMetrics(0)
    h = u.GetSystemMetrics(79) or u.GetSystemMetrics(1)
    x0 = u.GetSystemMetrics(76)
    y0 = u.GetSystemMetrics(77)
    return (int(w), int(h), int(x0), int(y0))


# ---------------------------------------------------------------------------
# Estado persistente (lo lee la pantallita)
# ---------------------------------------------------------------------------

def _ventanas_dict() -> list:
    out = []
    try:
        for h, p, t in EP.ventanas_en_escritorio():
            try:
                x, y, w, ht = EP.rect_ventana(h)
                out.append({"hwnd": int(h), "pid": int(p), "titulo": t, "rect": [x, y, w, ht]})
            except Exception:
                continue
    except Exception:
        pass
    return out


def guardar_estado(**extra) -> dict:
    tam = pantalla_tam()
    px, py = puntero()
    est = {
        "puntero": {"x": int(px), "y": int(py)},
        "activa": int(_ACTIVA["hwnd"]),
        "pantalla": {"w": tam[0], "h": tam[1], "x0": tam[2] if len(tam) > 2 else 0, "y0": tam[3] if len(tam) > 3 else 0},
        "ventanas": _ventanas_dict(),
        "ts": time.time(),
        "ultimo": dict(_ULTIMO),
    }
    est.update(extra)
    # conservar campos previos utiles (pantalla_pid, click)
    try:
        if _ESTADO.exists():
            prev = json.loads(_ESTADO.read_text(encoding="utf-8"))
            for k in ("pantalla_pid", "click"):
                if k in prev and k not in est:
                    est[k] = prev[k]
    except Exception:
        pass
    # Escritura atomica con reintento: en Windows os.replace da PermissionError
    # si la pantallita tiene el fichero abierto ese microsegundo (revision
    # adversarial 2026-09-08). No se pisa _ULTIMO: la accion recien anotada
    # (mover, clic...) vale mas que un fallo transitorio de persistencia.
    try:
        _ESTADO.parent.mkdir(parents=True, exist_ok=True)
        tmp = _ESTADO.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(est, ensure_ascii=False), encoding="utf-8")
        for intento in range(4):
            try:
                os.replace(tmp, _ESTADO)
                break
            except PermissionError:
                if intento == 3:
                    raise
                time.sleep(0.005)
    except Exception as exc:
        _ULTIMO["error_estado"] = ("no se pudo guardar: %s" % exc)[:200]
    return est


def cargar_estado() -> dict:
    try:
        if _ESTADO.exists():
            return json.loads(_ESTADO.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


# ---------------------------------------------------------------------------
# El puntero virtual y las ventanas de la mesa
# ---------------------------------------------------------------------------

def _clamp(x, y) -> tuple:
    tam = pantalla_tam()
    x0 = tam[2] if len(tam) > 2 else 0
    y0 = tam[3] if len(tam) > 3 else 0
    return (max(x0, min(x0 + tam[0] - 1, int(x))), max(y0, min(y0 + tam[1] - 1, int(y))))


def puntero() -> tuple:
    """(x, y) del puntero virtual. En ESTE proceso vive en _PUNTERO; si nadie
    lo movio aqui (la pantallita es otro proceso, o acabamos de arrancar) se lee
    del JSON que escribe quien lo mueve. Cazado por la revision adversarial
    2026-09-08: la pantallita pintaba el puntero siempre en el centro porque
    solo miraba la memoria de su propio proceso."""
    if _PUNTERO["x"] is not None:
        return (int(_PUNTERO["x"]), int(_PUNTERO["y"]))
    tam = pantalla_tam()
    x0 = tam[2] if len(tam) > 2 else 0
    y0 = tam[3] if len(tam) > 3 else 0
    p = cargar_estado().get("puntero")
    if isinstance(p, dict):
        try:
            return (int(p["x"]), int(p["y"]))
        except Exception:
            pass
    return (x0 + tam[0] // 2, y0 + tam[1] // 2)


def mover(x: int, y: int, animar: bool = True) -> dict:
    """Mueve el puntero virtual a (x,y) de pantalla. No toca el cursor del dueno."""
    x, y = _clamp(x, y)
    if animar and _PUNTERO["x"] is not None:
        x0, y0 = _PUNTERO["x"], _PUNTERO["y"]
        pasos = 12
        for i in range(1, pasos + 1):
            _PUNTERO["x"] = int(x0 + (x - x0) * i / pasos)
            _PUNTERO["y"] = int(y0 + (y - y0) * i / pasos)
            guardar_estado()
            time.sleep(0.012)
    _PUNTERO["x"], _PUNTERO["y"] = x, y
    _anotar("mover", "-> %d,%d" % (x, y))
    guardar_estado()
    return {"x": x, "y": y}


def ventana_en_punto(sx: int, sy: int):
    """La ventana de la mesa MAS AL FRENTE cuyo rectangulo contiene (sx,sy).
    EnumWindows va de arriba (z alto) a abajo, asi que la primera que contiene
    el punto es la de encima."""
    mesa = {h for h, _p, _t in EP.ventanas_en_escritorio()}
    for h, _p, _t in EP.ventanas_visibles():   # orden z: frente -> fondo
        if h not in mesa:
            continue
        try:
            x, y, w, ht = EP.rect_ventana(h)
            if x <= sx < x + w and y <= sy < y + ht:
                return h
        except Exception:
            continue
    return 0


def activa() -> int:
    """La ventana 'activa' de la mesa: la ultima usada, o la mas al frente."""
    if _ACTIVA["hwnd"] and EP.ventana_viva(_ACTIVA["hwnd"]):
        return _ACTIVA["hwnd"]
    mesa = {h for h, _p, _t in EP.ventanas_en_escritorio()}
    for h, _p, _t in EP.ventanas_visibles():
        if h in mesa:
            _ACTIVA["hwnd"] = h
            return h
    return 0


def fijar_activa(hwnd: int) -> None:
    _ACTIVA["hwnd"] = int(hwnd)


def en_uso() -> bool:
    """True mientras la mesa tenga una ventana activa VIVA (fijada por
    mesa_lanzar / mesa_ventanas activar). Lo consulta simple_mode para anunciar
    la familia entera al agente solo cuando hace falta. Barato: IsWindow."""
    h = _ACTIVA["hwnd"]
    return bool(h) and EP.ventana_viva(h)


# ---------------------------------------------------------------------------
# Clic: UIA Invoke bajo el punto, o clic por mensajes al control hijo
# ---------------------------------------------------------------------------

_UIA_MAX_NODOS = 800


def _uia_en_punto(hwnd: int, sx: int, sy: int):
    """El control UIA mas profundo cuyo BoundingRectangle contiene (sx,sy) en
    pantalla, y un patron accionable si lo tiene. Devuelve (ctrl, patron, tipo)
    o (None,None,''). Lee ventanas de otro escritorio (probado). Poda: no baja
    por ramas cuyo rectangulo (no vacio) no contiene el punto, y corta a
    _UIA_MAX_NODOS nodos (Chromium/Office tienen miles: sin tope se pasaba del
    timeout de la tool)."""
    try:
        import uiautomation as auto  # type: ignore
    except Exception:
        return None, None, ""
    try:
        raiz = auto.ControlFromHandle(int(hwnd))
    except Exception:
        raiz = None
    if not raiz:
        return None, None, ""
    mejor = [None, None, "", 1 << 62]
    vistos = [0]

    def rect_de(ctrl):
        try:
            r = ctrl.BoundingRectangle
            if r and (r.right - r.left) > 0 and (r.bottom - r.top) > 0:
                return r
        except Exception:
            pass
        return None

    def rec(ctrl, prof):
        if prof > 12 or vistos[0] >= _UIA_MAX_NODOS:
            return
        vistos[0] += 1
        r = rect_de(ctrl)
        dentro = r is not None and r.left <= sx < r.right and r.top <= sy < r.bottom
        if dentro:
            area = (r.right - r.left) * (r.bottom - r.top)
            if area < mejor[3]:
                pat, tipo = _patron_accionable(ctrl)
                if pat is not None:
                    mejor[0], mejor[1], mejor[2], mejor[3] = ctrl, pat, tipo, area
        elif r is not None:
            return          # rama con rectangulo real que no contiene el punto: podar
        try:
            for h in ctrl.GetChildren():
                rec(h, prof + 1)
        except Exception:
            pass
    try:
        rec(raiz, 0)
    except Exception:
        pass
    return mejor[0], mejor[1], mejor[2]


def _patron_de(ctrl, metodo: str, patron_id: str):
    """El patron UIA por el metodo tipado (ButtonControl.GetInvokePattern) o,
    si esa clase no lo declara (Custom/Pane/Group en WPF/Qt), por el generico
    GetPattern(PatternId.X). Revision adversarial 2026-09-08."""
    try:
        getter = getattr(ctrl, metodo, None)
        if getter:
            pat = getter()
            if pat is not None:
                return pat
    except Exception:
        pass
    try:
        import uiautomation as auto  # type: ignore
        return ctrl.GetPattern(getattr(auto.PatternId, patron_id))
    except Exception:
        return None


def _patron_accionable(ctrl):
    """(callable_que_acciona, etiqueta) o (None,'')."""
    for nombre, metodo, pid in (("Invoke", "GetInvokePattern", "InvokePattern"),
                                ("Toggle", "GetTogglePattern", "TogglePattern"),
                                ("Select", "GetSelectionItemPattern", "SelectionItemPattern"),
                                ("Expand", "GetExpandCollapsePattern", "ExpandCollapsePattern")):
        pat = _patron_de(ctrl, metodo, pid)
        if pat is None:
            continue
        if nombre == "Invoke":
            return (lambda p=pat: p.Invoke()), "UIA.Invoke"
        if nombre == "Toggle":
            return (lambda p=pat: p.Toggle()), "UIA.Toggle"
        if nombre == "Select":
            return (lambda p=pat: p.Select()), "UIA.Select"
        if nombre == "Expand":
            def _exp(p=pat):
                try:
                    p.Expand()
                except Exception:
                    p.Collapse()
            return _exp, "UIA.Expand"
    return None, ""


def clic(x: int, y: int, boton: str = "izquierdo", doble: bool = False, hwnd: int = 0) -> dict:
    """Clic del puntero virtual en (x,y) de pantalla. Prefiere UIA Invoke del
    control bajo el punto; si no hay patron, manda el clic por mensajes al
    control hijo (limitado: no vale para Tk/pygame/juegos). Con `hwnd` se clica
    en ESA ventana de la mesa (invocar la usa para no irse a la de encima)."""
    mover(x, y, animar=True)
    if hwnd and not (EP.ventana_viva(hwnd) and hwnd in {h for h, _p, _t in EP.ventanas_en_escritorio()}):
        hwnd = 0
    hwnd = hwnd or ventana_en_punto(x, y)
    res = {"x": x, "y": y, "hwnd": hwnd, "metodo": "", "control": "", "boton": boton, "doble": doble}
    if not hwnd:
        res["error"] = "no hay ninguna ventana de la mesa bajo %d,%d" % (x, y)
        _anotar("clic", res["error"])
        guardar_estado(click={"x": x, "y": y, "ts": time.time(), "boton": boton, "ok": False})
        return res
    fijar_activa(hwnd)
    # pulso visual del clic
    guardar_estado(click={"x": x, "y": y, "ts": time.time(), "boton": boton, "ok": True})
    if boton.startswith("izq"):
        ctrl, pat, tipo = _uia_en_punto(hwnd, x, y)
        if pat is not None:
            try:
                pat()
                if doble:
                    time.sleep(0.06)
                    pat()
                res["metodo"] = tipo
                try:
                    res["control"] = (ctrl.Name or ctrl.ControlTypeName)[:80]
                except Exception:
                    pass
                _anotar("clic", "%s en %r @%d,%d" % (tipo, res.get("control", ""), x, y))
                return res
            except Exception as exc:
                res["uia_error"] = str(exc)[:120]
    # cae a clic por mensajes (coords cliente de la ventana bajo el punto)
    try:
        cx, cy, _w, _h = EP.rect_cliente(hwnd)
        r = EP.clic(hwnd, x - cx, y - cy, boton=boton, doble=doble)
        res["metodo"] = "mensaje"
        res["control"] = r.get("control", "")
        _anotar("clic", "mensaje en %s @%d,%d" % (res["control"], x, y))
    except Exception as exc:
        res["error"] = "clic por mensajes fallo: %s" % exc
        _anotar("clic", "", res["error"])
    return res


def invocar(texto: str) -> dict:
    """Clica el control (boton, enlace, menu...) cuyo nombre contiene `texto`,
    en la ventana activa de la mesa. La via mas fiable: no depende del pixel."""
    hwnd = activa()
    if not hwnd:
        return {"ok": False, "error": "no hay ninguna ventana en la mesa (lanza algo con mesa_lanzar)"}
    r = None
    try:
        # REINTENTO: justo despues de un Invoke, apps WinUI (la Calculadora)
        # devuelven el arbol UIA VACIO unos cientos de ms mientras se
        # re-pintan; el agente encadenaba pulsaciones y "no encontraba" el
        # boton siguiente (visto tecleando 7 x 6 = con el 27B, 2026-09-09).
        for intento in range(INVOCAR_REINTENTOS):
            r = EP.buscar_control(hwnd, texto)
            if r:
                break
            time.sleep(INVOCAR_ESPERA_S)
    except Exception as exc:
        return {"ok": False, "error": "UIA no disponible: %s" % exc}
    if not r:
        # ¿La activa es el MARCO de una app de la Store (1 nodo)? Buscar la
        # ventana hermana con el mismo titulo que si expone controles.
        try:
            mv = mejor_ventana(hwnd, segundos=2.0)
            if mv.get("ok") and mv["hwnd"] != hwnd:
                hwnd = mv["hwnd"]
                fijar_activa(hwnd)
                r = EP.buscar_control(hwnd, texto)
        except Exception:
            r = None
    if not r:
        return {"ok": False, "error": "no encontre ningun control con %r en la ventana activa" % texto}
    cx, cy, tipo, nombre = r
    # cx,cy son coords de CLIENTE -> a pantalla para mover el puntero
    px, py, _w, _h = EP.rect_cliente(hwnd)
    resu = clic(px + cx, py + cy, boton="izquierdo", hwnd=hwnd)
    resu.update({"ok": "error" not in resu, "encontrado": nombre, "tipo": tipo})
    time.sleep(INVOCAR_ASIENTO_S)     # que la app asiente antes de la siguiente orden
    return resu


INVOCAR_REINTENTOS = 5
INVOCAR_ESPERA_S = 0.3
INVOCAR_ASIENTO_S = 0.15


def esperar_ui(hwnd: int, segundos: float = 4.0) -> dict:
    """Espera a que la ventana exponga controles por UIA (>= 2 nodos). Las apps
    WinUI (Calculadora) tardan en poblar el arbol tras abrir, y una instancia
    COLGADA (dos ventanas 'Calculadora' con 1 nodo cada una, visto el
    2026-09-09) no lo puebla nunca: entonces se dice, para que el agente no
    encadene mesa_invocar a ciegas. Devuelve {ok, nodos, segundos}."""
    t0 = time.time()
    nodos = 0
    while time.time() - t0 < segundos:
        try:
            nodos = len(EP.arbol_uia(hwnd, profundidad=6, maximo=40))
        except Exception:
            nodos = 0
        if nodos >= 2:
            return {"ok": True, "nodos": nodos, "segundos": round(time.time() - t0, 1)}
        time.sleep(0.3)
    return {"ok": False, "nodos": nodos, "segundos": round(time.time() - t0, 1)}


def mejor_ventana(hwnd: int, segundos: float = 4.0) -> dict:
    """Entre las ventanas de la mesa con el MISMO titulo que `hwnd`, la que
    expone controles por UIA. Una app de la Store (UWP) tiene DOS ventanas
    'Calculadora': el marco de ApplicationFrameHost (1 nodo siempre) y la
    CoreWindow de CalculatorApp.exe (50 nodos); `lanzar` puede devolver el
    marco. Antes, `plm.mantener_despierta` exime a sus procesos de la
    suspension (una UWP en un escritorio no visible se suspende y su arbol
    queda en 1 nodo: medido 2026-09-09). Devuelve {ok, hwnd, nodos, paquete}."""
    from cognia.agent import plm
    try:
        titulo = EP.titulo_ventana(hwnd)
    except Exception:
        titulo = ""
    candidatas = [hwnd]
    paquete = ""
    for h, p, t in EP.ventanas_en_escritorio():
        if h != hwnd and titulo and (t or "") == titulo:
            candidatas.append(h)
    for h in candidatas:
        try:
            r = plm.mantener_despierta(EP.pid_de(h))
            paquete = paquete or r.get("paquete", "")
        except Exception:
            pass
    t0 = time.time()
    ultimo = 0
    while True:
        for h in candidatas:
            try:
                n = len(EP.arbol_uia(h, profundidad=6, maximo=40))
            except Exception:
                n = 0
            ultimo = max(ultimo, n)
            if n >= 2:
                return {"ok": True, "hwnd": h, "nodos": n, "paquete": paquete,
                        "segundos": round(time.time() - t0, 1)}
        if time.time() - t0 >= segundos:
            return {"ok": False, "hwnd": hwnd, "nodos": ultimo, "paquete": paquete,
                    "segundos": round(time.time() - t0, 1)}
        time.sleep(0.3)


def esperar_ui(hwnd: int, segundos: float = 4.0) -> dict:
    """Compatibilidad: como mejor_ventana pero sin cambiar de ventana."""
    r = mejor_ventana(hwnd, segundos)
    return {"ok": r["ok"] and r["hwnd"] == hwnd, "nodos": r["nodos"], "segundos": r["segundos"]}


def arbol_estable(hwnd: int, profundidad: int = 8, maximo: int = 200, minimo_nodos: int = 2) -> list:
    """arbol_uia con reintento: si vuelve (casi) vacio por el re-pintado de la
    app, se espera y se repite (hasta INVOCAR_REINTENTOS)."""
    arbol = []
    for intento in range(INVOCAR_REINTENTOS):
        arbol = EP.arbol_uia(hwnd, profundidad=profundidad, maximo=maximo)
        if len(arbol) >= minimo_nodos:
            break
        time.sleep(INVOCAR_ESPERA_S)
    return arbol


def _hijo_en(hwnd: int, sx: int, sy: int) -> tuple:
    """(hwnd_hijo, x_cliente_del_hijo, y_cliente_del_hijo) para un punto de
    PANTALLA: el control bajo el punto y sus coordenadas, como hace EP.clic
    (un slider o listbox Win32 solo reacciona si el mensaje le llega a EL)."""
    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
    u = EP._u32()
    cx, cy, _w, _h = EP.rect_cliente(hwnd)
    p = POINT(int(sx - cx), int(sy - cy))
    hijo = u.ChildWindowFromPointEx(ctypes.c_void_p(hwnd), p, 0x0001 | 0x0002 | 0x0004)
    hijo = int(hijo) if hijo else hwnd
    if hijo != hwnd:
        u.MapWindowPoints(ctypes.c_void_p(hwnd), ctypes.c_void_p(hijo), ctypes.byref(p), 1)
    return hijo, int(p.x), int(p.y)


def arrastrar(x0: int, y0: int, x1: int, y1: int) -> dict:
    """Arrastre por mensajes (limitado). Mueve el puntero y manda DOWN/MOVE/UP."""
    mover(x0, y0)
    hwnd = ventana_en_punto(x0, y0)
    if not hwnd:
        return {"ok": False, "error": "no hay ventana bajo el origen %d,%d" % (x0, y0)}
    fijar_activa(hwnd)
    # el mensaje va al CONTROL bajo el origen, en SUS coordenadas (como EP.clic)
    hijo, hx, hy = _hijo_en(hwnd, x0, y0)
    dx, dy = hx - x0, hy - y0       # pantalla -> cliente del hijo

    def _lp(sx, sy):
        return ((int(sy + dy) & 0xFFFF) << 16) | (int(sx + dx) & 0xFFFF)
    EP._post(hijo, 0x0201, 1, _lp(x0, y0))       # LBUTTONDOWN
    pasos = 16
    for i in range(1, pasos + 1):
        mx = int(x0 + (x1 - x0) * i / pasos)
        my = int(y0 + (y1 - y0) * i / pasos)
        EP._post(hijo, 0x0200, 1, _lp(mx, my))   # MOUSEMOVE con boton
        mover(mx, my, animar=False)
        time.sleep(0.02)
    EP._post(hijo, 0x0202, 0, _lp(x1, y1))       # LBUTTONUP
    _anotar("arrastrar", "%d,%d -> %d,%d" % (x0, y0, x1, y1))
    return {"ok": True, "hwnd": hwnd, "desde": [x0, y0], "hasta": [x1, y1]}


def rueda(x: int, y: int, pasos: int) -> dict:
    """Rueda del raton en (x,y). pasos>0 arriba, <0 abajo. WM_MOUSEWHEEL."""
    mover(x, y)
    hwnd = ventana_en_punto(x, y)
    if not hwnd:
        return {"ok": False, "error": "no hay ventana bajo %d,%d" % (x, y)}
    delta = int(pasos) * 120
    lp = ((int(y) & 0xFFFF) << 16) | (int(x) & 0xFFFF)   # WM_MOUSEWHEEL usa coords de PANTALLA
    wp = (delta & 0xFFFF) << 16
    EP._post(hwnd, 0x020A, wp, lp)
    _anotar("rueda", "%d pasos @%d,%d" % (pasos, x, y))
    return {"ok": True, "hwnd": hwnd, "pasos": pasos}


# ---------------------------------------------------------------------------
# Teclado (a la ventana activa de la mesa)
# ---------------------------------------------------------------------------

def escribir(texto: str) -> dict:
    hwnd = activa()
    if not hwnd:
        return {"ok": False, "error": "no hay ventana activa en la mesa"}
    n = EP.escribir_texto(hwnd, texto)
    _anotar("escribir", "%d chars" % n)
    guardar_estado()
    return {"ok": True, "hwnd": hwnd, "chars": n}


def tecla(nombre: str, veces: int = 1) -> dict:
    hwnd = activa()
    if not hwnd:
        return {"ok": False, "error": "no hay ventana activa en la mesa"}
    n = EP.enviar_tecla(hwnd, nombre, veces=veces)
    _anotar("tecla", "%s x%d" % (nombre, n))
    guardar_estado()
    return {"ok": True, "hwnd": hwnd, "pulsaciones": n}


def atajo(combo: str) -> dict:
    """Combinacion tipo ctrl+s por mensajes: modificador down, tecla, up.
    LIMITADO: muchas apps miran GetKeyState y no ven un Ctrl que solo viajo por
    mensajes (ver la nota de memoria). Para acciones de menu, mejor mesa_invocar
    'Guardar'. Se intenta igual y se avisa si probablemente no valga."""
    hwnd = activa()
    if not hwnd:
        return {"ok": False, "error": "no hay ventana activa en la mesa"}
    partes = [p.strip().lower() for p in combo.replace("+", " ").split() if p.strip()]
    if not partes:
        return {"ok": False, "error": "combo vacio (ej: ctrl+s)"}
    mods = [p for p in partes if p in ("ctrl", "control", "alt", "mayus", "shift", "win")]
    teclas = [p for p in partes if p not in ("ctrl", "control", "alt", "mayus", "shift", "win")]
    destino = EP.hwnd_con_foco(hwnd)
    try:
        vks = []
        for m in mods:
            vk, _c = EP.vk_de(m)
            vks.append(vk)
            EP._post(destino, 0x0100, vk, 0)      # KEYDOWN mod
        for t in teclas:
            # SOLO KEYDOWN/KEYUP del vk, sin WM_CHAR: con WM_CHAR, ctrl+s
            # acababa escribiendo una "s" literal en el editor (revision
            # adversarial 2026-09-08), porque el Ctrl por mensaje no lo ve la app.
            vk, _c = EP.vk_de(t)
            if not vk:
                raise ValueError("tecla sin codigo virtual: %r" % t)
            EP._post(destino, 0x0100, vk, 1)
            time.sleep(0.03)
            EP._post(destino, 0x0101, vk, 1 | (1 << 30) | (1 << 31))
        for vk in reversed(vks):
            EP._post(destino, 0x0101, vk, 0)       # KEYUP mod
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    _anotar("atajo", combo)
    guardar_estado()
    aviso = ("" if not mods else
             "aviso: los modificadores por mensajes no siempre los ve la app; si no pasa nada usa mesa_invocar '<etiqueta del menu/boton>'")
    return {"ok": True, "hwnd": hwnd, "combo": combo, "aviso": aviso}


# ---------------------------------------------------------------------------
# Componer la "pantalla" de la mesa (todas sus ventanas + el puntero)
# ---------------------------------------------------------------------------

def componer(salida: str, escala: float = 1.0, con_puntero: bool = True, recortar: bool = False) -> dict:
    """Compone todas las ventanas de la mesa sobre un lienzo del tamano de la
    pantalla y dibuja el puntero. Si `recortar`, ajusta al contenido (union de
    los rectangulos de las ventanas + el puntero, con margen) para una pantallita
    ceñida. Devuelve {png, ancho, alto, ventanas}."""
    from PIL import Image, ImageDraw  # type: ignore
    tam = pantalla_tam()
    W, H = tam[0], tam[1]
    x0 = tam[2] if len(tam) > 2 else 0
    y0 = tam[3] if len(tam) > 3 else 0
    lienzo = Image.new("RGB", (W, H), (24, 26, 32))
    d = ImageDraw.Draw(lienzo)
    d.text((12, 10), "MESA de Cognia — escritorio '%s'" % EP.config().get("nombre", "Cognia"), fill=(120, 130, 150))
    ventanas = EP.ventanas_en_escritorio()
    pintadas = 0
    caja = None  # (l,t,r,b) en coords de lienzo
    # pintar de fondo (z bajo) a frente: invertir el orden z de ventanas_visibles
    mesa_ids = {h for h, _p, _t in ventanas}
    orden = [h for h, _p, _t in EP.ventanas_visibles() if h in mesa_ids]
    orden.reverse()
    tmpdir = Path(salida).parent
    tmpdir.mkdir(parents=True, exist_ok=True)
    for h in orden:
        try:
            rx, ry, rw, rh = EP.rect_ventana(h)
            if rw <= 0 or rh <= 0:
                continue
            tmp = tmpdir / ("_mesa_w%d.png" % h)
            EP.capturar_ventana(h, str(tmp))
            im = Image.open(str(tmp)).convert("RGB")
            # capturar_ventana RESTAURA una minimizada (que estaba en -32000):
            # el rectangulo bueno es el de despues de capturar
            rx, ry, rw, rh = EP.rect_ventana(h)
            lx, ly = rx - x0, ry - y0
            lienzo.paste(im, (lx, ly))
            c = (lx, ly, lx + im.width, ly + im.height)
            caja = c if caja is None else (min(caja[0], c[0]), min(caja[1], c[1]), max(caja[2], c[2]), max(caja[3], c[3]))
            pintadas += 1
            try:
                tmp.unlink()
            except Exception:
                pass
        except Exception:
            continue
    px, py = puntero()
    if con_puntero:
        _dibujar_puntero(d, px - x0, py - y0)
        # pulso de clic reciente
        est = cargar_estado()
        clk = est.get("click") or {}
        if clk and time.time() - clk.get("ts", 0) < 0.6:
            cxp, cyp = clk.get("x", px) - x0, clk.get("y", py) - y0
            for rad in (10, 18, 26):
                d.ellipse([cxp - rad, cyp - rad, cxp + rad, cyp + rad], outline=(90, 200, 255), width=2)
    if recortar and caja is not None:
        m = 24
        l = max(0, min(caja[0], px - x0) - m)
        t = max(0, min(caja[1], py - y0) - m)
        r = min(W, max(caja[2], px - x0) + m)
        b = min(H, max(caja[3], py - y0) + m)
        if r - l > 40 and b - t > 40:
            lienzo = lienzo.crop((l, t, r, b))
    if escala and escala != 1.0:
        lienzo = lienzo.resize((max(1, int(lienzo.width * escala)), max(1, int(lienzo.height * escala))), Image.LANCZOS)
    lienzo.save(str(salida))
    return {"png": str(salida), "ancho": lienzo.width, "alto": lienzo.height, "ventanas": pintadas}


def _dibujar_puntero(d, x, y) -> None:
    # flecha de cursor clasica
    pts = [(x, y), (x, y + 16), (x + 4, y + 12), (x + 7, y + 18), (x + 9, y + 17),
           (x + 6, y + 11), (x + 11, y + 11)]
    d.polygon(pts, fill=(255, 255, 255), outline=(0, 0, 0))


# ---------------------------------------------------------------------------
# La pantallita en vivo (proceso aparte, en el escritorio del dueno)
# ---------------------------------------------------------------------------

def pantalla_abrir(fps: int = 6, escala: float = 0.42) -> dict:
    """Lanza la pantallita en vivo (mesa_pantalla.py) como proceso propio.
    Si ya hay una viva, no abre otra."""
    est = cargar_estado()
    pid = est.get("pantalla_pid")
    if pid and _pid_vivo(pid):
        return {"ok": True, "ya": True, "pid": pid}
    guion = str(Path(__file__).with_name("mesa_pantalla.py"))
    env = dict(os.environ)
    # que importe ESTE cognia (repo), no el instalado, si corremos desde el repo
    raiz = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = raiz + os.pathsep + env.get("PYTHONPATH", "")
    env.setdefault("PYTHONUTF8", "1")
    try:
        proc = subprocess.Popen([sys.executable, guion, "--fps", str(fps), "--escala", str(escala)],
                                env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    except Exception as exc:
        return {"ok": False, "error": "no se pudo abrir la pantallita: %s" % exc}
    # si muere al instante (falta tkinter/Pillow), decirlo en vez de "abierta"
    time.sleep(0.5)
    if proc.poll() is not None:
        err = ""
        try:
            err = (proc.stderr.read() or b"").decode("utf-8", "replace")[-300:].strip()
        except Exception:
            pass
        return {"ok": False, "error": "la pantallita murio al arrancar (exit %s): %s" % (proc.returncode, err or "sin salida")}
    guardar_estado(pantalla_pid=proc.pid)
    _anotar("pantalla", "abierta pid %d" % proc.pid)
    return {"ok": True, "ya": False, "pid": proc.pid}


def pantalla_cerrar() -> dict:
    est = cargar_estado()
    pid = est.get("pantalla_pid")
    if not pid or not _pid_vivo(pid):
        guardar_estado(pantalla_pid=0)
        return {"ok": True, "cerrada": False}
    EP.matar_arbol(pid)
    guardar_estado(pantalla_pid=0)
    _anotar("pantalla", "cerrada pid %d" % pid)
    return {"ok": True, "cerrada": True, "pid": pid}


def _pid_vivo(pid: int) -> bool:
    """Vivo Y es la pantallita: el pid persiste en el JSON entre reinicios y
    tras un reboot puede ser de cualquier otro proceso; matarlo a ciegas con
    taskkill /T seria un desastre (revision adversarial 2026-09-08)."""
    try:
        import psutil  # type: ignore
        p = psutil.Process(int(pid))
        try:
            linea = " ".join(p.cmdline()).lower()
        except Exception:
            # el launcher del venv es un stub: el hijo real puede ser otro pid
            # y el padre no deja leer la linea; que el nombre sea python basta
            linea = (p.name() or "").lower()
        return ("mesa_pantalla" in linea) or ("python" in linea and "mesa_pantalla" in linea)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Estado para /mesa
# ---------------------------------------------------------------------------

def estado() -> dict:
    ok, motivo = EP.disponible()
    cfg = EP.config()
    px, py = puntero()
    est = cargar_estado()
    pid = est.get("pantalla_pid")
    return {
        "disponible": ok, "motivo": motivo, "escritorio": cfg.get("nombre"),
        "activo": EP.activo(),
        "puntero": {"x": px, "y": py},
        "ventanas": _ventanas_dict(),
        "activa": activa(),
        "pantalla_abierta": bool(pid and _pid_vivo(pid)),
        "pantalla_pid": pid or 0,
        "ultimo": dict(_ULTIMO),
    }


def ultimo() -> dict:
    return dict(_ULTIMO)
