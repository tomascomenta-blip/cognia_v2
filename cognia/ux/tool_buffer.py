"""
cognia/ux/tool_buffer.py -- el output COMPLETO de las tools del turno (2026-08-23)
==================================================================================
POR QUE EXISTE: el render colapsado (harness/render_tools.bloque_colapsado)
muestra 3 lineas de cabeza y una linea '... +N lineas (/expandir)'. Para que
/expandir pueda reimprimir el output entero, ALGUIEN tiene que guardarlo: el
evento ToolFin viaja con resumen=resultado[:200] (a proposito -- el bus va
tambien a telemetria jsonl y al movil) y el renderer jamas ve el cuerpo.

Quien alimenta: agent/loop.py, justo antes de emitir ToolFin, con el mismo
`resultado` que recorta para el evento -- por eso `resultado[:200] == resumen`
es la llave con la que el renderer casa evento y entrada (ultimo_para).
Quien consume: el renderer (cabeza del colapso) y /expandir en cli.py
(raw view). Quien limpia: loop.py al arrancar cada tarea (nuevo_turno).

CONTRATO: no lanza (el buffer es un adorno: perderlo degrada el render, jamas
el turno), thread-safe (con paralelo(cap=2) hay dos hilos registrando), y con
topes declarados -- entradas por turno y chars por entrada, con marca honesta
de truncado en vez de un recorte mudo.
"""
from __future__ import annotations

import threading

# Topes: 200 tools por turno cubre cualquier corrida real (max_turns tipico
# es 25-40); 400k chars por entrada aguanta un leer_archivo grande ya pasado
# por aci_trim sin dejar que un output patologico se coma la RAM.
MAX_ENTRADAS = 200
MAX_CHARS = 400_000
_MARCA_TRUNCADO = "\n... [truncado para /expandir: el output real siguio]"

_lock = threading.Lock()
_TURNO: list = []          # dicts: {"tool", "args", "resultado", "ok"}


def nuevo_turno() -> None:
    """Vacia el buffer. Lo llama loop.py al arrancar cada tarea: /expandir
    habla siempre del turno en curso (o del ultimo terminado)."""
    with _lock:
        _TURNO.clear()


def registrar(tool: str, args: str, resultado: str, ok: bool = True) -> None:
    """Guarda el output COMPLETO de una tool. Silencioso al tope de entradas
    (la 201 no se guarda: /expandir lista igual dice cuantas hay)."""
    with _lock:
        if len(_TURNO) >= MAX_ENTRADAS:
            return
        texto = resultado if resultado is not None else ""
        if len(texto) > MAX_CHARS:
            texto = texto[:MAX_CHARS] + _MARCA_TRUNCADO
        _TURNO.append({"tool": str(tool or ""), "args": str(args or ""),
                       "resultado": texto, "ok": bool(ok)})


def entradas() -> list:
    """Copia de las entradas del turno, en orden de ejecucion."""
    with _lock:
        return list(_TURNO)


def obtener(n=None):
    """La entrada `n` (1-based, como habla /expandir) o la ULTIMA con None.
    Fuera de rango -> None: el caller decide que decirle al usuario."""
    with _lock:
        if not _TURNO:
            return None
        if n is None:
            return _TURNO[-1]
        try:
            i = int(n)
        except (TypeError, ValueError):
            return None
        if 1 <= i <= len(_TURNO):
            return _TURNO[i - 1]
        return None


def ultimo_para(tool: str, resumen: str = ""):
    """La ultima entrada de `tool` cuyo output empieza por `resumen` (el
    ToolFin viaja con resultado[:200], asi que el prefijo casa exacto).
    Devuelve (indice_1based, entrada) o (0, None): con paralelo(cap=2) el
    'ultimo del buffer' puede ser de OTRO hilo y casar por tool+prefijo es
    lo que evita colgarle a un evento el output de otra tool."""
    with _lock:
        for i in range(len(_TURNO) - 1, -1, -1):
            e = _TURNO[i]
            if e["tool"] == tool and (not resumen
                                      or e["resultado"].startswith(resumen)):
                return i + 1, e
    return 0, None
