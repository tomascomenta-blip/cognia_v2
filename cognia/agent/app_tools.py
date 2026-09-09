# -*- coding: utf-8 -*-
"""
cognia/agent/app_tools.py
=========================
Familia `app_*` (2026-09-07): probar APLICACIONES GRAFICAS (tkinter, pygame,
Qt, Electron, un .exe, un juego) sin humano y sin molestar al dueno: la app se
lanza, su ventana se muda al ESCRITORIO PROPIO de Cognia (escritorio_propio),
y desde ahi se fotografia (PrintWindow), se le teclea y clica por mensajes,
se lee su interfaz (UI Automation) y se cierra. `app_probar` hace todo el
ciclo de un tiro y devuelve un mosaico con la captura tras cada paso.

Es la pareja de `renderizar | guion=` (paginas) y `ejecutar_guion` (consola)
para lo que abre una VENTANA. Lo que hoy era IMPOSIBLE: el agente escribia un
juego en pygame y solo podia decir "deberia funcionar".

Ids cortos (a1, a2...) por proceso; el registro persiste en
~/.cognia/escritorio_propio.json para que `app_lista` y `app_cerrar todas`
vean tambien lo lanzado por una corrida anterior. Solo se cierran ventanas
lanzadas por Cognia: nunca las del dueno.
"""
from __future__ import annotations

import atexit
import os
import re
import shlex
import subprocess
import tempfile
import time
from pathlib import Path

from cognia.agent import escritorio_propio as EP
from cognia.agent import pruebas_comun as PC

ESPERA_VENTANA_DEF_MS = 4000
ESPERA_VENTANA_MAX_MS = 60000
MAX_PASOS = 60

# id -> {pid, hwnd, cmd, titulo, ts, log (ruta), proc (Popen|None), capturas}
_APPS: dict = {}
_CONTADOR = [0]
_ULTIMO: dict = {"tool": "", "detalle": "", "ts": 0.0}


def _anotar(tool: str, detalle: str) -> None:
    _ULTIMO.update({"tool": tool, "detalle": detalle[:300], "ts": time.time()})


def ultimo() -> dict:
    return dict(_ULTIMO)


def _nuevo_id() -> str:
    reg = EP.registro_cargar()
    n = max([_CONTADOR[0]] + [int(k[1:]) for k in reg if re.match(r"^a\d+$", k)]) + 1
    _CONTADOR[0] = n
    return "a%d" % n


def _persistir() -> None:
    reg = EP.registro_cargar()
    for k, a in _APPS.items():
        reg[k] = {"pid": a["pid"], "hwnd": a["hwnd"], "cmd": a["cmd"], "titulo": a["titulo"], "ts": a["ts"]}
    EP.registro_guardar(reg)


def _olvidar(app_id: str) -> None:
    _APPS.pop(app_id, None)
    reg = EP.registro_cargar()
    if app_id in reg:
        reg.pop(app_id)
        EP.registro_guardar(reg)


def _app(app_id: str) -> dict:
    a = _APPS.get(app_id)
    if a is None:
        reg = EP.registro_cargar().get(app_id)
        if reg and EP.ventana_viva(reg.get("hwnd", 0)):
            a = dict(reg, proc=None, log="", capturas=[])
            _APPS[app_id] = a
    if a is None:
        raise ValueError("no hay app '%s' (lanza una con app_lanzar; ids vivos: %s)"
                         % (app_id, ", ".join(sorted(_APPS)) or "ninguno"))
    if not EP.ventana_viva(a["hwnd"]):
        # la ventana murio: refrescar por pid (algunas apps recrean la ventana)
        nuevo = _ventana_de_pid(a["pid"])
        if nuevo:
            a["hwnd"] = nuevo
        else:
            raise ValueError("la ventana de '%s' ya no existe (pid %s, %s)"
                             % (app_id, a["pid"], _estado_proceso(a)))
    return a


def _estado_proceso(a: dict) -> str:
    p = a.get("proc")
    if p is not None:
        rc = p.poll()
        return "proceso vivo" if rc is None else "proceso termino con exit %s" % rc
    try:
        import psutil  # type: ignore
        return "proceso vivo" if psutil.pid_exists(a["pid"]) else "proceso terminado"
    except Exception:
        return "proceso ?"


def _descendientes(pid: int) -> set:
    try:
        import psutil  # type: ignore
        p = psutil.Process(pid)
        return {pid} | {c.pid for c in p.children(recursive=True)}
    except Exception:
        return {pid}


def _exe_de(pid: int) -> str:
    """Nombre del ejecutable de un pid en minusculas ('' si no se puede leer)."""
    try:
        import psutil  # type: ignore
        return (psutil.Process(int(pid)).name() or "").lower()
    except Exception:
        return ""


def _ventana_de_pid(pid: int):
    pids = _descendientes(pid)
    for hwnd, wpid, _t in EP.ventanas_visibles():
        if wpid in pids and EP.rect_ventana(hwnd)[2] > 0:
            return hwnd
    return None


def _log_cola(a: dict, n: int = 1500) -> str:
    try:
        ruta = a.get("log")
        if ruta and Path(ruta).exists():
            txt = Path(ruta).read_text(encoding="utf-8", errors="replace")
            return txt[-n:] if len(txt) > n else txt
    except Exception:
        pass
    return ""


def _partir_comando(comando: str) -> list:
    """Tokens del comando. En Windows shlex no es posix y deja las comillas
    PEGADAS al token (la ruta entre comillas llega con ellas): Popen las pasaba
    tal cual y python decia "can't open file" con una comilla dentro de la ruta
    (cazado en el e2e de probar). Se quitan las comillas envolventes de cada
    token."""
    try:
        partes = shlex.split(comando, posix=(os.name != "nt"))
    except ValueError:
        partes = comando.split()
    limpias = []
    for t in partes:
        if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'":
            t = t[1:-1]
        limpias.append(t)
    return limpias


# Chromium/Electron ocluyen su propio compositor cuando Windows les dice que
# no son visibles (Occlusion API) para ahorrar CPU/GPU — y una ventana en el
# escritorio virtual propio de Cognia (no el activo) SIEMPRE se reporta
# ocluida. El navegador sigue vivo y respondiendo (clics, teclas, JS) pero
# deja de pintar cuadros nuevos: la mesa lo capturaba congelado ("se queda
# cargando") hasta que el dueno cambiaba al escritorio y volvia a ser visible.
# Cazado 2026-09-09: el dueno reporto la pagina pegada en la mesa aunque las
# acciones sobre ella funcionaban bien. Estas flags (las mismas que usa
# Playwright/Puppeteer para automatizacion sin cabeza visible) apagan ese
# throttling por oclusion para que siga renderizando de verdad.
_NAVEGADORES_CHROMIUM = {"msedge", "chrome", "chromium", "brave", "vivaldi", "opera"}
_FLAGS_SIN_OCLUSION = ("--disable-backgrounding-occluded-windows",
                        "--disable-renderer-backgrounding",
                        "--disable-background-timer-throttling")


def _agregar_flags_sin_oclusion(partes: list) -> list:
    if not partes:
        return partes
    try:
        exe = Path(partes[0]).stem.lower()
    except Exception:
        return partes
    if exe not in _NAVEGADORES_CHROMIUM:
        return partes
    ya = set(partes[1:])
    for f in _FLAGS_SIN_OCLUSION:
        if f not in ya:
            partes.append(f)
    # Perfil aislado: si el dueno ya tiene el mismo navegador abierto en su
    # propio escritorio, un segundo "msedge.exe <url>" con el perfil de
    # siempre NO abre un proceso nuevo — le pasa la URL al que ya corre (el
    # "process singleton" de Chromium) y se cierra; las flags de arriba
    # entonces no sirven porque el proceso que de verdad renderiza es el
    # viejo, lanzado sin ellas. Un --user-data-dir propio garantiza un
    # proceso nuevo de verdad (y de paso no mezcla historial/cookies).
    if not any(p.lower().startswith("--user-data-dir") for p in partes[1:]):
        perfil = tempfile.mkdtemp(prefix="cognia_mesa_%s_" % exe)
        partes.append("--user-data-dir=%s" % perfil)
    return partes


def lanzar(comando: str, cwd: str = None, espera_ms: int = ESPERA_VENTANA_DEF_MS, titulo: str = "") -> dict:
    """Lanza el comando, espera su ventana, la muda al escritorio de Cognia.
    Devuelve el dict de la app (o lanza ValueError con lo que paso)."""
    if not comando.strip():
        raise ValueError("falta el comando (ej: python juego.py, notepad.exe, ruta\\app.exe)")
    antes = {h for h, _p, _t in EP.ventanas_visibles()}
    log = tempfile.NamedTemporaryFile(prefix="cognia_app_", suffix=".log", delete=False)
    log.close()
    partes = _partir_comando(comando)
    if partes and partes[0].lower() in ("python", "python3", "py"):
        # el mismo interprete que corre Cognia: es el que tiene los paquetes
        # del proyecto (pygame, tkinter) instalados junto a ella
        import sys as _sys
        partes[0] = _sys.executable
    partes = _agregar_flags_sin_oclusion(partes)
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env.setdefault("PYTHONUTF8", "1")
    try:
        with open(log.name, "ab") as fh:
            proc = subprocess.Popen(partes, cwd=cwd or None, stdout=fh, stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL, env=env,
                                    creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    except FileNotFoundError:
        # p.ej. "juego.exe" sin ruta, o un comando de shell
        try:
            with open(log.name, "ab") as fh:
                proc = subprocess.Popen(comando, cwd=cwd or None, stdout=fh, stderr=subprocess.STDOUT,
                                        stdin=subprocess.DEVNULL, env=env, shell=True)
        except Exception as exc:
            raise ValueError("no se pudo lanzar %r: %s" % (comando, exc))
    t0 = time.time()
    hwnd = None
    adoptada = False
    limite = max(500, min(ESPERA_VENTANA_MAX_MS, espera_ms)) / 1000.0
    while time.time() - t0 < limite:
        time.sleep(0.25)
        pids = _descendientes(proc.pid)
        candidatas = [(h, p, t) for h, p, t in EP.ventanas_visibles() if h not in antes and EP.rect_ventana(h)[2] > 0]
        propias = [c for c in candidatas if c[1] in pids]
        if titulo:
            propias = [c for c in propias if titulo.lower() in (c[2] or "").lower()] or \
                      [c for c in candidatas if titulo.lower() in (c[2] or "").lower()]
        if propias:
            hwnd = propias[0][0]
            break
        if proc.poll() is not None:
            # Apps de la Store (calc.exe, notepad.exe en Windows 11): el
            # lanzador sale con exit 0 al instante y la ventana la abre OTRO
            # proceso que no es descendiente. Cazado tecleando `/mesa lanzar
            # calc.exe` (2026-09-09): "termino (exit 0) sin abrir ventana".
            # Con exit 0 se sigue esperando y se acepta una ventana NUEVA cuyo
            # exe se parece al comando (calc -> CalculatorApp.exe, notepad ->
            # Notepad.exe); si hay una sola nueva con titulo, esa.
            if proc.returncode == 0:
                base = (Path(partes[0]).stem.lower() if partes else "")[:4]
                con_titulo = [c for c in candidatas if (c[2] or "").strip()]
                afines = [c for c in con_titulo if base and base in _exe_de(c[1])]
                elegido = afines or (con_titulo if len(con_titulo) == 1 else [])
                if elegido:
                    hwnd = elegido[0][0]
                    break
                continue
            if not candidatas:
                break
    if hwnd is None:
        # App de UNA instancia (el Bloc de notas de Windows 11 abre pestanas
        # en la ventana que YA existe; Chrome igual): la orden no produce
        # ninguna ventana nueva. Si hay una visible cuyo exe se parece al
        # comando, se adopta y se muda a la mesa como cualquier otra. Cazado
        # tecleando `/mesa lanzar notepad.exe` con un Bloc ya abierto.
        base = (Path(partes[0]).stem.lower() if partes else "")[:4]
        if base:
            for h, p, t in EP.ventanas_visibles():
                if (t or "").strip() and EP.rect_ventana(h)[2] > 0 and base in _exe_de(p):
                    hwnd, adoptada = h, True
                    break
    if hwnd is None:
        rc = proc.poll()
        cola = ""
        try:
            cola = Path(log.name).read_text(encoding="utf-8", errors="replace")[-1200:]
        except Exception:
            pass
        if rc is not None:
            raise ValueError("el proceso termino (exit %s) sin abrir ventana en %.1fs. Salida:\n%s"
                             % (rc, limite, cola.strip() or "(vacia)")
                             + "\nSi es un programa de consola usa ejecutar_guion; si revento, arregla el error.")
        # sigue vivo pero sin ventana: no lo dejamos huerfano
        EP.matar_arbol(proc.pid)
        raise ValueError("no aparecio ninguna ventana nueva en %.1fs (proceso matado). Salida hasta ahora:\n%s"
                         % (limite, cola.strip() or "(vacia)")
                         + "\nSube espera=MS si tarda en arrancar, o usa ejecutar_guion si es de consola.")
    # mudanza al escritorio propio (si esta activo); si no se puede, se dice
    mudada = EP.mover_ventana(hwnd) if EP.activo() else False
    app_id = _nuevo_id()
    a = {"pid": proc.pid, "hwnd": hwnd, "cmd": comando, "titulo": EP.titulo_ventana(hwnd), "ts": time.time(),
         "log": log.name, "proc": proc, "capturas": [], "mudada": mudada, "adoptada": adoptada,
         "escritorio": EP.config()["nombre"] if mudada else "actual (escritorio propio %s)"
         % ("apagado" if not EP.config()["activo"] else "no disponible: " + EP.disponible()[1])}
    _APPS[app_id] = a
    _persistir()
    _anotar("app_lanzar", "%s = %s (hwnd %d)" % (app_id, comando, hwnd))
    return app_id, a


def capturar(app_id: str, ctx, nombre: str = "", salida: str = "") -> dict:
    a = _app(app_id)
    png = PC.ruta_salida(ctx, nombre or ("app_%s" % app_id), ".png", salida)
    r = EP.capturar_ventana(a["hwnd"], png)
    a["capturas"].append(str(png))
    try:
        r["resumen"] = PC.resumen_imagen(png)
    except Exception as exc:
        r["resumen"] = {"veredicto": "sin resumen: %s" % exc}
    return r


def _texto_captura(r: dict) -> str:
    res = r.get("resumen") or {}
    if "ancho" in res:
        return "%s (%s) · %s" % (r["png"], r.get("metodo", ""), PC.texto_resumen_imagen(res))
    return "%s (%s) · %s" % (r["png"], r.get("metodo", ""), res.get("veredicto", ""))


def _texto_ui(app_id: str, maximo: int = 1200) -> str:
    a = _app(app_id)
    partes = []
    try:
        arbol = EP.arbol_uia(a["hwnd"], profundidad=8, maximo=200)
        nombres = [n for _l, t, n, _r, _e in arbol if n and t not in ("Window",)]
        if nombres:
            partes.append("UI: " + " | ".join(dict.fromkeys(nombres))[:maximo])
    except Exception as exc:
        partes.append("UIA no disponible: %s" % str(exc)[:120])
    try:
        w32 = [t for c, t in EP.texto_win32(a["hwnd"]) if c != "ventana"]
        if w32:
            partes.append("controles: " + " | ".join(dict.fromkeys(w32))[:600])
    except Exception:
        pass
    return "\n".join(partes)


# ---------------------------------------------------------------------------
# Pasos (misma gramatica que el guion de renderizar, subconjunto de ventana)
# ---------------------------------------------------------------------------

_RE_TECLA = re.compile(r"^tecla\s+(\S+?)(?:\*(\d+))?$", re.I)


def parsear_pasos(texto: str) -> list:
    """'tecla derecha*3; escribir "hola"; clic 100,50; clic "Boton"; espera 500;
    captura [nombre]; atajo ctrl+s; texto; esperar "listo" [ms]; cerrar'
    -> [(op, args...)]. ValueError en el primer paso que no entiende."""
    pasos = []
    for crudo in re.split(r"\s*;\s*", (texto or "").strip()):
        s = crudo.strip()
        if not s:
            continue
        b = s.lower()
        m = _RE_TECLA.match(s)
        if m:
            pasos.append(("tecla", m.group(1), int(m.group(2) or 1)))
        elif b.startswith("teclas "):
            for t in re.split(r"\s*,\s*", s[7:].strip()):
                if t:
                    pasos.append(("tecla", t, 1))
        elif b.startswith("escribir ") or b.startswith("tipear "):
            v = s.split(None, 1)[1].strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            pasos.append(("escribir", v))
        elif b.startswith("clic ") or b.startswith("click ") or b.startswith("dobleclic ") or b.startswith("clicder "):
            op = "dobleclic" if b.startswith("doble") else ("clicder" if b.startswith("clicder") else "clic")
            v = s.split(None, 1)[1].strip()
            mm = re.match(r"^(-?\d+)\s*,\s*(-?\d+)$", v)
            if mm:
                pasos.append((op, int(mm.group(1)), int(mm.group(2))))
            else:
                pasos.append((op, v.strip("\"'")))
        elif b.startswith("espera ") or b.startswith("esperar ") and re.match(r"^esperar\s+\d+$", b):
            pasos.append(("espera", PC.entero(s.split(None, 1)[1], 300, 0, 30000)))
        elif b.startswith("esperar "):
            v = s.split(None, 1)[1].strip()
            mm = re.match(r'^"(.*)"\s*(\d+)?$|^\'(.*)\'\s*(\d+)?$|^(\S+)\s*(\d+)?$', v)
            txt = (mm.group(1) or mm.group(3) or mm.group(5) or "") if mm else v
            ms = int((mm.group(2) or mm.group(4) or mm.group(6) or 5000)) if mm else 5000
            pasos.append(("esperar", txt, ms))
        elif b == "captura" or b.startswith("captura "):
            pasos.append(("captura", s[8:].strip() if len(s) > 8 else ""))
        elif b.startswith("atajo "):
            pasos.append(("atajo", s[6:].strip()))
        elif b == "texto":
            pasos.append(("texto",))
        elif b == "arbol":
            pasos.append(("arbol",))
        elif b == "cerrar":
            pasos.append(("cerrar",))
        else:
            raise ValueError("paso no entendido: %r (usa tecla X[*N]; teclas a,b; escribir \"t\"; clic x,y | "
                             "clic \"Texto\"; dobleclic; espera MS; esperar \"texto\" [MS]; captura [nombre]; "
                             "atajo ctrl+s; texto; arbol; cerrar)" % s)
        if len(pasos) > MAX_PASOS:
            raise ValueError("demasiados pasos (max %d)" % MAX_PASOS)
    return pasos


def ejecutar_paso(app_id: str, paso: tuple, ctx, foco: bool = False) -> dict:
    """Ejecuta un paso y devuelve {texto, captura(png|None), cambio(fraccion|None), error}."""
    a = _app(app_id)
    op = paso[0]
    out = {"texto": "", "captura": None, "cambio": None, "error": ""}
    antes = None
    if op in ("tecla", "escribir", "clic", "clicder", "dobleclic", "atajo"):
        try:
            antes = PC.ruta_salida(ctx, "antes_%s" % app_id, ".png")
            EP.capturar_ventana(a["hwnd"], antes)
        except Exception:
            antes = None
    try:
        if op == "tecla":
            if foco or _necesita_foco(paso[1]):
                r = EP.entrada_real(a["hwnd"], [("tecla", paso[1], paso[2])])
                out["texto"] = "tecla %s x%d (entrada real: %s)" % (paso[1], paso[2], r["motivo"])
                if not r["ok"]:
                    out["error"] = r["motivo"]
            else:
                n = EP.enviar_tecla(a["hwnd"], paso[1], paso[2])
                out["texto"] = "tecla %s x%d" % (paso[1], n)
        elif op == "escribir":
            if foco:
                r = EP.entrada_real(a["hwnd"], [("escribir", paso[1])])
                out["texto"] = "escribir %r (entrada real: %s)" % (paso[1], r["motivo"])
                if not r["ok"]:
                    out["error"] = r["motivo"]
            else:
                EP.escribir_texto(a["hwnd"], paso[1])
                out["texto"] = "escribir %r" % paso[1]
        elif op in ("clic", "clicder", "dobleclic"):
            if len(paso) == 3:
                x, y, desc = paso[1], paso[2], "%d,%d" % (paso[1], paso[2])
            else:
                hit = EP.buscar_control(a["hwnd"], paso[1])
                if not hit:
                    raise ValueError("no hay ningun control con texto %r (mira app_arbol)" % paso[1])
                x, y, desc = hit[0], hit[1], "%r (%s en %d,%d)" % (paso[1], hit[2], hit[0], hit[1])
            # Un clic por mensajes llega al control pero SDL/pygame y Tk leen
            # la posicion del cursor REAL (GetMessagePos/GetCursorPos), que
            # esta en el escritorio del dueno: pygame recibio CLICK (0, 0) y
            # Tk no reacciono (medido 2026-09-07). Por eso el clic prefiere la
            # entrada real cuando la politica lo permite y cae a mensajes
            # diciendolo; las TECLAS si llegan bien por mensajes.
            permiso, motivo = (True, "forzado") if foco else EP.puede_tomar_foco()
            if permiso:
                r = EP.entrada_real(a["hwnd"], [("clic", x, y, "derecho" if op == "clicder" else "izquierdo")],
                                    forzar=foco)
                out["texto"] = "%s %s (entrada real: %s)" % (op, desc, r["motivo"])
                if not r["ok"]:
                    out["error"] = r["motivo"]
            else:
                r = EP.clic(a["hwnd"], x, y, boton="derecho" if op == "clicder" else "izquierdo",
                            doble=(op == "dobleclic"))
                out["texto"] = ("%s %s -> %s por mensajes (%s; si la app no reacciona o lee 0,0, "
                                "repite con foco=1)" % (op, desc, r.get("control") or "ventana", motivo))
        elif op == "atajo":
            r = EP.entrada_real(a["hwnd"], [("atajo", paso[1])])
            out["texto"] = "atajo %s (entrada real: %s)" % (paso[1], r["motivo"])
            if not r["ok"]:
                out["error"] = r["motivo"]
        elif op == "espera":
            time.sleep(paso[1] / 1000.0)
            out["texto"] = "espera %d ms" % paso[1]
        elif op == "esperar":
            t0 = time.time()
            visto = False
            while time.time() - t0 < paso[2] / 1000.0:
                if paso[1].lower() in _texto_ui(app_id, 4000).lower():
                    visto = True
                    break
                time.sleep(0.3)
            out["texto"] = "esperar %r: %s (%.1fs)" % (paso[1], "aparecio" if visto else "NO aparecio", time.time() - t0)
            if not visto:
                out["error"] = "no aparecio %r" % paso[1]
        elif op == "captura":
            r = capturar(app_id, ctx, paso[1] or "app_%s" % app_id)
            out["captura"] = r["png"]
            out["texto"] = "captura " + _texto_captura(r)
        elif op == "texto":
            out["texto"] = _texto_ui(app_id) or "(sin texto legible por UIA)"
        elif op == "arbol":
            out["texto"] = EP.texto_arbol(EP.arbol_uia(a["hwnd"]))
        elif op == "cerrar":
            out["texto"] = cerrar(app_id)
            return out
    except Exception as exc:
        out["error"] = "%s: %s" % (type(exc).__name__, str(exc)[:200])
        out["texto"] = out["texto"] or op
    if antes is not None and EP.ventana_viva(a["hwnd"]):
        time.sleep(0.35)
        try:
            despues = PC.ruta_salida(ctx, "despues_%s" % app_id, ".png")
            EP.capturar_ventana(a["hwnd"], despues)
            out["cambio"] = PC.fraccion_cambio(antes, despues)
            out["captura_despues"] = str(despues)
        except Exception:
            pass
    return out


def _necesita_foco(tecla: str) -> bool:
    return "+" in tecla and len(tecla) > 1


def cerrar(app_id: str) -> str:
    a = _APPS.get(app_id) or EP.registro_cargar().get(app_id)
    if not a:
        return "no hay app '%s'" % app_id
    hwnd, pid = a.get("hwnd", 0), a.get("pid", 0)
    detalle = []
    if hwnd and EP.ventana_viva(hwnd):
        EP.cerrar_ventana(hwnd)
        time.sleep(0.6)
        detalle.append("WM_CLOSE")
    proc = a.get("proc") if isinstance(a, dict) else None
    vivo = (proc.poll() is None) if proc is not None else (EP.ventana_viva(hwnd) if hwnd else False)
    if vivo and pid:
        detalle.append(EP.matar_arbol(pid))
    _olvidar(app_id)
    _anotar("app_cerrar", app_id)
    return "%s cerrada (%s)" % (app_id, ", ".join(detalle) or "ya no existia")


def cerrar_todas() -> list:
    ids = sorted(set(_APPS) | set(EP.registro_cargar()))
    return [cerrar(i) for i in ids]


@atexit.register
def _al_salir():
    # las apps lanzadas en ESTE proceso no se quedan huerfanas en el
    # escritorio de Cognia; las de corridas anteriores se listan, no se tocan
    for k in list(_APPS):
        try:
            if _APPS[k].get("proc") is not None:
                cerrar(k)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Registro de tools
# ---------------------------------------------------------------------------

_CLAVES = ("cwd", "espera", "titulo", "salida", "pasos", "boton", "doble", "foco", "texto",
           "timeout", "profundidad", "nombre")


def _err(tool: str, exc) -> str:
    return "RESULTADO %s ERROR: %s" % (tool, str(exc)[:600])


def _cabecera_escritorio(a: dict) -> str:
    return ("en el escritorio '%s'" % a["escritorio"]) if a.get("mudada") else ("en el escritorio %s" % a.get("escritorio", "actual"))


def register(tool) -> None:
    @tool("app_lanzar",
          "app_lanzar <comando> [| cwd=RUTA] [| espera=MS] [| titulo=texto]"
          "  -- lanza una app GRAFICA (python juego.py, app.exe) en el escritorio propio de Cognia, "
          "espera su ventana y devuelve su id, captura y texto de la interfaz",
          desc="Lanza una aplicacion con VENTANA (tkinter, pygame, Qt, Electron, un .exe) y la muda al "
               "escritorio virtual propio de Cognia para que no moleste al usuario. Espera hasta que aparece "
               "la ventana (espera=MS, default 4000), la fotografia y lee su interfaz por UI Automation. "
               "Devuelve el id (a1, a2...) para app_ver / app_teclas / app_clic / app_texto / app_arbol / "
               "app_cerrar. Si el proceso termina sin ventana devuelve su salida (para consola usa "
               "ejecutar_guion; para paginas web usa renderizar).",
          params=[{"nombre": "comando", "tipo": "string", "requerido": True, "descripcion": "comando a lanzar"},
                  {"nombre": "cwd", "tipo": "string", "requerido": False, "clave": True, "descripcion": "directorio de trabajo"},
                  {"nombre": "espera", "tipo": "integer", "requerido": False, "clave": True, "descripcion": "ms maximos hasta que aparezca la ventana (default 4000)"},
                  {"nombre": "titulo", "tipo": "string", "requerido": False, "clave": True, "descripcion": "parte del titulo de la ventana esperada"}],
          danger=True, timeout_s=120)
    def _app_lanzar(args, ctx):
        comando, o = PC.partir_args(args, _CLAVES)
        try:
            cwd = o.get("cwd") or (ctx or {}).get("workspace") if isinstance(ctx, dict) else o.get("cwd")
            if cwd and not Path(cwd).is_dir():
                return _err("app_lanzar", "cwd='%s' no es un directorio" % cwd)
            app_id, a = lanzar(comando, cwd=cwd, espera_ms=PC.entero(o.get("espera"), ESPERA_VENTANA_DEF_MS, 300, ESPERA_VENTANA_MAX_MS),
                               titulo=o.get("titulo", ""))
            r = capturar(app_id, ctx, "app_%s_inicio" % app_id)
            ui = _texto_ui(app_id)
            return ("RESULTADO app_lanzar %s: ventana %r (hwnd %d, %dx%d) %s · captura %s\n%s\n"
                    "Siguientes: app_teclas %s | tecla derecha*3 · app_clic %s | clic \"Boton\" · app_ver %s · app_cerrar %s"
                    % (app_id, a["titulo"], a["hwnd"], r["ancho"], r["alto"], _cabecera_escritorio(a), _texto_captura(r),
                       ui, app_id, app_id, app_id, app_id))
        except ValueError as exc:
            return _err("app_lanzar", exc)
        except Exception as exc:
            return _err("app_lanzar", "%s: %s" % (type(exc).__name__, exc))

    @tool("app_ver",
          "app_ver <id> [| salida=X.png]  -- captura la ventana de la app (aunque este en el otro escritorio) y resume lo visible",
          desc="Fotografia la ventana de una app lanzada con app_lanzar (PrintWindow: funciona con la ventana en "
               "el escritorio de Cognia, sin cambiar de escritorio) y devuelve la ruta del PNG, un resumen "
               "visual (colores, si esta vacia) y el texto legible de la interfaz.",
          params=[{"nombre": "id", "tipo": "string", "requerido": True, "descripcion": "id de la app (a1)"},
                  {"nombre": "salida", "tipo": "string", "requerido": False, "clave": True, "descripcion": "ruta del PNG"}],
          timeout_s=60)
    def _app_ver(args, ctx):
        app_id, o = PC.partir_args(args, _CLAVES)
        try:
            r = capturar(app_id, ctx, "app_%s" % app_id, o.get("salida", ""))
            return "RESULTADO app_ver %s: %s\n%s" % (app_id, _texto_captura(r), _texto_ui(app_id))
        except Exception as exc:
            return _err("app_ver", exc)

    @tool("app_teclas",
          "app_teclas <id> | <pasos: tecla derecha*3; escribir \"hola\"; espera 300; captura> [| foco=1]"
          "  -- teclea a la app y dice si la pantalla cambio",
          desc="Manda teclas a la ventana de la app por mensajes de Windows (no roba el foco): pasos separados "
               "por ';' entre tecla <nombre>[*N] (intro, escape, espacio, arriba, abajo, izquierda, derecha, "
               "f1..f12, letras), teclas a,b,c, escribir \"texto\", espera MS, captura [nombre], esperar \"texto\" [MS], "
               "atajo ctrl+s. Tras cada accion informa la fraccion de pantalla que cambio (0 = la app no reacciono). "
               "Con foco=1 (o para atajos con modificadores) usa entrada REAL cambiando al escritorio de Cognia, "
               "solo si la politica /escritorio foco lo permite.",
          params=[{"nombre": "id", "tipo": "string", "requerido": True, "descripcion": "id de la app"},
                  {"nombre": "pasos", "tipo": "string", "requerido": True, "descripcion": "pasos separados por ';'"},
                  {"nombre": "foco", "tipo": "integer", "requerido": False, "clave": True, "descripcion": "1 = entrada real con foco"}],
          danger=True, timeout_s=180)
    def _app_teclas(args, ctx):
        s, o = PC.partir_args(args, ("foco",))
        partes = re.split(r"\s*\|\s*", s, maxsplit=1)
        if len(partes) < 2 and "pasos" not in o:
            # forma JSON: id en posicional y pasos como clave
            s2, o2 = PC.partir_args(args, _CLAVES)
            partes = [s2, o2.get("pasos", "")]
            o.update(o2)
        app_id, pasos_txt = partes[0].strip(), (partes[1] if len(partes) > 1 else o.get("pasos", ""))
        try:
            pasos = parsear_pasos(pasos_txt)
            if not pasos:
                return _err("app_teclas", "faltan los pasos (ej: tecla derecha*3; escribir \"hola\")")
            return "RESULTADO app_teclas %s:\n%s" % (app_id, _correr_pasos(app_id, pasos, ctx, foco=o.get("foco") == "1"))
        except Exception as exc:
            return _err("app_teclas", exc)

    @tool("app_clic",
          "app_clic <id> | <x,y | \"Texto del control\"> [| boton=derecho] [| doble=1] [| foco=1]"
          "  -- clica en la ventana de la app (coordenadas de cliente o por texto del control)",
          desc="Clic en la ventana de la app: por coordenadas de cliente (x,y desde la esquina superior "
               "izquierda del area util) o por el TEXTO de un control (boton, menu) localizado con UI "
               "Automation (mira app_arbol para ver nombres y posiciones). Informa que control recibio el clic "
               "y cuanto cambio la pantalla.",
          params=[{"nombre": "id", "tipo": "string", "requerido": True, "descripcion": "id de la app"},
                  {"nombre": "destino", "tipo": "string", "requerido": True, "descripcion": "x,y o texto del control"},
                  {"nombre": "boton", "tipo": "string", "requerido": False, "clave": True, "descripcion": "izquierdo (default) o derecho"},
                  {"nombre": "doble", "tipo": "integer", "requerido": False, "clave": True, "descripcion": "1 = doble clic"},
                  {"nombre": "foco", "tipo": "integer", "requerido": False, "clave": True, "descripcion": "1 = clic real con foco"}],
          danger=True, timeout_s=60)
    def _app_clic(args, ctx):
        s, o = PC.partir_args(args, _CLAVES)
        partes = re.split(r"\s*\|\s*", s, maxsplit=1)
        if len(partes) < 2:
            partes = s.split(None, 1)
        if len(partes) < 2:
            return _err("app_clic", "uso: app_clic <id> | x,y  o  app_clic <id> | \"Texto\"")
        app_id, destino = partes[0].strip(), partes[1].strip()
        op = "dobleclic" if o.get("doble") == "1" else ("clicder" if (o.get("boton") or "").startswith("der") else "clic")
        try:
            pasos = parsear_pasos("%s %s" % (op, destino))
            return "RESULTADO app_clic %s:\n%s" % (app_id, _correr_pasos(app_id, pasos, ctx, foco=o.get("foco") == "1"))
        except Exception as exc:
            return _err("app_clic", exc)

    @tool("app_texto",
          "app_texto <id>  -- todo el texto legible de la interfaz de la app (UI Automation + controles Win32)",
          desc="Lee la interfaz de la app sin VLM: nombres de botones, etiquetas, contenido de cajas de texto, "
               "titulos, via UI Automation y WM_GETTEXT. Sirve para comprobar 'tras teclear X la app muestra Y'.",
          params=[{"nombre": "id", "tipo": "string", "requerido": True, "descripcion": "id de la app"}],
          timeout_s=60)
    def _app_texto(args, ctx):
        app_id, _o = PC.partir_args(args, _CLAVES)
        try:
            _app(app_id)
            return "RESULTADO app_texto %s:\n%s" % (app_id, _texto_ui(app_id, 3500) or "(sin texto legible)")
        except Exception as exc:
            return _err("app_texto", exc)

    @tool("app_arbol",
          "app_arbol <id> [| profundidad=N]  -- arbol de controles de la app (tipo, nombre, posicion x,y ancho x alto) para saber donde clicar",
          desc="Arbol de UI Automation de la ventana: cada control con su tipo (Button, Edit, Text, MenuItem...), "
               "nombre, posicion y tamano en coordenadas de cliente (las que usa app_clic) y estado. Usalo antes de "
               "app_clic para elegir el control.",
          params=[{"nombre": "id", "tipo": "string", "requerido": True, "descripcion": "id de la app"},
                  {"nombre": "profundidad", "tipo": "integer", "requerido": False, "clave": True, "descripcion": "niveles (default 6)"}],
          timeout_s=60)
    def _app_arbol(args, ctx):
        app_id, o = PC.partir_args(args, _CLAVES)
        try:
            a = _app(app_id)
            arbol = EP.arbol_uia(a["hwnd"], profundidad=PC.entero(o.get("profundidad"), 6, 1, 12))
            return "RESULTADO app_arbol %s (%d controles):\n%s" % (app_id, len(arbol), EP.texto_arbol(arbol))
        except Exception as exc:
            return _err("app_arbol", exc)

    @tool("app_salida",
          "app_salida <id>  -- stdout/stderr que lleva impreso el proceso de la app (tracebacks, prints) y si sigue vivo",
          desc="La salida de consola del proceso de la app (stdout+stderr capturados a un log): tracebacks de "
               "pygame/tkinter, prints de depuracion, y el estado del proceso.",
          params=[{"nombre": "id", "tipo": "string", "requerido": True, "descripcion": "id de la app"}],
          timeout_s=30)
    def _app_salida(args, ctx):
        app_id, _o = PC.partir_args(args, _CLAVES)
        a = _APPS.get(app_id)
        if a is None:
            return _err("app_salida", "no hay app '%s' en este proceso" % app_id)
        cola = _log_cola(a, 3000)
        return "RESULTADO app_salida %s: %s\n%s" % (app_id, _estado_proceso(a), cola.strip() or "(sin salida)")

    @tool("app_cerrar",
          "app_cerrar <id|todas>  -- cierra la app (WM_CLOSE y, si no obedece, mata su arbol de procesos)",
          desc="Cierra una app lanzada por Cognia (o todas): primero WM_CLOSE, luego taskkill del arbol. Nunca "
               "toca ventanas que no lanzo Cognia.",
          params=[{"nombre": "id", "tipo": "string", "requerido": True, "descripcion": "id o 'todas'"}],
          danger=True, timeout_s=60)
    def _app_cerrar(args, ctx):
        app_id, _o = PC.partir_args(args, _CLAVES)
        if app_id.lower() in ("todas", "all", "*"):
            r = cerrar_todas()
            return "RESULTADO app_cerrar: %s" % ("; ".join(r) or "no habia apps")
        return "RESULTADO app_cerrar: %s" % cerrar(app_id)

    @tool("app_lista",
          "app_lista  -- apps lanzadas por Cognia (vivas o no) y ventanas que hay en su escritorio",
          desc="Lista las apps lanzadas por Cognia con su id, comando, ventana y estado del proceso, y las "
               "ventanas presentes en el escritorio propio.",
          params=[], timeout_s=30)
    def _app_lista(args, ctx):
        lineas = []
        reg = EP.registro_cargar()
        ids = sorted(set(_APPS) | set(reg), key=lambda k: int(k[1:]) if k[1:].isdigit() else 0)
        for k in ids:
            a = _APPS.get(k) or reg.get(k)
            viva = EP.ventana_viva(a.get("hwnd", 0))
            lineas.append("%s: %s · %r · %s" % (k, a.get("cmd", "?"), a.get("titulo", ""),
                                                 ("ventana viva, " + _estado_proceso(a)) if viva else "ventana cerrada"))
        try:
            vs = EP.ventanas_en_escritorio() if EP.activo() else []
            lineas.append("ventanas en el escritorio '%s': %s" % (EP.config()["nombre"],
                          "; ".join("%r (pid %d)" % (t, p) for _h, p, t in vs) or "ninguna"))
        except Exception as exc:
            lineas.append("escritorio propio: %s" % exc)
        return "RESULTADO app_lista:\n" + ("\n".join(lineas) if lineas else "sin apps")

    @tool("app_probar",
          "app_probar <comando> [| pasos=tecla derecha*3; espera 500; captura; clic \"Boton\"; escribir \"x\"] [| espera=MS] [| cwd=RUTA]"
          "  -- lanza la app, ejecuta los pasos con captura tras cada uno, devuelve el informe + mosaico y la cierra",
          desc="PRUEBA COMPLETA de una aplicacion grafica de un tiro: la lanza en el escritorio propio, captura "
               "el estado inicial, ejecuta los pasos (misma gramatica que app_teclas/app_clic: tecla, teclas, escribir, "
               "clic x,y | clic \"Texto\", espera, esperar \"texto\", captura, texto, arbol) informando cuanto cambio la "
               "pantalla tras cada accion, recoge stdout/stderr (tracebacks), arma un MOSAICO con todas las capturas "
               "y cierra la app. Usala para verificar un juego en pygame, una GUI en tkinter o un .exe que acabas "
               "de escribir. Sin pasos: solo arranque + captura + texto de la interfaz + cierre.",
          params=[{"nombre": "comando", "tipo": "string", "requerido": True, "descripcion": "comando a lanzar"},
                  {"nombre": "pasos", "tipo": "string", "requerido": False, "clave": True, "descripcion": "pasos separados por ';'"},
                  {"nombre": "espera", "tipo": "integer", "requerido": False, "clave": True, "descripcion": "ms hasta la ventana (default 4000)"},
                  {"nombre": "cwd", "tipo": "string", "requerido": False, "clave": True, "descripcion": "directorio de trabajo"},
                  {"nombre": "foco", "tipo": "integer", "requerido": False, "clave": True, "descripcion": "1 = entrada real con foco"}],
          danger=True, timeout_s=300)
    def _app_probar(args, ctx):
        comando, o = PC.partir_args(args, _CLAVES)
        try:
            pasos = parsear_pasos(o.get("pasos", ""))
        except ValueError as exc:
            return _err("app_probar", exc)
        try:
            cwd = o.get("cwd") or ((ctx or {}).get("workspace") if isinstance(ctx, dict) else None)
            app_id, a = lanzar(comando, cwd=cwd, espera_ms=PC.entero(o.get("espera"), ESPERA_VENTANA_DEF_MS, 300, ESPERA_VENTANA_MAX_MS),
                               titulo=o.get("titulo", ""))
        except ValueError as exc:
            return _err("app_probar", exc)
        lineas = ["ventana %r (hwnd %d) %s" % (a["titulo"], a["hwnd"], _cabecera_escritorio(a))]
        capturas, etiquetas = [], []
        try:
            r0 = capturar(app_id, ctx, "app_%s_p0" % app_id)
            capturas.append(r0["png"])
            etiquetas.append("inicio")
            lineas.append("inicio: " + _texto_captura(r0))
            ui = _texto_ui(app_id, 800)
            if ui:
                lineas.append(ui)
            if not any(p[0] == "cerrar" for p in pasos):
                pasos = list(pasos)
            informe, caps = _correr_pasos_detalle(app_id, pasos, ctx, foco=o.get("foco") == "1")
            lineas.append(informe)
            for i, c in enumerate(caps):
                capturas.append(c[1])
                etiquetas.append(c[0])
        finally:
            salida = _log_cola(_APPS.get(app_id, {}), 1500) if app_id in _APPS else ""
            estado = _estado_proceso(_APPS[app_id]) if app_id in _APPS else "?"
            if app_id in _APPS:
                lineas.append("cierre: " + cerrar(app_id))
        if salida.strip():
            lineas.append("salida del proceso (%s):\n%s" % (estado, salida.strip()[-1500:]))
        else:
            lineas.append("salida del proceso: (vacia) · %s" % estado)
        if "Traceback" in salida:
            lineas.append("VEREDICTO: la app lanzo un TRACEBACK (ver salida)")
        if len(capturas) >= 1:
            try:
                m = PC.mosaico(capturas, PC.ruta_salida(ctx, "app_%s_mosaico" % app_id), etiquetas)
                lineas.append("mosaico de %d captura(s): %s" % (len(capturas), m))
            except Exception as exc:
                lineas.append("mosaico no generado: %s" % exc)
        _anotar("app_probar", "%s: %d pasos" % (comando, len(pasos)))
        return "RESULTADO app_probar %s:\n%s" % (comando, "\n".join(lineas))


def _correr_pasos(app_id: str, pasos: list, ctx, foco: bool = False) -> str:
    return _correr_pasos_detalle(app_id, pasos, ctx, foco)[0]


def _correr_pasos_detalle(app_id: str, pasos: list, ctx, foco: bool = False) -> tuple:
    """(informe, [(etiqueta, png)]) ejecutando los pasos en orden; se detiene
    si la ventana muere (y lo dice)."""
    lineas, caps = [], []
    for i, paso in enumerate(pasos, 1):
        try:
            r = ejecutar_paso(app_id, paso, ctx, foco=foco)
        except ValueError as exc:
            lineas.append("%d. %s -> DETENIDO: %s" % (i, paso[0], exc))
            break
        cambio = ""
        if r.get("cambio") is not None:
            f = r["cambio"]
            cambio = " · pantalla %s (%.1f%%)" % ("cambio" if f > 0.002 else "NO cambio", f * 100)
            if f > 0.002 and r.get("captura_despues"):
                caps.append(("%d %s" % (i, r["texto"][:18]), r["captura_despues"]))
        if r.get("captura"):
            caps.append(("%d captura" % i, r["captura"]))
        err = (" · ERROR: " + r["error"]) if r.get("error") else ""
        lineas.append("%d. %s%s%s" % (i, r["texto"], cambio, err))
        if paso[0] == "cerrar":
            break
    return "\n".join(lineas) if lineas else "(sin pasos)", caps
