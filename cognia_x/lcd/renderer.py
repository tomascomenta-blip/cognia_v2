"""
cognia_x/lcd/renderer.py — Render APROXIMADO determinista (LCD, paper §4.1 mod 5).

Toma la escena estructurada y produce una imagen de baja fidelidad
(rasterización de primitivas con sombreado simple según la luz). Es la etapa
"render aproximado" del pipeline LCD — NO el refinador neuronal fotorrealista
(§4.1 mod 6), que requiere GPU/difusión y queda FUERA de alcance en CPU
(declarado). El punto que este render SÍ demuestra: geometría-antes-que-píxeles
y control composicional exacto (los objetos caen donde la escena dice).

Determinista, sin red neuronal. PIL para rasterizar.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from cognia_x.lcd.scene import Scene


def _shade(color, factor):
    """Sombreado simple: multiplica el color por un factor de luz [0.6, 1.15]."""
    return tuple(max(0, min(255, int(c * factor))) for c in color)


def render(scene: Scene, labels: bool = True) -> Image.Image:
    """Escena estructurada -> imagen PIL (RGB). Dibuja cada objeto como su
    figura (detallada si la tiene, si no la primitiva), en orden de z, con
    sombreado. labels=False -> render LIMPIO (sin las etiquetas de nombre)."""
    W, H = scene.width, scene.height
    img = Image.new("RGB", (W, H), scene.background)
    d = ImageDraw.Draw(img)
    # piso sutil (mitad inferior mas oscura) para dar suelo
    d.rectangle([0, int(H * 0.75), W, H], fill=_shade(scene.background, 0.92))

    from cognia_x.lcd.detailed_shapes import detailed_drawer, draw_polygon
    for o in sorted(scene.objects, key=lambda o: o.z):
        cx, cy = o.x * W, o.y * H
        hw, hh = o.w * W / 2, o.h * H / 2
        box = [cx - hw, cy - hh, cx + hw, cy + hh]
        fill = _shade(o.color, 1.0)
        edge = _shade(o.color, 0.65)
        # 1) vertices custom (edicion de figuras): shape='polygon' + o.points
        if o.shape == "polygon" and o.points:
            draw_polygon(d, cx, cy, hw, hh, o.color, _shade, o.points)
        # 2) figura DETALLADA multi-parte si el objeto tiene una (taza/mesa/plato)
        elif detailed_drawer(o.name) is not None:
            detailed_drawer(o.name)(d, cx, cy, hw, hh, o.color, _shade)
        # 3) primitivas base
        elif o.shape == "rect":
            d.rectangle(box, fill=fill, outline=edge, width=2)
        elif o.shape in ("ellipse", "circle"):
            if o.shape == "circle":
                r = min(hw, hh)
                box = [cx - r, cy - r, cx + r, cy + r]
            d.ellipse(box, fill=fill, outline=edge, width=2)
        elif o.shape == "triangle":
            d.polygon([(cx, cy - hh), (cx - hw, cy + hh), (cx + hw, cy + hh)],
                      fill=fill, outline=edge)
        # etiqueta chica (nombre) para inspeccionabilidad (§9 interpretabilidad)
        if labels:
            try:
                d.text((cx - hw + 2, cy - hh - 10), o.name[:10], fill=(90, 90, 90))
            except Exception:
                pass
    return img


def render_to(scene: Scene, path, labels: bool = True) -> str:
    """Renderiza y guarda a PNG. Devuelve la ruta. labels=False = render limpio."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    render(scene, labels=labels).save(path)
    return str(path)
