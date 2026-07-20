"""
feromona.py — el rastro que la colonia deja en el entorno.

La idea viene de AMRO-S (enrutado multi-agente por colonia de hormigas, arXiv
2603.12933): las decisiones buenas REFUERZAN el rastro y las malas lo
evaporan, y los miembros no se hablan entre si — se comunican por el registro
compartido (estigmergia).

Aplicado a la flota de micro-expertos con la regla pre-registrada del plan:
un experto NUNCA reemplaza a su heuristica en silencio. Primero acumula
rastro: cada discrepancia experto-vs-heuristica queda registrada, y cuando el
resultado downstream confirma quien tenia razon, el peso del experto sube o
baja. Solo un peso alto sostenido (>= UMBRAL_CONFIANZA con >= MIN_EVIDENCIA
confirmaciones) le da derecho a decidir — y eso se revisa, no se automatiza
todavia.

Estado en JSON plano junto a los modelos: legible, versionable, sin sqlite.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

RUTA_RASTRO = Path(__file__).resolve().parent.parent / "microexpertos" / "feromona.json"

# Suavizado laplaciano: nadie nace con peso 0 ni con peso 1.
_PSEUDO = 2.0
# Cuanta evidencia confirmada hace falta para que el peso signifique algo.
MIN_EVIDENCIA = 20
UMBRAL_CONFIANZA = 0.8

_lock = threading.Lock()


def _cargar() -> dict:
    try:
        return json.loads(RUTA_RASTRO.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _guardar(datos: dict) -> None:
    try:
        RUTA_RASTRO.write_text(json.dumps(datos, indent=2, ensure_ascii=False),
                               encoding="utf-8")
    except Exception as e:
        logger.warning("Feromona: no pude guardar el rastro: %s", e)


def registrar_discrepancia(tarea: str, texto: str, experto: str,
                           heuristica: str) -> None:
    """Un desacuerdo experto-vs-heuristica. Es senal, no veredicto."""
    with _lock:
        datos = _cargar()
        t = datos.setdefault(tarea, {
            "discrepancias": [], "experto_acerto": 0, "heuristica_acerto": 0})
        t["discrepancias"].append({
            "texto": texto[:120], "experto": experto, "heuristica": heuristica})
        # el registro no crece sin limite: las ultimas 200 bastan para revisar
        t["discrepancias"] = t["discrepancias"][-200:]
        _guardar(datos)


def confirmar(tarea: str, acerto_experto: bool) -> None:
    """El resultado downstream dijo quien tenia razon: refuerza el rastro."""
    with _lock:
        datos = _cargar()
        t = datos.setdefault(tarea, {
            "discrepancias": [], "experto_acerto": 0, "heuristica_acerto": 0})
        if acerto_experto:
            t["experto_acerto"] += 1
        else:
            t["heuristica_acerto"] += 1
        _guardar(datos)


def peso(tarea: str) -> tuple[float, int]:
    """
    (peso del experto en [0,1], n de confirmaciones). El peso solo es
    accionable con n >= MIN_EVIDENCIA — antes es rastro, no camino.
    """
    datos = _cargar()
    t = datos.get(tarea)
    if not t:
        return 0.5, 0
    e, h = t.get("experto_acerto", 0), t.get("heuristica_acerto", 0)
    n = e + h
    return (e + _PSEUDO) / (n + 2 * _PSEUDO), n


def el_experto_manda(tarea: str) -> bool:
    """True solo con rastro fuerte Y suficiente: la regla del plan."""
    w, n = peso(tarea)
    return n >= MIN_EVIDENCIA and w >= UMBRAL_CONFIANZA
