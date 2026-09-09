# -*- coding: utf-8 -*-
"""
cognia/agent/escritorio_propio.py
=================================
El ESCRITORIO PROPIO de Cognia (2026-09-07). Pedido del dueno: "algo como lo
que hace Grok Bot, darle el control total de otro escritorio que sea de Cognia
unicamente: un escritorio para ella solita, y ahi hace lo que quiera".

Lo que hay debajo: un ESCRITORIO VIRTUAL de Windows (los de Win+Ctrl+D) con
nombre "Cognia". Las aplicaciones que el agente lanza (app_lanzar / app_probar)
se mueven ahi nada mas aparecer su ventana, asi que el dueno sigue en su
escritorio con sus ventanas intactas y Cognia trabaja en el suyo. MEDIDO en
este Windows 11 (build 26200) antes de escribir esto:

  - pyvda crea/renombra/borra escritorios y mueve ventanas (AppView.move).
  - PrintWindow(PW_RENDERFULLCONTENT) CAPTURA una ventana que esta en OTRO
    escritorio virtual (DWM la sigue componiendo): sin cambiar de escritorio
    ni robar el foco.
  - PostMessage(WM_KEYDOWN/WM_CHAR/WM_KEYUP) al hijo con foco de la ventana
    LLEGA aunque la ventana este en el otro escritorio (tkinter reacciono:
    la etiqueta cambio y el fondo se volvio azul).
  - El clic por mensajes hay que mandarlo al CONTROL bajo el punto (no al
    top-level) con coordenadas de cliente de ese control.

Lo que NO puede hacer sin foco real: combinaciones con modificadores
(ctrl+s: GetKeyState no ve un Ctrl que solo viajo por PostMessage), juegos
que leen el teclado por Raw Input / DirectInput, y el raton relativo. Para
eso esta el MODO FOCO: cambiar al escritorio de Cognia, usar entrada REAL
(pyautogui) y volver al escritorio del dueno. Como eso si interrumpe al
dueno un instante, va gobernado por la politica `escritorio_foco`:
  nunca     -> jamas se cambia de escritorio (solo mensajes)     [DEFAULT]
  inactivo  -> solo si el dueno lleva >= escritorio_inactividad_s sin tocar
               teclado ni raton (GetLastInputInfo)
  siempre   -> cuando haga falta

DEFAULT es 'nunca' desde 2026-09-09 (pedido del dueño: "que mi monitor no lo
use nunca, que lo haga siempre en el de él"). Antes era 'inactivo'; ademas
`app_clic` con foco=1 bypasseaba la politica igual (forzar=foco directo a
con_foco), asi que 'nunca' no era realmente nunca. Con el bypass cerrado y
el default en 'nunca', las apps que solo funcionan con entrada real (juegos,
atajos con modificador) quedan sin poder clicarse/atajarse del todo salvo que
el dueño elija /escritorio foco inactivo|siempre a proposito.

Config (cli._load_config): escritorio_propio (on/off, default on),
escritorio_nombre ("Cognia"), escritorio_foco, escritorio_inactividad_s (90).
Env COGNIA_ESCRITORIO=0 lo apaga en una corrida. Sin pyvda o fuera de Windows
todo degrada con causa visible: las apps se lanzan en el escritorio actual y
`estado()` lo dice.

Backends indirectos (_vd(), _u32()) para que los tests inyecten fakes: nunca
se crea un escritorio real bajo pytest salvo COGNIA_E2E_ESCRITORIO=1.
"""
from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import time
from pathlib import Path

NOMBRE_DEF = "Cognia"
FOCO_DEF = "nunca"
INACTIVIDAD_DEF_S = 90
_REGISTRO = Path.home() / ".cognia" / "escritorio_propio.json"

# Ultimo evento (puerta /escritorio estado)
_ULTIMO: dict = {"accion": "", "detalle": "", "ts": 0.0, "error": ""}
# Escritorio anterior al ultimo ir(): para volver()
_ANTERIOR: dict = {"id": None}


def _anotar(accion: str, detalle: str = "", error: str = "") -> None:
    _ULTIMO.update({"accion": accion, "detalle": detalle[:300], "ts": time.time(), "error": error[:300]})


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _cfg() -> dict:
    try:
        _cli = sys.modules.get("cognia.cli")
        if _cli is not None:
            return dict(_cli._load_config() or {})
    except Exception:
        pass
    try:
        ruta = Path.home() / ".cognia_config.json"
        if ruta.exists():
            return json.loads(ruta.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def config() -> dict:
    c = _cfg()
    env = os.environ.get("COGNIA_ESCRITORIO", "").strip().lower()
    activo = bool(c.get("escritorio_propio", True))
    if env:
        activo = env in ("1", "on", "true", "yes", "si")
    foco = str(os.environ.get("COGNIA_ESCRITORIO_FOCO") or c.get("escritorio_foco") or FOCO_DEF).lower()
    if foco not in ("nunca", "inactivo", "siempre"):
        foco = FOCO_DEF
    try:
        inact = int(c.get("escritorio_inactividad_s", INACTIVIDAD_DEF_S))
    except Exception:
        inact = INACTIVIDAD_DEF_S
    return {"activo": activo, "nombre": str(c.get("escritorio_nombre") or NOMBRE_DEF),
            "foco": foco, "inactividad_s": max(5, inact)}


def activo() -> bool:
    return config()["activo"] and disponible()[0]


# ---------------------------------------------------------------------------
# Backends (indirectos para tests)
# ---------------------------------------------------------------------------

def _vd():
    """pyvda o ValueError con el pip exacto."""
    if os.name != "nt":
        raise ValueError("el escritorio propio solo existe en Windows (escritorios virtuales)")
    try:
        import pyvda  # type: ignore
        return pyvda
    except Exception as exc:
        raise ValueError("falta pyvda (%s: %s). Instalalo con: pip install pyvda"
                         % (type(exc).__name__, str(exc)[:80]))


def disponible() -> tuple:
    """(bool, motivo)."""
    try:
        vd = _vd()
        vd.get_virtual_desktops()
        return True, ""
    except Exception as exc:
        return False, str(exc)


_TIPOS_PUESTOS = [False]


def _configurar_tipos() -> None:
    """Handles de 64 bits: sin restype/argtypes ctypes los devuelve como int de
    32 bits y un HDC grande revienta con 'int too long to convert' (cazado en
    el primer e2e: fallaba una captura de cada tres, al azar del handle)."""
    if _TIPOS_PUESTOS[0] or os.name != "nt":
        return
    u, g = ctypes.windll.user32, ctypes.windll.gdi32
    P = ctypes.c_void_p
    u.GetWindowDC.restype = P
    u.GetWindowDC.argtypes = [P]
    u.ReleaseDC.argtypes = [P, P]
    u.PrintWindow.argtypes = [P, P, ctypes.c_uint]
    u.ChildWindowFromPointEx.restype = P
    u.GetForegroundWindow.restype = P
    u.SetForegroundWindow.argtypes = [P]
    u.PostMessageW.argtypes = [P, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
    u.SendMessageW.restype = ctypes.c_ssize_t
    g.CreateCompatibleDC.restype = P
    g.CreateCompatibleDC.argtypes = [P]
    g.CreateCompatibleBitmap.restype = P
    g.CreateCompatibleBitmap.argtypes = [P, ctypes.c_int, ctypes.c_int]
    g.SelectObject.restype = P
    g.SelectObject.argtypes = [P, P]
    g.DeleteObject.argtypes = [P]
    g.DeleteDC.argtypes = [P]
    g.GetDIBits.argtypes = [P, P, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
    _TIPOS_PUESTOS[0] = True


def _u32():
    _configurar_tipos()
    return ctypes.windll.user32


def _g32():
    _configurar_tipos()
    return ctypes.windll.gdi32


# ---------------------------------------------------------------------------
# Escritorio
# ---------------------------------------------------------------------------

def _buscar(nombre: str):
    vd = _vd()
    for d in vd.get_virtual_desktops():
        try:
            if (d.name or "").strip().lower() == nombre.strip().lower():
                return d
        except Exception:
            continue
    return None


def asegurar():
    """El escritorio de Cognia (lo crea si no existe). Devuelve el objeto pyvda."""
    c = config()
    if not c["activo"]:
        raise ValueError("el escritorio propio esta apagado (/escritorio on o COGNIA_ESCRITORIO=1)")
    vd = _vd()
    d = _buscar(c["nombre"])
    if d is None:
        d = vd.VirtualDesktop.create()
        try:
            d.rename(c["nombre"])
        except Exception as exc:
            _anotar("crear", "creado sin nombre", "rename: %s" % exc)
        _anotar("crear", "escritorio '%s' creado (n%d)" % (c["nombre"], _numero(d)))
    return d


def _numero(d) -> int:
    try:
        return int(d.number)
    except Exception:
        return -1


def actual():
    return _vd().VirtualDesktop.current()


def es_el_actual(d=None) -> bool:
    try:
        d = d or _buscar(config()["nombre"])
        return d is not None and actual().id == d.id
    except Exception:
        return False


def mover_ventana(hwnd: int) -> bool:
    """Lleva la ventana al escritorio de Cognia. False (con _ULTIMO.error) si no pudo."""
    try:
        d = asegurar()
        vd = _vd()
        vd.AppView(hwnd=int(hwnd)).move(d)
        _anotar("mover", "hwnd %d -> '%s'" % (hwnd, config()["nombre"]))
        return True
    except Exception as exc:
        _anotar("mover", "hwnd %d" % hwnd, "%s: %s" % (type(exc).__name__, exc))
        return False


def ventanas_en_escritorio() -> list:
    """[(hwnd, pid, titulo)] de las ventanas visibles que viven en el escritorio de Cognia."""
    d = _buscar(config()["nombre"])
    if d is None:
        return []
    vd = _vd()
    out = []
    for hwnd, pid, titulo in ventanas_visibles():
        try:
            if vd.AppView(hwnd=hwnd).desktop.id == d.id:
                out.append((hwnd, pid, titulo))
        except Exception:
            continue
    return out


def dueno_inactivo_s() -> float:
    """Segundos desde la ultima tecla/raton del dueno (GetLastInputInfo)."""
    class LII(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
    lii = LII()
    lii.cbSize = ctypes.sizeof(LII)
    if not _u32().GetLastInputInfo(ctypes.byref(lii)):
        return 0.0
    tick = ctypes.windll.kernel32.GetTickCount()
    return max(0.0, (tick - lii.dwTime) / 1000.0)


def puede_tomar_foco() -> tuple:
    """(bool, motivo) segun la politica escritorio_foco."""
    c = config()
    if c["foco"] == "siempre":
        return True, "politica: siempre"
    if c["foco"] == "nunca":
        return False, "politica escritorio_foco=nunca (cambiala con /escritorio foco inactivo|siempre)"
    try:
        s = dueno_inactivo_s()
    except Exception as exc:
        return False, "no se pudo medir la inactividad del dueno: %s" % exc
    if s >= c["inactividad_s"]:
        return True, "dueno inactivo %ds (umbral %ds)" % (int(s), c["inactividad_s"])
    return False, ("el dueno esta usando el equipo (ultimo input hace %ds, umbral %ds): "
                   "no se cambia de escritorio" % (int(s), c["inactividad_s"]))


def ir() -> bool:
    """Cambia al escritorio de Cognia (guarda el anterior para volver)."""
    d = asegurar()
    cur = actual()
    if cur.id == d.id:
        return True
    _ANTERIOR["id"] = cur.id
    d.go()
    time.sleep(0.25)
    _anotar("ir", "al escritorio '%s'" % config()["nombre"])
    return True


def volver() -> bool:
    """Vuelve al escritorio donde estaba el dueno antes de ir()."""
    vd = _vd()
    prev = _ANTERIOR.get("id")
    destino = None
    if prev is not None:
        for d in vd.get_virtual_desktops():
            if d.id == prev:
                destino = d
                break
    if destino is None:
        # sin memoria del anterior: el primero que no sea el de Cognia
        mio = _buscar(config()["nombre"])
        for d in vd.get_virtual_desktops():
            if mio is None or d.id != mio.id:
                destino = d
                break
    if destino is None:
        return False
    destino.go()
    time.sleep(0.2)
    _ANTERIOR["id"] = None
    _anotar("volver", "al escritorio del dueno")
    return True


class con_foco:
    """`with con_foco() as ok:` cambia al escritorio de Cognia si la politica
    lo permite y VUELVE siempre al salir (tambien con excepcion). `ok` es
    (bool, motivo)."""

    def __init__(self, forzar: bool = False):
        self.forzar = forzar
        self.cambiado = False
        self.ok = (False, "")

    def __enter__(self):
        if es_el_actual():
            self.ok = (True, "ya en el escritorio de Cognia")
            return self.ok
        permiso, motivo = (True, "forzado") if self.forzar else puede_tomar_foco()
        if not permiso:
            self.ok = (False, motivo)
            return self.ok
        try:
            ir()
            self.cambiado = True
            self.ok = (True, motivo)
        except Exception as exc:
            self.ok = (False, "no se pudo cambiar de escritorio: %s" % exc)
        return self.ok

    def __exit__(self, *exc):
        if self.cambiado:
            try:
                volver()
            except Exception as e:
                _anotar("volver", "", "%s" % e)
        return False


def limpiar(cerrar_ventanas: bool = True, borrar: bool = False) -> dict:
    """Cierra las ventanas del escritorio de Cognia (WM_CLOSE) y, si se pide y
    no es el actual, borra el escritorio. Nunca toca ventanas de otro escritorio."""
    res = {"cerradas": 0, "borrado": False, "error": ""}
    try:
        d = _buscar(config()["nombre"])
        if d is None:
            return res
        if cerrar_ventanas:
            for hwnd, _pid, _t in ventanas_en_escritorio():
                cerrar_ventana(hwnd)
                res["cerradas"] += 1
            # apps de la Store eximidas de la suspension por la mesa: dejar
            # Windows como estaba (cognia/agent/plm.py)
            try:
                from cognia.agent import plm as _plm
                _plm.liberar()
            except Exception:
                pass
        if borrar:
            if es_el_actual(d):
                res["error"] = "no se borra el escritorio actual"
            else:
                d.remove()
                res["borrado"] = True
        _anotar("limpiar", "%d ventana(s) cerradas%s" % (res["cerradas"], ", escritorio borrado" if res["borrado"] else ""))
    except Exception as exc:
        res["error"] = "%s: %s" % (type(exc).__name__, exc)
        _anotar("limpiar", "", res["error"])
    return res


def estado() -> dict:
    c = config()
    ok, motivo = disponible()
    out = {"activo": c["activo"] and ok, "configurado": c["activo"], "disponible": ok, "motivo": motivo,
           "nombre": c["nombre"], "foco": c["foco"], "inactividad_s": c["inactividad_s"],
           "existe": False, "numero": -1, "es_actual": False, "ventanas": [], "ultimo": dict(_ULTIMO)}
    if not ok:
        return out
    try:
        d = _buscar(c["nombre"])
        if d is not None:
            out["existe"] = True
            out["numero"] = _numero(d)
            out["es_actual"] = es_el_actual(d)
            out["ventanas"] = [{"hwnd": h, "pid": p, "titulo": t} for h, p, t in ventanas_en_escritorio()]
        out["dueno_inactivo_s"] = int(dueno_inactivo_s())
    except Exception as exc:
        out["motivo"] = "%s: %s" % (type(exc).__name__, exc)
    return out


# ---------------------------------------------------------------------------
# Ventanas Win32: enumerar, capturar, teclear, clicar, leer
# ---------------------------------------------------------------------------

_WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p) if os.name == "nt" else None


def titulo_ventana(hwnd: int) -> str:
    u = _u32()
    n = u.GetWindowTextLengthW(ctypes.c_void_p(hwnd))
    b = ctypes.create_unicode_buffer(n + 1)
    u.GetWindowTextW(ctypes.c_void_p(hwnd), b, n + 1)
    return b.value


def pid_de(hwnd: int) -> int:
    pid = ctypes.c_uint(0)
    _u32().GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(pid))
    return pid.value


def ventanas_visibles() -> list:
    """[(hwnd, pid, titulo)] de todas las top-level visibles (con o sin titulo)."""
    u = _u32()
    out = []

    def cb(h, _l):
        h = int(h)
        if u.IsWindowVisible(ctypes.c_void_p(h)):
            out.append((h, pid_de(h), titulo_ventana(h)))
        return True
    u.EnumWindows(_WNDENUMPROC(cb), 0)
    return out


def rect_ventana(hwnd: int) -> tuple:
    class RECT(ctypes.Structure):
        _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long), ("r", ctypes.c_long), ("b", ctypes.c_long)]
    r = RECT()
    _u32().GetWindowRect(ctypes.c_void_p(hwnd), ctypes.byref(r))
    return r.l, r.t, r.r - r.l, r.b - r.t


def rect_cliente(hwnd: int) -> tuple:
    """(x_pantalla, y_pantalla, ancho, alto) del area de cliente."""
    class RECT(ctypes.Structure):
        _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long), ("r", ctypes.c_long), ("b", ctypes.c_long)]

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
    u = _u32()
    r = RECT()
    u.GetClientRect(ctypes.c_void_p(hwnd), ctypes.byref(r))
    p = POINT(0, 0)
    u.ClientToScreen(ctypes.c_void_p(hwnd), ctypes.byref(p))
    return p.x, p.y, r.r - r.l, r.b - r.t


def ventana_viva(hwnd: int) -> bool:
    try:
        return bool(_u32().IsWindow(ctypes.c_void_p(int(hwnd))))
    except Exception:
        return False


def capturar_ventana(hwnd: int, salida) -> dict:
    """PNG de la ventana via PrintWindow(PW_RENDERFULLCONTENT): funciona con la
    ventana en otro escritorio virtual y tapada. Devuelve {png, ancho, alto,
    metodo}. Si PrintWindow no pinta nada (algunas apps DirectX exclusivas)
    y la ventana esta en pantalla, cae a ImageGrab del rectangulo."""
    from PIL import Image  # type: ignore
    u, g = _u32(), _g32()
    x, y, W, H = rect_ventana(hwnd)
    if W <= 0 or H <= 0:
        raise ValueError("la ventana %d no tiene tamano (minimizada o cerrada)" % hwnd)
    # una minimizada no se compone: restaurarla sin activarla (SW_SHOWNOACTIVATE)
    if u.IsIconic(ctypes.c_void_p(hwnd)):
        u.ShowWindow(ctypes.c_void_p(hwnd), 4)
        time.sleep(0.3)
        x, y, W, H = rect_ventana(hwnd)

    class BMI(ctypes.Structure):
        _fields_ = [("biSize", ctypes.c_uint), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                    ("biPlanes", ctypes.c_ushort), ("biBitCount", ctypes.c_ushort),
                    ("biCompression", ctypes.c_uint), ("biSizeImage", ctypes.c_uint),
                    ("x", ctypes.c_long), ("y", ctypes.c_long), ("c", ctypes.c_uint), ("i", ctypes.c_uint)]
    hdc = u.GetWindowDC(ctypes.c_void_p(hwnd))
    mdc = g.CreateCompatibleDC(hdc)
    bmp = g.CreateCompatibleBitmap(hdc, W, H)
    g.SelectObject(mdc, bmp)
    try:
        ok = u.PrintWindow(ctypes.c_void_p(hwnd), mdc, 2)      # PW_RENDERFULLCONTENT
        bi = BMI()
        bi.biSize = ctypes.sizeof(BMI)
        bi.biWidth, bi.biHeight, bi.biPlanes, bi.biBitCount = W, -H, 1, 32
        buf = ctypes.create_string_buffer(W * H * 4)
        g.GetDIBits(mdc, bmp, 0, H, buf, ctypes.byref(bi), 0)
        im = Image.frombuffer("RGBA", (W, H), buf, "raw", "BGRA", 0, 1).convert("RGB")
    finally:
        g.DeleteObject(bmp)
        g.DeleteDC(mdc)
        u.ReleaseDC(ctypes.c_void_p(hwnd), hdc)
    metodo = "PrintWindow"
    colores = im.copy()
    colores.thumbnail((64, 64))
    if (not ok or len(colores.getcolors(64 * 64) or []) <= 1):
        # PrintWindow devolvio negro/vacio: si esta en el escritorio actual,
        # fotografiar la pantalla en su rectangulo (apps DirectX exclusivas)
        try:
            from PIL import ImageGrab  # type: ignore
            if es_el_actual() or not activo():
                im2 = ImageGrab.grab(bbox=(x, y, x + W, y + H), all_screens=True)
                c2 = im2.copy()
                c2.thumbnail((64, 64))
                if len(c2.getcolors(64 * 64) or []) > 1:
                    im, metodo = im2, "ImageGrab"
        except Exception:
            pass
    Path(str(salida)).parent.mkdir(parents=True, exist_ok=True)
    im.save(str(salida))
    return {"png": str(salida), "ancho": W, "alto": H, "metodo": metodo}


# Teclas: nombre (castellano/ingles) -> codigo virtual
_VK = {
    "intro": 0x0D, "enter": 0x0D, "return": 0x0D, "escape": 0x1B, "esc": 0x1B,
    "espacio": 0x20, "space": 0x20, "tab": 0x09, "retroceso": 0x08, "backspace": 0x08,
    "supr": 0x2E, "delete": 0x2E, "del": 0x2E, "insert": 0x2D,
    "arriba": 0x26, "up": 0x26, "arrowup": 0x26, "abajo": 0x28, "down": 0x28, "arrowdown": 0x28,
    "izquierda": 0x25, "left": 0x25, "arrowleft": 0x25, "derecha": 0x27, "right": 0x27, "arrowright": 0x27,
    "inicio": 0x24, "home": 0x24, "fin": 0x23, "end": 0x23, "repag": 0x21, "pageup": 0x21,
    "avpag": 0x22, "pagedown": 0x22, "mayus": 0x10, "shift": 0x10, "ctrl": 0x11, "control": 0x11,
    "alt": 0x12, "win": 0x5B, "pausa": 0x13, "capslock": 0x14,
}
for _i in range(1, 13):
    _VK["f%d" % _i] = 0x6F + _i
_CHAR_DE_VK = {0x0D: "\r", 0x20: " ", 0x09: "\t", 0x08: "\b", 0x1B: "\x1b"}


def vk_de(nombre: str) -> tuple:
    """(vk, char) para un nombre de tecla o un caracter. ValueError si no se conoce."""
    n = (nombre or "").strip()
    if not n:
        raise ValueError("tecla vacia")
    b = n.lower()
    if b in _VK:
        vk = _VK[b]
        return vk, _CHAR_DE_VK.get(vk, "")
    if len(n) == 1:
        r = _u32().VkKeyScanW(ord(n))
        vk = r & 0xFF if r != -1 else 0
        return vk, n
    raise ValueError("tecla desconocida: %r (usa intro, escape, espacio, arriba, abajo, izquierda, derecha, f1..f12, letras...)" % n)


def hwnd_con_foco(hwnd: int) -> int:
    """El control con foco del hilo de la ventana (GetGUIThreadInfo), o la ventana."""
    class GTI(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("flags", ctypes.c_uint), ("hwndActive", ctypes.c_void_p),
                    ("hwndFocus", ctypes.c_void_p), ("hwndCapture", ctypes.c_void_p),
                    ("hwndMenuOwner", ctypes.c_void_p), ("hwndMoveSize", ctypes.c_void_p),
                    ("hwndCaret", ctypes.c_void_p), ("rc", ctypes.c_long * 4)]
    u = _u32()
    tid = u.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), None)
    g = GTI()
    g.cbSize = ctypes.sizeof(GTI)
    if tid and u.GetGUIThreadInfo(tid, ctypes.byref(g)) and g.hwndFocus:
        return int(g.hwndFocus)
    return hwnd


def _post(hwnd: int, msg: int, w: int, l: int) -> None:
    _u32().PostMessageW(ctypes.c_void_p(hwnd), msg, ctypes.c_size_t(w), ctypes.c_ssize_t(l))


def enviar_tecla(hwnd: int, nombre: str, veces: int = 1, pausa_ms: int = 40) -> int:
    """Pulsa una tecla por mensajes (WM_KEYDOWN/WM_CHAR/WM_KEYUP) al control con
    foco. Devuelve cuantas pulsaciones mando. Sin modificadores (ver modulo)."""
    vk, ch = vk_de(nombre)
    u = _u32()
    destino = hwnd_con_foco(hwnd)
    scan = u.MapVirtualKeyW(vk, 0) if vk else 0
    lp_down = 1 | (scan << 16)
    lp_up = lp_down | (1 << 30) | (1 << 31)
    n = 0
    for _ in range(max(1, veces)):
        if vk:
            _post(destino, 0x0100, vk, lp_down)
        if ch:
            _post(destino, 0x0102, ord(ch), lp_down)
        if vk:
            _post(destino, 0x0101, vk, lp_up)
        n += 1
        time.sleep(pausa_ms / 1000.0)
    return n


def escribir_texto(hwnd: int, texto: str, pausa_ms: int = 15) -> int:
    destino = hwnd_con_foco(hwnd)
    for ch in texto:
        if ch == "\n":
            enviar_tecla(hwnd, "intro", pausa_ms=pausa_ms)
            continue
        _post(destino, 0x0102, ord(ch), 1)
        time.sleep(pausa_ms / 1000.0)
    return len(texto)


def clic(hwnd: int, x: int, y: int, boton: str = "izquierdo", doble: bool = False) -> dict:
    """Clic por mensajes en coordenadas de CLIENTE de la ventana: se localiza el
    control bajo el punto y se le manda WM_MOUSEMOVE + DOWN/UP en SUS coords."""
    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
    u = _u32()
    p = POINT(int(x), int(y))
    hijo = u.ChildWindowFromPointEx(ctypes.c_void_p(hwnd), p, 0x0001 | 0x0002 | 0x0004)  # skip invisible|disabled|transparent
    hijo = int(hijo) if hijo else hwnd
    if hijo != hwnd:
        # coordenadas del hijo: MapWindowPoints(hwnd -> hijo)
        u.MapWindowPoints(ctypes.c_void_p(hwnd), ctypes.c_void_p(hijo), ctypes.byref(p), 1)
    lp = (int(p.y) & 0xFFFF) << 16 | (int(p.x) & 0xFFFF)
    if boton.startswith("der"):
        down, up, wp, dbl = 0x0204, 0x0205, 0x0002, 0x0206
    else:
        down, up, wp, dbl = 0x0201, 0x0202, 0x0001, 0x0203
    _post(hijo, 0x0200, 0, lp)
    time.sleep(0.03)
    _post(hijo, down, wp, lp)
    _post(hijo, up, 0, lp)
    if doble:
        time.sleep(0.05)
        _post(hijo, dbl, wp, lp)
        _post(hijo, up, 0, lp)
    return {"hwnd_destino": hijo, "x": int(p.x), "y": int(p.y), "control": clase_ventana(hijo)}


def clase_ventana(hwnd: int) -> str:
    b = ctypes.create_unicode_buffer(128)
    _u32().GetClassNameW(ctypes.c_void_p(hwnd), b, 128)
    return b.value


def cerrar_ventana(hwnd: int) -> None:
    _post(hwnd, 0x0010, 0, 0)          # WM_CLOSE


def matar_arbol(pid: int) -> str:
    try:
        if os.name == "nt":
            r = subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True, timeout=15)
            return "taskkill exit %d" % r.returncode
        os.kill(pid, 9)
        return "kill -9"
    except Exception as exc:
        return "no se pudo matar %d: %s" % (pid, exc)


# ---------------------------------------------------------------------------
# Leer la interfaz: texto y arbol UIA
# ---------------------------------------------------------------------------

def _texto_control(hwnd: int) -> str:
    u = _u32()
    n = u.SendMessageW(ctypes.c_void_p(hwnd), 0x000E, 0, 0)     # WM_GETTEXTLENGTH
    if n <= 0 or n > 20000:
        return ""
    b = ctypes.create_unicode_buffer(n + 1)
    u.SendMessageW(ctypes.c_void_p(hwnd), 0x000D, n + 1, b)    # WM_GETTEXT
    return b.value


def texto_win32(hwnd: int, maximo: int = 80) -> list:
    """[(clase, texto)] de la ventana y sus hijos con texto (Edit, Static, Button...)."""
    u = _u32()
    out = []
    t = titulo_ventana(hwnd)
    if t:
        out.append(("ventana", t))

    def cb(h, _l):
        h = int(h)
        tx = _texto_control(h)
        if tx.strip():
            out.append((clase_ventana(h), tx.strip()[:300]))
        return len(out) < maximo
    u.EnumChildWindows(ctypes.c_void_p(hwnd), _WNDENUMPROC(cb), 0)
    return out


def arbol_uia(hwnd: int, profundidad: int = 6, maximo: int = 150) -> list:
    """Arbol de UI Automation: [(nivel, tipo, nombre, (x,y,w,h) en coords de
    cliente de la ventana, estado)]. Con uiautomation (instalado en el venv);
    ValueError con el pip exacto si falta. Lee ventanas de otro escritorio."""
    try:
        import uiautomation as auto  # type: ignore
    except Exception as exc:
        raise ValueError("falta uiautomation (%s). Instalalo con: pip install uiautomation" % exc)
    raiz = auto.ControlFromHandle(int(hwnd))
    if not raiz:
        raise ValueError("UIA no devolvio control para hwnd %d" % hwnd)
    cx, cy, _w, _h = rect_cliente(hwnd)
    out = []

    def rec(ctrl, nivel):
        if len(out) >= maximo or nivel > profundidad:
            return
        try:
            r = ctrl.BoundingRectangle
            rect = (r.left - cx, r.top - cy, r.width(), r.height()) if r else (0, 0, 0, 0)
            tipo = ctrl.ControlTypeName.replace("Control", "")
            nombre = (ctrl.Name or "")[:80]
            estado = []
            try:
                if ctrl.IsEnabled is False:
                    estado.append("deshabilitado")
            except Exception:
                pass
            try:
                pat = ctrl.GetValuePattern() if hasattr(ctrl, "GetValuePattern") else None
                if pat and pat.Value:
                    estado.append("valor=%r" % pat.Value[:60])
            except Exception:
                pass
            try:
                tp = ctrl.GetTogglePattern() if hasattr(ctrl, "GetTogglePattern") else None
                if tp:
                    estado.append("toggle=%s" % tp.ToggleState)
            except Exception:
                pass
            out.append((nivel, tipo, nombre, rect, ", ".join(estado)))
        except Exception:
            return
        try:
            for hijo in ctrl.GetChildren():
                rec(hijo, nivel + 1)
        except Exception:
            pass
    rec(raiz, 0)
    return out


def texto_arbol(arbol: list, maximo_chars: int = 3500) -> str:
    lineas = []
    for nivel, tipo, nombre, rect, estado in arbol:
        if not nombre and tipo in ("Pane", "Group", "Custom") and nivel > 0:
            continue
        lineas.append("%s%s%s @%d,%d %dx%d%s" % ("  " * nivel, tipo, (" %r" % nombre) if nombre else "",
                                                 rect[0], rect[1], rect[2], rect[3],
                                                 (" [%s]" % estado) if estado else ""))
    s = "\n".join(lineas)
    if len(s) > maximo_chars:
        s = s[:maximo_chars] + "\n... (arbol truncado)"
    return s


def buscar_control(hwnd: int, texto: str) -> tuple:
    """Centro (x, y) en coords de cliente del primer control UIA cuyo nombre
    contiene `texto` (sin distinguir mayusculas), o None."""
    t = (texto or "").strip().lower()
    for _n, tipo, nombre, rect, _e in arbol_uia(hwnd, profundidad=10, maximo=400):
        if t and t in (nombre or "").lower() and rect[2] > 0:
            return (rect[0] + rect[2] // 2, rect[1] + rect[3] // 2, tipo, nombre)
    return None


# ---------------------------------------------------------------------------
# Entrada REAL (modo foco): pyautogui en el escritorio de Cognia
# ---------------------------------------------------------------------------

def entrada_real(hwnd: int, acciones: list, forzar: bool = False) -> dict:
    """Ejecuta acciones con entrada REAL: [('tecla', nombre, veces), ('escribir',
    texto), ('clic', x, y, boton), ('atajo', 'ctrl+s')]. Cambia al escritorio de
    Cognia segun la politica y vuelve. Devuelve {ok, motivo, hechas}."""
    try:
        import pyautogui  # type: ignore
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.05
    except Exception as exc:
        return {"ok": False, "motivo": "falta pyautogui: %s" % exc, "hechas": 0}
    hechas = 0
    with con_foco(forzar=forzar) as (ok, motivo):
        if not ok:
            return {"ok": False, "motivo": motivo, "hechas": 0}
        u = _u32()
        u.SetForegroundWindow(ctypes.c_void_p(hwnd))
        time.sleep(0.2)
        cx, cy, _w, _h = rect_cliente(hwnd)
        for a in acciones:
            try:
                if a[0] == "tecla":
                    nombre = a[1].lower()
                    nombre = {"intro": "enter", "espacio": "space", "arriba": "up", "abajo": "down",
                              "izquierda": "left", "derecha": "right", "retroceso": "backspace",
                              "supr": "delete", "escape": "esc", "inicio": "home", "fin": "end"}.get(nombre, nombre)
                    pyautogui.press(nombre, presses=int(a[2]) if len(a) > 2 else 1, interval=0.05)
                elif a[0] == "escribir":
                    pyautogui.typewrite(a[1], interval=0.02)
                elif a[0] == "clic":
                    pyautogui.click(cx + int(a[1]), cy + int(a[2]), button="right" if len(a) > 3 and str(a[3]).startswith("der") else "left")
                elif a[0] == "atajo":
                    pyautogui.hotkey(*[p.strip() for p in a[1].replace("+", " ").split()])
                hechas += 1
            except Exception as exc:
                return {"ok": False, "motivo": "accion %r fallo: %s" % (a, exc), "hechas": hechas}
        time.sleep(0.15)
    return {"ok": True, "motivo": motivo, "hechas": hechas}


# ---------------------------------------------------------------------------
# Registro de apps lanzadas por Cognia (para no tocar nunca ventanas ajenas)
# ---------------------------------------------------------------------------

def registro_cargar() -> dict:
    try:
        if _REGISTRO.exists():
            return json.loads(_REGISTRO.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def registro_guardar(reg: dict) -> None:
    try:
        _REGISTRO.parent.mkdir(parents=True, exist_ok=True)
        tmp = _REGISTRO.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, _REGISTRO)
    except Exception as exc:
        _anotar("registro", "", "no se pudo guardar: %s" % exc)


def ultimo() -> dict:
    return dict(_ULTIMO)
