# -*- coding: utf-8 -*-
"""Subsistema de ASSETS de imagen generados por difusión (GPU).

F1 del goal 2026-07-22 (PLAN_ASSETS_IA.md): que Cognia produzca assets de imagen
TRANSPARENTES (PNG con alfa) para juegos/web, en vez de "cuadrados CSS". A
diferencia de `cognia/lcd/` (render procedural PIL, CPU), esto usa difusión en
GPU (SDXL + LayerDiffuse) y vive DELIBERADAMENTE fuera de "sin PyTorch en nodos"
(autorizado por el dueño para imagen). Los imports pesados (torch/diffusers) son
perezosos: importar `cognia.assets` en un nodo CPU no arrastra nada.

API pública: `generar_transparente(prompt, ...)` -> ruta de PNG RGBA.
"""
from .diffusion_backend import (  # noqa: F401
    AssetsError,
    backend_disponible,
    generar_transparente,
)
