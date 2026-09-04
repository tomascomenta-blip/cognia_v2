# -*- coding: utf-8 -*-
"""Una edición que ROMPE la sintaxis de un fichero que parseaba se REVIERTE.

Portado de SWE-agent (`tools/windowed/lib/flake8_utils.py:
format_flake8_output/_update_previous_errors` + `tools/windowed_edit_replace/
bin/edit`: "lint diferencial") el 2026-09-04, tras leer su código. Allí el
edit se aplica, se pasa flake8 antes y después, y si aparecen errores NUEVOS
se deshace (`undo_edit`) y se le enseñan al modelo las dos ventanas con
"DO NOT re-run the same failed edit command". Es, según sus propios docs, la
pieza que más rinde con modelos pequeños.

Aquí ya existía la mitad: `interceptor.despues` verifica la sintaxis tras
escribir y le dice al modelo "el fichero NO parsea". Pero el fichero se
quedaba ROTO en disco, y el modelo, que ya tenía el texto viejo en su
contexto, tendía a reescribirlo entero (caro) o a editar encima del roto.
Con esto: solo `editar_archivo` (buscar/reemplazar sobre un fichero que
existía y PARSEABA), solo extensiones con verificador (.py/.pyi/.json), y
solo si el resultado NO parsea -> se restaura el contenido previo (vía el
checkpoint que `interceptor.antes` acaba de registrar, o directo si el
checkpoint falló) y el resultado explica el error y que el fichero volvió al
estado anterior.

NO toca `escribir_archivo` ni `apendar_archivo`: la escritura "por partes"
(rescate de argumentos cortados) deja a propósito ficheros que aún no
parsean entre parte y parte. Kill-switch: COGNIA_REVERTIR_SINTAXIS=0.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

ENV_ACTIVO = "COGNIA_REVERTIR_SINTAXIS"
TOOLS_REVERTIBLES = frozenset({"editar_archivo"})
_LOG = logging.getLogger(__name__)


def activo() -> bool:
    return os.environ.get(ENV_ACTIVO, "1").strip().lower() not in ("0", "no", "off", "false")


def _leer(ruta: Path) -> str | None:
    try:
        with open(ruta, "r", encoding="utf-8", newline="") as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return None


def _escribir(ruta: Path, contenido: str) -> None:
    with open(ruta, "w", encoding="utf-8", newline="") as f:
        f.write(contenido)


def _restaurar(ruta: Path, previo: str, ctx: dict) -> str:
    """Devuelve 'checkpoint' o 'directo' según cómo se restauró."""
    entrada = ctx.get("_harness_checkpoint") if isinstance(ctx, dict) else None
    n = entrada.get("n") if isinstance(entrada, dict) else None
    if n is not None:
        try:
            from cognia.harness import checkpoints
            checkpoints.deshacer(n)
            if _leer(ruta) == previo:
                return "checkpoint"
        except Exception as exc:
            _LOG.warning("reversion_sintaxis: deshacer(#%s) fallo (%s); restauro directo", n, exc)
    _escribir(ruta, previo)
    return "directo"


def aplicar(name: str, destino: str, ctx: dict, texto: str) -> str:
    """El texto del resultado, con la reversión anexada si tocó revertir.

    Nunca lanza: cualquier fallo del instrumento deja el texto como estaba y
    lo dice en el log (no en silencio).
    """
    try:
        if not activo() or name not in TOOLS_REVERTIBLES or not destino:
            return texto
        previo_info = ctx.get("_harness_previo") if isinstance(ctx, dict) else None
        if not isinstance(previo_info, dict) or previo_info.get("contenido") is None:
            return texto                      # el fichero no existía: nada que restaurar
        from cognia.harness.interceptor import raiz_proyecto
        from cognia.harness.verificacion import verificar_sintaxis
        ruta = Path(destino)
        if not ruta.is_absolute():
            ruta = raiz_proyecto(ctx) / ruta
        try:
            ruta = ruta.resolve()
        except OSError:
            pass
        if str(ruta) != str(Path(previo_info.get("ruta", "")).resolve()) if previo_info.get("ruta") else True:
            return texto                      # el previo guardado es de otro fichero
        if ruta.suffix.lower() not in (".py", ".pyi", ".json"):
            return texto
        previo = previo_info["contenido"]
        ok_previo, _ = verificar_sintaxis(ruta, previo)
        if not ok_previo:
            return texto                      # ya estaba roto: el modelo lo está arreglando
        nuevo = _leer(ruta)
        if nuevo is None:
            return texto
        ok_nuevo, mensaje = verificar_sintaxis(ruta, nuevo)
        if ok_nuevo:
            return texto
        como = _restaurar(ruta, previo, ctx)
        aviso = (f"\nRESULTADO verificacion {ruta.name}: la edición dejó el fichero SIN "
                 f"PARSEAR ({mensaje}). Antes de tu cambio parseaba, así que se REVIRTIÓ "
                 f"al estado anterior ({como}): el disco está como ANTES de este "
                 f"editar_archivo y tu cambio NO está aplicado. No repitas el mismo "
                 f"edit: corrige el bloque de reemplazo (indentación, paréntesis, "
                 f"comillas) y vuelve a llamar a editar_archivo.")
        if isinstance(ctx, dict):
            ctx["_harness_revertido"] = str(ruta)
        return f"{texto}{aviso}"
    except Exception as exc:
        _LOG.warning("reversion_sintaxis degradada: %s: %s", type(exc).__name__, exc)
        return texto


__all__ = ["aplicar", "activo", "ENV_ACTIVO", "TOOLS_REVERTIBLES"]
