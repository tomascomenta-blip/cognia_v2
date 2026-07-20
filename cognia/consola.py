"""
consola.py — Salida de texto que no revienta en Windows.

POR QUE EXISTE: en Windows, cuando stdout no es una consola UTF-8 (tuberia,
redireccion a fichero, o cp1252 por locale), cualquier print con emoji o
caracteres de caja lanza UnicodeEncodeError y MATA el proceso entero.

Medido el 2026-07-19: `/crear` moria en su primer print
(`print("\\n[emoji] [ProgramCreator] Iniciando sesion...")`) antes de generar
una sola linea de codigo. El error que veia el dueno era
`'charmap' codec can't encode character '\\U0001f3a8'` — un fallo de encoding
disfrazado de fallo del generador.

El arreglo ya existia en `cli.py:repl()`, pero vivia DENTRO del REPL: solo
protegia a quien entraba por el chat interactivo. El ciclo idle (`/dormir` ->
`maybe_run_hobby`), `create_program()` y cualquier uso programatico de Cognia
se quedaban sin el. Aqui esta izado a un solo sitio para que lo use todo el
paquete desde el import.

errors="replace" es deliberado: perder un emoji es aceptable, perder la
sesion no.
"""

import io
import sys


def _ya_es_utf8(stream) -> bool:
    enc = getattr(stream, "encoding", None)
    if not enc:
        return False
    return enc.lower().replace("-", "") in ("utf8", "utf8mb4")


def forzar_utf8() -> bool:
    """
    Reenvuelve stdout/stderr en UTF-8 si no lo estan ya.

    Devuelve True si reenvolvio algo. Idempotente: llamarla dos veces no
    apila wrappers, porque tras la primera el stream ya reporta utf-8.
    """
    tocado = False
    for nombre in ("stdout", "stderr"):
        stream = getattr(sys, nombre, None)
        if stream is None or not hasattr(stream, "buffer"):
            continue
        if _ya_es_utf8(stream):
            continue
        setattr(sys, nombre,
                io.TextIOWrapper(stream.buffer, encoding="utf-8",
                                 errors="replace", line_buffering=True))
        tocado = True
    return tocado
