"""
cognia/lcd/exporters.py — Export/import de la escena LCD (paper §8: la
escena estructurada es portable, no queda atrapada en el pipeline).

scene.to_json()/Scene.from_json() YA cubren el formato JSON (scene.py); este
modulo agrega el otro formato de export -- SVG determinista, vectorial e
inspeccionable a ojo o por cualquier visor -- mas las funciones de I/O a
archivo que usan las tools de servicio (tools_services.py). Sin dependencias
nuevas: el SVG se arma con f-strings (mismo espiritu que renderer.py, pero
vectorial en vez de rasterizado).
"""
from __future__ import annotations

from pathlib import Path

from cognia.lcd.scene import Scene


def _svg_shape(o, w_px: float, h_px: float) -> str:
    """Un objeto -> el elemento SVG que le corresponde, en coordenadas de
    pixel (la escena vive en [0,1]; se escala a width/height del canvas). La
    rotacion (grados, 0=sin rotar) se aplica como transform alrededor del
    centro del objeto -- mismo criterio de o.rotation que usa el resto de LCD."""
    cx, cy = o.x * w_px, o.y * h_px
    hw, hh = o.w * w_px / 2, o.h * h_px / 2
    fill = "rgb({},{},{})".format(*o.color)
    rot = f' transform="rotate({o.rotation:g} {cx:.2f} {cy:.2f})"' if o.rotation else ""
    if o.shape == "ellipse" or o.shape == "circle":
        if o.shape == "circle":
            r = min(hw, hh)
            return f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r:.2f}" fill="{fill}"{rot}/>'
        return (f'<ellipse cx="{cx:.2f}" cy="{cy:.2f}" rx="{hw:.2f}" ry="{hh:.2f}" '
                f'fill="{fill}"{rot}/>')
    if o.shape == "triangle":
        pts = (f"{cx:.2f},{cy - hh:.2f} {cx - hw:.2f},{cy + hh:.2f} "
               f"{cx + hw:.2f},{cy + hh:.2f}")
        return f'<polygon points="{pts}" fill="{fill}"{rot}/>'
    # rect (y default para una forma desconocida: no rompe el export).
    x0, y0 = cx - hw, cy - hh
    return (f'<rect x="{x0:.2f}" y="{y0:.2f}" width="{2 * hw:.2f}" '
            f'height="{2 * hh:.2f}" fill="{fill}"{rot}/>')


def scene_to_svg(scene: Scene) -> str:
    """Escena -> SVG determinista: un elemento por objeto (en orden z), mas
    el fondo como <rect> de fondo cubriendo todo el canvas. XML bien formado
    (parseable con xml.etree.ElementTree)."""
    w_px, h_px = scene.width, scene.height
    bg = "rgb({},{},{})".format(*scene.background)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w_px}" height="{h_px}" '
        f'viewBox="0 0 {w_px} {h_px}">',
        f'<rect x="0" y="0" width="{w_px}" height="{h_px}" fill="{bg}"/>',
    ]
    for o in sorted(scene.objects, key=lambda o: o.z):
        parts.append(_svg_shape(o, w_px, h_px))
    parts.append("</svg>")
    return "\n".join(parts)


def export_scene(scene: Scene, fmt: str, path: str = None) -> str:
    """Exporta la escena en `fmt` ('svg'|'json'). Sin `path`, devuelve el
    contenido (para incrustar un extracto en el RESULTADO de la tool); con
    `path`, escribe el archivo (crea directorios si hace falta) y devuelve la
    ruta escrita."""
    fmt = fmt.lower()
    if fmt == "svg":
        content = scene_to_svg(scene)
    elif fmt == "json":
        content = scene.to_json()
    else:
        raise ValueError(f"formato de export desconocido: '{fmt}' (svg|json)")
    if path is None:
        return content
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return str(p)


def import_scene_json(path: str) -> Scene:
    """Carga una escena desde un archivo JSON (usa Scene.from_json)."""
    text = Path(path).read_text(encoding="utf-8")
    return Scene.from_json(text)
