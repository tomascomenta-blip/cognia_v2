"""
cognia_x/lcd/detailed_shapes.py — Figuras DETALLADAS (multi-parte) para el render.

El render base dibuja primitivas (rect/ellipse/circle/triangle): una 'taza' salia
como una elipse, que no se parece a una taza. Aca cada objeto conocido se dibuja
como una COMPOSICION de primitivas que SI se le parece (una taza = cuerpo +
borde hueco + asa). Determinista, PIL, sin red neuronal.

Registro DETAILED: canonical_name -> funcion draw(d, cx, cy, hw, hh, color, shade).
El renderer consulta este registro primero; si no hay entrada, cae a la primitiva.
Coords en PIXELES (cx,cy = centro; hw,hh = medio ancho/alto en px).
"""
from __future__ import annotations


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def draw_cup(d, cx, cy, hw, hh, color, shade):
    """Taza vista de costado: cuerpo troncocónico (un poco más angosto abajo),
    borde eliptico con el hueco interior mas oscuro, y asa en 'C' PEGADA al
    cuerpo a la derecha. Robusta a la proporcion (se ve como taza aunque el
    objeto sea alto o ancho)."""
    fill = shade(color, 1.0)
    edge = shade(color, 0.5)
    dark = shade(color, 0.42)         # interior (sombra del hueco)
    light = shade(color, 1.18)        # brillo

    # el cuerpo ocupa la parte IZQUIERDA; el asa la derecha. Usar el menor de
    # w/h como escala del asa para que no se deforme.
    body_left = cx - hw
    body_right = cx + hw * 0.52       # el cuerpo llega hasta aca; el resto = asa
    body_hw = (body_right - body_left) / 2
    body_cx = (body_left + body_right) / 2
    top = cy - hh
    bot = cy + hh
    rim_h = min(hh * 0.34, body_hw * 0.9)   # alto de la elipse del borde

    # --- asa: media elipse (C) cuyos extremos TOCAN el borde derecho del cuerpo.
    # PIL: angulos en grados horarios desde las 3h; el semicirculo DERECHO
    # (extremos arriba y abajo, panza a la derecha) va de -90 a 90. El eje
    # vertical de la elipse cae en body_right -> los extremos nacen del cuerpo.
    handle_w = hw * 0.66
    h_top = cy - hh * 0.30
    h_bot = cy + hh * 0.44
    lw = max(6, int(hw * 0.24))
    # doble trazo: exterior mas oscuro + interior del color -> asa con volumen
    d.arc([body_right - handle_w, h_top, body_right + handle_w, h_bot],
          start=-90, end=90, fill=edge, width=lw)
    d.arc([body_right - handle_w, h_top + lw * 0.4, body_right + handle_w - lw * 0.5,
           h_bot - lw * 0.4], start=-88, end=88, fill=fill, width=max(2, lw // 2))

    # --- cuerpo: troncocono (borde superior mas ancho que el inferior) ---
    top_hw = body_hw
    bot_hw = body_hw * 0.80
    body_top = top + rim_h * 0.5
    body_bot = bot - rim_h * 0.35
    body = [(body_cx - top_hw, body_top), (body_cx + top_hw, body_top),
            (body_cx + bot_hw, body_bot), (body_cx - bot_hw, body_bot)]
    d.polygon(body, fill=fill, outline=edge)
    # sombreado vertical: banda clara a la izquierda + banda oscura a la derecha
    d.polygon([(body_cx - top_hw, body_top), (body_cx - top_hw * 0.45, body_top),
               (body_cx - bot_hw * 0.45, body_bot), (body_cx - bot_hw, body_bot)],
              fill=_lerp(fill, light, 0.45))
    d.polygon([(body_cx + top_hw, body_top), (body_cx + top_hw * 0.60, body_top),
               (body_cx + bot_hw * 0.60, body_bot), (body_cx + bot_hw, body_bot)],
              fill=_lerp(fill, edge, 0.35))
    # --- fondo redondeado del cuerpo ---
    d.chord([body_cx - bot_hw, body_bot - rim_h * 0.9, body_cx + bot_hw, body_bot + rim_h * 0.5],
            0, 180, fill=fill, outline=edge)

    # --- borde superior: elipse exterior (color) + interior (hueco oscuro) ---
    d.ellipse([body_cx - top_hw, top, body_cx + top_hw, top + rim_h],
              fill=fill, outline=edge, width=2)
    d.ellipse([body_cx - top_hw * 0.82, top + rim_h * 0.20,
               body_cx + top_hw * 0.82, top + rim_h * 0.80],
              fill=dark, outline=edge)


def draw_table(d, cx, cy, hw, hh, color, shade):
    """Mesa: tablero + 4 patas (en vez de un rectangulo plano)."""
    fill = shade(color, 1.0)
    edge = shade(color, 0.55)
    top_h = hh * 0.42
    # tablero
    d.rectangle([cx - hw, cy - hh, cx + hw, cy - hh + top_h], fill=fill, outline=edge, width=2)
    # patas
    leg_w = hw * 0.10
    for lx in (cx - hw * 0.86, cx + hw * 0.86 - leg_w):
        d.rectangle([lx, cy - hh + top_h, lx + leg_w, cy + hh],
                    fill=shade(color, 0.8), outline=edge)


def draw_plate(d, cx, cy, hw, hh, color, shade):
    """Plato: elipse con un anillo interior (borde del plato)."""
    fill = shade(color, 1.0)
    edge = shade(color, 0.55)
    d.ellipse([cx - hw, cy - hh, cx + hw, cy + hh], fill=fill, outline=edge, width=2)
    d.ellipse([cx - hw * 0.6, cy - hh * 0.6, cx + hw * 0.6, cy + hh * 0.6],
              fill=shade(color, 0.92), outline=edge)


def draw_polygon(d, cx, cy, hw, hh, color, shade, points):
    """Dibuja un objeto con VERTICES custom (shape='polygon'). points en coords
    locales [-0.5,0.5] (0=centro del objeto); se escalan a la bbox en px."""
    fill = shade(color, 1.0)
    edge = shade(color, 0.55)
    pts = [(cx + px * 2 * hw, cy + py * 2 * hh) for px, py in points]
    if len(pts) >= 3:
        d.polygon(pts, fill=fill, outline=edge)


# canonical_name -> drawer detallado (el renderer lo consulta primero)
DETAILED = {
    "cup": draw_cup,
    "table": draw_table,
    "plate": draw_plate,
}


def detailed_drawer(name: str):
    """Drawer detallado para un objeto (por su nombre canonico), o None."""
    from cognia_x.lcd.scene import canonical_name
    return DETAILED.get(canonical_name(name))
