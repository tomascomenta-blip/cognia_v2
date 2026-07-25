# -*- coding: utf-8 -*-
"""Tools de IMAGEN para el agente (cableado del barrido nocturno 2026-07-24).

POR QUE: cognia.assets tenia generar/editar/quitar_fondo verificadas en GPU y el
AGENTE no podia alcanzarlas — el modo de fallo clasico del repo (capacidad
construida, probada y desconectada). Con esto el loop ReAct puede producir y
retocar imagenes de verdad.

Imports PEREZOSOS dentro de cada tool: registrar esto no arrastra torch. Si la
GPU esta ocupada (cerebro+VLM servidos) o no hay backend, cada tool devuelve un
RESULTADO ... ERROR legible — nunca rompe el loop.
"""
from __future__ import annotations

import re
from pathlib import Path


def _salida_en_workspace(ctx, nombre: str) -> Path:
    """Deja las imagenes junto al resto del trabajo del agente."""
    from cognia.agents.workers.dev_tools import _root_actual
    base = Path(_root_actual()) / "imagenes"
    base.mkdir(parents=True, exist_ok=True)
    return base / nombre


def register(tool):
    @tool("imagen_generar",
          "imagen_generar <descripcion> [| estilo=pixel|pvz]  -- genera un PNG "
          "transparente con el modelo de imagenes (GPU)")
    def _imagen_generar(args, ctx):
        partes = re.split(r"\s*\|\s*", args.strip(), maxsplit=1)
        prompt = partes[0].strip()
        if not prompt:
            return "RESULTADO imagen_generar ERROR: falta la descripcion"
        estilo = None
        if len(partes) == 2:
            m = re.search(r"estilo\s*=\s*(\w+)", partes[1])
            if m:
                estilo = m.group(1)
        try:
            from cognia.assets import backend_disponible, generar_transparente
            ok, motivo = backend_disponible()
            if not ok:
                return f"RESULTADO imagen_generar ERROR: {motivo}"
            destino = _salida_en_workspace(
                ctx, f"gen_{abs(hash(prompt)) % 10**8}.png")
            ruta = generar_transparente(prompt, estilo=estilo, recortar=True,
                                        salida=str(destino))
            return f"RESULTADO imagen_generar OK: {ruta}"
        except Exception as exc:
            return f"RESULTADO imagen_generar ERROR: {exc}"

    @tool("imagen_editar",
          "imagen_editar <ruta> | <instruccion>       -- edita una imagen "
          "existente (img2img; conserva composicion)")
    def _imagen_editar(args, ctx):
        partes = re.split(r"\s*\|\s*", args, maxsplit=1)
        if len(partes) != 2:
            return "RESULTADO imagen_editar ERROR: formato (usa ruta | instruccion)"
        ruta, instruccion = partes[0].strip(), partes[1].strip()
        if not Path(ruta).is_file():
            return f"RESULTADO imagen_editar ERROR: no existe {ruta}"
        try:
            from cognia.assets import backend_disponible, editar_transparente
            ok, motivo = backend_disponible()
            if not ok:
                return f"RESULTADO imagen_editar ERROR: {motivo}"
            destino = _salida_en_workspace(
                ctx, f"edit_{abs(hash((ruta, instruccion))) % 10**8}.png")
            salida = editar_transparente(ruta, instruccion, salida=str(destino))
            return f"RESULTADO imagen_editar OK: {salida}"
        except Exception as exc:
            return f"RESULTADO imagen_editar ERROR: {exc}"

    @tool("imagen_quitar_fondo",
          "imagen_quitar_fondo <ruta>                 -- quita el fondo "
          "(BiRefNet) y deja un PNG RGBA")
    def _imagen_quitar_fondo(args, ctx):
        ruta = args.strip()
        if not Path(ruta).is_file():
            return f"RESULTADO imagen_quitar_fondo ERROR: no existe {ruta}"
        try:
            from cognia.assets import birefnet_disponible, quitar_fondo
            ok, motivo = birefnet_disponible()
            if not ok:
                return f"RESULTADO imagen_quitar_fondo ERROR: {motivo}"
            destino = _salida_en_workspace(
                ctx, f"alfa_{abs(hash(ruta)) % 10**8}.png")
            salida = quitar_fondo(ruta, salida=str(destino))
            return f"RESULTADO imagen_quitar_fondo OK: {salida}"
        except Exception as exc:
            return f"RESULTADO imagen_quitar_fondo ERROR: {exc}"
