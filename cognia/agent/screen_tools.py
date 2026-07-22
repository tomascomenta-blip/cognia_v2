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


def localizar(ctx: dict, image_path: str, confidence: float = 0.9):
    """Localiza una imagen en pantalla (READ-ONLY). Devuelve centro o None."""
    ok, err = _gate(ctx, "localizar", destructiva=False, detalle=image_path)
    if not ok:
        return err
    global _acciones_hechas
    try:
        g = _gui()
        try:
            box = g.locateOnScreen(image_path, confidence=confidence)
        except TypeError:                       # sin opencv, sin confidence
            box = g.locateOnScreen(image_path)
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
