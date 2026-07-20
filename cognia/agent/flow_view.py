# -*- coding: utf-8 -*-
"""
cognia/agent/flow_view.py — lienzo visual de flujos estilo n8n
==============================================================
Los flujos (flows.py) son motor + JSON; esto los hace VISIBLES como un lienzo
estilo n8n. Mandato del dueño (2026-07-13): que NO sean cajas negras planas —
cada nodo tiene INTERIOR NEGRO y FONT BLANCO, con el BORDE de color según el
MODELO que Cognia recomienda para ese paso (o un color elegido por el usuario).
Así el flujo queda "dividido por modelos" de un vistazo.

HTML/SVG autocontenido, offline, sin dependencias. Placeholders con
.replace() — SIN llaves dobles (bug histórico del graph_view: {{ }} de
str.format renderizadas con replace dejaban el CSS/JS rotos).
"""
from __future__ import annotations

import html
import json


def _color_modelo(key: str | None, override: str | None = None) -> tuple[str, str]:
    """(color_borde, nombre_modelo) para un nodo. override gana; si no, el
    color de identidad del modelo recomendado; default gris."""
    if override:
        return override, ""
    try:
        from cognia.oficina.identidad import identidad
        ide = identidad(key or "")
        return ide["color"], ide["nombre"]
    except Exception:
        return "#8A8F98", ""


def build_layout(flujo: dict) -> dict:
    """Posiciones {id:{x,y}}, cajas (con color de modelo) y cables."""
    nodos = flujo.get("nodos", [])
    # profundidad topológica -> columna
    hijos = {n["id"]: list(n.get("wires") or []) for n in nodos}
    padres: dict[str, list] = {n["id"]: [] for n in nodos}
    for i, ws in hijos.items():
        for w in ws:
            if w in padres:
                padres[w].append(i)
    nivel: dict[str, int] = {}

    def prof(nid, visto=None):
        if nid in nivel:
            return nivel[nid]
        visto = visto or set()
        if nid in visto:
            return 0
        visto.add(nid)
        p = padres.get(nid, [])
        nivel[nid] = 0 if not p else 1 + max(prof(x, visto) for x in p)
        return nivel[nid]
    for n in nodos:
        prof(n["id"])

    W, H, GAPX, GAPY, X0, Y0 = 210, 66, 96, 34, 40, 56
    porcol: dict[int, int] = {}
    pos = {}
    for n in nodos:
        c = nivel.get(n["id"], 0)
        fila = porcol.get(c, 0)
        porcol[c] = fila + 1
        pos[n["id"]] = {"x": X0 + c * (W + GAPX), "y": Y0 + fila * (H + GAPY)}
    cajas, modelos = [], {}
    for i, n in enumerate(nodos):
        p = pos[n["id"]]
        color, nombre = _color_modelo(n.get("modelo"), n.get("color"))
        if nombre:
            modelos[nombre] = color
        cajas.append({"id": n["id"], "x": p["x"], "y": p["y"], "w": W, "h": H,
                      "n": i + 1, "tool": n.get("tool", ""),
                      "args": (n.get("args", "") or "")[:46],
                      "color": color, "modelo": nombre})
    cables = []
    for n in nodos:
        a = pos[n["id"]]
        for w in (n.get("wires") or []):
            if w in pos:
                b = pos[w]
                cables.append({"x1": a["x"] + W, "y1": a["y"] + H / 2,
                               "x2": b["x"], "y2": b["y"] + H / 2})
    ancho = max((c["x"] + W for c in cajas), default=400) + 40
    alto = max((c["y"] + H for c in cajas), default=200) + 40
    return {"cajas": cajas, "cables": cables, "w": ancho, "h": alto,
            "modelos": modelos}


_HTML = r"""<!doctype html><html><head><meta charset="utf-8"><title>__TITLE__</title>
<style>
 html,body{margin:0;background:#12141a;color:#e6edf3;
   font:13px system-ui,sans-serif}
 h1{font-size:16px;margin:16px 20px 2px}
 .sub{margin:0 20px 6px;opacity:.6;font-size:12px}
 .leg{margin:0 20px 12px;font-size:12px}
 .leg span{display:inline-flex;align-items:center;margin:2px 12px 2px 0}
 .leg i{width:11px;height:11px;border-radius:3px;margin-right:5px;
   border:2px solid;display:inline-block}
 svg{display:block;margin:0 auto;max-width:100%}
 .box{fill:#0b0d11;stroke-width:3;rx:11}
 .num{fill:#9fb4e6;font-weight:700;font-size:12px}
 .tool{fill:#ffffff;font-weight:600;font-size:13.5px}
 .args{fill:#c9d1d9;font-size:11px}
 .mdl{font-weight:700;font-size:10.5px}
 .cable{stroke:#556;stroke-width:2.5;fill:none}
</style></head><body>
<h1>__TITLE__</h1><p class="sub">__SUB__</p>
<div class="leg">__LEG__</div>
<svg width="__W__" height="__H__" viewBox="0 0 __W__ __H__">
 <defs><marker id="a" markerWidth="10" markerHeight="10" refX="8" refY="3"
   orient="auto"><path d="M0,0 L8,3 L0,6 Z" fill="#8899bb"/></marker></defs>
 __CABLES__
 __CAJAS__
</svg></body></html>"""


def render_html(flujo: dict, title: str = "Cognia · Flujo") -> str:
    lay = build_layout(flujo)
    cables = "".join(
        f'<path class="cable" marker-end="url(#a)" d="M{c["x1"]},{c["y1"]} '
        f'C{c["x1"]+48},{c["y1"]} {c["x2"]-48},{c["y2"]} {c["x2"]},{c["y2"]}"/>'
        f'<circle cx="{c["x1"]}" cy="{c["y1"]}" r="3.5" fill="#8899bb"/>'
        for c in lay["cables"])
    cajas = ""
    for b in lay["cajas"]:
        t = html.escape(b["tool"])
        a = html.escape(b["args"])
        mdl = html.escape(b["modelo"] or "")
        cajas += (
            f'<g><rect class="box" x="{b["x"]}" y="{b["y"]}" width="{b["w"]}" '
            f'height="{b["h"]}" rx="11" style="stroke:{b["color"]}"/>'
            f'<text class="num" x="{b["x"]+13}" y="{b["y"]+25}">{b["n"]}</text>'
            f'<text class="tool" x="{b["x"]+31}" y="{b["y"]+25}">{t}</text>'
            f'<text class="args" x="{b["x"]+13}" y="{b["y"]+45}">{a}</text>'
            f'<text class="mdl" x="{b["x"]+13}" y="{b["y"]+60}" '
            f'style="fill:{b["color"]}">{mdl}</text></g>')
    leg = "".join(
        f'<span><i style="border-color:{col}"></i>{html.escape(nom)}</span>'
        for nom, col in lay["modelos"].items())
    sub = f'{len(lay["cajas"])} pasos · {len(lay["cables"])} conexiones · borde = modelo recomendado'
    return (_HTML.replace("__TITLE__", html.escape(title))
            .replace("__SUB__", sub).replace("__LEG__", leg)
            .replace("__W__", str(lay["w"])).replace("__H__", str(lay["h"]))
            .replace("__CABLES__", cables).replace("__CAJAS__", cajas))


def export(flujo: dict, path: str, title: str = "Cognia · Flujo") -> str:
    from pathlib import Path
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(render_html(flujo, title), encoding="utf-8")
    return str(p)


if __name__ == "__main__":
    import sys
    from cognia.agent.flows import organizar_flujo
    texto = sys.argv[1] if len(sys.argv) > 1 else "analizar el proyecto y escribir un informe"
    f = organizar_flujo(texto)
    from pathlib import Path
    print(export(f, str(Path.home() / ".cognia" / "flujo.html")))
