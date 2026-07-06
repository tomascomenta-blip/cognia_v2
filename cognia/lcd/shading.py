"""
cognia/lcd/shading.py — Herramientas de SHADING procedural (analogo 2D del
Principled BSDF + luces de Blender), para acercar el render a foto-realismo en CPU.

Todo con PIL + numpy, determinista, sin GPU. Las piezas que mas suben la
fidelidad de un objeto rasterizado (medido iterando el lapiz):
  - gradiente lineal/radial: simula la curvatura de un cilindro/esfera (el borde
    se va a sombra, el centro-lit queda claro) -> da VOLUMEN, no color plano.
  - highlight especular: una banda/mancha clara (glossy/metallic); su ancho =
    roughness (angosto=espejo, ancho=mate).
  - banda metalica: gradiente vertical con reflejos (virola cepillada).
Coords en PIXELES.
"""
from __future__ import annotations

import numpy as np
from PIL import Image


def _clamp(c):
    return tuple(int(max(0, min(255, v))) for v in c)


def cylinder_gradient(color, w, h, light=1.28, shadow=0.55, axis="x",
                      lit=0.36) -> Image.Image:
    """Parche RGBA de w×h con el sombreado de un CILINDRO iluminado de costado:
    claro en la franja `lit` (0..1 a lo largo del eje transversal) y oscuro hacia
    los bordes. axis='x' (cilindro vertical, gradiente horizontal, p.ej. el barril
    de un lapiz de pie) o 'y' (cilindro horizontal, p.ej. un lapiz acostado)."""
    w, h = int(w), int(h)
    if w < 1 or h < 1:
        return Image.new("RGBA", (max(1, w), max(1, h)), (0, 0, 0, 0))
    base = np.array(color[:3], dtype=np.float32)
    n = w if axis == "x" else h
    t = np.linspace(0.0, 1.0, n)
    # distancia (en curva de coseno) al centro-lit -> factor de luz
    d = np.abs(t - lit)
    d = d / max(d.max(), 1e-6)
    factor = shadow + (light - shadow) * np.cos(d * (np.pi / 2)) ** 1.4
    line = np.clip(base[None, :] * factor[:, None], 0, 255)   # (n,3)
    if axis == "x":
        arr = np.repeat(line[None, :, :], h, axis=0)          # (h,w,3)
    else:
        arr = np.repeat(line[:, None, :], w, axis=1)          # (h,w,3)
    rgba = np.dstack([arr.astype(np.uint8),
                      np.full((h, w), 255, dtype=np.uint8)])
    return Image.fromarray(rgba, "RGBA")


def specular_streak(w, h, color=(255, 255, 255), pos=0.30, width=0.10,
                    strength=200, axis="x") -> Image.Image:
    """Franja especular (brillo glossy) sobre un parche RGBA transparente: una
    linea clara a lo largo del cilindro en la posicion `pos` (0..1), de ancho
    `width` (roughness: chico=espejo). strength = alpha pico (0..255)."""
    w, h = int(w), int(h)
    if w < 1 or h < 1:
        return Image.new("RGBA", (max(1, w), max(1, h)), (0, 0, 0, 0))
    n = w if axis == "x" else h
    t = np.linspace(0.0, 1.0, n)
    a = np.exp(-((t - pos) ** 2) / (2 * (width ** 2 + 1e-6))) * strength
    a = a.astype(np.uint8)
    col = np.array(color[:3], dtype=np.uint8)
    if axis == "x":
        alpha = np.repeat(a[None, :], h, axis=0)
        rgb = np.broadcast_to(col, (h, w, 3))
    else:
        alpha = np.repeat(a[:, None], w, axis=1)
        rgb = np.broadcast_to(col, (h, w, 3))
    rgba = np.dstack([rgb.astype(np.uint8), alpha])
    return Image.fromarray(rgba, "RGBA")


def paste_shaded(img: Image.Image, patch: Image.Image, x0: int, y0: int,
                 mask_poly=None):
    """Pega un parche RGBA sobre img (RGB), opcionalmente recortado a un poligono
    (para que el gradiente respete la silueta de la figura)."""
    if mask_poly is not None:
        from PIL import ImageDraw
        m = Image.new("L", patch.size, 0)
        ImageDraw.Draw(m).polygon([(px - x0, py - y0) for px, py in mask_poly],
                                  fill=255)
        # combinar la mascara del poligono con el alpha del parche
        pa = patch.split()[3]
        m = Image.composite(pa, Image.new("L", patch.size, 0), m)
        img.paste(patch, (x0, y0), m)
    else:
        img.paste(patch, (x0, y0), patch)
