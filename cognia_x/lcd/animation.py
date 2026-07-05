"""
cognia_x/lcd/animation.py — ANIMACION: dinamica de caida + rebote de un objeto
LCD, renderizada cuadro a cuadro a un GIF. Determinista, CPU, sin GPU.

A diferencia de physics.settle() (resuelve un estado de REPOSO), aca hay
DINAMICA real en el tiempo: posicion + velocidad + gravedad + rebote con
coeficiente de restitucion (la altura de cada rebote decrece), y rotacion
(el objeto tumba al caer y cambia el giro en cada golpe). Coords y en [0,1]
(0=arriba/cielo, 1=abajo/suelo), consistente con scene.py.

Dos piezas:
  - simulate_bounce(...): lista de estados (y, vy, angle) por frame.
  - render_fall_gif(...): renderiza el sprite del lapiz rotado en cada estado
    sobre un fondo de cielo, con sombra de contacto que se ajusta con la altura,
    y guarda el GIF.
"""
from __future__ import annotations

import math

from PIL import Image, ImageDraw, ImageFilter


def simulate_bounce(frames=60, y0=0.06, floor=0.80, gravity=0.0042,
                    restitution=0.68, ang_vel0=7.0, dt=1.0) -> list:
    """Dinamica de caida + rebote. Devuelve [(y, vy, angle)] por frame.

    y0=altura inicial (arriba=cielo); floor=y del centro cuando toca el suelo;
    gravity=aceleracion por frame^2; restitution=fraccion de velocidad que
    conserva cada rebote (0.72 = rebotes decrecientes que convergen); ang_vel0=
    giro inicial (grados/frame), que decae y se invierte un poco en cada golpe."""
    y, vy = y0, 0.0
    angle, vang = 0.0, ang_vel0
    out = []
    for _ in range(frames):
        out.append((y, vy, angle))
        vy += gravity * dt
        y += vy * dt
        angle += vang * dt
        if y >= floor:                       # golpe con el suelo
            y = floor
            if vy > 0:
                vy = -vy * restitution       # rebota (pierde energia)
                # el giro pierde energia y afloja en cada bote (friccion del piso)
                vang = -vang * 0.55
            if abs(vy) < gravity * 2:        # ya casi no rebota -> se asienta
                vy = 0.0
                vang *= 0.6
    return out


def render_pencil_sprite(w_px, h_px, color=(240, 195, 40), scale=3) -> Image.Image:
    """Sprite RGBA del lapiz (transparente, SIN sombra de suelo), para rotarlo y
    pegarlo por frame. Renderiza a scale x y baja con LANCZOS (anti-aliasing)."""
    from cognia_x.lcd.detailed_shapes import draw_pencil

    W, H = int(w_px * scale), int(h_px * scale)
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def _shade(c, f):
        return tuple(max(0, min(255, int(v * f))) for v in c)

    # el lapiz ocupa casi todo el sprite, centrado (margen para el asa/punta)
    draw_pencil(d, W / 2, H / 2, W * 0.46, H * 0.34, color, _shade, img=img,
                shadow=False)
    return img.resize((int(w_px), int(h_px)), Image.LANCZOS)


def _sky(w, h) -> Image.Image:
    """Fondo de CIELO: gradiente vertical celeste (arriba mas claro) + suelo."""
    import numpy as np
    top = np.array([150, 200, 245], dtype=np.float32)
    bot = np.array([205, 230, 250], dtype=np.float32)
    t = np.linspace(0, 1, h)[:, None]
    col = (top[None, :] * (1 - t) + bot[None, :] * t).astype(np.uint8)
    arr = np.repeat(col[:, None, :], w, axis=1)
    img = Image.fromarray(arr, "RGB")
    d = ImageDraw.Draw(img)
    floor_y = int(h * 0.86)
    d.rectangle([0, floor_y, w, h], fill=(225, 220, 210))     # piso
    d.line([(0, floor_y), (w, floor_y)], fill=(200, 194, 182), width=2)
    return img


def render_fall_gif(out_path, W=420, H=420, frames=60, color=(240, 195, 40),
                    duration=45) -> str:
    """Renderiza el GIF del lapiz cayendo del cielo y rebotando. Devuelve la ruta.

    duration = ms por frame. El sprite se rota por su angulo y se pega en la
    posicion y(t); la sombra de contacto se hace mas chica/nitida cuando el lapiz
    esta cerca del suelo (mas lejos = mas grande y difusa)."""
    sprite = render_pencil_sprite(int(W * 0.60), int(H * 0.16), color=color)
    floor_frac = 0.80
    states = simulate_bounce(frames=frames, floor=floor_frac)
    sky = _sky(W, H)
    floor_px = int(H * 0.86)
    sw, sh = sprite.size

    imgs = []
    for (y, vy, angle) in states:
        fr = sky.copy()
        cx, cy = W // 2, int(y * H)
        # sombra de contacto: mas chica y oscura cuando esta cerca del suelo
        prox = max(0.0, min(1.0, (y) / floor_frac))     # 0 arriba, 1 en el suelo
        shw = int(sw * (0.55 + 0.35 * prox))
        shh = max(3, int(sh * (0.5 + 0.5 * prox)))
        alpha = int(40 + 90 * prox)
        sh_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(sh_layer).ellipse(
            [cx - shw // 2, floor_px - shh // 2, cx + shw // 2, floor_px + shh // 2],
            fill=(40, 35, 30, alpha))
        sh_layer = sh_layer.filter(ImageFilter.GaussianBlur(6 + int(10 * (1 - prox))))
        fr.paste(sh_layer, (0, 0), sh_layer)
        # sprite rotado
        rot = sprite.rotate(angle, expand=True, resample=Image.BICUBIC)
        rw, rh = rot.size
        fr.paste(rot, (cx - rw // 2, cy - rh // 2), rot)
        imgs.append(fr.convert("P", palette=Image.ADAPTIVE))

    imgs[0].save(out_path, save_all=True, append_images=imgs[1:],
                 duration=duration, loop=0, optimize=True)
    return str(out_path)
