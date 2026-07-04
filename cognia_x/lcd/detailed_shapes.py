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


def draw_cup(d, cx, cy, hw, hh, color, shade, img=None):
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


def draw_table(d, cx, cy, hw, hh, color, shade, img=None):
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


def draw_plate(d, cx, cy, hw, hh, color, shade, img=None):
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


def draw_pencil(d, cx, cy, hw, hh, color, shade, img=None):
    """Lapiz HORIZONTAL foto-realista (izq->der): goma + virola metalica con
    bandas + cuerpo pintado (barril hexagonal, gradiente cilindrico + brillo) +
    cono de madera afilada + punta de grafito. color = color del cuerpo pintado
    (default amarillo si es gris). Usa gradientes de shading.py si hay img."""
    from PIL import Image, ImageDraw, ImageFilter

    from cognia_x.lcd.shading import (cylinder_gradient, paste_shaded,
                                       specular_streak)
    body_col = color if color != (150, 150, 150) else (240, 195, 40)  # amarillo lapiz

    x0, x1 = cx - hw, cx + hw
    W = x1 - x0
    top, bot = cy - hh, cy + hh
    H = bot - top

    def seg(a, b):
        return int(x0 + W * a), int(x0 + W * b)

    # segmentos a lo largo del lapiz (fracciones del largo)
    er0, er1 = seg(0.00, 0.055)     # goma
    fe0, fe1 = seg(0.055, 0.135)    # virola metalica
    bo0, bo1 = seg(0.135, 0.82)     # cuerpo pintado
    wo0, wo1 = seg(0.82, 0.965)     # cono de madera (mas largo)
    gr0, gr1 = seg(0.955, 1.00)     # grafito (solo la puntita)
    ty0, ty1 = int(top), int(bot)

    # --- SOMBRA PROYECTADA (aterriza el objeto): elipse oscura difuminada ---
    if img is not None:
        sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
        sd = ImageDraw.Draw(sh)
        sy = int(bot + H * 0.35)
        sd.ellipse([int(x0 + W * 0.02), sy - int(H * 0.30),
                    int(x1 - W * 0.04), sy + int(H * 0.30)], fill=(30, 30, 40, 90))
        sh = sh.filter(ImageFilter.GaussianBlur(max(2, int(H * 0.18))))
        img.paste(sh, (0, 0), sh)

    # helper: pegar gradiente cilindrico (eje horizontal -> sombreado vertical)
    def cyl(a, b, col, lit=0.34, light=1.25, shadow=0.5):
        if img is None or b <= a:
            d.rectangle([a, ty0, b, ty1], fill=shade(col, 1.0))
            return
        patch = cylinder_gradient(col, b - a, H, axis="y", lit=lit,
                                  light=light, shadow=shadow)
        paste_shaded(img, patch, a, ty0)

    # --- goma (rosa, con casquete redondeado) ---
    eraser = (230, 130, 140)
    cyl(er0, er1, eraser, lit=0.30, light=1.2, shadow=0.6)
    d.pieslice([er0 - (er1 - er0), ty0, er0 + (er1 - er0), ty1], 90, 270,
               fill=shade(eraser, 1.05))

    # --- virola metalica (gris, gradiente + 2 bandas oscuras) ---
    metal = (170, 172, 178)
    cyl(fe0, fe1, metal, lit=0.28, light=1.45, shadow=0.45)
    for bx in (fe0 + (fe1 - fe0) * 0.30, fe0 + (fe1 - fe0) * 0.62):
        d.line([(bx, ty0), (bx, ty1)], fill=shade(metal, 0.55),
               width=max(1, int(H * 0.06)))

    # --- cuerpo pintado (barril hexagonal: gradiente + facetas + brillo) ---
    cyl(bo0, bo1, body_col, lit=0.33, light=1.22, shadow=0.52)
    # facetas del hexagono: 2 lineas sutiles que insinuan las caras
    d.line([(bo0, cy - hh * 0.34), (bo1, cy - hh * 0.34)],
           fill=shade(body_col, 0.82), width=max(1, int(H * 0.04)))
    d.line([(bo0, cy + hh * 0.34), (bo1, cy + hh * 0.34)],
           fill=shade(body_col, 0.7), width=max(1, int(H * 0.04)))
    if img is not None:
        # specular en DOS capas (research): highlight base ancho + clearcoat nitido
        paste_shaded(img, specular_streak(bo1 - bo0, H, pos=0.28, width=0.09,
                     strength=110, axis="y"), bo0, ty0)
        paste_shaded(img, specular_streak(bo1 - bo0, H, pos=0.22, width=0.028,
                     strength=190, axis="y"), bo0, ty0)
        # rim light en el borde superior (separa la figura del fondo, Fresnel-fake)
        paste_shaded(img, specular_streak(bo1 - bo0, H, pos=0.04, width=0.02,
                     strength=90, axis="y"), bo0, ty0)

    # --- cono de madera afilada (tan, con las facetas del sacapuntas) ---
    wood = (222, 184, 130)
    gpt = (gr1, cy)                                  # la punta exacta
    d.polygon([(wo0, ty0 + H * 0.06), (wo0, ty1 - H * 0.06), gpt],
              fill=shade(wood, 1.06), outline=shade(wood, 0.72))
    # mitad inferior en sombra (volumen del cono)
    d.polygon([(wo0, cy), (wo0, ty1 - H * 0.06), gpt], fill=shade(wood, 0.86))
    # facetas talladas por el sacapuntas (lineas del vertice a la base)
    for gy in (ty0 + H * 0.18, cy, ty1 - H * 0.18):
        d.line([(wo0, gy), gpt], fill=shade(wood, 0.66), width=1)
    # GRANO de madera (research: Noise a lo largo del eje): vetas finas onduladas
    import math as _m
    for k in range(6):
        gy0 = ty0 + H * (0.10 + 0.13 * k)
        pts = [(wo0 + (gr1 - wo0) * t / 8,
                gy0 + _m.sin(t * 1.3 + k) * H * 0.02 - (gy0 - cy) * (t / 8) * 0.85)
               for t in range(9)]
        d.line(pts, fill=shade(wood, 0.78 if k % 2 else 0.88), width=1)

    # --- punta de grafito (cono corto oscuro, solo la puntita, con reflejo) ---
    graph = (52, 52, 58)
    d.polygon([(gr0, cy - hh * 0.22), (gr0, cy + hh * 0.22), gpt],
              fill=graph, outline=(28, 28, 32))
    d.polygon([(gr0, cy - hh * 0.22), (gr0, cy), gpt], fill=(92, 92, 102))  # cara lit
    d.line([(gr0, cy - hh * 0.06), (gr1 - (gr1 - gr0) * 0.35, cy - hh * 0.015)],
           fill=(150, 150, 162), width=1)   # reflejo especular en el grafito

    # --- AMBIENT OCCLUSION en las uniones (research: la tecnica mas barata para
    # 'objeto real'): oscurecer las costuras goma|virola|cuerpo|madera ---
    if img is not None:
        ao = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ad = ImageDraw.Draw(ao)
        for jx in (fe0, bo0, wo0):
            ad.rectangle([jx - max(1, int(H * 0.05)), ty0, jx + max(1, int(H * 0.05)), ty1],
                         fill=(20, 15, 10, 70))
        ao = ao.filter(ImageFilter.GaussianBlur(max(1, int(H * 0.06))))
        img.paste(ao, (0, 0), ao)

        # --- GRANO procedural (research: Noise para micro-textura/imperfeccion):
        # ruido fino determinista (seed fija) modulando el brillo dentro del
        # lapiz. Sube la entropia de alta frecuencia hacia lo fotografico sin
        # deformar la figura. Enmascarado a la bbox del cuerpo+madera.
        import numpy as _np
        rng = _np.random.default_rng(7)
        gx0, gx1 = int(er0), int(gr1)
        gw, gh = max(1, gx1 - gx0), max(1, ty1 - ty0)
        noise = rng.normal(0, 10, size=(gh, gw))          # +-10 niveles
        arr = _np.asarray(img).astype(_np.float32).copy()
        reg = arr[ty0:ty0 + gh, gx0:gx0 + gw, :3]
        # aplicar solo donde el pixel NO es fondo (dif. con el background)
        bg = _np.array(img.getpixel((2, 2))[:3], dtype=_np.float32)
        mask = (_np.abs(reg - bg).sum(axis=2) > 40)[:, :, None]
        reg += noise[:, :, None] * mask
        arr[ty0:ty0 + gh, gx0:gx0 + gw, :3] = _np.clip(reg, 0, 255)
        img.paste(Image.fromarray(arr.astype("uint8"), "RGB"), (0, 0))


# canonical_name -> drawer detallado (el renderer lo consulta primero)
DETAILED = {
    "cup": draw_cup,
    "table": draw_table,
    "plate": draw_plate,
    "pencil": draw_pencil,
    "lapiz": draw_pencil,
}


def detailed_drawer(name: str):
    """Drawer detallado para un objeto (por su nombre canonico), o None."""
    from cognia_x.lcd.scene import canonical_name
    return DETAILED.get(canonical_name(name))
