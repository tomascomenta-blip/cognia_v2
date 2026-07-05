"""Regresion de la animacion de caida+rebote (cognia_x/lcd/animation.py):
dinamica real (gravedad+rebote+rotacion) + sprite RGBA + ensamblado de GIF."""
from pathlib import Path

from cognia_x.lcd.animation import (
    render_fall_gif, render_pencil_sprite, simulate_bounce,
)


def test_simulate_cae_y_rebota():
    st = simulate_bounce(frames=96, floor=0.80)
    ys = [y for y, _, _ in st]
    # arranca arriba (cielo) y en algun momento toca el suelo
    assert ys[0] < 0.2
    assert max(ys) >= 0.80 - 1e-6


def test_rebotes_decrecen_y_convergen():
    st = simulate_bounce(frames=120, floor=0.80)
    ys = [y for y, _, _ in st]
    floor = 0.80
    touches = [i for i in range(1, len(st)) if ys[i] >= floor - 1e-6 and ys[i - 1] < floor - 1e-6]
    peaks = [min(ys[touches[k]:touches[k + 1]]) for k in range(len(touches) - 1)]
    # cada rebote sube MENOS (la altura minima-y crece hacia el suelo)
    assert len(peaks) >= 2
    assert all(peaks[i] <= peaks[i + 1] + 1e-6 for i in range(len(peaks) - 1))
    # al final esta practicamente en el suelo (se asento)
    assert ys[-1] > 0.78


def test_simulate_deterministico():
    a = simulate_bounce(frames=50)
    b = simulate_bounce(frames=50)
    assert a == b


def test_hay_rotacion():
    st = simulate_bounce(frames=40)
    angles = [a for _, _, a in st]
    assert angles[0] == 0.0 and abs(angles[-1]) > 30      # tumba al caer


def test_sprite_es_rgba_con_transparencia():
    sp = render_pencil_sprite(200, 60)
    assert sp.mode == "RGBA"
    assert sp.getpixel((2, 2))[3] < 20          # esquina transparente
    # el centro es opaco y amarillento (el cuerpo del lapiz)
    r, g, b, a = sp.getpixel((sp.size[0] // 2, sp.size[1] // 2))
    assert a > 200 and r > 180 and g > 150 and b < 130


def test_render_fall_gif_produce_animacion(tmp_path):
    out = tmp_path / "caida.gif"
    render_fall_gif(str(out), W=200, H=200, frames=24)
    assert out.exists() and out.stat().st_size > 0
    from PIL import Image
    g = Image.open(out)
    assert getattr(g, "n_frames", 1) > 5        # es una animacion multi-frame
