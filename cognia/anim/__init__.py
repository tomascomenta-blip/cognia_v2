# -*- coding: utf-8 -*-
"""Motor de animación 2D por keyframes/capas (F5 del goal assets IA).

Determinista (interpolar es matemática, sin IA): huesos jerárquicos + slots (sprites)
+ timelines con easing, formato JSON estilo DragonBones. `engine.bake()` hornea a una
tabla de frames que `runtime` reproduce en web (Canvas2D autocontenido, offline).

API: engine.posar/bake, runtime.pagina_animada.
"""
from .engine import bake, posar, mat_trs, mat_mul  # noqa: F401
from .runtime import pagina_animada, RUNTIME_JS     # noqa: F401
