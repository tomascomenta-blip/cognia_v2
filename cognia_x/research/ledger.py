"""
ledger.py — EvidenceLedger: la compuerta "nunca optimizar solo con opiniones" (§1) en código.

POR QUÉ: la directiva v2 dice que la jerarquía de evidencia la hace el ledger, no la buena voluntad.
Una DECISIÓN IMPORTANTE se rechaza (OpinionOnlyError) si su única fundación son fuentes grado-opinión
(tier 6, sin ref, o no obtenidas). Necesita ≥1 fuente obtenida de tier ≤ 4, O ≥1 dato propio (tier 5)
obtenido. Las decisiones NO importantes se permiten pero se marcan (flagged) en el registro.

Escalabilidad obligatoria (§6):
- Complejidad temporal: add_source / record_decision = O(1) amortizado (un append JSONL). La
  validación de una decisión es O(m) con m = nº de fuentes citadas en ESA decisión (típicamente <10).
- Complejidad espacial: O(1) por escritura (no carga el histórico). El histórico vive en disco.
- Comportamiento en CPU: I/O-bound, sin cómputo pesado; trivial en 2c/4t sin GPU.
- Multi-dispositivo: JSONL portable; el ledger de un nodo se lee/fusiona en otro por concatenación.
- Distribución futura: merge append-only de ledgers; la compuerta se reaplica al re-validar.
"""
from cognia_x.research.record import PermanentRecord
from cognia_x.research.schema import Source, Decision, to_dict, from_dict, OPINION_TIER


class OpinionOnlyError(Exception):
    """Se lanza al intentar fundar una decisión importante solo con fuentes grado-opinión."""
    pass


def _is_grounding_source(d):
    """
    True si un dict-fuente PUEDE fundar una decisión importante:
    tier ≤ 4 obtenido (paper/libro/doc/benchmark), o tier == 5 obtenido (dato propio reproducible).
    Una fuente no obtenida, sin ref o tier 6 NUNCA funda (es grado-opinión).
    """
    if not d.get('obtained', False):
        return False
    if not d.get('ref'):
        return False
    tier = d.get('tier', OPINION_TIER)
    return tier <= 4 or tier == 5


class EvidenceLedger:
    def __init__(self, path):
        # path = dir base del engine (el PermanentRecord journaliza ahí). Stores: sources, decisions.
        self.record = PermanentRecord(path)

    def add_source(self, source):
        """Append una Source al store 'sources' (journaleado). NUNCA fabrica: obtained refleja realidad."""
        d = to_dict(source) if isinstance(source, Source) else dict(source)
        self.record.journaled_append('sources', d, key=d.get('ref', ''))
        return from_dict(Source, d)

    def record_decision(self, decision):
        """
        Registra una Decision. ENFORZA la compuerta: si es important y NINGUNA de sus fuentes funda
        (≥1 tier≤4 obtenida O ≥1 tier 5 obtenida) -> OpinionOnlyError. No importantes pasan flagged.
        """
        d = to_dict(decision) if isinstance(decision, Decision) else dict(decision)
        sources = d.get('sources', []) or []
        grounded = any(_is_grounding_source(s) for s in sources)
        if d.get('important', True) and not grounded:
            raise OpinionOnlyError(
                "Decisión importante '{}' rechazada: requiere >=1 fuente obtenida tier<=4 o "
                ">=1 dato propio (tier 5) obtenido. Solo cita fuentes grado-opinión "
                "(tier 6 / sin ref / no obtenidas).".format(d.get('id', '?'))
            )
        # flagged: True si pasó SIN fundación dura (solo posible para no-importantes).
        d['_flagged_opinion_only'] = (not grounded)
        self.record.journaled_append('decisions', d, key=d.get('id', ''))
        return from_dict(Decision, d)
