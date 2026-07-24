# -*- coding: utf-8 -*-
"""
mockup.py — el cerebro IMAGINA el producto y el modelo de imagenes lo DIBUJA.

POR QUE EXISTE (pedido del dueno): antes de construir la pagina, el cerebro se
imagina como deberia verse el producto final (un dashboard, un juego, una
landing...) y esa VISION se convierte en el objetivo contra el que el arbitro
visual (arbitro_visual.py) evalua la pagina construida. El modelo de imagenes
puede proponer algo graficamente mas llamativo que lo que el coder inventa desde
cero; el cerebro luego trabaja para que la pagina se PAREZCA a esa vision.

Dos salidas, ambas utiles al arbitro:
  - un BRIEF en palabras (layout, paleta, jerarquia, elementos clave). Sirve como
    `vision_texto` del arbitro aunque no haya GPU de imagen.
  - un MOCKUP en PNG (opcional, GPU). Es la IMAGEN objetivo que el arbitro compara
    contra el screenshot real.

Degrada con gracia: sin LLM, el brief cae a la idea cruda; sin backend de imagen
(o COGNIA_ASSETS=0), generar_mockup devuelve None y el lazo sigue con solo el
brief de texto. Nunca lanza hacia el llamador.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Callable, Dict, Optional

from ..llm_local import generar

logger = logging.getLogger(__name__)

# Firma del backend inyectable, igual que en generator.py:
#   (prompt, system, max_tokens, temperature) -> texto|None
LlmFn = Callable[[str, str, int, float], Optional[str]]

_SISTEMA_VISION = (
    "You are a senior product designer. Given a product idea, you imagine how the "
    "finished thing should LOOK and describe it concretely: overall layout and "
    "regions, visual hierarchy, color palette and mood, typography, and the key "
    "on-screen elements. You are concrete and visual, never vague."
)

_PLANTILLA_VISION = """Product idea: "{idea}"

Imagine the finished product and describe how it should look. Answer EXACTLY in
this format, nothing else:

BRIEF: <2-4 sentences: layout & regions, visual hierarchy, palette/mood, key elements>
IMAGEN: <one short comma-separated prompt for an image generator that captures
that look — style, layout, colors, mood; no text labels, no words in the image>
"""

# Sufijo que empuja a SDXL hacia un mockup de interfaz (no una foto ni un objeto
# aislado). "no text" porque SDXL escribe texto ilegible que ensucia el mockup y
# confunde al arbitro; el arbitro juzga estructura/paleta, no palabras.
_SUFIJO_MOCKUP = (", ui design mockup, web interface, clean layout, flat design, "
                  "high quality, no text, no words, no lettering")


def _parsear_vision(texto: str) -> Optional[Dict]:
    """Extrae BRIEF e IMAGEN. Tolerante a caja, idioma y a bloques <think>."""
    try:
        if "</think>" in texto:
            texto = texto.split("</think>", 1)[1]
        brief, imagen = "", ""
        for linea in texto.splitlines():
            s = linea.strip()
            low = s.lower()
            if low.startswith("brief:"):
                brief = s.split(":", 1)[1].strip()
            elif low.startswith(("imagen:", "image:")):
                imagen = s.split(":", 1)[1].strip()
        if not brief and not imagen:
            return None
        return {"brief": brief, "prompt_imagen": imagen}
    except Exception:
        return None


def imaginar_vision(idea: str, llm: Optional[LlmFn] = None) -> Dict:
    """El cerebro imagina el producto. Devuelve
    {"brief": str, "prompt_imagen": str}. NUNCA lanza: sin LLM o sin respuesta
    parseable, cae a la idea cruda (el lazo sigue funcionando)."""
    fallback = {"brief": (idea or "").strip(),
                "prompt_imagen": (idea or "").strip()}
    try:
        prompt = _PLANTILLA_VISION.format(idea=(idea or "")[:400])
        raw = None
        if llm is not None:
            try:
                raw = llm(prompt, _SISTEMA_VISION, 400, 0.7)
            except Exception as e:
                logger.warning("mockup: backend inyectado fallo (%s)", e)
        if not raw:
            raw = generar(prompt, system=_SISTEMA_VISION,
                          temperature=0.7, max_tokens=400)
        if not raw:
            return fallback
        parsed = _parsear_vision(raw)
        if parsed is None:
            return fallback
        # Rellenar huecos con la idea para no dejar campos vacios.
        parsed["brief"] = parsed["brief"] or fallback["brief"]
        parsed["prompt_imagen"] = parsed["prompt_imagen"] or parsed["brief"]
        return parsed
    except Exception as e:
        logger.warning("mockup: imaginar_vision fallo (%s)", e)
        return fallback


def _componer_sobre_blanco(ruta_rgba: str, salida: str) -> str:
    """El pipeline de imagen (LayerDiffuse) devuelve RGBA; un mockup se juzga
    opaco. Se compone sobre blanco y se guarda opaco. Devuelve la ruta final."""
    from PIL import Image
    img = Image.open(ruta_rgba).convert("RGBA")
    fondo = Image.new("RGBA", img.size, (255, 255, 255, 255))
    fondo.alpha_composite(img)
    fondo.convert("RGB").save(salida)
    return salida


def generar_mockup(descripcion: str, *, salida: str = None,
                   ancho: int = 1024, alto: int = 768, pasos: int = 28,
                   seed: int = 7) -> Optional[str]:
    """Dibuja el mockup del producto con el modelo de imagenes. Devuelve la ruta
    del PNG opaco, o None si el backend de imagen no esta disponible (el lazo
    sigue con el brief de texto). NUNCA lanza.

    descripcion: el `prompt_imagen` de imaginar_vision (o la idea cruda).
    """
    try:
        from cognia.assets import backend_disponible, generar_transparente
    except Exception as e:
        logger.warning("mockup: no pude importar cognia.assets (%s)", e)
        return None

    try:
        ok, motivo = backend_disponible()
        if not ok:
            logger.info("mockup: backend de imagen no disponible (%s)", motivo)
            return None

        prompt = (descripcion or "").strip() + _SUFIJO_MOCKUP
        if salida is None:
            base = Path(os.environ.get(
                "COGNIA_ASSETS_OUT",
                str(Path.home() / ".cognia" / "assets")))
            base.mkdir(parents=True, exist_ok=True)
            h = abs(hash((descripcion, seed, ancho, alto))) % (10 ** 10)
            salida = str(base / f"mockup_{h}.png")

        # asset=False: nada de "isolated single object" — queremos una escena de
        # interfaz completa, no un sprite recortado. metodo='layerdiffuse' evita
        # el rescate BiRefNet (no hay fondo que quitar en un mockup).
        rgba = generar_transparente(
            prompt, asset=False, recortar=False, metodo="layerdiffuse",
            ancho=ancho, alto=alto, pasos=pasos, seed=seed,
            salida=salida + ".rgba.png")
        final = _componer_sobre_blanco(rgba, salida)
        try:
            os.remove(rgba)
        except OSError:
            pass
        return final
    except Exception as e:
        logger.warning("mockup: generar_mockup fallo (%s)", e)
        return None
