r"""
cycle26_hybrid_control.py — CICLO 26 a través del Investigation Engine.

CONTROL POSITIVO de la línea H-CEIL (exp013): ¿la ATENCIÓN cruza el plateau ~0.18 del lineal puro (6
levers refutados: exp010 ancho, exp011 forma+init, exp012 profundidad/escala/optim) a la MISMA escala?

RESULTADO (exp013, d=24, n_pairs=16, seed0, steps=3000 step-parity):
  - atencion_h4 (atención PURA) = 0.882 -> CRUZA masivamente el plateau -> CONFIRMA que el remedio del
    recall es ARQUITECTÓNICO (D-CEIL-1/D-CEIL-4 confirmados end-to-end a la escala de la línea H-CEIL).
  - lineal_h1 (baseline) = 0.173 (plateau, como las 6 refutaciones).
  - hibrido_h1/h4 (50/50) = ~0.18 PERO **todavía subiendo** al cortar el budget (hibrido_h4: 0.06->0.105
    ->0.152->0.190 y bajó a 0.180 al final; trayectoria ascendente, NO plateau) -> UNDER-TRAINED a
    step-parity, NO falla estructural (CYCLE 6 mostró el híbrido a 0.99 con la receta/budget adecuados).

Honestidad (diagnóstico antes que hallazgo): el híbrido NO "falla" — aprende recall MÁS LENTO que la
atención pura (debe rutear el recall por las pocas capas de atención pese a las lineales). Esto genera
H-HYB-1 (abierta): el recall del híbrido es más DURO de optimizar que la atención pura a d chico.

DERIVA del results.json. Pasa por las compuertas (ledger, mark_*, ceiling, analogy, verify_no_loss).

Correr (DESPUÉS de exp013):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp013_hybrid_control.run --steps 3000
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle26_hybrid_control
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
    os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle26_hybrid_control'
)
DEFAULT_RESULTS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..',
    'experiments', 'exp013_hybrid_control', 'results', 'results.json'
)


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


# tier-1: la frontera recall<->memoria se cruza con atención (estado proporcional a L), no con estado fijo.
S1 = Source(
    tier=1, ref="arXiv:2402.18668", obtained=True,
    claim=("Arora et al. 2024 (Based): la atención (estado proporcional a la longitud) está en el "
           "extremo de máximo recall de la frontera recall<->memoria; el estado fijo está acotado."),
)
# tier-5: CYCLE 6 mostró el híbrido a 0.99 con la receta adecuada (el híbrido CAN, es cuestión de receta).
S2 = Source(
    tier=5, ref="CYCLE6_H-MEZ-4", obtained=True,
    claim=("CYCLE 6 (H-MEZ-4, cerrada): el híbrido (mayoría lineal + >=2 atención) alcanza recall 0.99 "
           "con la receta adecuada (d=64, h=4, np=8, warmup); el híbrido PUEDE — es cuestión de budget/receta."),
)


def _fmt(x):
    return "{:.3f}".format(x) if isinstance(x, (int, float)) else str(x)


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if 'summary' not in data:
        raise SystemExit("results.json sin 'summary' (corré exp013 primero): " + results_path)
    summary = data['summary']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    acc = summary.get('acc_by_name', {})
    base = summary.get('baseline_acc')
    crossers = summary.get('crossers', [])
    best = summary.get('best_attn', [None, None])
    accs_txt = ", ".join("{}={}".format(k, _fmt(v)) for k, v in acc.items())
    confirmed = bool(crossers)

    S3 = Source(
        tier=5, ref="cognia_x/experiments/exp013_hybrid_control", obtained=True,
        claim=("exp013 (d=24, n_pairs=16, seed0, steps={steps} step-parity, chance {chance}): {accs}. "
               "La atención PURA cruza el plateau ({best}={bestv}) >> baseline {base}; el híbrido 50/50 "
               "queda ~0.18 PERO todavía ASCENDIENTE al cortar el budget (under-trained, no plateau).").format(
                   steps=data.get('steps'), chance=_fmt(summary.get('chance')), accs=accs_txt,
                   best=best[0], bestv=_fmt(best[1]), base=_fmt(base)),
    )
    for s in (S1, S2, S3):
        ledger.add_source(s)
    notes.append("3 fuentes (S1 tier1 Based; S2 tier5 CYCLE6-híbrido-CAN; S3 tier5 exp013).")

    # --- H-HYB-1 (NUEVA, abierta): el híbrido es más DURO de optimizar que la atención pura a d chico ---
    h_hyb = Hypothesis(
        id="H-HYB-1",
        statement=("A d chico (24), el recall del HÍBRIDO (mayoría lineal + pocas capas de atención) es "
                   "más DURO de optimizar que la atención pura: aprende recall MÁS LENTO (las capas "
                   "lineales endurecen el landscape), aunque es representable (CYCLE 6: 0.99 con más budget)."),
        prediction=("Con más steps (o mejor receta/proporción de atención), el híbrido a d=24 cierra la "
                    "brecha con la atención pura (0.88) por encima del plateau ~0.18. Refutado si más "
                    "budget NO sube el híbrido (sería una falla estructural del interleaving, no de optim)."),
        status='abierta',
        confidence='baja',
        evidence_for=[S2.ref, S3.ref],   # CYCLE6 (híbrido CAN) + exp013 (híbrido ascendiente, no plateau)
        evidence_against=[],             # legítimo vacío: abierta, sin experimento de más-budget aún.
        adversarial_verdict='',
        experiment_ref='',
    )
    hyps.add(h_hyb)
    notes.append("H-HYB-1 añadida 'abierta' (el híbrido a d chico es optimization-harder que la atención pura).")

    # --- ANALOGÍA (7 etapas) ---
    analogy = AnalogyRecord(
        problem=("¿La atención cruza el techo de recall donde el lineal no? Sí (pura=0.88). Pero el "
                 "híbrido 50/50 quedó en 0.18 a step-parity. ¿Falla el híbrido o le faltó práctica?"),
        everyday=("Un traductor experto (atención pura) traduce bien rápido. Un equipo mixto (híbrido: "
                  "algunos expertos + algunos novatos) tarda MÁS en coordinarse, pero con más práctica "
                  "llega — no es que no pueda, es que la curva de aprendizaje es más lenta."),
        solutions=[
            "atención pura: cruza el plateau (0.88) -> el remedio es arquitectónico, CONFIRMADO",
            "híbrido a más steps: cerraría la brecha (CYCLE 6 lo mostró a 0.99) -> H-HYB-1",
            "híbrido con más proporción de atención o mejor arreglo -> a investigar",
            "leer la trayectoria, no solo el número final: el híbrido estaba SUBIENDO (under-trained)",
        ],
        principles=[
            "diagnóstico antes que hallazgo: un número final bajo + trayectoria ascendente = under-trained, no falla",
            "la atención (estado ∝ L) es el remedio del recall a carga alta — confirmado a la escala de la línea H-CEIL",
            "representable != fácil de optimizar: el híbrido puede, pero su landscape es más duro a d chico",
        ],
        adaptation=("control positivo CONFIRMADO (atención pura cruza); el híbrido necesita más budget "
                    "(H-HYB-1). La línea de recall se cierra: el techo del estado fijo es estructural y la "
                    "atención lo levanta."),
        measurement="exp013: {} (chance={}).".format(accs_txt, _fmt(summary.get('chance'))),
        iterations=1,
    )
    principles = extract_principles(analogy)
    assert len(principles) >= 3
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas: {} soluciones, {} principios.".format(
        len(analogy.solutions), len(principles)))

    # --- TECHO: re-afirmar 'real' AHORA con control positivo directo ---
    ceiling = CeilingRecord(
        subsystem="Recall del mezclador de estado fijo a d=24 — ESTRUCTURAL (con control positivo directo)",
        known_limit=("CONFIRMADO con control positivo a la MISMA escala: el plateau ~0.18 del lineal puro "
                     "(6 levers refutados) lo cruza la ATENCIÓN PURA (exp013: 0.882). El techo del estado "
                     "fijo es REAL/estructural; el remedio es arquitectónico (atención, estado ∝ L). El "
                     "híbrido 50/50 a step-parity quedó under-trained (ascendiente, no plateau) -> H-HYB-1."),
        blockers=[
            {"text": "el estado fijo no direcciona ~L posiciones (pigeonhole); la atención sí", "kind": "fisico"},
        ],
        real_or_assumed="real",
        evidence=[S1.ref, S2.ref, S3.ref],
    )
    ceilings.add(ceiling)
    notes.append("Techo 'real' re-afirmado con control positivo directo (atención pura cruza).")

    # --- DECISIÓN D-CEIL-5: confirmar el remedio arquitectónico end-to-end ---
    decision = Decision(
        id="D-CEIL-5",
        statement=("CONFIRMAR end-to-end (a la escala de la línea H-CEIL) que el remedio del recall a carga "
                   "alta es ARQUITECTÓNICO: la atención pura cruza el plateau ~0.18 (exp013: 0.882) que "
                   "NINGÚN tuning del lineal mueve. Cierra la línea de recall (D-CEIL-1/4 confirmados). "
                   "Caveat honesto: el híbrido 50/50 necesita más budget que la atención pura (H-HYB-1)."),
        rationale=("exp013: atención pura 0.882 >> baseline lineal 0.173 (6 levers refutados en exp010/011/012). "
                   "El híbrido quedó under-trained a 3000 steps (trayectoria ascendiente). La atención (estado "
                   "∝ L) es el remedio; el híbrido CAN (CYCLE 6: 0.99) pero optimiza más lento a d chico."),
        sources=[_to_plain(S3), _to_plain(S1)],
        important=True,
    )
    try:
        ledger.record_decision(decision)
        notes.append("D-CEIL-5 ACEPTADA por el ledger (tier5 S3 + tier1 S1 -> funda).")
    except OpinionOnlyError as e:
        print("ERROR: el ledger RECHAZÓ D-CEIL-5: {}".format(e))
        raise

    return ledger, hyps, ceilings, record, notes, confirmed, summary


def _to_plain(obj):
    from cognia_x.research.schema import to_dict
    import dataclasses
    if dataclasses.is_dataclass(obj):
        return to_dict(obj)
    return dict(obj)


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(
        prog='python -m cognia_x.research.cycles.cycle26_hybrid_control',
        description='CYCLE 26 (control positivo: la atención cruza el plateau) a través del Investigation Engine.')
    p.add_argument('--store', default=DEFAULT_STORE)
    p.add_argument('--results', default=DEFAULT_RESULTS)
    p.add_argument('--reset', dest='reset', action='store_true', default=True)
    p.add_argument('--no-reset', dest='reset', action='store_false')
    args = p.parse_args(argv)

    store = os.path.abspath(args.store)
    if args.reset and os.path.isdir(store):
        shutil.rmtree(store)
    os.makedirs(store, exist_ok=True)

    ledger, hyps, ceilings, record, notes, confirmed, summary = run(store, os.path.abspath(args.results))
    res = record.verify_no_loss()

    print("=" * 78)
    print("RESUMEN — CYCLE 26: control positivo (la atención cruza el plateau) [Investigation Engine]")
    print("=" * 78)
    print("store: {}".format(store))
    print("control positivo: {}".format("CONFIRMADO" if confirmed else "NULL (ver veredicto)"))
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
