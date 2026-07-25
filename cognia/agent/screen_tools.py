r"""
cognia/agent/screen_tools.py — computer-use nativo (pantalla) con gate de seguridad
===================================================================================
Mandato del dueño (2026-07-13): darle a Cognia acceso a la pantalla con
herramientas nativas estilo pyautogui + navegador. Control de mouse/teclado
es la superficie MÁS peligrosa del agente (puede hacer cualquier cosa en la
máquina), así que el gate de seguridad es la pieza central, no un extra:

  1. OPT-IN duro: COGNIA_SCREEN=1 para habilitar. Sin eso, todas las acciones
     devuelven un mensaje de "deshabilitado" (nunca tocan la máquina).
  2. FAILSAFE de pyautogui: mover el mouse a una esquina ABORTA todo.
  3. PAUSA entre acciones (no ráfagas) + límite de acciones por tarea.
  4. AUDITORÍA append-only: cada acción se registra en
     ~/.cognia/screen_audit.jsonl (qué, cuándo, resultado).
  5. Acciones READ-ONLY (captura, localizar) permitidas con el opt-in;
     acciones DESTRUCTIVAS (click, escribir, tecla) además exigen confirmación
     (callback ctx['confirm'] o modo autónomo COGNIA_SCREEN_AUTO=1).
  6. Bounds check: los clicks deben caer dentro de la pantalla.

Las tools se registran como danger=True → solo el rol implementador las ve.
El backend (pyautogui) va detrás de _gui() para poder inyectar un fake en
tests (nunca se mueve el mouse real en CI).
"""
from __future__ import annotations

import datetime
import json
import os
from pathlib import Path

_AUDIT = Path.home() / ".cognia" / "screen_audit.jsonl"
_MAX_ACCIONES = int(os.environ.get("COGNIA_SCREEN_MAX", "40"))
_acciones_hechas = 0


def _enabled() -> bool:
    return os.environ.get("COGNIA_SCREEN", "").strip().lower() in (
        "1", "on", "true", "yes")


def _auto() -> bool:
    """Modo autónomo: las acciones destructivas no piden confirmación
    interactiva (para corridas manager/deadline). Igual auditan."""
    return os.environ.get("COGNIA_SCREEN_AUTO", "").strip().lower() in (
        "1", "on", "true", "yes")


def _gui():
    """Backend real (pyautogui) con FAILSAFE. Indirección para test."""
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = float(os.environ.get("COGNIA_SCREEN_PAUSE", "0.3"))
    return pyautogui


def _audit(accion: str, detalle: dict, resultado: str) -> None:
    try:
        _AUDIT.parent.mkdir(parents=True, exist_ok=True)
        with _AUDIT.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                "accion": accion, "detalle": detalle,
                "resultado": resultado[:200]}, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _confirmado(ctx: dict, accion: str, detalle: str) -> bool:
    """True si la acción destructiva puede proceder: modo autónomo, o el
    caller provee ctx['confirm'](accion, detalle)->bool y devuelve True."""
    if _auto():
        return True
    confirm = (ctx or {}).get("confirm")
    if callable(confirm):
        try:
            return bool(confirm(accion, detalle))
        except Exception:
            return False
    return False


def _gate(ctx: dict, accion: str, destructiva: bool, detalle: str):
    """(ok, mensaje_de_error_o_None). Aplica opt-in, tope de acciones y
    confirmación. No toca la pantalla."""
    global _acciones_hechas
    if not _enabled():
        return False, ("RESULTADO pantalla ERROR: acceso a pantalla "
                       "DESHABILITADO. Habilitar con COGNIA_SCREEN=1 (control "
                       "de mouse/teclado; usar con cuidado).")
    if _acciones_hechas >= _MAX_ACCIONES:
        return False, (f"RESULTADO pantalla ERROR: tope de {_MAX_ACCIONES} "
                       "acciones por tarea alcanzado (COGNIA_SCREEN_MAX).")
    if destructiva and not _confirmado(ctx, accion, detalle):
        _audit(accion, {"detalle": detalle}, "RECHAZADA (sin confirmacion)")
        return False, (f"RESULTADO pantalla ERROR: acción '{accion}' requiere "
                       "confirmación (destructiva). Modo autónomo: "
                       "COGNIA_SCREEN_AUTO=1, o proveer confirm() en el ctx.")
    return True, None


def reset_contador() -> None:
    global _acciones_hechas
    _acciones_hechas = 0


# ── Core (cada uno gateado; devuelve string RESULTADO ...) ──────────────────

def captura(ctx: dict, region=None) -> str:
    """Screenshot (READ-ONLY). Guarda PNG en el workspace del agente y
    devuelve la ruta + tamaño. region=(x,y,w,h) opcional."""
    ok, err = _gate(ctx, "captura", destructiva=False, detalle=str(region))
    if not ok:
        return err
    global _acciones_hechas
    try:
        from cognia.agents.workers.dev_tools import _root_actual
        base = Path(_root_actual())
    except Exception:
        base = Path.home() / ".cognia" / "capturas"
    base.mkdir(parents=True, exist_ok=True)
    dest = base / f"captura_{datetime.datetime.now():%H%M%S}.png"
    try:
        img = _gui().screenshot(region=region) if region else _gui().screenshot()
        img.save(str(dest))
        _acciones_hechas += 1
        _audit("captura", {"region": region, "dest": str(dest)}, "OK")
        return (f"RESULTADO pantalla captura: {dest} ({img.width}x{img.height})")
    except Exception as exc:
        _audit("captura", {"region": region}, f"ERROR {exc}")
        return f"RESULTADO pantalla captura ERROR: {exc}"


def _excs_no_encontrada() -> tuple:
    """Las excepciones de 'la imagen no esta en pantalla'.

    Son DOS clases distintas y hay que capturar las dos: pyautogui define su
    propia ImageNotFoundException y no es la de pyscreeze (medido 2026-07-25:
    capturar solo la de pyscreeze dejaba pasar la de pyautogui, que salia como
    'ERROR: ' con mensaje vacio)."""
    excs = []
    for modulo in ("pyautogui", "pyscreeze"):
        try:
            mod = __import__(modulo)
            exc = getattr(mod, "ImageNotFoundException", None)
            if isinstance(exc, type) and issubclass(exc, BaseException):
                excs.append(exc)
        except Exception:
            pass
    return tuple(excs) or (_NuncaOcurre,)


class _NuncaOcurre(Exception):
    """Centinela: si no hay ninguna clase que capturar, el except no dispara."""


def localizar(ctx: dict, image_path: str, confidence: float = 0.9):
    """Localiza una imagen en pantalla (READ-ONLY). Devuelve centro o None."""
    ok, err = _gate(ctx, "localizar", destructiva=False, detalle=image_path)
    if not ok:
        return err
    global _acciones_hechas
    if not Path(image_path).is_file():
        return f"RESULTADO pantalla localizar ERROR: no existe {image_path}"
    try:
        g = _gui()
        # pyscreeze >=1.0 NO devuelve None cuando no encuentra: lanza
        # ImageNotFoundException (USE_IMAGE_NOT_FOUND_EXCEPTION=True). Esa
        # excepcion se colaba al except Exception y salia como ERROR — para el
        # agente un ERROR es una accion fallida, y tres seguidas lo apagan.
        # "No esta en pantalla" es un RESULTADO normal, no un fallo.
        _NoEsta = _excs_no_encontrada()
        try:
            box = g.locateOnScreen(image_path, confidence=confidence)
        except _NoEsta:
            _audit("localizar", {"img": image_path}, "no encontrada")
            return "RESULTADO pantalla localizar: no encontrada"
        except (TypeError, NotImplementedError):
            # sin opencv no hay `confidence`: se reintenta SIN el keyword.
            # Cazado 2026-07-25 en una sesion real del dueno: pyscreeze lanza
            # NotImplementedError (no TypeError), asi que este fallback nunca
            # corria y cada localizar moria con "ERROR: The confidence keyword
            # argument is only available if OpenCV is installed". Tres tareas
            # seguidas del agente se apagaron por esto ("sin progreso").
            try:
                box = g.locateOnScreen(image_path)
            except _NoEsta:
                _audit("localizar", {"img": image_path}, "no encontrada")
                return "RESULTADO pantalla localizar: no encontrada"
        _acciones_hechas += 1
        if box is None:
            _audit("localizar", {"img": image_path}, "no encontrada")
            return "RESULTADO pantalla localizar: no encontrada"
        c = g.center(box)
        _audit("localizar", {"img": image_path, "centro": [c.x, c.y]}, "OK")
        return f"RESULTADO pantalla localizar: centro ({c.x}, {c.y})"
    except Exception as exc:
        return f"RESULTADO pantalla localizar ERROR: {exc}"


def click(ctx: dict, x: int, y: int, boton: str = "left") -> str:
    """Click en (x,y). DESTRUCTIVA (exige confirmación)."""
    detalle = f"click {boton} ({x},{y})"
    ok, err = _gate(ctx, "click", destructiva=True, detalle=detalle)
    if not ok:
        return err
    global _acciones_hechas
    try:
        g = _gui()
        w, h = g.size()
        if not (0 <= x < w and 0 <= y < h):
            return f"RESULTADO pantalla click ERROR: ({x},{y}) fuera de {w}x{h}"
        g.click(x=x, y=y, button=boton)
        _acciones_hechas += 1
        _audit("click", {"x": x, "y": y, "boton": boton}, "OK")
        return f"RESULTADO pantalla click: {boton} en ({x}, {y})"
    except Exception as exc:
        _audit("click", {"x": x, "y": y}, f"ERROR {exc}")
        return f"RESULTADO pantalla click ERROR: {exc}"


def escribir(ctx: dict, texto: str) -> str:
    """Teclea texto. DESTRUCTIVA."""
    ok, err = _gate(ctx, "escribir", destructiva=True, detalle=texto[:60])
    if not ok:
        return err
    global _acciones_hechas
    try:
        _gui().typewrite(texto, interval=0.02)
        _acciones_hechas += 1
        _audit("escribir", {"len": len(texto)}, "OK")
        return f"RESULTADO pantalla escribir: {len(texto)} chars"
    except Exception as exc:
        return f"RESULTADO pantalla escribir ERROR: {exc}"


def tecla(ctx: dict, *teclas: str) -> str:
    """Atajo de teclado (hotkey), p.ej. ctrl+s. DESTRUCTIVA."""
    detalle = "+".join(teclas)
    ok, err = _gate(ctx, "tecla", destructiva=True, detalle=detalle)
    if not ok:
        return err
    global _acciones_hechas
    try:
        _gui().hotkey(*teclas)
        _acciones_hechas += 1
        _audit("tecla", {"teclas": list(teclas)}, "OK")
        return f"RESULTADO pantalla tecla: {detalle}"
    except Exception as exc:
        return f"RESULTADO pantalla tecla ERROR: {exc}"


def ventanas(ctx: dict, filtro: str = "") -> str:
    """Lista las ventanas abiertas con titulo (READ-ONLY)."""
    ok, err = _gate(ctx, "ventanas", destructiva=False, detalle=filtro)
    if not ok:
        return err
    try:
        import pygetwindow as gw
        titulos = [w.title for w in gw.getAllWindows() if w.title.strip()]
        if filtro:
            f = filtro.lower()
            titulos = [t for t in titulos if f in t.lower()]
        if not titulos:
            return ("RESULTADO pantalla ventanas: ninguna" +
                    (f" con '{filtro}'" if filtro else ""))
        _audit("ventanas", {"filtro": filtro, "n": len(titulos)}, "OK")
        return "RESULTADO pantalla ventanas: " + " | ".join(titulos[:15])
    except Exception as exc:
        return f"RESULTADO pantalla ventanas ERROR: {exc}"


def activar_ventana(ctx: dict, titulo: str) -> str:
    """Trae al frente la ventana cuyo titulo CONTIENE `titulo`.

    Faltaba (cazado 2026-07-25): el dueno pidio "pone Chrome al frente, esta
    detras de otras ventanas" y el agente no tenia ninguna tool de ventanas —
    solo podia buscar una imagen en pantalla, que ademas fallaba. Sin esto,
    capturar una app concreta es a ciegas.

    Es DESTRUCTIVA en el sentido del gate: cambia el foco de la maquina."""
    titulo = (titulo or "").strip()
    if not titulo:
        return "RESULTADO pantalla activar_ventana ERROR: falta el titulo"
    ok, err = _gate(ctx, "activar_ventana", destructiva=True, detalle=titulo)
    if not ok:
        return err
    global _acciones_hechas
    try:
        import pygetwindow as gw
        cands = [w for w in gw.getAllWindows()
                 if titulo.lower() in w.title.lower() and w.title.strip()]
        if not cands:
            _audit("activar_ventana", {"titulo": titulo}, "no encontrada")
            return (f"RESULTADO pantalla activar_ventana: no hay ventana con "
                    f"'{titulo}' (usa pantalla_ventanas para ver los titulos)")
        v = cands[0]
        try:
            if v.isMinimized:
                v.restore()
        except Exception:
            pass
        v.activate()
        _acciones_hechas += 1
        _audit("activar_ventana", {"titulo": v.title}, "OK")
        return f"RESULTADO pantalla activar_ventana: {v.title}"
    except Exception as exc:
        # activate() de pygetwindow falla si otro proceso tiene el foreground
        # lock de Windows; el minimizar+restaurar suele saltarselo.
        try:
            v.minimize(); v.restore()
            _acciones_hechas += 1
            _audit("activar_ventana", {"titulo": v.title}, "OK (restore)")
            return f"RESULTADO pantalla activar_ventana: {v.title}"
        except Exception:
            return f"RESULTADO pantalla activar_ventana ERROR: {exc}"


# ── Registro como @tool (danger) ────────────────────────────────────────────
def register(tool_decorator) -> None:
    """Registra las tools de pantalla en el registry del agente. Llamado
    desde tools.py. Todas danger=True (solo rol implementador)."""

    @tool_decorator("pantalla_captura",
                    "pantalla_captura -- screenshot de la pantalla (guarda PNG)",
                    danger=True)
    def _t_captura(args, ctx):
        return captura(ctx)

    @tool_decorator("pantalla_localizar",
                    "pantalla_localizar <ruta.png> -- busca una imagen en "
                    "pantalla y devuelve sus coordenadas", danger=True)
    def _t_localizar(args, ctx):
        return localizar(ctx, args.strip())

    @tool_decorator("pantalla_ventanas",
                    "pantalla_ventanas [filtro] -- lista las ventanas abiertas "
                    "por titulo (para saber que hay y como se llama)",
                    danger=True)
    def _t_ventanas(args, ctx):
        return ventanas(ctx, args.strip())

    @tool_decorator("pantalla_activar_ventana",
                    "pantalla_activar_ventana <titulo> -- trae esa ventana al "
                    "frente (usar ANTES de capturar una app concreta)",
                    danger=True)
    def _t_activar(args, ctx):
        return activar_ventana(ctx, args)

    @tool_decorator("pantalla_click",
                    "pantalla_click <x> <y> -- click del mouse en (x,y) "
                    "[requiere COGNIA_SCREEN=1 + confirmacion]", danger=True)
    def _t_click(args, ctx):
        parts = args.split()
        if len(parts) < 2:
            return "RESULTADO pantalla click ERROR: formato (x y)"
        try:
            return click(ctx, int(parts[0]), int(parts[1]))
        except ValueError:
            return "RESULTADO pantalla click ERROR: x,y deben ser enteros"

    @tool_decorator("pantalla_escribir",
                    "pantalla_escribir <texto> -- teclea texto "
                    "[requiere COGNIA_SCREEN=1 + confirmacion]", danger=True)
    def _t_escribir(args, ctx):
        return escribir(ctx, args)

    @tool_decorator("pantalla_tecla",
                    "pantalla_tecla <t1+t2> -- atajo de teclado, p.ej. ctrl+s "
                    "[requiere COGNIA_SCREEN=1 + confirmacion]", danger=True)
    def _t_tecla(args, ctx):
        teclas = [t for t in args.replace("+", " ").split() if t]
        if not teclas:
            return "RESULTADO pantalla tecla ERROR: sin teclas"
        return tecla(ctx, *teclas)
