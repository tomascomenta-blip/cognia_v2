# -*- coding: utf-8 -*-
"""
cognia/agent/flow_view.py — lienzo visual de flujos estilo n8n
==============================================================
Los flujos (flows.py) son un motor + JSON; esto los hace VISIBLES como un
lienzo estilo n8n: cada nodo es una caja con su tool + args, conectados por
cables curvos (Bézier) que muestran las dependencias (wires). HTML
autocontenido (SVG), offline, sin dependencias — mismo criterio que el grafo.

Layout: niveles por orden topológico (columna = profundidad en el DAG), filas
apiladas. Suficiente para leer un flujo de un vistazo y mandar una captura.
"""
from __future__ import annotations

import html
import json


def _niveles(flujo: dict) -> dict:
    """profundidad (columna) de cada nodo por orden topológico."""
    nodos = flujo.get("nodos", [])
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
    return nivel


def build_layout(flujo: dict) -> dict:
    """Posiciones {id:{x,y}}, cajas y cables para el SVG."""
    nodos = flujo.get("nodos", [])
    nivel = _niveles(flujo)
    porcol: dict[int, int] = {}
    W, H, GAPX, GAPY, X0, Y0 = 200, 64, 90, 34, 40, 40
    pos = {}
    for n in nodos:
        c = nivel.get(n["id"], 0)
        fila = porcol.get(c, 0)
        porcol[c] = fila + 1
        pos[n["id"]] = {"x": X0 + c * (W + GAPX), "y": Y0 + fila * (H + GAPY)}
    cajas = []
    for i, n in enumerate(nodos):
        p = pos[n["id"]]
        cajas.append({"id": n["id"], "x": p["x"], "y": p["y"], "w": W, "h": H,
                      "n": i + 1, "tool": n.get("tool", ""),
                      "args": (n.get("args", "") or "")[:48]})
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
    return {"cajas": cajas, "cables": cables, "w": ancho, "h": alto}


_HTML = r"""<!doctype html><html><head><meta charset="utf-8"><title>{title}</title>
<style>
 html,body{{margin:0;background:#1a1d24;color:#c9d1d9;
   font:13px system-ui,sans-serif}}
 h1{{font-size:15px;margin:14px 18px 4px}}
 .sub{{margin:0 18px 10px;opacity:.6;font-size:12px}}
 svg{{display:block;margin:0 auto}}
 .box{{fill:#242833;stroke:#3a4150;stroke-width:1.5;rx:10}}
 .num{{fill:#7b93e0;font-weight:700;font-size:12px}}
 .tool{{fill:#e6edf3;font-weight:600;font-size:13px}}
 .args{{fill:#8b949e;font-size:11px}}
 .cable{{stroke:#4d7ad6;stroke-width:2;fill:none}}
 .dot{{fill:#4d7ad6}}
</style></head><body>
<h1>{title}</h1><p class="sub">{sub}</p>
<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}">
 <defs><marker id="a" markerWidth="9" markerHeight="9" refX="7" refY="3"
   orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#4d7ad6"/></marker></defs>
 {cables}
 {cajas}
</svg></body></html>"""


def render_html(flujo: dict, title: str = "Cognia · Flujo") -> str:
    lay = build_layout(flujo)
    cables = "".join(
        f'<path class="cable" marker-end="url(#a)" d="M{c["x1"]},{c["y1"]} '
        f'C{c["x1"]+45},{c["y1"]} {c["x2"]-45},{c["y2"]} {c["x2"]},{c["y2"]}"/>'
        f'<circle class="dot" cx="{c["x1"]}" cy="{c["y1"]}" r="3"/>'
        for c in lay["cables"])
    cajas = ""
    for b in lay["cajas"]:
        t = html.escape(b["tool"])
        a = html.escape(b["args"])
        cajas += (
            f'<g><rect class="box" x="{b["x"]}" y="{b["y"]}" width="{b["w"]}" '
            f'height="{b["h"]}" rx="10"/>'
            f'<text class="num" x="{b["x"]+12}" y="{b["y"]+24}">{b["n"]}</text>'
            f'<text class="tool" x="{b["x"]+30}" y="{b["y"]+24}">{t}</text>'
            f'<text class="args" x="{b["x"]+12}" y="{b["y"]+46}">{a}</text></g>')
    sub = f'{len(lay["cajas"])} pasos · {len(lay["cables"])} conexiones'
    return (_HTML.replace("{title}", html.escape(title)).replace("{sub}", sub)
            .replace("{w}", str(lay["w"])).replace("{h}", str(lay["h"]))
            .replace("{cables}", cables).replace("{cajas}", cajas))


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
    out = export(f, str(__import__("pathlib").Path.home() / ".cognia" / "flujo.html"))
    print(out)
