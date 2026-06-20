r"""
cycle27_hybrid_budget.py — CICLO 27 a través del Investigation Engine.

H-HYB-1 (CYCLE 26): el híbrido a d=24 cerraría la brecha con la atención pura con MÁS budget (el 0.18 de
exp013 sería under-training). exp014 lo TESTEA con 3.3x el budget (10000 steps) — y lo REFUTA.

RESULTADO (exp014, d=24, n_heads=4, n_pairs=16, seed0, steps=10000):
  - hibrido_h4 (2 lineales + 2 atención) = 0.186 -> PLATEÓ (0.180@4000 -> 0.186@7500 -> 0.186 final, PLANO).
    NO es under-training: con 3.3x el budget sigue en el plateau ~0.18 del lineal puro.
  - atencion_h4 (atención pura) = 0.948 -> cruzó por ~4000 y siguió subiendo.

AUTOCORRECCIÓN HONESTA (el proceso funciona): en CYCLE 26 diagnostiqué el 0.18 del híbrido como
"under-training" (estaba ASCENDIENTE a 3000 steps). exp014 muestra que era el COMIENZO de un plateau DURO:
el híbrido interleaved a d=24 NO recupera recall — las 2 capas LINEALES BLOQUEAN el recall que la atención
pura sí logra. Diagnóstico corregido por más evidencia (directiva v3 §4.2 invertida: lo que parecía
sub-recursos era estructural; siempre se confirma con más budget antes de cerrar).

IMPLICACIÓN: ACOTA H-MEZ-4 (el híbrido recuperaba recall a d=64/np=8, CYCLE 6) — la recuperación del recall
del híbrido es **d-dependiente**: falla a d=24 (las capas lineales de baja capacidad bottleneckean). NO
refuta H-MEZ-4 (otra escala), la limita. Genera H-HYB-2 (¿es d, arreglo, ratio o carga?).

DERIVA de exp014/results.json. Pasa por las compuertas.

Correr (DESPUÉS de exp014):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp014_hybrid_budget.run --steps 10000
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle27_hybrid_budget
"""
import argparse
import json
import os
import shutil
import sys

from cognia_x.research.schema import (
    Source, Hypothesis, Decision, AnalogyRecord, CeilingRecord,
)
from cognia_x.research.ledger import EvidenceLedger, OpinionOnlyError
from cognia_x.research.hypotheses import HypothesisRegistry
from cognia_x.research.analogy import extract_principles
from cognia_x.research.ceiling import CeilingTracker
from cognia_x.research.record import PermanentRecord

DEFAULT_STORE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle27_hybrid_budget'
)
DEFAULT_RESULTS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..',
    'experiments', 'exp014_hybrid_budget', 'results', 'results.json'
)


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


# tier-5: CYCLE 6 mostró el híbrido a 0.99 — PERO a d=64. La 'evidencia a favor' de H-HYB-1 que NO se cumplió.
S1 = Source(
    tier=5, ref="CYCLE6_H-MEZ-4", obtained=True,
    claim=("CYCLE 6 (H-MEZ-4): el híbrido recupera recall (0.99) a d=64, np=8, h=4 — predecía que el "
           "híbrido a d=24 también cerraría con más budget. exp014 lo refuta: la recuperación es d-dependiente."),
)


def _fmt(x):
    return "{:.3f}".format(x) if isinstance(x, (int, float)) else str(x)


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if 'summary' not in data:
        raise SystemExit("results.json sin 'summary' (corré exp014 primero): " + results_path)
    summary = data['summary']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    hyb = summary.get('hibrido_acc')
    ref = summary.get('atencion_acc')
    steps = summary.get('steps')
    closes = summary.get('closes', False)

    S2 = Source(
        tier=5, ref="cognia_x/experiments/exp014_hybrid_budget", obtained=True,
        claim=("exp014 (d=24, n_heads=4, n_pairs=16, seed0, steps={steps}, 3.3x el budget de exp013): "
               "hibrido_h4={hyb} (PLATEÓ: 0.180@4000 -> 0.186@7500 -> 0.186 final, PLANO; NO under-training) "
               "vs atencion_h4={ref} (cruzó por ~4000). El híbrido interleaved a d=24 NO recupera recall: "
               "las capas lineales bottleneckean.").format(steps=steps, hyb=_fmt(hyb), ref=_fmt(ref)),
    )
    for s in (S1, S2):
        ledger.add_source(s)
    notes.append("2 fuentes (S1 tier5 CYCLE6-hibrido-a-d64; S2 tier5 exp014).")

    # --- H-HYB-1: REFUTADA (no cierra con budget -> estructural) ---
    h1 = Hypothesis(
        id="H-HYB-1",
        statement=("A d chico (24), el recall del híbrido (mayoría lineal + pocas atención) cierra la brecha "
                   "con la atención pura si se le da más BUDGET (el 0.18 de exp013 sería under-training)."),
        prediction=("Con más steps (10000, 3.3x), hibrido_h4 a d=24 sube >> 0.18 hacia la atención pura. "
                    "Refutado si sigue ~0.18."),
        status='abierta',
        confidence='media',
        evidence_for=[S1.ref],     # CYCLE6 (el híbrido CAN a d=64) -> predecía que cerraría
        evidence_against=[S2.ref],  # exp014: 10000 steps, sigue 0.186 (plateó)
        adversarial_verdict=(
            "REFUTADA: con 3.3x el budget (10000 steps) el híbrido sigue en {} — PLATEÓ por el paso ~4000, "
            "no under-training. CORRIGE el diagnóstico de CYCLE 26 (lo llamé under-training porque a 3000 "
            "steps ascendía; era el comienzo de un plateau DURO). El híbrido interleaved a d=24 NO recupera "
            "recall: las 2 capas LINEALES (baja capacidad a d=24, ~0.18) BLOQUEAN el recall que la atención "
            "pura sí logra ({}). Esto ACOTA H-MEZ-4 (el híbrido recuperaba a d=64): la recuperación es "
            "d-dependiente. Genera H-HYB-2.").format(_fmt(hyb), _fmt(ref)),
        experiment_ref="exp014_hybrid_budget",
    )
    hyps.add(h1)
    if closes:
        # rama defensiva: si SÍ cerró (no fue el caso), sería 'apoyada'.
        h1f = hyps.mark_supported("H-HYB-1"); status = 'apoyada'
    else:
        h1f = hyps.mark_refuted("H-HYB-1"); status = 'refutada'
    assert h1f.status == status
    notes.append("H-HYB-1 marcada '{}' con DoD completo (corrige el diagnóstico de CYCLE 26).".format(status))

    # --- H-HYB-2 (NUEVA, abierta): por qué el híbrido falla a d=24 pero funciona a d=64 ---
    if status == 'refutada':
        h2 = Hypothesis(
            id="H-HYB-2",
            statement=("La recuperación de recall del híbrido es d-dependiente: a d chico (24) las capas "
                       "LINEALES (recall ~0.18) bottleneckean el recall que las de atención darían; a d=64 "
                       "(CYCLE 6) no. El cuello es la capacidad de las capas lineales y/o el arreglo "
                       "(lineal-primero destruye la asociación clave-valor antes de la atención)."),
            prediction=("Subir d (24->48->64) o poner la atención PRIMERA (no lineal-primero) o subir el "
                        "ratio de atención hace que el híbrido cruce el plateau a esta carga. Refutado si "
                        "ninguna de esas variables lo mueve (sería más profundo)."),
            status='abierta',
            confidence='baja',
            evidence_for=[S1.ref, S2.ref],
            evidence_against=[],
            adversarial_verdict='',
            experiment_ref='',
        )
        hyps.add(h2)
        notes.append("H-HYB-2 añadida 'abierta' (¿por qué el híbrido falla a d=24 pero funciona a d=64?).")

    # --- ANALOGÍA ---
    analogy = AnalogyRecord(
        problem=("¿El híbrido (mayoría lineal + pocas atención) cierra la brecha con la atención pura si "
                 "entrena más? A d=24, con 3.3x el budget, NO: sigue en 0.18. ¿Por qué?"),
        everyday=("Una cadena de montaje con eslabones débiles (capas lineales de poca capacidad) NO mejora "
                  "por más horas: los eslabones débiles cuellan el flujo aunque los fuertes (atención) puedan "
                  "más. A d=64 los eslabones lineales son más fuertes y no cuellan."),
        solutions=[
            "más budget al híbrido a d=24 -> NO ayuda (exp014: plateó a 0.18)",
            "subir d (eslabones lineales más fuertes) -> a investigar (H-HYB-2; CYCLE 6 a d=64 funcionó)",
            "poner la atención primero (no lineal-primero) -> a investigar (H-HYB-2)",
            "subir el ratio de atención -> a investigar; en el límite es atención pura (0.95)",
        ],
        principles=[
            "diagnóstico se CONFIRMA con más budget antes de cerrar: lo 'ascendiente' (CYCLE 26) era un plateau duro",
            "el híbrido NO es free lunch: a d chico las capas lineales bottleneckean el recall (acota H-MEZ-4)",
            "una cadena rinde como su eslabón más débil: el recall del híbrido lo limita la capacidad lineal",
        ],
        adaptation=("H-HYB-1 refutada (estructural, no budget) -> caveat a D-007 (el híbrido necesita d "
                    "suficiente); H-HYB-2 investiga d/arreglo/ratio. La atención pura sigue siendo el remedio claro."),
        measurement="exp014: hibrido_h4={} (10000 steps, plateó), atencion_h4={}.".format(_fmt(hyb), _fmt(ref)),
        iterations=1,
    )
    principles = extract_principles(analogy)
    assert len(principles) >= 3
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas: {} soluciones, {} principios.".format(
        len(analogy.solutions), len(principles)))

    # --- TECHO: facet nuevo — el híbrido interleaved bottleneckea a d chico ---
    ceiling = CeilingRecord(
        subsystem="Recall del híbrido interleaved a d chico (24) — las capas lineales bottleneckean",
        known_limit=("exp014: el híbrido (2 lineal + 2 atención) a d=24 PLATEA en ~0.18 (= lineal puro) con "
                     "10000 steps; la atención pura cruza (0.95). Las capas lineales de baja capacidad a "
                     "d=24 bottleneckean el recall. ACOTA H-MEZ-4 (funcionaba a d=64): la recuperación del "
                     "híbrido es d-dependiente. ASUMIDO/mejorable (H-HYB-2: d/arreglo/ratio a investigar)."),
        blockers=[
            {"text": "capas lineales de baja capacidad (recall ~0.18 a d=24) cuellan el flujo del recall", "kind": "diseno"},
            {"text": "arreglo lineal-primero puede destruir la asociación clave-valor antes de la atención", "kind": "diseno"},
        ],
        real_or_assumed="asumido",
        evidence=[S1.ref, S2.ref],
    )
    ceilings.add(ceiling)
    notes.append("1 techo 'asumido' añadido (el híbrido bottleneckea a d chico -> backlog H-HYB-2).")

    # --- DECISIÓN D-HYB-1: caveat al híbrido (D-007) ---
    decision = Decision(
        id="D-HYB-1",
        statement=("Añadir caveat a D-007 (backbone híbrido): el híbrido NO recupera recall automáticamente "
                   "— a d chico (24) las capas lineales bottleneckean y el híbrido platea como el lineal "
                   "(exp014). El híbrido necesita d suficiente (funcionó a d=64, CYCLE 6) y/o el arreglo/ratio "
                   "adecuado (H-HYB-2). La atención pura sigue siendo el remedio claro del recall a carga alta."),
        rationale=("exp014: hibrido_h4 a d=24 con 10000 steps platea en 0.186 (= lineal puro) mientras la "
                   "atención pura llega a 0.948. NO es budget (plateó por el paso 4000). Corrige el "
                   "diagnóstico de under-training de CYCLE 26. Acota H-MEZ-4 a d>=cierto umbral."),
        sources=[_to_plain(S2), _to_plain(S1)],   # 2 tier5 propios obtenidos -> fundan (no opinión)
        important=True,
    )
    try:
        ledger.record_decision(decision)
        notes.append("D-HYB-1 ACEPTADA por el ledger (2 tier5 propios obtenidos -> fundan).")
    except OpinionOnlyError as e:
        print("ERROR: el ledger RECHAZÓ D-HYB-1: {}".format(e))
        raise

    return ledger, hyps, ceilings, record, notes, status, hyb, ref


def _to_plain(obj):
    from cognia_x.research.schema import to_dict
    import dataclasses
    if dataclasses.is_dataclass(obj):
        return to_dict(obj)
    return dict(obj)


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(
        prog='python -m cognia_x.research.cycles.cycle27_hybrid_budget',
        description='CYCLE 27 (H-HYB-1: el hibrido cierra con budget?) a través del Investigation Engine.')
    p.add_argument('--store', default=DEFAULT_STORE)
    p.add_argument('--results', default=DEFAULT_RESULTS)
    p.add_argument('--reset', dest='reset', action='store_true', default=True)
    p.add_argument('--no-reset', dest='reset', action='store_false')
    args = p.parse_args(argv)

    store = os.path.abspath(args.store)
    if args.reset and os.path.isdir(store):
        shutil.rmtree(store)
    os.makedirs(store, exist_ok=True)

    ledger, hyps, ceilings, record, notes, status, hyb, ref = run(store, os.path.abspath(args.results))
    res = record.verify_no_loss()

    print("=" * 78)
    print("RESUMEN — CYCLE 27: H-HYB-1 (el hibrido cierra con budget?) [Investigation Engine]")
    print("=" * 78)
    print("store: {}".format(store))
    print("veredicto H-HYB-1: {}  (hibrido={}, atencion_pura={})".format(status.upper(), _fmt(hyb), _fmt(ref)))
    print("")
    for n in notes:
        print("  CHECK  {}".format(n))
    print("")
    from cognia_x.research.record import count_lines
    for name in ('sources', 'hypotheses', 'analogies', 'ceilings', 'decisions'):
        print("  {:<12}: {}".format(name, count_lines(record.store_path(name))))
    print("  {:<12}: {} (backlog de refutación)".format('asumidos', len(ceilings.assumed_limits())))
    print("")
    print("  verify_no_loss:")
    for d in res['details']:
        flag = 'OK' if d['ok'] else 'FAIL'
        print("    [{}] {:<12} journaled={} live={} missing={}".format(
            flag, d['store'], d['journaled'], d['live'], d.get('missing', 0)))
    print("")
    if res['ok']:
        print("  verify_no_loss = OK (sin pérdida de conocimiento)")
        print("=" * 78)
        return 0
    print("  verify_no_loss = FAIL")
    print("=" * 78)
    return 1


if __name__ == '__main__':
    sys.exit(main())
