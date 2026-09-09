# -*- coding: utf-8 -*-
"""
cognia/agent/mesa_pantalla.py
=============================
La PANTALLITA en vivo de la MESA (2026-09-08). Proceso propio que corre en el
escritorio del DUENO y muestra, a unos pocos fps, lo que hace el puntero virtual
de Cognia sobre su escritorio propio: compone las ventanas de la mesa
(`mesa.componer`) + dibuja el puntero y el pulso de clic. Ventana pequena,
siempre encima, movible, sin robar foco al escritorio del dueno.

Se lanza desde `mesa.pantalla_abrir()` con el mismo interprete y PYTHONPATH al
repo. Se cierra con la X o con `mesa.pantalla_cerrar()` (mata el pid guardado en
~/.cognia/mesa_estado.json).
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

# importar ESTE cognia (repo o instalado)
_RAIZ = str(Path(__file__).resolve().parents[2])
if _RAIZ not in sys.path:
    sys.path.insert(0, _RAIZ)

try:
    ctypes_ok = True
    import ctypes
except Exception:
    ctypes_ok = False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fps", type=float, default=6.0)
    ap.add_argument("--escala", type=float, default=0.42)
    args = ap.parse_args()

    try:
        import tkinter as tk
        from PIL import Image, ImageTk  # type: ignore
    except Exception as exc:
        print("pantallita: falta tkinter/Pillow: %s" % exc, file=sys.stderr)
        return 2

    from cognia.agent import mesa as M

    if ctypes_ok:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

    tmp_png = os.path.join(tempfile.gettempdir(), "cognia_mesa_vivo.png")

    root = tk.Tk()
    root.title("Cognia · mesa en vivo")
    root.attributes("-topmost", True)
    root.configure(bg="#12141a")
    try:
        root.attributes("-alpha", 0.97)
    except Exception:
        pass

    barra = tk.Frame(root, bg="#12141a")
    barra.pack(fill="x")
    etiqueta = tk.Label(barra, text="Cognia · mesa", fg="#7fd4ff", bg="#12141a",
                        font=("Segoe UI", 9, "bold"), anchor="w")
    etiqueta.pack(side="left", padx=8, pady=3)
    estado_lbl = tk.Label(barra, text="", fg="#8a93a6", bg="#12141a", font=("Segoe UI", 8), anchor="e")
    estado_lbl.pack(side="right", padx=8)

    lienzo = tk.Label(root, bg="#000000", text="esperando ventanas en la mesa…",
                      fg="#8a93a6", font=("Segoe UI", 10))
    lienzo.pack(fill="both", expand=True)

    # arrastrar la ventanita por su barra
    _drag = {"x": 0, "y": 0}
    def _dn(e):
        _drag["x"], _drag["y"] = e.x, e.y
    def _mv(e):
        root.geometry("+%d+%d" % (root.winfo_x() + e.x - _drag["x"], root.winfo_y() + e.y - _drag["y"]))
    for w in (barra, etiqueta):
        w.bind("<Button-1>", _dn)
        w.bind("<B1-Motion>", _mv)

    ref = {"img": None, "parar": False, "geom": False}

    def cerrar():
        ref["parar"] = True
        # solo tocar pantalla_pid: guardar_estado() desde ESTE proceso pisaria
        # el puntero/activa que escribe el proceso que mueve la mesa
        try:
            import json as _json
            est = M.cargar_estado()
            est["pantalla_pid"] = 0
            tmp = M._ESTADO.with_suffix(".json.tmp2")
            tmp.write_text(_json.dumps(est, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, M._ESTADO)
        except Exception:
            pass
        root.destroy()
    root.protocol("WM_DELETE_WINDOW", cerrar)

    intervalo = max(60, int(1000 / max(1.0, args.fps)))

    def tick():
        if ref["parar"]:
            return
        t0 = time.time()
        try:
            r = M.componer(tmp_png, escala=args.escala, con_puntero=True, recortar=True)
            im = Image.open(tmp_png).convert("RGB")
            # nunca mas ancha que el monitor del dueno (mesa vacia con 3 monitores
            # daba un lienzo de 2400 px)
            max_w = max(320, root.winfo_screenwidth() - 80)
            max_h = max(200, root.winfo_screenheight() - 120)
            if im.width > max_w or im.height > max_h:
                f = min(max_w / im.width, max_h / im.height)
                im = im.resize((max(1, int(im.width * f)), max(1, int(im.height * f))), Image.LANCZOS)
            ph = ImageTk.PhotoImage(im)
            ref["img"] = ph
            lienzo.configure(image=ph, text="")
            prev = ref.get("size")
            if prev != (im.width, im.height):
                # reajustar el tamano de la ventanita al contenido (sin saltar de sitio)
                x = root.winfo_x() if ref["geom"] else 40
                y = root.winfo_y() if ref["geom"] else 40
                root.geometry("%dx%d+%d+%d" % (im.width, im.height + 24, x, y))
                ref["size"] = (im.width, im.height)
                ref["geom"] = True
            nv = r.get("ventanas", 0)
            px = M.puntero()
            estado_lbl.configure(text="%d ventana(s) · puntero %d,%d · %.0f ms" %
                                 (nv, px[0], px[1], (time.time() - t0) * 1000))
        except Exception as exc:
            estado_lbl.configure(text="…%s" % str(exc)[:40])
        root.after(intervalo, tick)

    root.after(200, tick)
    try:
        root.mainloop()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
