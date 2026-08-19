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
import os
import sys


def _ya_es_utf8(stream) -> bool:
    enc = getattr(stream, "encoding", None)
    if not enc:
        return False
    return enc.lower().replace("-", "") in ("utf8", "utf8mb4")


def preparar_consola_windows() -> dict:
    """Pone la consola de Windows en UTF-8 y con secuencias ANSI activas.

    POR QUE (2026-08-18). `forzar_utf8()` arregla el lado de PYTHON (no revienta
    con UnicodeEncodeError) pero no el de la CONSOLA: si el code page de salida
    es 1252/850 -- el de esta maquina por defecto -- los bytes UTF-8 llegan al
    conhost como mojibake, y el banner Braille (U+28xx) sale como una pared de
    '?'. Eso parece corrupcion, que es PEOR que no dibujarlo. Y el CLI emite
    color de 24 bits crudo sin que nadie garantice que VT este habilitado.

    Devuelve que se pudo hacer; nunca lanza (en otro SO, no hace nada).
    """
    hecho = {"code_page": False, "vt": False, "so": os.name}
    if os.name != "nt":
        return hecho
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        # 65001 = UTF-8. Se toca la de SALIDA y la de ENTRADA (los acentos que
        # el usuario teclea entran por la segunda).
        if k32.SetConsoleOutputCP(65001):
            hecho["code_page"] = True
        k32.SetConsoleCP(65001)
        # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004 sobre STD_OUTPUT (-11).
        handle = k32.GetStdHandle(-11)
        modo = ctypes.c_uint32()
        if k32.GetConsoleMode(handle, ctypes.byref(modo)):
            if k32.SetConsoleMode(handle, modo.value | 0x0004):
                hecho["vt"] = True
    except Exception as exc:            # consola redirigida, sin conhost, etc.
        hecho["error"] = f"{type(exc).__name__}: {exc}"
    return hecho


def forzar_utf8() -> bool:
    """
    Reenvuelve stdout/stderr en UTF-8 si no lo estan ya.

    Devuelve True si reenvolvio algo. Idempotente: llamarla dos veces no
    apila wrappers, porque tras la primera el stream ya reporta utf-8.
    """
    # La consola primero: sin code page UTF-8, reenvolver los streams solo
    # consigue mandar bytes correctos a una consola que los pinta mal.
    preparar_consola_windows()
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
