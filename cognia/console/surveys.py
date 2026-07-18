"""
cognia/console/surveys.py
=========================
Encuestas interactivas para el REPL de Cognia.

ask_survey() muestra una pregunta con opciones numeradas y devuelve
{"selected": list[str], "libre": str | None}. Si prompt_toolkit esta
instalado y hay TTY real, usa radiolist/checkbox (las etiquetas llevan el
numero como atajo visual); si no, cae SIEMPRE al modo texto plano: opciones
numeradas 1..N mas 'O) Otra respuesta (redactar)', y el usuario tipea
numeros separados por coma.

input_fn/print_fn son inyectables, asi el modulo se testea sin TTY y sin
input() real. Con input_fn inyectada se usa directo el modo texto (nunca
prompt_toolkit), para que los tests sean deterministas.

Entrada invalida: reintenta hasta 3 veces y despues devuelve seleccion vacia
({"selected": [], "libre": None}) en vez de colgarse.
"""

from __future__ import annotations

import sys

# ---------------------------------------------------------------------------
# Optional: prompt_toolkit (mismo patron que cognia/cli.py)
# ---------------------------------------------------------------------------
try:
    from prompt_toolkit.shortcuts import checkboxlist_dialog, radiolist_dialog
    _HAS_PT = True
except ImportError:
    _HAS_PT = False

# Valor centinela para la opcion libre en los dialogos de prompt_toolkit.
_OTRA = "__otra__"
_MAX_REINTENTOS = 3


def ask_survey(pregunta: str, opciones: list[str], multi: bool = False,
               libre: bool = True, input_fn=input, print_fn=print) -> dict:
    """Encuesta interactiva. Devuelve {"selected": list[str], "libre": str|None}.

    - multi=False: una sola opcion (o solo la respuesta libre).
    - multi=True:  varias opciones separadas por coma (ej: "1,3").
    - libre=True:  agrega 'O) Otra respuesta (redactar)'.
    """
    if not opciones:
        return {"selected": [], "libre": None}
    # prompt_toolkit solo con TTY real y sin I/O inyectada (tests -> texto)
    if _HAS_PT and input_fn is input and sys.stdin.isatty():
        try:
            return _ask_pt(pregunta, opciones, multi, libre, input_fn)
        except Exception:
            pass  # sin pantalla utilizable: cae al modo texto
    return _ask_texto(pregunta, opciones, multi, libre, input_fn, print_fn)


# ── Modo texto plano (siempre disponible) ─────────────────────────────────────

def _ask_texto(pregunta, opciones, multi, libre, input_fn, print_fn) -> dict:
    print_fn(pregunta)
    for i, op in enumerate(opciones, start=1):
        print_fn(f"  {i}) {op}")
    if libre:
        print_fn("  O) Otra respuesta (redactar)")
    hint = "numeros separados por coma" if multi else "un numero"
    if libre:
        hint += " u O"
    for _ in range(_MAX_REINTENTOS):
        try:
            raw = input_fn(f"Eleccion ({hint}): ")
        except (EOFError, KeyboardInterrupt, StopIteration):
            return {"selected": [], "libre": None}
        parsed = _parse_seleccion(raw, len(opciones), multi, libre)
        if parsed is None:
            print_fn(f"Entrada invalida. Proba de nuevo ({hint}).")
            continue
        indices, quiere_libre = parsed
        texto_libre = None
        if quiere_libre:
            try:
                texto_libre = input_fn("Otra respuesta: ").strip() or None
            except (EOFError, KeyboardInterrupt, StopIteration):
                texto_libre = None
        return {"selected": [opciones[i - 1] for i in indices], "libre": texto_libre}
    return {"selected": [], "libre": None}


def _parse_seleccion(raw, n_opciones, multi, libre):
    """Parsea "1,3" / "2" / "o". Devuelve (indices_1based, quiere_libre) o
    None si la entrada es invalida (numero fuera de rango, texto, exceso de
    selecciones en modo unico, entrada vacia)."""
    tokens = [t.strip() for t in (raw or "").split(",") if t.strip()]
    if not tokens:
        return None
    indices: list[int] = []
    quiere_libre = False
    for tok in tokens:
        if libre and tok.lower() in ("o", "otra"):
            quiere_libre = True
            continue
        if not tok.isdigit():
            return None
        idx = int(tok)
        if not 1 <= idx <= n_opciones:
            return None
        if idx not in indices:
            indices.append(idx)
    if not multi and (len(indices) + (1 if quiere_libre else 0)) > 1:
        return None
    return indices, quiere_libre


# ── Modo prompt_toolkit (opcional, solo TTY real) ─────────────────────────────

def _ask_pt(pregunta, opciones, multi, libre, input_fn) -> dict:
    """Dialogo radiolist (unico) o checkbox (multi) de prompt_toolkit.

    Las etiquetas llevan el numero de la opcion como atajo visual; la opcion
    libre pide el texto con input_fn despues de cerrar el dialogo.
    """
    values = [(i, f"{i}) {op}") for i, op in enumerate(opciones, start=1)]
    if libre:
        values.append((_OTRA, "O) Otra respuesta (redactar)"))
    if multi:
        result = checkboxlist_dialog(title="Encuesta", text=pregunta, values=values).run()
        seleccion = list(result) if result else []
    else:
        result = radiolist_dialog(title="Encuesta", text=pregunta, values=values).run()
        seleccion = [result] if result is not None else []
    texto_libre = None
    if _OTRA in seleccion:
        seleccion = [s for s in seleccion if s != _OTRA]
        try:
            texto_libre = input_fn("Otra respuesta: ").strip() or None
        except (EOFError, KeyboardInterrupt):
            texto_libre = None
    return {"selected": [opciones[i - 1] for i in seleccion], "libre": texto_libre}
