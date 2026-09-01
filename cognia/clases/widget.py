# -*- coding: utf-8 -*-
"""
cognia/clases/widget.py
=======================
EL CEREBRITO: el icono flotante que el duenio ve todos los dias. Es la unica
pieza de Cognia que no se teclea -- vive en una esquina del escritorio, dice
de un vistazo si la clase se esta grabando, y con un clic abre el menu de la
jornada (grabar / pausar / mutear / materia / ver cuaderno / exportar).

MANDA `jornada.estado()`, NO ESTE FICHERO
-----------------------------------------
El menu y el color del icono se construyen SIEMPRE desde `jornada.estado()`.
No hay una copia local de "estoy grabando": si la hubiera, el widget y el REPL
se contradirian en cuanto el duenio parara la jornada desde el otro lado (que
es exactamente lo que pasa: el lock de proceso de `jornada.py` existe porque
las dos ventanas conviven). Por eso el menu no ofrece Detener cuando no hay
nada que detener: no es cosmetica, es que el estado se pregunta cada segundo.

Y SE MIRAN LAS DOS CLAVES, `grabando` Y `otro_proceso`. La primera solo es
True si la jornada vive en ESTE proceso; la segunda sale del lock y es la que
dice que graba el REPL de al lado -- el caso normal. Mirar solo `grabando`
pintaba el cerebrito apagado con la clase grabandose (ver `graba_alguien`).

LAS TRES TRAMPAS DE UN ICONO FLOTANTE EN WINDOWS, y como se resuelven aqui
-------------------------------------------------------------------------
1. DPI. Sin `SetProcessDpiAwareness(2)` (per-monitor v2) Windows escala la
   ventana por su cuenta: el PNG sale BORROSO y las coordenadas que devuelve
   Tk no son las de la pantalla, asi que el icono aparece desplazado. La
   llamada tiene que ir ANTES de crear la ventana -- despues no hace nada --
   y por eso es lo primero de `Cerebrito.__init__` (y esta suelta en
   `hacerse_consciente_del_dpi()` para poder llamarla desde `__main__`).

2. TRANSPARENCIA. Tk no tiene alfa por pixel. `-transparentcolor` es
   transparencia POR CLAVE DE COLOR y por eso el icono se dibuja con borde
   DURO (todo el porque, medido, esta en el encabezado de widget_icono.py).
   Aqui solo hay que respetar la consecuencia: el fondo de la ventana y el de
   la etiqueta valen `widget_icono.COLOR_CLAVE`, exactamente.

3. LA POSICION NO SE PREGUNTA A TK. `winfo_screenwidth()` devuelve el ancho
   del monitor PRIMARIO y no sabe nada de la barra de tareas: con dos
   pantallas -- o con la barra a la izquierda -- pone el icono donde no es o
   debajo de la barra. Se pide `SPI_GETWORKAREA` (el area util real) y, para
   validar una posicion guardada, `EnumDisplayMonitors` (todas las pantallas).
   Si el monitor donde estaba ya no existe, el icono vuelve al sitio por
   defecto en vez de aparecer fuera de la pantalla, donde no se puede ni
   agarrar para traerlo.

NADA BLOQUEA EL HILO DE TK
--------------------------
Arrancar la jornada abre el dispositivo de audio, arrancar el servidor levanta
un socket y exportar recorre el cuaderno entero: cualquiera de las tres tarda
lo bastante como para que la interfaz se quede clavada. Van a un hilo y el
resultado vuelve por una COLA que el bucle de Tk vacia en cada tick. La cola
-- y no `raiz.after()` desde el hilo -- porque `after` desde otro hilo toca
estructuras de Tcl sin el lock del interprete: funciona casi siempre, que es
la peor clase de bug. Y la animacion va con `after`, JAMAS con `time.sleep`:
dormir en el hilo de Tk congela la ventana entera, menu incluido.

TODO `after` PENDIENTE SE CANCELA AL CERRAR. Un callback programado que se
dispara medio segundo despues de `destroy()` toca widgets que ya no existen y
vuelca un TclError al terminar el proceso.
"""

from __future__ import annotations

import base64
import logging
import os
import queue
import subprocess
import threading
import time
from pathlib import Path

from cognia.clases import almacen as alm
from cognia.clases import cuaderno as cua
from cognia.clases import jornada as jor
from cognia.clases import widget_icono as ico

log = logging.getLogger(__name__)

# Config del widget, dentro del cuaderno (asi COGNIA_CLASES_DIR tambien la
# mueve y una suite no puede pisarle la posicion al duenio).
CONFIG = "widget.json"

# El lock del widget. NO es el de jornada.py: aquel solo existe MIENTRAS se
# graba, asi que dos cerebritos con la jornada parada no se verian el uno al
# otro -- y son dos iconos superpuestos, dos menus y dos exportaciones.
LOCK_WIDGET = "widget.lock"

# Lado del icono en pixeles fisicos. 48 es lo que ocupa un icono de bandeja
# grande en Windows a 100 %; con DPI consciente no lo reescala nadie.
LADO = 48

# Margen contra el borde del area de trabajo. 12 px: separado del borde y
# lejos de los botones de cerrar de las ventanas maximizadas.
MARGEN = 12

# Ritmo del bucle de Tk. 120 ms es el fotograma del latido (ver
# widget_icono.PASOS_LATIDO) y a la vez la latencia con la que se recogen los
# resultados de los hilos: mas rapido no se nota y gasta CPU todo el dia.
PERIODO_TICK_MS = 120

# Cada cuantos ticks se relee `jornada.estado()`. 8 x 120 ms ~ 1 s: el estado
# lo cambia una persona, no hace falta mas fino, y `estado()` lee ficheros.
TICKS_POR_REFRESCO = 8

# Cuanto se puede mover el raton entre pulsar y soltar para que siga contando
# como CLIC y no como arrastre. 4 px: con un raton normal un clic no se mueve,
# pero con un trackpad si tiembla y sin esta holgura el menu no abriria nunca.
UMBRAL_ARRASTRE = 4

# Que fraccion del icono tiene que caer dentro de alguna pantalla para que una
# posicion guardada se considere valida. La mitad: menos que eso ya no se
# puede agarrar con el raton para traerlo de vuelta.
VISIBLE_MINIMO = 0.5

SPI_GETWORKAREA = 0x0030

_ULTIMO_ERROR: dict = {}


def _avisar(donde: str, motivo: str, accion: str = "") -> None:
    """Deja constancia de una degradacion por el canal de la casa.

    Mismo patron que `almacen._degradar_una_vez` y `servidor_vivo._avisar`,
    con el import perezoso por la misma razon. Aqui importa especialmente:
    el widget no tiene consola donde escribir, asi que un fallo suyo que no
    pase por este canal NO LO VE NADIE -- se veria igual que "no lo cablearon".
    """
    _ULTIMO_ERROR.clear()
    _ULTIMO_ERROR.update({"donde": donde, "motivo": motivo, "t": time.time()})
    log.warning("clases.widget: %s -- %s", donde, motivo)
    try:
        from cognia.ux import events as _ux
        _ux.emitir(_ux.Degradado(donde=donde, motivo=motivo,
                                 accion_sugerida=accion))
    except Exception as exc:
        # El canal de avisos es justo lo que se acaba de romper: queda en el
        # log y se sigue. Nunca un except mudo.
        log.warning("clases.widget: tampoco pude avisar por ux (%s)", exc)


def ultimo_error() -> dict:
    """Lo ultimo que se degrado en el widget, o {}. Puerta de diagnostico."""
    return dict(_ULTIMO_ERROR)


# ── DPI ──────────────────────────────────────────────────────────────────────

def hacerse_consciente_del_dpi() -> str:
    """Declara el proceso per-monitor DPI aware. Devuelve "" o el motivo.

    TIENE QUE LLAMARSE ANTES DE CREAR LA VENTANA: Windows fija el modo DPI del
    proceso en la primera ventana y despues la llamada devuelve
    E_ACCESSDENIED. Sin esto, en un monitor al 125 % o al 150 % el sistema
    estira la ventana por su cuenta (el PNG sale borroso) y las coordenadas
    que se le dan a `geometry()` no son pixeles fisicos, asi que el icono
    tampoco cae donde se le dijo.

    MEDIDO en esta maquina el 2026-08-31: `SetProcessDpiAwareness(2)` devuelve
    S_OK (0). Devuelve el motivo en vez de lanzar porque un icono borroso es
    molesto y un widget que no arranca es inutil.
    """
    if os.name != "nt":
        return "no es Windows: no hay DPI que declarar"
    try:
        import ctypes
        # 2 = PROCESS_PER_MONITOR_DPI_AWARE. Es el unico que sirve con dos
        # pantallas a distinta escala, que es el caso que rompe la posicion.
        hr = ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception as exc:
        return "%s: %s" % (type(exc).__name__, exc)
    if hr == 0:
        return ""
    # E_ACCESSDENIED (0x80070005) = ya estaba puesto (por otra llamada o por
    # el manifiesto). No es un fallo: es que el trabajo ya estaba hecho.
    if hr in (-2147024891, 0x80070005):
        return ""
    return "SetProcessDpiAwareness devolvio 0x%08x" % (hr & 0xFFFFFFFF)


# ── Geometria de la pantalla ─────────────────────────────────────────────────

def area_trabajo() -> tuple:
    """(x, y, ancho, alto) del area UTIL del monitor primario, o () si no se
    puede saber.

    Area util = pantalla menos la barra de tareas. Es lo que hace falta para
    la esquina superior derecha: con la barra arriba (o con dos filas de
    barra) la esquina de la PANTALLA queda tapada.
    """
    if os.name != "nt":
        return ()
    try:
        import ctypes
        from ctypes import wintypes

        class RECT(ctypes.Structure):
            _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                        ("right", wintypes.LONG), ("bottom", wintypes.LONG)]

        r = RECT()
        ok = ctypes.windll.user32.SystemParametersInfoW(
            SPI_GETWORKAREA, 0, ctypes.byref(r), 0)
        if not ok:
            return ()
        return (int(r.left), int(r.top),
                int(r.right - r.left), int(r.bottom - r.top))
    except Exception as exc:
        _avisar("clases.widget.area",
                "no pude leer el area de trabajo (%s: %s)"
                % (type(exc).__name__, exc),
                accion="el icono ira a la esquina que sepa Tk")
        return ()


def monitores() -> list:
    """[(x, y, ancho, alto), ...] de TODAS las pantallas conectadas.

    Hace falta para validar una posicion guardada. El caso real: el duenio
    dejo el cerebrito en el monitor de la derecha, se llevo el portatil y hoy
    solo hay una pantalla. Sin esta lista, el widget se pinta en x=2600 --
    fuera de todo -- y no hay forma de agarrarlo con el raton.
    """
    if os.name != "nt":
        return []
    try:
        import ctypes
        from ctypes import wintypes

        class RECT(ctypes.Structure):
            _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                        ("right", wintypes.LONG), ("bottom", wintypes.LONG)]

        PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HANDLE,
                                  wintypes.HDC, ctypes.POINTER(RECT),
                                  wintypes.LPARAM)
        fuera = []

        def _uno(_h, _hdc, caja, _lp):
            c = caja.contents
            fuera.append((int(c.left), int(c.top),
                          int(c.right - c.left), int(c.bottom - c.top)))
            return 1

        # La referencia al PROC se guarda en una variable: si se pasa el
        # objeto temporal, CPython puede liberarlo mientras user32 todavia lo
        # esta llamando.
        cb = PROC(_uno)
        ctypes.windll.user32.EnumDisplayMonitors(0, 0, cb, 0)
        return fuera
    except Exception as exc:
        _avisar("clases.widget.monitores",
                "no pude enumerar las pantallas (%s: %s)"
                % (type(exc).__name__, exc),
                accion="no se validara la posicion guardada")
        return []


def posicion_por_defecto(area: tuple, lado: int = LADO,
                         margen: int = MARGEN) -> tuple:
    """Esquina superior derecha del AREA DE TRABAJO. Pura, y por eso probable.

    `area` es (x, y, ancho, alto) y NO se supone que empiece en (0, 0): con la
    barra de tareas a la izquierda empieza en x=48, y con dos pantallas el
    origen puede ser negativo. Usar `ancho` como si fuera el borde derecho es
    justo el bug que esta funcion evita.
    """
    if not area or len(area) != 4:
        return (margen, margen)
    x, y, ancho, alto = (int(v) for v in area)
    return (x + ancho - int(lado) - int(margen), y + int(margen))


def _solape(a: tuple, b: tuple) -> int:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    dx = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    dy = max(0, min(ay + ah, by + bh) - max(ay, by))
    return dx * dy


def posicion_valida(pos, pantallas: list, lado: int = LADO,
                    minimo: float = VISIBLE_MINIMO) -> bool:
    """Si un icono en `pos` se veria (y se podria agarrar) en alguna pantalla.

    No basta con "el punto cae dentro": un icono con la esquina superior
    izquierda dentro del monitor pero el resto fuera es igual de inagarrable.
    Se mide el AREA solapada contra cada pantalla y se exige `minimo`.

    Sin pantallas conocidas se responde True: no se puede demostrar que la
    posicion sea mala y tirar la del duenio por no poder comprobarla seria
    peor (le moveria el icono en cada arranque).
    """
    if not pos or len(pos) != 2:
        return False
    if not pantallas:
        return True
    lado = int(lado)
    caja = (int(pos[0]), int(pos[1]), lado, lado)
    area = float(lado * lado) or 1.0
    return any(_solape(caja, p) / area >= float(minimo) for p in pantallas)


def elegir_posicion(guardada, pantallas: list, area: tuple,
                    lado: int = LADO, margen: int = MARGEN) -> tuple:
    """La posicion con la que arranca el icono. Pura.

    Es la funcion que cumple el contrato "posicion persistida y VALIDADA al
    arrancar": si lo guardado sigue cayendo en una pantalla que existe, se
    respeta; si no -- monitor desconectado, resolucion cambiada, fichero con
    basura -- se vuelve al sitio por defecto en vez de pintar el icono en un
    sitio del que no se puede rescatar.
    """
    try:
        pos = (int(guardada[0]), int(guardada[1]))
    except (TypeError, ValueError, IndexError, KeyError):
        pos = None
    if pos is not None and posicion_valida(pos, pantallas, lado):
        return pos
    return posicion_por_defecto(area, lado, margen)


# ── Config persistida ────────────────────────────────────────────────────────

def ruta_config() -> Path:
    return alm.raiz() / CONFIG


def cargar_config() -> dict:
    """La config del widget, con defaults sensatos. Nunca lanza.

    Un JSON corrupto aqui NO puede impedir que el icono arranque: se avisa y
    se sigue con los defaults, que es lo que separa "no configurado" de
    "roto".
    """
    datos = alm.leer_json(ruta_config(), None)
    cfg = {"x": None, "y": None, "lado": LADO}
    if isinstance(datos, dict):
        cfg.update({k: datos.get(k, cfg[k]) for k in cfg})
    elif datos is not None:
        _avisar("clases.widget.config",
                "%s no contiene un objeto JSON: uso los valores por defecto"
                % ruta_config(),
                accion="borrar el fichero si el icono aparece donde no toca")
    try:
        cfg["lado"] = max(16, min(256, int(cfg["lado"])))
    except (TypeError, ValueError):
        cfg["lado"] = LADO
    return cfg


def guardar_config(cfg: dict) -> None:
    """Persiste la config. `almacen.guardar_json` ya escribe de forma atomica."""
    try:
        alm.guardar_json(ruta_config(), dict(cfg))
    except OSError as exc:
        _avisar("clases.widget.config",
                "no pude guardar %s (%s): el icono volvera a su sitio por "
                "defecto en el proximo arranque" % (ruta_config(), exc),
                accion="revisar permisos de la carpeta de clases")


# ── Lock del widget (un unico cerebrito por escritorio) ──────────────────────
# Copiado en forma de `jornada._tomar_lock`, que es el lock ya depurado de esta
# casa, pero sobre OTRO fichero y con `jornada._pid_vivo` REUTILIZADO a
# proposito: reescribir aqui el OpenProcess/GetExitCodeProcess con sus
# argtypes es exactamente el bug que aquel modulo documenta (sin argtypes el
# HANDLE llega truncado y todo proceso parece muerto).

def ruta_lock_widget() -> Path:
    return alm.raiz() / LOCK_WIDGET


def lock_widget_actual() -> dict:
    """{} o el lock con 'pid', 'vivo', 'ajeno' y 'edad'."""
    datos = alm.leer_json(ruta_lock_widget(), None)
    if not isinstance(datos, dict) or not datos.get("pid"):
        return {}
    pid = int(datos.get("pid") or 0)
    fuera = dict(datos)
    fuera["pid"] = pid
    fuera["vivo"] = jor._pid_vivo(pid)
    fuera["ajeno"] = pid != os.getpid()
    fuera["edad"] = max(0.0, time.time() - float(datos.get("epoch") or 0.0))
    return fuera


def tomar_lock_widget() -> tuple:
    """(ok, aviso). Reserva EL cerebrito para este proceso.

    Se niega solo si hay otro widget VIVO. Un lock de un PID muerto es rancio
    (el equipo se apago sin cerrar) y se roba dejando aviso, porque "nadie lo
    cerro" y "se lo he quitado a otro" no pueden verse igual desde fuera.
    """
    ruta = ruta_lock_widget()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    viejo = lock_widget_actual()
    pid = int(viejo.get("pid") or 0)
    if pid and viejo.get("vivo") and viejo.get("ajeno"):
        return False, ("ya hay un cerebrito abierto en el proceso PID %d "
                       "(desde las %s). Cierra ese antes de abrir otro."
                       % (pid, time.strftime("%H:%M", time.localtime(
                           float(viejo.get("epoch") or 0.0)))))
    aviso = ""
    if ruta.exists() and pid and viejo.get("ajeno"):
        aviso = ("habia un lock del cerebrito del PID %d, que ya no existe: "
                 "me quedo yo" % pid)
        log.warning(aviso)
    elif ruta.exists() and not pid:
        aviso = ("el lock del cerebrito estaba ilegible (vacio o corrupto): "
                 "no protegia a nadie, me quedo yo")
        log.warning(aviso)
    try:
        alm.guardar_json(ruta, {"pid": os.getpid(), "epoch": time.time()})
    except OSError as exc:
        return False, "no pude tomar el lock del cerebrito: %s" % exc
    return True, aviso


def soltar_lock_widget() -> str:
    """Borra el lock SOLO si es nuestro. Devuelve "" o el motivo de por que no.

    Comprobar el PID no es paranoia: si otro proceso ya nos lo robo por
    rancio, borrarlo aqui le dejaria sin lock y volveriamos a los dos
    cerebritos.
    """
    ruta = ruta_lock_widget()
    try:
        if not ruta.exists():
            return ""
        datos = alm.leer_json(ruta, None)
        if not isinstance(datos, dict) or not datos.get("pid"):
            return ("no suelto el lock del cerebrito: esta ilegible y no "
                    "puedo demostrar que sea mio")
        if int(datos.get("pid") or 0) != os.getpid():
            return ("no suelto el lock del cerebrito: ahora es del PID %d"
                    % int(datos.get("pid") or 0))
        os.unlink(str(ruta))
    except FileNotFoundError:
        return ""
    except OSError as exc:
        return "no pude soltar el lock del cerebrito: %s" % exc
    return ""


# ── El navegador en modo aplicacion ──────────────────────────────────────────
# El duenio pidio VER EL CUADERNO, no "una pestania mas": `--app=<url>` abre
# una ventana propia, sin pestanias, sin barra de direcciones y con su propia
# entrada en la barra de tareas. Lo soportan Edge y Chrome (los dos son
# Chromium); Firefox quito `-ssb` en 2021 y no tiene equivalente, asi que ahi
# se cae al navegador por defecto DICIENDOLO.

APP_PATHS = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"

# Orden deliberado: Edge primero porque en Windows 11 esta SIEMPRE, asi que es
# el que hace que esto funcione sin instalar nada.
EJECUTABLES = ("msedge.exe", "chrome.exe", "brave.exe")

# Carpetas conocidas, como plan B del registro. NO se hardcodea una sola ruta:
# Edge esta en Program Files (x86) en unas maquinas y en Program Files en
# otras, y Chrome se instala tambien por usuario en %LOCALAPPDATA%.
_SUBRUTAS = {
    "msedge.exe": (r"Microsoft\Edge\Application\msedge.exe",),
    "chrome.exe": (r"Google\Chrome\Application\chrome.exe",),
    "brave.exe": (r"BraveSoftware\Brave-Browser\Application\brave.exe",),
}


def _de_registro(exe: str) -> list:
    """Lo que dice `App Paths` sobre ese ejecutable. Es la fuente BUENA: la
    escribe el instalador, asi que sigue siendo correcta cuando el navegador
    esta en una carpeta rara."""
    if os.name != "nt":
        return []
    fuera = []
    try:
        import winreg
    except ImportError:
        return []
    for raiz in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(raiz, APP_PATHS + "\\" + exe) as k:
                valor, _ = winreg.QueryValueEx(k, None)
        except OSError:
            continue                    # esa rama no lo tiene: normal
        valor = str(valor or "").strip().strip('"')
        if valor:
            fuera.append(valor)
    return fuera


def candidatos_navegador() -> list:
    """Rutas candidatas a un navegador Chromium, de la mas fiable a la menos.

    Registro -> carpetas conocidas -> PATH. Las tres, y en ese orden, porque
    ninguna sola acierta siempre: el registro falla con instalaciones
    portables, las carpetas conocidas fallan si se instalo en otro disco, y el
    PATH normalmente no tiene ningun navegador.
    """
    import shutil
    fuera, visto = [], set()

    def _mete(p):
        p = str(p or "").strip()
        if p and p.lower() not in visto:
            visto.add(p.lower())
            fuera.append(p)

    bases = [os.environ.get("PROGRAMFILES", ""),
             os.environ.get("PROGRAMFILES(X86)", ""),
             os.environ.get("LOCALAPPDATA", "")]
    for exe in EJECUTABLES:
        for p in _de_registro(exe):
            _mete(p)
        for base in bases:
            for sub in _SUBRUTAS.get(exe, ()):
                if base:
                    _mete(os.path.join(base, sub))
        _mete(shutil.which(exe) or "")
    return fuera


def buscar_navegador(candidatos=None) -> str:
    """La primera ruta de `candidatos` que exista, o "" si ninguna.

    `candidatos` se inyecta para poder probar la eleccion sin depender de que
    la maquina de test tenga Edge instalado.
    """
    for ruta in (candidatos if candidatos is not None
                 else candidatos_navegador()):
        try:
            if ruta and os.path.isfile(ruta):
                return str(ruta)
        except OSError:
            continue                    # ruta imposible (unidad de red caida)
    return ""


def comando_app(exe: str, url: str, tam=(1100, 820)) -> list:
    """La linea de comandos que abre `url` como APLICACION.

    `--app=` es lo que quita pestanias y barra de direcciones.
    `--window-size` va porque sin el la ventana hereda el tamanio de la ultima
    del perfil, que suele ser una ventana de navegacion maximizada.
    """
    return [str(exe), "--app=%s" % url,
            "--window-size=%d,%d" % (int(tam[0]), int(tam[1]))]


def abrir_en_app(url: str, candidatos=None) -> tuple:
    """(ok, mensaje). Abre la URL en ventana propia; si no puede, cae al
    navegador por defecto DICIENDOLO.

    La caida se avisa por el canal de degradacion: un cuaderno que aparece con
    pestanias y barra de direcciones no es un fallo silencioso -- se ve -- pero
    el duenio tiene que poder saber POR QUE, y "no encontre Edge ni Chrome" es
    accionable; una ventana distinta sin explicacion, no.
    """
    exe = buscar_navegador(candidatos)
    if exe:
        try:
            subprocess.Popen(comando_app(exe, url),
                             close_fds=True)
            return True, "cuaderno abierto en %s" % os.path.basename(exe)
        except OSError as exc:
            _avisar("clases.widget.navegador",
                    "no pude lanzar %s (%s): abro el navegador por defecto"
                    % (exe, exc),
                    accion="ninguna: la pagina se abre igual, con pestanias")
    else:
        _avisar("clases.widget.navegador",
                "no encontre Edge ni Chrome para abrir el cuaderno en ventana "
                "propia (--app): abro el navegador por defecto",
                accion="instalar Edge o Chrome si quieres la ventana limpia")
    try:
        import webbrowser
        webbrowser.open(url)
        return True, "cuaderno abierto en el navegador por defecto (sin --app)"
    except Exception as exc:
        motivo = ("no pude abrir el cuaderno (%s: %s). La URL es %s"
                  % (type(exc).__name__, exc, url))
        _avisar("clases.widget.navegador", motivo,
                accion="pegar la URL a mano en el navegador")
        return False, motivo


# ── El menu, construido desde jornada.estado() ───────────────────────────────

SEPARADOR = {"tipo": "separador"}


def _cmd(clave: str, etiqueta: str, activo: bool = True) -> dict:
    return {"tipo": "comando", "clave": clave, "etiqueta": etiqueta,
            "activo": bool(activo)}


def entradas_menu(est: dict, materias=None) -> list:
    """La estructura del menu para ESE estado. Pura: es lo que se prueba.

    Devuelve una lista de dicts ('comando' / 'separador' / 'submenu') que
    `Cerebrito._menu` traduce a `tk.Menu`. Separar la decision del dibujo es
    lo unico que permite comprobar sin pantalla la regla que pidio el duenio:
    EL MENU REFLEJA LO QUE DE VERDAD PASA. Si no graba no aparece Detener --
    no "aparece en gris": no aparece -- porque un boton que solo puede fallar
    es peor que ningun boton.

    Los tres estados posibles y lo que ofrecen:
      - graba OTRO proceso (el lock de jornada.py es ajeno y su PID vive): no
        se ofrece nada de grabacion, porque desde aqui no se puede tocar esa
        jornada; se dice quien la tiene Y SE OFRECE LA SALIDA DE EMERGENCIA.
      - no graba nadie: solo Grabar.
      - grabamos nosotros: Pausar/Reanudar, Detener, Mutear/Desmutear y el
        submenu de Materia, que necesita una jornada viva donde marcar.

    POR QUE 'Liberar el bloqueo' TIENE QUE ESTAR AHI. `jornada._pid_vivo`
    responde VIVO cuando no puede comprobar el proceso, y ademas Windows
    RECICLA los PID: un lock olvidado cuyo numero hoy es de un chrome.exe deja
    la grabacion bloqueada para siempre, y desde el cerebrito -- que es la
    unica interfaz que el duenio mira -- no habria ninguna forma de salir. Es
    exactamente el caso para el que existe `jornada.forzar_liberacion`, asi que
    la puerta se ofrece justo donde aparece el problema. Va con pregunta
    (`Cerebrito._liberar_bloqueo`): forzar sobre una grabacion viva de verdad
    deja dos grabadores sobre la misma carpeta.
    """
    est = est or {}
    grabando = bool(est.get("grabando"))
    otro = bool(est.get("otro_proceso")) and not grabando
    ent = []
    if otro:
        pid = (est.get("lock") or {}).get("pid") or "?"
        ent.append(_cmd("ocupado", "Graba otro proceso (PID %s)" % pid,
                        activo=False))
        ent.append(_cmd("liberar",
                        "Liberar el bloqueo (si ese proceso ya no existe)"))
    elif not grabando:
        ent.append(_cmd("grabar", "Grabar"))
    else:
        ent.append(_cmd("pausar",
                        "Reanudar" if est.get("pausada") else "Pausar"))
        ent.append(_cmd("detener", "Detener"))
        ent.append(_cmd("mutear",
                        "Desmutear" if est.get("muteada") else "Mutear"))
    ent.append(dict(SEPARADOR))

    nombres = list(materias) if materias is not None else []
    hijos = [_cmd("materia:" + n, n) for n in nombres]
    hijos.append(_cmd("materia:otra", "otra..."))
    ent.append({"tipo": "submenu", "clave": "materia", "etiqueta": "Materia",
                "activo": grabando, "hijos": hijos})

    ent.append(dict(SEPARADOR))
    ent.append(_cmd("cuaderno", "Ver cuaderno"))
    ent.append(_cmd("exportar", "Exportar"))
    ent.append(dict(SEPARADOR))
    ent.append(_cmd("salir", "Salir"))
    return ent


def hay_fallo(est: dict) -> bool:
    """Si el estado trae algun aviso que el duenio deberia ver.

    `jornada.estado()` publica `aviso` (el ultimo guardado en jornada.json) y
    `avisos` (los tres ultimos del grabador y la transcripcion). Cualquiera de
    los dos no vacio pinta el icono en rojo. Es DELIBERADAMENTE amplio: el
    modo de fallo que este widget existe para matar es el duenio dando por
    grabada una clase que no se grabo, y para eso un rojo de mas cuesta una
    mirada al tooltip mientras que un rojo de menos cuesta la clase.
    """
    est = est or {}
    return bool(est.get("aviso")) or bool(est.get("avisos"))


def graba_alguien(est: dict) -> bool:
    """Si la clase se esta grabando, EN ESTE PROCESO O EN OTRO.

    ESTA DISTINCION ES EL BUG QUE ESTA FUNCION EXISTE PARA MATAR.
    `est['grabando']` es True solo cuando la jornada vive en ESTE proceso:
    `jornada.estado()` lo saca de `viva()`, que es una variable de modulo. Con
    la clase grabandose desde el REPL -- el caso NORMAL, que es justo para el
    que se hizo este widget -- esa clave vale False y solo `otro_proceso`
    (leido del lock de jornada.py, o sea de un PID ajeno y VIVO) dice la
    verdad. Mirar unicamente `grabando` pintaba el cerebrito APAGADO con la
    clase grabandose: la mentira mas cara que puede contar este icono, porque
    el duenio la lee de un vistazo y da la clase por perdida (o por grabada)
    sin abrir nada.
    """
    est = est or {}
    return bool(est.get("grabando")) or bool(est.get("otro_proceso"))


def estado_icono(est: dict) -> str:
    """Que cara pone el cerebrito para ese estado. Pura.

    ORDEN DE PRIORIDAD, y es lo que se prueba: el fallo gana a todo (si la
    captura se rompio, da igual que ademas este muteado), luego el mute, luego
    la pausa. Sin jornada -- ni aqui ni en otro proceso -- apagado.

    Con la jornada en OTRO proceso el estado fino sale de lo que ese proceso
    dejo escrito en el cuaderno: `pausada` (de `jornada.json`) y los avisos si
    la captura se rompio. `muteada` no se publica ahi, asi que ese matiz solo
    se ve en la ventana que graba; encendido vs apagado, que es lo que importa
    de un vistazo, se ve en las dos.
    """
    est = est or {}
    if not graba_alguien(est):
        return "apagado"
    if hay_fallo(est):
        return "fallo"
    if est.get("muteada"):
        return "muteado"
    if est.get("pausada"):
        return "pausada"
    return "grabando"


def texto_tooltip(est: dict) -> str:
    """Lo que se lee al posar el raton. Pura.

    Dice SIEMPRE el porque: un icono rojo sin explicacion obliga a abrir el
    REPL para averiguar que pasa, que es justo lo que el widget evita.
    """
    est = est or {}
    if not est.get("grabando"):
        if est.get("otro_proceso"):
            # El icono va ENCENDIDO en este caso (ver `graba_alguien`), asi
            # que el tooltip tiene que explicar por que no aparece Detener.
            lock = est.get("lock") or {}
            return ("Cognia -- GRABANDO en otro proceso (PID %s, jornada "
                    "'%s'). Desde aqui no se puede parar: ve a esa ventana, o "
                    "libera el bloqueo en el menu si ese proceso ya no existe."
                    % (lock.get("pid") or "?", lock.get("jornada") or "?"))
        return "Cognia -- sin jornada. Clic para empezar a grabar."
    partes = ["Grabando %s" % (est.get("jornada") or "")]
    mins = int(float(est.get("segundos") or 0.0) // 60)
    partes.append("%d min" % mins)
    partes.append(str(est.get("materia") or "sin clasificar"))
    if est.get("pausada"):
        partes.append("EN PAUSA")
    if est.get("muteada"):
        partes.append("MUTEADO")
    texto = " - ".join(p for p in partes if p)
    avisos = [a for a in ([est.get("aviso")] + list(est.get("avisos") or []))
              if a]
    if avisos:
        texto += "\nAVISO: " + avisos[-1]
    return texto


# ── El widget ────────────────────────────────────────────────────────────────

class Cerebrito:
    """El icono flotante. `correr()` entra en el bucle de Tk y no vuelve.

    No se instancia dos veces en el mismo proceso: hay un `tk.Tk()` dentro.
    Quien quiera comprobar que no hay dos EN LA MAQUINA usa el lock
    (`tomar_lock_widget`), que es lo que hace `__main__`.
    """

    def __init__(self, lado: int = 0):
        # ANTES de crear la ventana: despues no hace nada (ver la funcion).
        self.aviso_dpi = hacerse_consciente_del_dpi()
        if self.aviso_dpi:
            _avisar("clases.widget.dpi", self.aviso_dpi,
                    accion="el icono puede verse borroso en un monitor "
                           "escalado")
        import tkinter as tk
        self.tk = tk
        self.cfg = cargar_config()
        self.lado = int(lado or self.cfg.get("lado") or LADO)

        self.cola: queue.Queue = queue.Queue()
        self._pendientes: set = set()
        self._hilos: list = []
        self._imagenes: dict = {}
        # Iconos que ya se estan dibujando en un hilo, para no lanzar uno por
        # cada tick mientras tarda (ver `_pedir_icono`).
        self._pidiendo: set = set()
        # Mientras dura el arranque el dibujo va EN ESTE HILO a proposito: la
        # ventana todavia no esta a la vista (`withdraw`) y el bucle de Tk aun
        # no corre, asi que nadie vaciaria la cola de los hilos -- el icono se
        # quedaria en blanco hasta el primer tick. Se apaga tras `deiconify`.
        self._arrancando = True
        self._paso = 0
        self._ticks = 0
        self._tick_id = None
        self._cerrando = False
        self.est: dict = {}
        self.icono_actual = ""
        self._arrastrando = False
        self._origen = (0, 0)
        self._pulsado = (0, 0)

        self.raiz = tk.Tk()
        self.raiz.withdraw()            # nada de un cuadrado gris en el centro
        self.raiz.overrideredirect(True)
        self.raiz.attributes("-topmost", True)
        for atributo in ("-toolwindow",):
            try:
                self.raiz.attributes(atributo, True)
            except tk.TclError as exc:
                # -toolwindow no existe fuera de Windows. El icono funciona
                # igual; lo que se pierde es no salir con Alt-Tab.
                log.warning("clases.widget: %s no disponible (%s)",
                            atributo, exc)
        clave = ico.COLOR_CLAVE
        try:
            self.raiz.attributes("-transparentcolor", clave)
        except tk.TclError as exc:
            _avisar("clases.widget.transparencia",
                    "-transparentcolor no disponible (%s): el icono saldra "
                    "dentro de un cuadrado magenta" % exc,
                    accion="ninguna: el widget sigue funcionando")
        self.raiz.configure(bg=clave)
        self.etiqueta = tk.Label(self.raiz, bd=0, highlightthickness=0,
                                 bg=clave, cursor="hand2")
        self.etiqueta.pack(fill="both", expand=True)

        pos = elegir_posicion((self.cfg.get("x"), self.cfg.get("y")),
                              monitores(), area_trabajo(), self.lado, MARGEN)
        self.raiz.geometry("%dx%d+%d+%d" % (self.lado, self.lado,
                                            pos[0], pos[1]))
        self.pos = pos

        self.etiqueta.bind("<Button-1>", self._al_pulsar)
        self.etiqueta.bind("<B1-Motion>", self._al_arrastrar)
        self.etiqueta.bind("<ButtonRelease-1>", self._al_soltar)
        self.etiqueta.bind("<Button-3>", lambda ev: self._abrir_menu(ev))
        self.etiqueta.bind("<Enter>", self._tooltip_mostrar)
        self.etiqueta.bind("<Leave>", self._tooltip_ocultar)
        self.raiz.protocol("WM_DELETE_WINDOW", self.salir)

        self._tip = None
        # 'apagado' primero para que SIEMPRE haya un icono aunque leer el
        # estado falle, y el estado real justo despues: sin esto el cerebrito
        # nace apagado y no se corrige hasta el primer refresco, o sea que
        # aparece diciendo que no se graba cuando si se graba.
        self._pintar("apagado")
        self._refrescar_estado()
        self.raiz.deiconify()
        self._arrancando = False
        # Los diez PNG la primera vez cuestan decimas de segundo: fuera del
        # hilo de Tk o el arranque se ve como un cuelgue.
        self._en_hilo(lambda: ico.precalentar(self.lado), None,
                      "precalentar iconos")

    # -- pintar -------------------------------------------------------------
    def _imagen(self, estado: str, paso: int, dibujar: bool = True):
        """El PhotoImage de ese fotograma, o None si habria que DIBUJARLO y
        `dibujar` es False.

        POR QUE SE PUEDE DECIR QUE NO. `widget_icono.icono_png` compone el PNG
        con Pillow si no esta en el cache, y publicarlo reintenta el
        `os.replace` hasta 20 veces con 25 ms de espera (`_ESPERA_REPLACE`):
        medio segundo de `time.sleep` en el peor caso. En un hilo de trabajo
        eso no lo nota nadie; en el hilo de Tk es la ventana CONGELADA -- menu
        incluido -- que es justo lo que promete el encabezado de este fichero
        que no pasa. Asi que el latido y el refresco piden `dibujar=False` y,
        si el fotograma no esta, `_pintar` lo manda a un hilo.
        """
        clave = (estado, paso)
        if clave not in self._imagenes:
            if not dibujar and not ico.cache_valido(
                    ico.ruta_cache(estado, self.lado, paso), self.lado):
                return None
            ruta = ico.icono_png(estado, self.lado, paso)
            # Tk 8.6 lee PNG de serie: no hace falta ImageTk (que ademas
            # obligaria a mantener viva una referencia mas).
            #
            # SE LE PASAN LOS BYTES, NO LA RUTA, y es una decision MEDIDA
            # (2026-08-31): `PhotoImage(file=...)` sobre un PNG recien escrito
            # falla en Windows de forma intermitente con `TclError('')` -- un
            # error SIN MENSAJE, con el fichero entero y legible en disco;
            # reproducido en 3 de cada 5 corridas de 12 cargas. Leyendo el
            # fichero desde Python y dandole el base64, el que abre el fichero
            # es CPython (que si dice que ha pasado si falla) y Tk solo decodifica
            # memoria. El cache en disco sigue igual: lo que cambia es quien
            # lee.
            #
            # `master=self.raiz` NO ES OPCIONAL. Sin el, `PhotoImage` se crea
            # contra `tkinter._default_root` -- el PRIMER interprete Tcl del
            # proceso, que no tiene por que ser el nuestro -- y la imagen
            # acaba viviendo en una ventana distinta de la que la pinta:
            # `TclError: image "pyimage2" doesn't exist`. En un proceso con un
            # solo Tk no se nota nunca; en cuanto hay otro (la suite, o un
            # dialogo abierto por otra parte de Cognia) el icono desaparece.
            datos = base64.b64encode(ruta.read_bytes()).decode("ascii")
            self._imagenes[clave] = self.tk.PhotoImage(master=self.raiz,
                                                       data=datos)
        return self._imagenes[clave]

    def _pintar(self, estado: str, paso: int = 0, dibujar=None) -> None:
        """Pone esa cara. `dibujar=None` = dibujar solo durante el arranque."""
        if dibujar is None:
            dibujar = self._arrancando
        try:
            img = self._imagen(estado, paso, dibujar)
        except Exception as exc:
            _avisar("clases.widget.icono",
                    "no pude cargar el icono '%s' (%s: %s)"
                    % (estado, type(exc).__name__, exc),
                    accion="borrar la carpeta iconos/ del cuaderno")
            return
        if img is None:
            # El PNG no estaba: se dibuja fuera (ver `_imagen`). `icono_actual`
            # se apunta YA, porque es "la cara que toca" y no "la que se ve":
            # si no, `_refrescar_estado` volveria a pedir lo mismo cada segundo
            # y el latido dejaria de avanzar mientras tanto.
            self.icono_actual = estado
            self._pedir_icono(estado, paso)
            return
        try:
            self.etiqueta.configure(image=img)
        except Exception as exc:
            # La etiqueta ya no existe (se esta cerrando): no es un fallo que
            # el duenio pueda accionar, pero no se calla.
            log.debug("clases.widget: no pude pintar '%s' (%s)", estado, exc)
            return
        # La referencia se guarda EN EL WIDGET: Tk no la retiene y el
        # recolector se lleva la imagen dejando la etiqueta en blanco. Es el
        # bug clasico de PhotoImage y aqui apareceria como "el icono
        # desaparece al rato".
        self.etiqueta.image = img
        self.icono_actual = estado

    def _pedir_icono(self, estado: str, paso: int) -> None:
        """Manda dibujar un fotograma que no estaba en el cache, a un hilo.

        UNO POR FOTOGRAMA Y NO UNO POR TICK: sin la cuenta de `_pidiendo`, un
        icono que no se puede dibujar (disco lleno, carpeta sin permisos)
        lanzaria un hilo cada 120 ms hasta que el duenio cerrara el widget.
        """
        clave = (estado, paso)
        if self._cerrando or clave in self._pidiendo:
            return
        self._pidiendo.add(clave)

        def _luego(res):
            self._pidiendo.discard(clave)
            # Si el dibujo FALLO (`_en_hilo` devuelve la excepcion y ya la ha
            # avisado) no se repinta: `_pintar` volveria a encontrar el cache
            # vacio y pediria otro hilo en el acto, y otro, en bucle. Se deja
            # para el proximo refresco, que llega en un segundo.
            if self._cerrando or isinstance(res, BaseException):
                return
            # Solo se repinta si esa sigue siendo la cara buena: entre que se
            # pidio y que llego el PNG el duenio puede haber parado la clase.
            if estado == estado_icono(self.est):
                self._pintar(estado, paso, dibujar=False)

        self._en_hilo(lambda: ico.icono_png(estado, self.lado, paso),
                      _luego, "icono %s" % estado)

    # -- bucle --------------------------------------------------------------
    def _tras(self, ms: int, fn):
        """`after` con contabilidad: todo lo pendiente se cancela al cerrar."""
        if self._cerrando:
            return None
        try:
            ident = self.raiz.after(ms, fn)
        except Exception as exc:
            # La ventana ya no esta y nadie marco `_cerrando` (un destroy que
            # vino de fuera, p.ej. el gestor de ventanas). Programar sobre un
            # interprete muerto solo puede volver a fallar: se deja de intentar
            # y queda dicho.
            log.warning("clases.widget: no pude programar el after (%s)", exc)
            self._cerrando = True
            return None
        self._pendientes.add(ident)
        return ident

    def _cancelar_pendientes(self) -> None:
        for ident in list(self._pendientes):
            try:
                self.raiz.after_cancel(ident)
            except Exception as exc:
                # Un `after` que ya salto no se puede cancelar: no es un
                # fallo, pero se deja dicho para no esconder los que si lo son.
                log.debug("clases.widget: after_cancel(%s): %s", ident, exc)
        self._pendientes.clear()

    def _tick(self) -> None:
        """Un latido del bucle: cola de hilos, animacion y refresco de estado."""
        if self._cerrando:
            return
        self._pendientes.discard(self._tick_id)
        self._vaciar_cola()
        self._ticks += 1
        if self._ticks % TICKS_POR_REFRESCO == 0:
            self._refrescar_estado()
        if self.icono_actual == "grabando":
            self._paso = (self._paso + 1) % ico.pasos_de("grabando")
            self._pintar("grabando", self._paso)
        self._tick_id = self._tras(PERIODO_TICK_MS, self._tick)

    def _vaciar_cola(self) -> None:
        """Ejecuta EN EL HILO DE TK lo que dejaron los hilos de trabajo."""
        while True:
            try:
                fn = self.cola.get_nowait()
            except queue.Empty:
                return
            try:
                fn()
            except Exception as exc:
                _avisar("clases.widget.cola",
                        "fallo al aplicar el resultado de un hilo (%s: %s)"
                        % (type(exc).__name__, exc),
                        accion="reabrir el cerebrito si algo se quedo a medias")

    def _refrescar_estado(self) -> None:
        """Relee `jornada.estado()` y repinta si cambio la cara.

        `estado()` lee ficheros pequenios del cuaderno: a 1 Hz no se nota y
        evita el hilo (con hilo habria que sincronizar el repintado, que es
        mas riesgo que el que quita).
        """
        try:
            self.est = jor.estado()
        except Exception as exc:
            _avisar("clases.widget.estado",
                    "no pude leer el estado de la jornada (%s: %s)"
                    % (type(exc).__name__, exc),
                    accion="mirar /grabar-clase en el REPL")
            return
        nuevo = estado_icono(self.est)
        if nuevo != self.icono_actual:
            self._paso = 0
            self._pintar(nuevo, 0)
        if self._tip is not None:
            self._tip_texto(texto_tooltip(self.est))

    def _en_hilo(self, trabajo, luego=None, nombre: str = "tarea"):
        """Corre `trabajo()` fuera de Tk y devuelve el resultado por la cola.

        `luego(resultado_o_excepcion)` se ejecuta EN EL HILO DE TK. Nunca se
        llama a `after` desde el hilo de trabajo: ver el encabezado.
        """
        def _correr():
            try:
                res = trabajo()
            except Exception as exc:
                res = exc
                _avisar("clases.widget.hilo",
                        "%s fallo (%s: %s)" % (nombre, type(exc).__name__, exc),
                        accion="reintentar desde el menu del cerebrito")
            if luego is not None:
                self.cola.put(lambda: luego(res))

        h = threading.Thread(target=_correr, name="cerebrito-" + nombre,
                             daemon=True)
        # Los ya terminados se sueltan aqui: cada Thread retiene su closure y
        # la closure retiene a `self`. En una jornada de siete horas de clics
        # (mas un hilo por fotograma que haya que dibujar) la lista crece sin
        # que nadie la vacie hasta el cierre.
        self._hilos = [v for v in self._hilos if v.is_alive()]
        self._hilos.append(h)
        h.start()
        return h

    # -- raton --------------------------------------------------------------
    def _al_pulsar(self, ev) -> None:
        self._arrastrando = False
        self._pulsado = (ev.x_root, ev.y_root)
        self._origen = (ev.x_root - self.raiz.winfo_x(),
                        ev.y_root - self.raiz.winfo_y())

    def _al_arrastrar(self, ev) -> None:
        if (abs(ev.x_root - self._pulsado[0]) > UMBRAL_ARRASTRE
                or abs(ev.y_root - self._pulsado[1]) > UMBRAL_ARRASTRE):
            self._arrastrando = True
        if not self._arrastrando:
            return
        x = ev.x_root - self._origen[0]
        y = ev.y_root - self._origen[1]
        self.pos = (x, y)
        self.raiz.geometry("+%d+%d" % (x, y))

    def _al_soltar(self, ev) -> None:
        if self._arrastrando:
            self.cfg["x"], self.cfg["y"] = int(self.pos[0]), int(self.pos[1])
            guardar_config(self.cfg)
            self._arrastrando = False
            return
        self._abrir_menu(ev)

    # -- menu ---------------------------------------------------------------
    def _menu_tk(self, entradas: list, padre=None):
        """Traduce la estructura de `entradas_menu` a `tk.Menu`.

        EL SUBMENU CUELGA DEL MENU, NO DE LA VENTANA (`padre`). Colgandolo de
        la ventana los dos son hermanos, y entonces destruir el menu al
        cerrarlo deja el submenu de materias vivo en el interprete: un widget
        huerfano por cada clic del duenio.
        """
        tk = self.tk
        m = tk.Menu(padre if padre is not None else self.raiz, tearoff=0)
        for e in entradas:
            if e.get("tipo") == "separador":
                m.add_separator()
            elif e.get("tipo") == "submenu":
                sub = self._menu_tk(e.get("hijos") or [], padre=m)
                m.add_cascade(label=e.get("etiqueta"), menu=sub,
                              state=("normal" if e.get("activo")
                                     else "disabled"))
            else:
                clave = e.get("clave")
                m.add_command(
                    label=e.get("etiqueta"),
                    state=("normal" if e.get("activo") else "disabled"),
                    command=(lambda c=clave: self.ejecutar(c)))
        return m

    def _abrir_menu(self, ev=None) -> None:
        """Despliega el menu del estado ACTUAL.

        EL `<FocusOut>` NO ES OPCIONAL. Una ventana `overrideredirect` no
        entra en el reparto normal del foco de Windows, asi que el menu
        emergente no se entera de que el duenio pincho en otro sitio y se
        queda PEGADO sobre el escritorio hasta que se elige algo. Con el
        `unpost` en `<FocusOut>` -- mas el `grab_release` de `_cerrar_menu`,
        que es lo que devuelve el raton al resto del escritorio -- se cierra
        como cualquier otro menu.
        """
        self._refrescar_estado()
        try:
            materias = cua.materias_conocidas()
        except Exception as exc:
            materias = []
            _avisar("clases.widget.materias",
                    "no pude leer las materias del cuaderno (%s: %s)"
                    % (type(exc).__name__, exc),
                    accion="usar 'otra...' para escribirla a mano")
        m = self._menu_tk(entradas_menu(self.est, materias))
        m.bind("<FocusOut>", lambda _e: self._despegar_menu(m))
        x = ev.x_root if ev is not None else self.raiz.winfo_x()
        y = ev.y_root if ev is not None else self.raiz.winfo_y()
        try:
            m.tk_popup(int(x), int(y))
        finally:
            self._cerrar_menu(m)

    def _despegar_menu(self, m) -> None:
        """`unpost` del menu cuando pierde el foco. NO PUEDE LANZAR.

        Corre dentro de un callback de Tk, y el menu puede haber desaparecido
        ya (lo destruye `_cerrar_menu` en cuanto `tk_popup` vuelve): `unpost`
        sobre un widget destruido lanza `TclError: invalid command name` --
        medido -- y desde ahi el traceback sale por
        `report_callback_exception`, o sea a la consola del duenio, cada vez
        que cierra el menu haciendo clic fuera.
        """
        try:
            m.unpost()
        except Exception as exc:
            log.debug("clases.widget: el menu ya no estaba al despegarlo (%s)",
                      exc)

    def _cerrar_menu(self, m) -> None:
        """Suelta el raton y destruye el menu. NINGUNA DE LAS DOS PUEDE LANZAR.

        EL BUG QUE ESTO MATA. Esto corre en el `finally` de `tk_popup`, y la
        entrada que el duenio eligio ya se ha EJECUTADO cuando `tk_popup`
        vuelve. Si eligio Salir, la ventana -- y con ella el interprete de Tcl
        entero -- ya no existe: `m.grab_release()` lanza entonces
        `TclError: can't invoke "grab" command: application has been destroyed`
        (medido el 2026-08-31 en esta maquina). Y lanzar desde un `finally`
        significa que la excepcion se escapa del manejador del clic en mitad
        del cierre, con su traceback por la consola.

        El `grab_release` sigue estando -- cuando la ventana SI existe es lo
        que devuelve el raton al resto del escritorio -- pero envuelto.
        """
        try:
            m.grab_release()
        except Exception as exc:
            log.debug("clases.widget: grab_release sobre un menu cuya ventana "
                      "ya no esta (%s)", exc)
        self._soltar_menu(m)

    def _soltar_menu(self, m) -> None:
        """Destruye el menu emergente y sus submenus.

        NO es opcional en un widget que vive todo el dia. Un `tk.Menu` cuyo
        objeto Python se queda sin referencias NO desaparece del interprete de
        Tcl: tkinter no destruye el widget en `__del__`. O sea que cada clic
        del duenio dejaria un menu (mas su submenu de materias) colgando de la
        ventana para siempre, y en una jornada de siete horas eso son cientos.
        `destroy()` de un menu se lleva por delante a sus hijos.
        """
        try:
            m.destroy()
        except Exception as exc:
            # Pasa si el propio menu cerro el widget (Salir): la ventana ya no
            # esta y con ella se fue el menu. Queda dicho, no callado.
            log.debug("clases.widget: el menu ya no existia al soltarlo (%s)",
                      exc)

    # -- acciones -----------------------------------------------------------
    def ejecutar(self, clave: str) -> None:
        """Traduce una clave del menu a la llamada de `jornada`. Sin bloquear.

        Es publica a proposito: es la puerta por la que un test (o el REPL)
        puede disparar exactamente lo mismo que el menu, sin sintetizar
        eventos de raton.
        """
        if clave == "grabar":
            self._en_hilo(self._arrancar_jornada, self._tras_accion, "grabar")
        elif clave == "pausar":
            self._en_hilo(
                lambda: (jor.reanudar() if self.est.get("pausada")
                         else jor.pausar()),
                self._tras_accion, "pausar")
        elif clave == "mutear":
            self._en_hilo(
                lambda: (jor.desmutear() if self.est.get("muteada")
                         else jor.mutear()),
                self._tras_accion, "mutear")
        elif clave == "detener":
            self._en_hilo(jor.parar, self._tras_accion, "detener")
        elif clave == "cuaderno":
            self._en_hilo(self._abrir_cuaderno, self._tras_accion, "cuaderno")
        elif clave == "exportar":
            self._en_hilo(self._exportar, self._tras_accion, "exportar")
        elif clave == "salir":
            self.salir()
        elif clave == "materia:otra":
            self._materia_a_mano()
        elif str(clave).startswith("materia:"):
            nombre = str(clave).split(":", 1)[1]
            self._en_hilo(lambda: self._marcar(nombre), self._tras_accion,
                          "materia")
        elif clave == "liberar":
            self._liberar_bloqueo()
        elif clave == "ocupado":
            return
        else:
            _avisar("clases.widget.menu",
                    "entrada de menu desconocida: %r" % (clave,),
                    accion="ninguna: no se hizo nada")

    def _tras_accion(self, res) -> None:
        """Lo que pasa EN TK cuando un hilo termina: repintar, y nada mas."""
        self._refrescar_estado()
        if isinstance(res, str) and res:
            self._tip_texto(res)

    def _arrancar_jornada(self):
        jv, motivo = jor.arrancar()
        if jv is None:
            _avisar("clases.widget.grabar",
                    "no pude arrancar la jornada: %s" % motivo,
                    accion="mirar /grabar-clase en el REPL")
            return "no arranco: %s" % motivo
        return "grabando %s" % jv.nombre

    def _marcar(self, materia: str):
        jv = jor.viva()
        if jv is None:
            return "no hay jornada donde marcar la materia"
        jv.marcar_materia(materia)
        return "materia: %s" % materia

    def _materia_a_mano(self) -> None:
        """Pide la materia por teclado. Va en el hilo de Tk a proposito: un
        dialogo modal ES la interfaz, no trabajo que bloquee."""
        from tkinter import simpledialog
        nombre = simpledialog.askstring("Materia", "Materia de esta clase:",
                                        parent=self.raiz)
        if nombre and nombre.strip():
            self._en_hilo(lambda: self._marcar(nombre.strip()),
                          self._tras_accion, "materia")

    def _liberar_bloqueo(self) -> None:
        """La salida de emergencia del menu: quitar el lock de grabacion ajeno.

        PREGUNTA ANTES, y no es cortesia: `jornada.forzar_liberacion` quita el
        lock sea de quien sea, asi que hacerlo con una grabacion viva de verdad
        deja DOS grabadores escribiendo sobre la misma clase. El dialogo dice
        el PID porque es lo unico con lo que el duenio puede decidir: el sabe
        si esa otra ventana de Cognia existe o si ese numero es de un
        chrome.exe que heredo el PID.

        El dialogo va en el hilo de Tk (es la interfaz) y el borrado en un
        hilo, como el resto de acciones.
        """
        lock = (self.est or {}).get("lock") or {}
        from tkinter import messagebox
        if not messagebox.askyesno(
                "Cognia",
                "El bloqueo de grabacion dice que la clase la graba el "
                "proceso PID %s (jornada '%s').\n\n"
                "Liberalo SOLO si ese proceso ya no existe. Si de verdad "
                "sigue grabando, quedarian dos grabadores sobre la misma "
                "clase.\n\n"
                "Libero el bloqueo?"
                % (lock.get("pid") or "?", lock.get("jornada") or "?"),
                parent=self.raiz):
            return
        self._en_hilo(self._forzar_liberacion, self._tras_accion, "liberar")

    def _forzar_liberacion(self):
        res = jor.forzar_liberacion("desde el menu del cerebrito")
        aviso = res.get("aviso") or ""
        if not res.get("liberado"):
            _avisar("clases.widget.liberar",
                    "no pude liberar el lock de grabacion: %s" % aviso,
                    accion="mirar /grabar-clase en el REPL")
        return aviso

    def _abrir_cuaderno(self):
        """Levanta el servidor vivo si hace falta y abre la URL con token."""
        from cognia.clases import servidor_vivo as sv
        info = sv.arrancar()
        ok, mensaje = abrir_en_app(info.get("url") or "")
        return mensaje if ok else ("no pude abrir el cuaderno: " + mensaje)

    def _exportar(self):
        from cognia.clases import vista
        destino = vista.export(open_browser=False)
        return "cuaderno exportado a %s" % destino

    # -- tooltip ------------------------------------------------------------
    def _tip_texto(self, texto: str) -> None:
        if self._tip is None:
            return
        try:
            self._tip_label.configure(text=texto)
        except Exception as exc:
            log.debug("clases.widget: tooltip ya destruido (%s)", exc)

    def _tooltip_mostrar(self, _ev=None) -> None:
        """Crea el tooltip. NO PUEDE LANZAR: corre en un callback de Tk.

        El `<Enter>` puede llegar con la ventana ya cerrandose (el raton esta
        encima del icono justo cuando el duenio elige Salir en el menu), y
        entonces `Toplevel` -- o cualquiera de los `winfo` de aqui -- lanza
        TclError sobre un interprete que ya no esta. Un tooltip que no sale no
        rompe nada; un TclError en un callback vuelca el traceback por la
        consola y deja `self._tip` apuntando a un widget muerto.
        """
        if self._tip is not None or self._cerrando:
            return
        tk = self.tk
        try:
            self._tip = tk.Toplevel(self.raiz)
            self._tip.overrideredirect(True)
            self._tip.attributes("-topmost", True)
            rojo = hay_fallo(self.est)
            self._tip_label = tk.Label(
                self._tip, justify="left", padx=8, pady=5,
                bg=("#3a1412" if rojo else "#16181c"),
                fg=(ico.ROJO_AVISO if rojo else "#d7dde3"),
                text=texto_tooltip(self.est))
            self._tip_label.pack()
            self._tip.update_idletasks()
            # Debajo del icono, y pegado a su borde derecho: en la esquina
            # superior derecha (el sitio por defecto) un tooltip alineado a la
            # izquierda se saldria de la pantalla.
            x = self.raiz.winfo_x() + self.lado - self._tip.winfo_width()
            y = self.raiz.winfo_y() + self.lado + 4
            self._tip.geometry("+%d+%d" % (max(0, x), y))
        except Exception as exc:
            log.debug("clases.widget: no pude montar el tooltip (%s)", exc)
            self._tooltip_ocultar()

    def _tooltip_ocultar(self, _ev=None) -> None:
        if self._tip is None:
            return
        try:
            self._tip.destroy()
        except Exception as exc:
            log.debug("clases.widget: no pude destruir el tooltip (%s)", exc)
        self._tip = None

    # -- cierre -------------------------------------------------------------
    def salir(self) -> None:
        """Salir del menu: pregunta si hay grabacion, y despues cierra.

        PREGUNTA porque cerrar el widget con la clase grabando es
        indistinguible de un clic sin querer, y la clase no se puede rehacer.
        Tres respuestas: Si (para y cierra), No (cierra dejando la jornada
        grabando en este proceso -- que muere, asi que en la practica la corta
        el atexit de jornada.py) y Cancelar (no cierra).
        """
        est = self.est or {}
        if est.get("grabando"):
            from tkinter import messagebox
            r = messagebox.askyesnocancel(
                "Cognia",
                "La clase se esta grabando.\n\n"
                "Si -> paro la jornada y cierro el cerebrito.\n"
                "No -> cierro sin parar (la grabacion se corta igual al "
                "cerrarse el proceso).\n"
                "Cancelar -> no cierro.",
                parent=self.raiz)
            if r is None:
                return
            if r:
                self._en_hilo(jor.parar, lambda _r: self.cerrar(), "parar")
                return
        self.cerrar()

    def cerrar(self) -> None:
        """Cierre limpio: pendientes cancelados, servidor parado, sin hilos.

        EL ORDEN IMPORTA. Primero se marca `_cerrando` (para que ningun
        `after` se vuelva a programar), luego se cancelan los pendientes -- un
        callback que salte despues del `destroy()` toca widgets muertos y
        vuelca un TclError -- y solo al final se destruye la ventana.
        """
        if self._cerrando:
            return
        self._cerrando = True
        self._cancelar_pendientes()
        self._pidiendo.clear()
        self._tooltip_ocultar()
        # LAS IMAGENES SE SUELTAN ANTES DEL destroy(). `tk.PhotoImage.__del__`
        # llama al interprete de Tcl para borrar la imagen; si el objeto sigue
        # vivo cuando la ventana ya no esta, ese `__del__` cae mas tarde --
        # en el recolector, fuera de cualquier try -- con "main thread is not
        # in main loop", y ademas deja el interprete a medio limpiar (medido
        # el 2026-08-31: el siguiente `tk.Tk()` del proceso fallaba con "Can't
        # find a usable init.tcl"). Soltandolas aqui, el `__del__` corre con
        # el interprete todavia vivo y no pasa nada.
        try:
            self.etiqueta.configure(image="")
        except Exception as exc:
            log.debug("clases.widget: etiqueta ya sin imagen (%s)", exc)
        self.etiqueta.image = None
        self._imagenes.clear()
        try:
            from cognia.clases import servidor_vivo as sv
            sv.parar()
        except Exception as exc:
            log.warning("clases.widget: no pude parar el cuaderno vivo (%s)",
                        exc)
        for h in list(self._hilos):
            if h.is_alive():
                h.join(timeout=2.0)
        vivos = [h.name for h in self._hilos if h.is_alive()]
        if vivos:
            # Son daemon, asi que no impiden salir; pero un hilo que sigue
            # abierto al cerrar es informacion, no ruido.
            log.warning("clases.widget: hilos aun vivos al cerrar: %s",
                        ", ".join(vivos))
        try:
            self.raiz.destroy()
        except Exception as exc:
            log.debug("clases.widget: ventana ya destruida (%s)", exc)
        # Los Thread ya terminados se sueltan: cada uno retiene su closure, y
        # esa closure retiene a `self`. Es un ciclo, asi que el widget cerrado
        # no lo libera el contador de referencias sino el recolector -- que
        # corre en CUALQUIER hilo. Y liberar un interprete de Tcl fuera del
        # hilo que lo creo aborta el proceso ("Tcl_AsyncDelete: async handler
        # deleted by the wrong thread"), no lanza: reproducido el 2026-08-31.
        self._hilos.clear()

    def correr(self) -> None:
        """Entra en el bucle de Tk. No vuelve hasta que se cierra la ventana."""
        self._refrescar_estado()
        self._tick_id = self._tras(PERIODO_TICK_MS, self._tick)
        self.raiz.mainloop()
