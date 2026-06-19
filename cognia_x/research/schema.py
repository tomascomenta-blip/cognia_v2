"""
schema.py — tipos de datos planos del Investigation Engine (stdlib dataclasses, sin deps).

POR QUÉ: la directiva v2 (cognia_x/manager/_directiva_v2.md) exige que el método de investigación
sea CÓDIGO ejecutable, no buena voluntad. Estos dataclasses son el vocabulario enforzado: fuentes
con tier, hipótesis falsables, decisiones fundadas, analogías de 7 etapas, techos real/asumido y
notas de escalabilidad. Todo serializa a JSON (asdict) porque el registro es append-only JSONL.

Escalabilidad obligatoria (§6 de la directiva):
- Complejidad temporal: O(1) por to_dict/from_dict (asdict recorre campos fijos del dataclass).
- Complejidad espacial: O(k) con k = nº de campos del registro (constante por tipo); las listas
  internas (evidence_for, sources, ...) crecen O(m) con la evidencia que el usuario adjunta.
- Comportamiento en CPU: aritmética/diccionarios puros, sin vectorización; trivial en 2c/4t sin GPU.
- Multi-dispositivo: los dicts son JSON-portables; un registro escrito en un nodo se lee en otro.
- Distribución futura: al ser JSON plano, un merge de JSONL de varios nodos es concatenación + dedup.
"""
import dataclasses
from dataclasses import dataclass, field

# Jerarquía de calidad de información (§1). menor = mejor.
TIER_NAMES = {
    1: 'paper_peer_reviewed',
    2: 'libro_academico',
    3: 'doc_oficial',
    4: 'benchmark_reproducible',
    5: 'dato_propio',
    6: 'fuente_secundaria',
}

# POR QUÉ: tier 6 (y CUALQUIER fuente sin referencia resoluble) es "grado-opinión": no puede
# fundar por sí sola una decisión importante. El ledger usa esto como compuerta dura.
OPINION_TIER = 6


def is_opinion_grade(source):
    """True si la fuente es grado-opinión: tier 6, sin ref, o no obtenida (no funda decisiones)."""
    return (source.tier >= OPINION_TIER) or (not source.ref) or (not source.obtained)


@dataclass
class Source:
    # ref = DOI/arXiv/URL/expNNN. obtained=False si NO se pudo obtener (NUNCA inventar la cita/dato).
    tier: int
    ref: str
    claim: str
    obtained: bool = True


@dataclass
class Hypothesis:
    # status in {abierta, apoyada, refutada, mixta}; confidence libre (baja/media/alta).
    id: str
    statement: str
    prediction: str
    status: str = 'abierta'
    confidence: str = 'baja'
    evidence_for: list = field(default_factory=list)
    evidence_against: list = field(default_factory=list)
    adversarial_verdict: str = ''
    experiment_ref: str = ''


@dataclass
class Decision:
    # important=True activa la compuerta del ledger (nunca optimizar solo con opiniones).
    id: str
    statement: str
    rationale: str
    sources: list = field(default_factory=list)
    important: bool = True


@dataclass
class AnalogyRecord:
    # El Sistema de Analogías Universales de 7 etapas (§2). solutions >=3 antes de extraer principios.
    problem: str
    everyday: str
    solutions: list = field(default_factory=list)
    principles: list = field(default_factory=list)
    adaptation: str = ''
    measurement: str = ''
    iterations: int = 0


@dataclass
class CeilingRecord:
    # blockers = list of {text, kind} con kind in {fisico, diseno, historico}.
    # real_or_assumed in {real, asumido}: "límite asumido es invitación a refutar" (§5).
    subsystem: str
    known_limit: str
    blockers: list = field(default_factory=list)
    real_or_assumed: str = 'asumido'
    evidence: list = field(default_factory=list)


@dataclass
class ScalabilityNote:
    # §6: documentar o el componente NO se acepta.
    component: str
    time_complexity: str
    space_complexity: str
    cpu_behavior: str
    multidevice: str
    distribution: str


def to_dict(obj):
    """Serializa cualquier dataclass del schema a dict JSON-able (O(1), campos fijos)."""
    return dataclasses.asdict(obj)


def from_dict(cls, d):
    """Reconstruye un dataclass desde dict. Ignora claves extra (forward-compat de JSONL viejo)."""
    fields = {f.name for f in dataclasses.fields(cls)}
    return cls(**{k: v for k, v in d.items() if k in fields})
