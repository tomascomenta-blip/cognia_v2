# -*- coding: utf-8 -*-
"""
dsh_render_html.py — rasteriza un HTML local a PNG con Chromium.

PARA QUE: cuando el agente entrega una pagina, "el fichero existe y tiene
estilos" no dice si la pagina se VE bien. Esto la abre en un navegador de
verdad y guarda la captura, que es la unica forma honesta de juzgar el
resultado visual de una tarea de front-end.

Uso:
    python scripts/dsh_render_html.py index.html --salida pagina.png [--ancho 1200]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("html", help="fichero .html a renderizar")
    ap.add_argument("--salida", required=True)
    ap.add_argument("--ancho", type=int, default=1200)
    ap.add_argument("--alto", type=int, default=900)
    ap.add_argument("--completa", action="store_true",
                    help="captura la pagina entera, no solo lo visible")
    args = ap.parse_args()

    ruta = Path(args.html).resolve()
    if not ruta.is_file():
        print(f"no existe {ruta}", file=sys.stderr)
        return 2
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        print(f"playwright no disponible: {exc}", file=sys.stderr)
        return 1

    destino = Path(args.salida).resolve()
    destino.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        navegador = p.chromium.launch()
        pagina = navegador.new_page(viewport={"width": args.ancho,
                                              "height": args.alto},
                                    device_scale_factor=2)
        pagina.goto(ruta.as_uri())
        # Un respiro para fuentes y animaciones de entrada: sin esto se
        # capturan paginas a medio pintar y el juicio visual es sobre otra cosa.
        pagina.wait_for_timeout(1200)
        pagina.screenshot(path=str(destino), full_page=args.completa)
        navegador.close()
    print(f"PNG: {destino} ({destino.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
