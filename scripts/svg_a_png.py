# -*- coding: utf-8 -*-
"""Convierte los SVG de escenas_cli.py a PNG (playwright headless).

    venv312\\Scripts\\python.exe scripts\\svg_a_png.py <dir_con_svgs>

Parte del arnes de autoevaluacion visual: el orquestador (o un humano) mira
los PNG y decide si la estetica mejoro de verdad.
"""
from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    carpeta = Path(sys.argv[1])
    svgs = sorted(carpeta.glob("*.svg"))
    if not svgs:
        print("sin SVGs en", carpeta)
        return 1
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1200, "height": 900})
        for svg in svgs:
            page.goto(svg.resolve().as_uri())
            elemento = page.locator("svg").first
            destino = svg.with_suffix(".png")
            try:
                elemento.screenshot(path=str(destino))
            except Exception:
                page.screenshot(path=str(destino), full_page=True)
            print("png ->", destino)
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
