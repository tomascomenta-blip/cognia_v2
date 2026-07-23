# -*- coding: utf-8 -*-
"""Puente F4: inyecta ASSETS de imagen transparentes en las webs/juegos generados.

`generator._build_prompt_web` produce un HTML autocontenido y PROHÍBE recursos
externos (para que abra offline desde file://). Esta regla es correcta y NO se
rompe: los sprites transparentes (PNG RGBA de cognia/assets, GPU) se embeben como
**data URIs base64** — siguen siendo inline y offline-safe, pero son IMÁGENES de
verdad, no "cuadrados CSS".

Flujo (determinista donde importa):
1. El caller declara qué sprites necesita la escena: specs [{name, prompt, estilo?,
   metodo?, recortar?}]. `preparar_assets` los genera (cognia.assets) y los codifica.
2. `build_prompt_web_con_assets` arma el prompt: el modelo referencia cada sprite con
   `<img data-asset="NAME">` (NO tiene que escribir base64, solo el nombre).
3. `inyectar_assets` mete en el HTML el objeto global `ASSETS` (name -> data URI) y un
   cableado que rellena el `src` de todo `[data-asset]` — así, aunque el modelo solo
   escriba `<img data-asset="girasol">`, el sprite aparece. Robusto al modelo chico.

Los imports de cognia.assets (torch/diffusers) son perezosos (dentro de las
funciones): importar este módulo en un nodo CPU no arrastra la GPU.
"""
from __future__ import annotations

import base64
import json
import re
from pathlib import Path


def asset_a_datauri(ruta_png) -> str:
    """Lee un PNG y devuelve su data URI base64 (image/png)."""
    datos = Path(ruta_png).read_bytes()
    b64 = base64.b64encode(datos).decode("ascii")
    return f"data:image/png;base64,{b64}"


def preparar_assets(specs: list, **kw) -> dict:
    """Genera los sprites declarados y devuelve {name: data_uri}.

    specs: lista de dicts {name, prompt, estilo?, metodo?, recortar?, seed?, ...}.
           Cada campo extra (pasos, ancho, alto...) se reenvía a generar_transparente.
    kw: overrides comunes a todos (p.ej. recortar=True, pasos=25).
    GPU (cognia.assets). Lanza si el backend no está disponible."""
    from cognia.assets import generar_transparente
    out = {}
    for spec in specs:
        name = spec["name"]
        params = {k: v for k, v in spec.items() if k != "name"}
        params = {**kw, **params}  # el spec puntual gana sobre los comunes
        ruta = generar_transparente(spec["prompt"], **{
            k: v for k, v in params.items() if k != "prompt"})
        out[name] = asset_a_datauri(ruta)
    return out


def _bloque_assets_disponibles(specs: list) -> str:
    """Lista legible de sprites disponibles para el prompt del modelo."""
    lineas = []
    for s in specs:
        desc = s.get("desc") or s["prompt"]
        lineas.append(f'  - data-asset="{s["name"]}": {desc}')
    return "\n".join(lineas)


def build_prompt_web_con_assets(category: str, specs: list,
                                extra_hint: str = "") -> str:
    """Como generator._build_prompt_web pero PERMITE (y exige) usar los sprites
    transparentes provistos, vía <img data-asset="NAME">. Mantiene la regla de
    'autocontenido / sin recursos externos' (los assets van embebidos aparte)."""
    from cognia.program_creator.generator import _componentes_de_idea
    componentes = "".join(
        f"- REQUIRED component {i}: {c}\n"
        for i, c in enumerate(_componentes_de_idea(category), start=1))
    return (
        f"You are a creative front-end developer making a self-contained, "
        f"animated web page/game for: **{category}**\n\n"
        f"You are given ready-made TRANSPARENT PNG sprites. Use them as real images "
        f"— NOT CSS boxes, NOT emoji. Reference a sprite with an <img> whose "
        f'data-asset attribute is its name, e.g. <img data-asset="hero" '
        f'class="sprite" alt="hero">. Do NOT write the image data yourself and do '
        f"NOT set src — the runtime fills src from the sprite library by name.\n\n"
        f"Available sprites:\n{_bloque_assets_disponibles(specs)}\n\n"
        f"CRITICAL RULES — all must be followed:\n"
        f"- ONE single self-contained .html file; inline <style> and <script>.\n"
        f"- NO external resources: no CDN, no remote images/fonts, no fetch(). "
        f"It must work fully offline. (The sprites are embedded for you.)\n"
        f"- Use EVERY sprite listed above at least once, as <img data-asset=...>.\n"
        f"- Position/scale sprites with CSS; give them transparent backgrounds "
        f"(they already are). Animate them (CSS transitions/keyframes or JS "
        f"updating style.left/top/transform) — the scene must move on its own.\n"
        f"- Render a complete first frame IMMEDIATELY on load.\n"
        f"- Responsive and legible on a phone screen.\n"
        f"- Write ALL visible text in the SAME language as the topic above.\n"
        f"{componentes}"
        f"- Implement EVERY required component. Prefer a LONGER page over an "
        f"incomplete one; there is no size limit.\n"
        f"- {extra_hint}\n\n"
        f"Respond EXACTLY in this format:\n\n"
        f"Title: <short title>\n"
        f"Description: <one sentence>\n"
        f"HTML Code:\n```html\n<!DOCTYPE html>\n<complete working page>\n```"
    )


# Cableado que rellena el src de cada [data-asset] desde ASSETS. Idempotente y
# tolerante: si falta un sprite, deja el <img> sin romper la página.
_WIRING = (
    "\n(function(){function wire(){var A=window.ASSETS||{};"
    "document.querySelectorAll('[data-asset]').forEach(function(el){"
    "var k=el.getAttribute('data-asset');if(A[k]){el.src=A[k];"
    "el.style.backgroundColor='transparent';}});}"
    "if(document.readyState!=='loading')wire();"
    "else document.addEventListener('DOMContentLoaded',wire);}());\n"
)


def inyectar_assets(html: str, assets: dict) -> str:
    """Inyecta en el HTML el objeto global ASSETS (name -> data URI) al inicio del
    <head> y el cableado de src al final del <body>. Devuelve el HTML resultante.

    Determinista y puro (sin GPU): testeable en CPU."""
    lib = "<script>window.ASSETS=" + json.dumps(assets) + ";</script>"
    wire = "<script>" + _WIRING + "</script>"

    # ASSETS temprano: justo tras <head ...> (o tras <html>, o al principio).
    m = re.search(r"<head[^>]*>", html, re.IGNORECASE)
    if m:
        html = html[:m.end()] + lib + html[m.end():]
    else:
        mh = re.search(r"<html[^>]*>", html, re.IGNORECASE)
        if mh:
            html = html[:mh.end()] + lib + html[mh.end():]
        else:
            html = lib + html

    # cableado al final: justo antes de </body> (o al final del documento).
    mb = re.search(r"</body\s*>", html, re.IGNORECASE)
    if mb:
        html = html[:mb.start()] + wire + html[mb.start():]
    else:
        html = html + wire
    return html


def generar_web_con_assets(category: str, specs: list, llm, *,
                           extra_hint: str = "", gen_kw: dict = None):
    """E2E: genera los sprites, pide la página al LLM y embebe los sprites.

    llm: LlmFn (prompt, system, max_tokens, temperature) -> str|None (backend real).
    Devuelve dict {html, assets, title, description} o None si el LLM no respondió.
    """
    from cognia.program_creator.generator import _SISTEMA_WEB, _parse_response
    assets = preparar_assets(specs, **(gen_kw or {}))
    prompt = build_prompt_web_con_assets(category, specs, extra_hint)
    raw = llm(prompt, _SISTEMA_WEB, 6000, 0.9)
    prog = _parse_response(raw, category, lenguaje="html")
    if prog is None:
        return None
    html = inyectar_assets(prog.code, assets)
    return {"html": html, "assets": assets,
            "title": prog.title, "description": prog.description}
