# -*- coding: utf-8 -*-
"""Tool 3D para el agente (ola 1 flota multimodal, 2026-08-09).

POR QUE: TripoSR convierte una imagen de objeto en malla 3D y el agente no
tenia como alcanzarlo — el modo de fallo clasico del repo (capacidad
construida y desconectada). Con tresd_generar el loop ReAct puede cerrar la
cadena imagen_generar/imagen_quitar_fondo -> malla .glb servible por la
oficina.

Opt-in: se registra solo con COGNIA_3D_TOOLS=1 (cableado en tools.py, ola 2).
Rol: implementador.

VRAM: la tool NO decide si TripoSR cabe junto al cerebro; pide el rol
'tresd' (presupuesto ~4000 MiB) via el gate compartido
(_backend_gate.pedir_backend) y reporta el motivo legible si no se puede.
El gate es de otro agente de esta misma ola: el import es perezoso y
tolerante a ImportError, con AVISO por stderr si falta — degradacion
VISIBLE, jamas silenciosa.
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

# Extensiones que el CLI sabe abrir con PIL y MIME honesto. El input ideal es
# un PNG RGBA de imagen_quitar_fondo (BiRefNet): objeto aislado sobre alfa.
_EXT_IMAGEN = (".png", ".jpg", ".jpeg")

_FORMATOS = ("glb", "obj")

# MiB que pide el gate para el rol tresd (presupuesto, plan congelado).
_VRAM_TRESD_MIB = 4000

# Cota de resolucion de marching cubes: el campo es n^3 — debajo de 32 no hay
# objeto y arriba de 1024 revienta RAM/VRAM sin ganancia visible.
_RES_MIN, _RES_MAX = 32, 1024


def _pedir_backend_tresd():
    """(ok, url, motivo) via el gate compartido; sin gate, sigue con AVISO.

    POR QUE seguir y no bloquear: sin _backend_gate no existe aqui una sonda
    honesta de VRAM (esa sonda ES el gate); negar la capacidad entera por un
    helper ausente seria peor que dejar que el CLI falle VISIBLE (CUDA OOM
    con traceback en el ERROR). El aviso por stderr deja rastro del hueco.
    """
    try:
        from cognia.agent._backend_gate import pedir_backend
        return pedir_backend("tresd", _VRAM_TRESD_MIB)
    except ImportError:
        print("[tresd_tools] sin _backend_gate: no se pudo verificar la "
              "VRAM antes de lanzar TripoSR", file=sys.stderr)
        return True, "", ""


def _soltar_backend_tresd() -> None:
    """Suelta la reserva del rol tresd (best-effort). Jamas rompe la tool."""
    try:
        from cognia.agent._backend_gate import soltar_backend
        soltar_backend("tresd")
    except ImportError:
        pass    # sin gate no hubo reserva que soltar
    except Exception:
        pass    # soltar es best-effort: el resultado de la tool manda


def _salida_en_workspace(nombre: str) -> Path:
    """Deja las mallas junto al resto del trabajo del agente."""
    from cognia.agents.workers.dev_tools import _root_actual
    base = Path(_root_actual()) / "tresd"
    base.mkdir(parents=True, exist_ok=True)
    return base / nombre


def register(tool):
    @tool("tresd_generar",
          "tresd_generar <ruta_imagen> [| formato=obj|glb] [| resolucion=<n>]"
          "  -- convierte una imagen de objeto en malla 3D (TripoSR, GPU "
          "~4GB); ideal un PNG RGBA de imagen_generar/imagen_quitar_fondo")
    def _tresd_generar(args, ctx):
        # Formato legacy: ruta primero, luego opciones k=v en orden libre.
        # Las rutas Windows no pueden contener '|', asi que el split simple
        # es seguro (a diferencia de las tools con texto libre).
        partes = re.split(r"\s*\|\s*", (args or "").strip())
        ruta = partes[0].strip()
        if not ruta:
            return ("RESULTADO tresd_generar ERROR: falta la ruta de la "
                    "imagen (usa: tresd_generar <ruta> [| formato=obj|glb] "
                    "[| resolucion=<n>])")
        formato, resolucion = "glb", 256
        for extra in partes[1:]:
            extra = extra.strip()
            if not extra:
                continue
            m = re.match(r"^formato\s*=\s*(\w+)$", extra)
            if m:
                formato = m.group(1).lower()
                continue
            m = re.match(r"^resolucion\s*=\s*(\d+)$", extra)
            if m:
                resolucion = int(m.group(1))
                continue
            return (f"RESULTADO tresd_generar ERROR: opcion no reconocida "
                    f"'{extra}' (usa formato=obj|glb y resolucion=<n>)")
        if formato not in _FORMATOS:
            return (f"RESULTADO tresd_generar ERROR: formato '{formato}' no "
                    f"soportado (usa {' o '.join(_FORMATOS)})")
        if not (_RES_MIN <= resolucion <= _RES_MAX):
            return (f"RESULTADO tresd_generar ERROR: resolucion {resolucion} "
                    f"fuera de rango ({_RES_MIN}-{_RES_MAX})")
        p = Path(ruta)
        if not p.is_file():
            return f"RESULTADO tresd_generar ERROR: no existe {ruta}"
        if p.suffix.lower() not in _EXT_IMAGEN:
            return (f"RESULTADO tresd_generar ERROR: extension "
                    f"'{p.suffix or '(ninguna)'}' no soportada "
                    f"(acepto {', '.join(_EXT_IMAGEN)})")

        concedido = False
        try:
            # Chequeo barato de disco ANTES de reservar VRAM: si falta el
            # vendor o el venv GPU, el motivo llega sin gastar la reserva.
            from cognia.tresd import generar_malla, tresd_disponible
            ok, motivo = tresd_disponible()
            if not ok:
                return f"RESULTADO tresd_generar ERROR: {motivo}"
            ok, _url, motivo = _pedir_backend_tresd()
            if not ok:
                return ("RESULTADO tresd_generar ERROR: "
                        f"{motivo or 'backend 3D no disponible'}")
            concedido = True
            # hashlib y no hash(): PYTHONHASHSEED cambia hash() por proceso
            # y el nombre del artefacto debe ser estable/reproducible.
            huella = hashlib.md5(
                f"{p.resolve()}|{formato}|{resolucion}".encode("utf-8")
            ).hexdigest()[:8]
            destino = _salida_en_workspace(f"malla_{huella}.{formato}")
            r = generar_malla(str(p), str(destino), formato=formato,
                              resolucion=resolucion)
            return (f"RESULTADO tresd_generar OK: {r['ruta']} "
                    f"({r['verts']} verts, {r['caras']} caras, "
                    f"{r['seg']:.0f}s)")
        except Exception as exc:
            return f"RESULTADO tresd_generar ERROR: {exc}"
        finally:
            # Soltar SIEMPRE que el backend fue concedido, incluso si el CLI
            # reventara: una reserva colgada bloquea la VRAM de la flota.
            if concedido:
                _soltar_backend_tresd()
