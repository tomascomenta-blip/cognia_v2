# -*- coding: utf-8 -*-
"""Arnés de captura del flappy.py de Cognia: NO toca el juego.

Monkeypatchea pygame para (a) guardar un frame PNG cada 12 flips, (b) inyectar
un salto (K_SPACE) cada 32 frames como autopilot, (c) cortar a los 900 frames.
El juego corre tal cual lo escribió el agente (runpy).
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pygame  # noqa: E402

CAP = Path(__file__).parent / "capturas"
CAP.mkdir(exist_ok=True)
for f in CAP.glob("frame_*.png"):
    f.unlink()

_frames = {"n": 0}
_real_flip = pygame.display.flip


def _flip():
    _frames["n"] += 1
    if _frames["n"] % 12 == 0:
        surf = pygame.display.get_surface()
        if surf is not None:
            pygame.image.save(surf, str(CAP / f"frame_{_frames['n']:04d}.png"))
    _real_flip()


_real_get = pygame.event.get


def _get(*a, **kw):
    evs = list(_real_get(*a, **kw))
    if _frames["n"] % 32 == 0 and _frames["n"] > 0:
        evs.append(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE))
    if _frames["n"] >= 900:
        evs.append(pygame.event.Event(pygame.QUIT))
    return evs


pygame.display.flip = _flip
pygame.event.get = _get

import runpy  # noqa: E402

try:
    runpy.run_path(str(Path(__file__).parent / "flappy.py"), run_name="__main__")
except SystemExit:
    pass
print(f"CAPTURA OK: {_frames['n']} frames, {len(list(CAP.glob('*.png')))} PNGs en {CAP}")
