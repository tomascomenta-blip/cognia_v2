"""
analogy.py — el Sistema de Analogías Universales de 7 etapas como artefacto VALIDADO (§2).

POR QUÉ: ante un problema difícil la directiva manda NO atacarlo directo, sino recorrer 7 etapas y
dejar registro. extract_principles ENFORZA las etapas previas: lanza IncompleteAnalogyError salvo que
  - problem no vacío            (etapa 1: describir el problema simple).
  - everyday no vacío           (etapa 2: convertir a situación cotidiana).
  - len(solutions) >= 3         (etapa 3: GENERAR MÚLTIPLES soluciones, no una).
Recién entonces se permite poblar principles (etapa 4: extraer principios fundamentales). Las etapas
5-7 (adaptar / medir / repetir) viven en los campos adaptation/measurement/iterations del registro.

Escalabilidad obligatoria (§6):
- Complejidad temporal: extract_principles = O(s) con s = nº de soluciones (solo cuenta/itera la
  lista); deriva un principio por solución -> lineal en el tamaño del registro, no en el histórico.
- Complejidad espacial: O(p) con p = principios generados (<= s); no carga ningún histórico.
- Comportamiento en CPU: manipulación de listas/strings pura; trivial en 2c/4t sin GPU.
- Multi-dispositivo: AnalogyRecord es JSON-portable (lo serializa schema.to_dict).
- Distribución futura: registros independientes; se fusionan por concatenación sin estado compartido.
"""
from cognia_x.research.schema import AnalogyRecord


class IncompleteAnalogyError(Exception):
    """Se lanza al extraer principios de una analogía que no completó las etapas 1-3."""
    pass


def extract_principles(rec):
    """
    Etapa 4: extrae principios SOLO si las etapas 1-3 están completas (problem, everyday, >=3 soluciones).
    Si rec ya trae principles, los respeta; si no, deriva uno por solución (placeholder honesto que el
    investigador refina). Muta rec.principles y lo devuelve. Lanza IncompleteAnalogyError si falta etapa.
    """
    missing = []
    if not (rec.problem or '').strip():
        missing.append("problem vacío (falta etapa 1)")
    if not (rec.everyday or '').strip():
        missing.append("everyday vacío (falta etapa 2: situación cotidiana)")
    if len(rec.solutions) < 3:
        missing.append(
            "solo {} solución(es); se requieren >=3 (etapa 3: generar múltiples)".format(len(rec.solutions))
        )
    if missing:
        raise IncompleteAnalogyError(
            "No se pueden extraer principios: {}".format("; ".join(missing))
        )

    if not rec.principles:
        # POR QUÉ: deja un principio por solución como semilla trazable; no inventa contenido nuevo,
        # referencia la solución de la que surge para que el investigador lo afine (etapa 4 manual).
        rec.principles = [
            "principio derivado de solución: {}".format(s) for s in rec.solutions
        ]
    return rec.principles
