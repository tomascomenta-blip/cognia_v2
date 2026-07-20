"""
critico.py — un critico profesional de diseno opina el trabajo del pipeline.

POR QUE EXISTE (pedido del dueno, 2026-07-20, con su argumento): "si alguien
que no es artista opina sobre su propio trabajo dira 'uff, esta buenisimo';
tiene que criticar un profesional para que valga la pena". Medido ese mismo
dia: el evaluador daba 8.4/10 a una pagina que un revisor externo suspendio de
un vistazo, y 7.6 a una cuyo "grafico" era una caja blanca vacia. La regla del
repo lo respalda: auto-corregirse sin verificador externo EMPEORA (Huang et
al., ICLR 2024, arXiv:2310.01798). El critico es un rol SEPARADO del creador:
no defiende el trabajo porque no es suyo.

Sus ojos son los hechos MEDIDOS por la sonda de vista_navegador
(InformeVisual.hechos): el critico no ve pixeles, pero "n_graficos: 0" o
"15 de 18 valores en un solo color" no se pueden discutir.

EL EXPERTO ES INTERCAMBIABLE: por defecto critica el modelo residente con rol
de disenador senior. Si COGNIA_CRITICO_URL apunta a otro backend (p. ej.
UIGEN-X-8B, el modelo experto en UI que hay en ~/.cognia/models, servido en
otro puerto), el critico pasa a ser EL sin tocar codigo. La variable se lee en
CADA llamada, no al importar: exportarla a mitad de sesion funciona.

Autoria: escrito por Cognia via G4. El centinela corrigio en revision que la
preparacion del prompt solo ocurria en la rama del experto (el camino normal
metia el dict crudo y el HTML entero sin truncar) y que la URL se leia al
importar.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from typing import Dict, List, Optional

from ..llm_local import disponible, generar

logger = logging.getLogger(__name__)

_SYSTEM = (
    "You are a senior UI designer brutally honest about reviewing someone "
    "else's work. You never inflate grades. A mediocre-functional page is "
    "a 5, not an 8."
)

_PLANTILLA = """The idea was: "{idea}"

Facts MEASURED by rendering the page in a real browser (these do not lie):
{hechos}

The generated HTML (truncated):
```html
{html}
```

Score it against this professional checklist:
1. Does it fulfill the request (every element of the idea truly present)?
2. Visual hierarchy (clear sections, something dominates the view)?
3. A real chart: axes with values, correct scale — not an empty box?
4. Painted states (green/red on the values that change)?
5. Number formatting (separators, currency, consistent decimals)?
6. Information density (an empty dashboard informs nobody)?

Answer EXACTLY in this format, nothing else:
NOTA: <number 0-10, one decimal>
VEREDICTO: <one line>
DEFECTOS:
- <actionable defect>
- <actionable defect>
If the page is excellent, DEFECTOS is exactly "- ninguno".
"""


def _parsear(texto: str) -> Optional[Dict]:
    """NOTA/VEREDICTO/DEFECTOS, tolerante a caja, coma decimal e idioma."""
    try:
        # Los modelos con razonamiento (UIGEN-X) anteponen <think>...</think>;
        # el veredicto real viene despues.
        if "</think>" in texto:
            texto = texto.split("</think>", 1)[1]
        lineas = texto.strip().splitlines()
        nota_l = next(l for l in lineas
                      if l.lower().lstrip().startswith(("nota:", "note:")))
        vered_l = next((l for l in lineas
                        if l.lower().lstrip().startswith(("veredicto:",
                                                          "veredict:",
                                                          "verdict:"))), "")
        defectos = [l.strip().lstrip("-*").strip() for l in lineas
                    if l.strip().startswith(("- ", "* "))]
        defectos = [d for d in defectos if d]
        if [d.lower() for d in defectos] in (["ninguno"], ["none"]):
            defectos = []

        nota = float(nota_l.split(":", 1)[1].strip().replace(",", "."))
        return {
            "nota": max(0.0, min(10.0, nota)),
            "veredicto": vered_l.split(":", 1)[1].strip() if vered_l else "",
            "defectos": defectos,
        }
    except Exception as e:
        logger.warning("critico: respuesta imparseable (%s): %r", e, texto[:120])
        return None


def _preguntar_experto(url: str, prompt: str) -> Optional[str]:
    """POST directo al backend experto (formato OpenAI). None si falla."""
    try:
        cuerpo = json.dumps({
            "model": "local",
            "messages": [{"role": "system", "content": _SYSTEM},
                         {"role": "user", "content": prompt}],
            "temperature": 0.2,
            # 900 y no 400: los modelos expertos con razonamiento (UIGEN-X)
            # gastan presupuesto pensando ANTES de responder; con 400 el
            # contenido llegaba vacio en paginas grandes.
            "max_tokens": 900,
        }).encode("utf-8")
        peticion = urllib.request.Request(
            url.rstrip("/") + "/v1/chat/completions", data=cuerpo,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(peticion, timeout=120) as r:
            datos = json.loads(r.read().decode("utf-8"))
        return datos["choices"][0]["message"]["content"]
    except Exception as e:
        logger.warning("critico: el experto de %s no respondio (%s); "
                       "caigo al modelo residente", url, e)
        return None


def criticar_web(idea: str, html: str, hechos: dict) -> Optional[Dict]:
    """
    La opinion del profesional: {"nota": float, "veredicto": str,
    "defectos": [str]}. None si no hay ningun backend o nada parsea — el
    llamador decide que hacer sin critico. NUNCA lanza.
    """
    hechos_txt = "\n".join(f"- {k}: {v}" for k, v in (hechos or {}).items()) \
                 or "- (sin medicion de navegador)"
    prompt = _PLANTILLA.format(idea=idea[:300], hechos=hechos_txt,
                               html=(html or "")[:5000])

    # El experto, si el dueno lo tiene servido. Se lee AQUI y no al importar.
    url_experto = os.environ.get("COGNIA_CRITICO_URL", "").strip()
    if url_experto:
        texto = _preguntar_experto(url_experto, prompt)
        if texto:
            resultado = _parsear(texto)
            if resultado is not None:
                resultado["critico"] = "experto"
                return resultado

    if not disponible():
        return None
    texto = generar(prompt, system=_SYSTEM, temperature=0.2, max_tokens=400)
    if not texto:
        logger.warning("critico: sin respuesta del LLM")
        return None
    resultado = _parsear(texto)
    if resultado is not None:
        resultado["critico"] = "residente"
    return resultado
