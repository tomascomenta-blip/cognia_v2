# -*- coding: utf-8 -*-
"""Experto de imágenes: expande un pedido corto en un prompt de difusión detallado.

El cerebro grande (o el usuario) pide "un perro"; la difusión necesita
"a fluffy golden retriever puppy sitting, big round eyes, soft fur, ...". Este
módulo hace esa expansión. Por ahora con el LLM del repo (`cognia.llm_local.generar`)
+ plantilla; en F3 lo reemplaza un LoRA de MiniCPM entrenado para escribir prompts.

Diseño:
- SIN dependencias pesadas: solo texto. Importable en cualquier nodo (CPU incluido).
- El LLM es OPCIONAL e inyectable (patrón LlmFn = (prompt, system, max_tokens,
  temperature) -> str|None, el mismo de program_creator). Si no hay LLM (o falla),
  cae a una plantilla determinista -> el subsistema nunca se queda sin prompt.
- Produce el NÚCLEO visual del sujeto; el backend (generar_transparente, asset=True)
  ya añade las señales de aislamiento (_PROMPT_ASSET) y el trigger del estilo. Así
  no se duplican las coletillas.

LIMITACIÓN honesta (verificada 2026-07-22): SDXL entiende mucho mejor el INGLÉS. La
vía LLM traduce el pedido a inglés (lo pide el system prompt), pero la plantilla de
respaldo pasa el pedido VERBATIM. Con LLM caído + pedido en español, el sujeto puede
salir equivocado ("un cofre del tesoro" -> una cara cartoon en vez de un cofre).
Para español fiable hace falta la vía LLM (o pasar el pedido ya en inglés). El LoRA
de MiniCPM de F3 endurece esta vía; por ahora, si no hay LLM, prefiere pedidos en inglés.
"""
from __future__ import annotations

import re

# Negativo curado para assets aislados (anti-escena, anti-texto, anti-recorte).
# Es bastante universal; el LLM enriquece el positivo, no este.
NEGATIVO_ASSET = ("text, watermark, signature, logo, multiple objects, "
                  "scene, landscape, background clutter, frame, border, "
                  "drop shadow, cropped, out of frame, blurry, low quality, "
                  "jpeg artifacts, deformed")

_SYSTEM = (
    "Eres un experto en prompts para modelos de difusión de imágenes (SDXL). "
    "Recibes un pedido corto y devuelves UNA sola línea en INGLÉS: etiquetas "
    "visuales separadas por comas que describen el objeto con detalle (forma, "
    "color, material, iluminación suave, estilo). El objeto debe ir AISLADO, "
    "sin escena ni fondo, sin texto. NO incluyas 'transparent background' ni "
    "comillas ni explicaciones: solo las etiquetas del objeto.")


def _plantilla(pedido: str, estilo: str = None) -> str:
    """Prompt de respaldo, determinista, cuando no hay LLM. Enriquece el pedido
    con adjetivos genéricos de asset limpio (sin escena)."""
    base = pedido.strip().rstrip(".")
    extra = "detailed, soft studio lighting, vibrant colors, clean design"
    if estilo == "pixel":
        extra = "crisp pixels, limited palette, clean readable silhouette"
    elif estilo == "pvz":
        extra = "cartoon, bold outlines, friendly, playful, vibrant colors"
    return f"{base}, {extra}"


def _limpiar_salida_llm(texto: str) -> str:
    """Normaliza la salida del LLM a una línea de etiquetas usable. Puro texto
    (testeable): toma la 1ª línea con contenido, quita comillas/prefijos y recorta."""
    if not texto:
        return ""
    linea = ""
    for l in texto.splitlines():
        l = l.strip()
        if l:
            linea = l
            break
    linea = linea.strip().strip('"').strip("'").strip()
    # Quita viñetas/numeraciones de lista al inicio ("- ", "* ", "1. ", "2) ").
    linea = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", linea)
    # Quita prefijos tipo "Prompt:", "Positive:".
    for pref in ("prompt:", "positive:", "positive prompt:", "output:", "tags:"):
        if linea.lower().startswith(pref):
            linea = linea[len(pref):].strip()
    # Descarta si el LLM se fue por las ramas (frase larga en vez de etiquetas).
    if len(linea) > 400:
        linea = linea[:400].rsplit(",", 1)[0]
    return linea.strip().rstrip(".")


def _resolver_llm(llm):
    """Devuelve un LlmFn: el inyectado, o el del repo (cognia.llm_local.generar),
    o None si no hay ninguno disponible."""
    if llm is not None:
        return llm
    try:
        from cognia.llm_local import generar as _generar
    except Exception:
        return None

    def _llm(prompt, system="", max_tokens=200, temperature=0.7):
        return _generar(prompt, system=system, temperature=temperature,
                        max_tokens=max_tokens)
    return _llm


def expandir_prompt(pedido: str, *, estilo: str = None, llm=None,
                    temperature: float = 0.7) -> dict:
    """Expande un pedido corto en un prompt de difusión. Devuelve
    {'prompt': str, 'negative': str, 'fuente': 'llm'|'plantilla'}.

    pedido: descripción corta ("un perro", "una espada mágica").
    estilo: sesga la plantilla de respaldo (pixel/pvz) — no obliga al LLM.
    llm: LlmFn opcional (prompt, system, max_tokens, temperature)->str|None. Si es
         None, usa cognia.llm_local.generar; si tampoco hay, cae a plantilla.
    """
    pedido = (pedido or "").strip()
    if not pedido:
        raise ValueError("pedido vacío")

    fn = _resolver_llm(llm)
    fuente = "plantilla"
    prompt = _plantilla(pedido, estilo)
    if fn is not None:
        try:
            salida = fn(f"Pedido: {pedido}", _SYSTEM, 200, temperature)
        except Exception:
            salida = None
        limpio = _limpiar_salida_llm(salida or "")
        if len(limpio) >= 8:  # respuesta útil; si no, se queda la plantilla
            prompt = limpio
            fuente = "llm"

    return {"prompt": prompt, "negative": NEGATIVO_ASSET, "fuente": fuente}


def generar_desde_pedido(pedido: str, *, estilo: str = None, llm=None, **kw):
    """Atajo E2E: experto de imágenes -> generar_transparente. Expande el pedido
    y genera el PNG RGBA. `kw` pasa a generar_transparente (metodo, recortar, seed…).
    Devuelve (ruta_png, dict_del_experto)."""
    from .diffusion_backend import generar_transparente
    exp = expandir_prompt(pedido, estilo=estilo, llm=llm)
    ruta = generar_transparente(exp["prompt"], estilo=estilo,
                                negative=exp["negative"], **kw)
    return ruta, exp
