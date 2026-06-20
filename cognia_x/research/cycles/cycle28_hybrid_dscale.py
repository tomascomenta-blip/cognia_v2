r"""
cycle28_hybrid_dscale.py — CICLO 28 a través del Investigation Engine.

H-HYB-2 (CYCLE 27): la recuperación de recall del híbrido es d-dependiente (a d=24 bottleneckea por la
baja capacidad lineal; subir d lo arreglaría, reconciliando con CYCLE 6 a d=64). exp015 lo TESTEA con un
barrido de d (24/48/64, attn_every=2, np=16) — y lo REFUTA.

RESULTADO (exp015, hibrido 2lin+2attn, n_heads=4, n_pairs=16, seed0, steps=6000):
  - hibrido_d24 = 0.189 ; hibrido_d48 = 0.253 ; hibrido_d64 = 0.190.
  - NO recupera (umbral 0.40) a NINGÚN d, y NO es monótono en d (d48=0.253 > d64=0.190).

VEREDICTO: H-HYB-2 REFUTADA — el cuello del híbrido NO es solo d. A np=16 con el arreglo interleaved
(lineal-primero), ni d=64 recupera recall. TENSIÓN con CYCLE 6 (d=64 -> 0.99) RECONCILIADA: aquel era
np=8 (carga baja); aquí np=16. -> la recuperación del híbrido depende de la CARGA (np) y/o el ARREGLO
(lineal-primero destruye la asociación clave-valor antes de la atención), no de d. Caveat REAL a D-007.
Genera H-HYB-3 (arreglo/carga). PERO: la sub-línea del híbrido (H-HYB-1->2->3) está en rendimientos
decrecientes (cada ciclo refuta y genera el siguiente sobre una pregunta cada vez más estrecha) -> se
PAUSA tras registrar; la conclusión central de la línea de recall (lineal=estructural, atención=remedio)
no cambia.

DERIVA de exp015/results.json. Pasa por las compuertas.

Correr (DESPUÉS de exp015):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp015_hybrid_dscale.run --steps 6000
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle28_hybrid_dscale
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
    os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle28_hybrid_dscale'
)
DEFAULT_RESULTS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..',
    'experiments', 'exp015_hybrid_dscale', 'results', 'results.json'
)


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


# tier-5: CYCLE 6 — el híbrido a 0.99, PERO a d=64 y np=8 (carga baja). La 'evidencia a favor' que NO se cumplió a np=16.
S1 = Source(
    tier=5, ref="CYCLE6_H-MEZ-4", obtained=True,
    claim=("CYCLE 6 (H-MEZ-4): el híbrido recupera recall (0.99) a d=64 PERO con np=8 (carga baja). "
           "Predecía que subir d arreglaría el híbrido a d=24; exp015 lo refuta a np=16."),
)


def _fmt(x):
    return "{:.3f}".format(x) if isinstance(x, (int, float)) else str(x)


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if 'summary' not in data:
        raise SystemExit("results.json sin 'summary' (corré exp015 primero): " + results_path)
    summary = data['summary']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    acc = summary.get('acc_by_name', {})
    recovered = summary.get('recovered', [])
    accs_txt = ", ".join("{}={}".format(k, _fmt(v)) for k, v in acc.items())
    status = 'apoyada' if recovered else 'refutada'

    S2 = Source(
        tier=5, ref="cognia_x/experiments/exp015_hybrid_dscale", obtained=True,
        claim=("exp015 (hibrido 2lin+2attn, n_heads=4, n_pairs=16, seed0, steps=6000, barrido de d): "
               "{accs}. NO recupera recall (umbral 0.40) a ningún d, y NO monótono en d (d48 > d64). "
               "A np=16 con interleaved lineal-primero, ni d=64 recupera (vs CYCLE 6 a np=8: 0.99).").format(accs=accs_txt),
    )
    for s in (S1, S2):
        ledger.add_source(s)
    notes.append("2 fuentes (S1 tier5 CYCLE6-a-np8; S2 tier5 exp015 barrido de d).")

    # --- H-HYB-2: REFUTADA ---
    h2 = Hypothesis(
        id="H-HYB-2",
        statement=("La recuperación de recall del híbrido es d-dependiente: subir d (24->48->64) hace que "
                   "el híbrido cruce el plateau ~0.18 que tiene a d=24."),
        prediction=("hibrido_d48/d64 recuperan recall (>= 0.40). Refutado si siguen ~0.18 aun a d=64."),
        status='abierta',
        confidence='media',
        evidence_for=[S1.ref],     # CYCLE6 (d=64 funcionó a np=8)
        evidence_against=[S2.ref],  # exp015 (d=64 a np=16 = 0.19, no recupera; no monótono)
        adversarial_verdict=(
            "REFUTADA: el híbrido NO recupera a ningún d ({}) y NO es monótono en d (d48=0.253 > "
            "d64=0.190). El cuello NO es solo d. RECONCILIA la tensión con CYCLE 6 (d=64 -> 0.99): aquel era "
            "np=8 (carga baja), este np=16 -> la recuperación del híbrido depende de la CARGA (np) y/o el "
            "ARREGLO (lineal-primero destruye la asociación clave-valor antes de la atención). Genera "
            "H-HYB-3.").format(accs_txt),
        experiment_ref="exp015_hybrid_dscale",
    )
    hyps.add(h2)
    marker = {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted}[status]
    hf = marker("H-HYB-2"); assert hf.status == status
    notes.append("H-HYB-2 marcada '{}' con DoD completo.".format(status))

    # --- H-HYB-3 (abierta) SOLO si se refutó ---
    if status == 'refutada':
        h3 = Hypothesis(
            id="H-HYB-3",
            statement=("El cuello del híbrido a carga alta (np=16) es el ARREGLO (lineal-primero) y/o la "
                       "CARGA (np), no d: poner la atención PRIMERA (o subir el ratio de atención, o bajar np) "
                       "hace que el híbrido recupere recall donde el interleaved lineal-primero no."),
            prediction=("Un híbrido atención-primero (o más atención, o np menor) cruza el plateau a d<=64. "
                        "Refutado si tampoco."),
            status='abierta',
            confidence='baja',
            evidence_for=[S1.ref, S2.ref],
            evidence_against=[],
            adversarial_verdict='',
            experiment_ref='',
        )
        hyps.add(h3)
        notes.append("H-HYB-3 añadida 'abierta' (arreglo/carga, no d) — PERO la sub-línea se PAUSA (ver decisión).")

    # --- ANALOGÍA ---
    analogy = AnalogyRecord(
        problem=("¿El híbrido recupera recall si agrando d? exp015: no — ni a d=64 (np=16), y no monótono "
                 "(d48 > d64). ¿Entonces de qué depende?"),
        everyday=("Un equipo mixto (lineales novatos + expertos de atención) no mejora por contratar gente "
                  "más capaz (d mayor) si el novato va PRIMERO y pierde la info antes de que el experto la "
                  "vea — y empeora si hay MÁS casos que atender (np alto). El orden y la carga mandan, no el tamaño."),
        solutions=[
            "subir d (más capacidad lineal) -> NO recupera (exp015: d64=0.19)",
            "poner la atención primero (no lineal-primero) -> a investigar (H-HYB-3)",
            "bajar la carga np -> CYCLE 6 funcionó a np=8 -> la carga importa",
            "atención pura -> recupera siempre (0.95, exp013/014) -> el remedio robusto",
        ],
        principles=[
            "el cuello del híbrido NO es la capacidad (d) sino el ARREGLO y la CARGA",
            "lineal-primero puede destruir la asociación clave-valor antes de que la atención la use",
            "la atención pura es el remedio ROBUSTO del recall; el híbrido es frágil a arreglo/carga",
        ],
        adaptation=("H-HYB-2 refutada (no es d) -> caveat fuerte a D-007: el híbrido naive no recupera recall "
                    "robustamente. H-HYB-3 (arreglo/carga) queda documentada pero la sub-línea se PAUSA."),
        measurement="exp015: {}.".format(accs_txt),
        iterations=1,
    )
    principles = extract_principles(analogy)
    assert len(principles) >= 3
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas: {} soluciones, {} principios.".format(
        len(analogy.solutions), len(principles)))

    # --- TECHO ---
    ceiling = CeilingRecord(
        subsystem="Recuperación de recall del híbrido interleaved a carga alta (np=16) — NO es d",
        known_limit=("exp015: el híbrido (2lin+2attn, lineal-primero) NO recupera recall a ningún d "
                     "(d24=0.189, d48=0.253, d64=0.190) a np=16; no monótono en d. El cuello es el ARREGLO "
                     "(lineal-primero) y/o la CARGA (np), no d. Reconcilia con CYCLE 6 (funcionó a np=8). "
                     "La atención pura recupera robustamente (0.95). ASUMIDO (H-HYB-3 a investigar; sub-línea pausada)."),
        blockers=[
            {"text": "arreglo lineal-primero destruye la asociación clave-valor antes de la atención", "kind": "diseno"},
            {"text": "carga alta (np=16) excede lo que las pocas capas de atención manejan con el bottleneck lineal", "kind": "diseno"},
        ],
        real_or_assumed="asumido",
        evidence=[S1.ref, S2.ref],
    )
    ceilings.add(ceiling)
    notes.append("1 techo 'asumido' añadido (el cuello del híbrido es arreglo/carga, no d).")

    # --- DECISIÓN D-HYB-2: caveat FUERTE a D-007 + PAUSAR la sub-línea ---
    decision = Decision(
        id="D-HYB-2",
        statement=("Reforzar el caveat a D-007: el híbrido naive (interleaved lineal-primero) NO recupera "
                   "recall robustamente — no lo arregla subir d (exp015); depende del ARREGLO y la CARGA "
                   "(funcionó solo a d=64/np=8 en CYCLE 6). La ATENCIÓN PURA es el remedio robusto del recall. "
                   "PAUSAR la sub-línea del híbrido (H-HYB-3) por rendimientos decrecientes; retomar con "
                   "orientación o pivotar a F-LEARN-2 (prioridad #2)."),
        rationale=("exp015: hibrido d24=0.189, d48=0.253, d64=0.190 (np=16) — no recupera a ningún d, no "
                   "monótono. Refuta H-HYB-2 (no es d). La sub-línea H-HYB-1->2->3 está en rendimientos "
                   "decrecientes (refuta y genera sobre una pregunta cada vez más estrecha); la conclusión "
                   "central de la línea de recall (lineal=estructural, atención=remedio) ya es sólida."),
        sources=[_to_plain(S2), _to_plain(S1)],
        important=True,
    )
    try:
        ledger.record_decision(decision)
        notes.append("D-HYB-2 ACEPTADA por el ledger (2 tier5 propios obtenidos).")
    except OpinionOnlyError as e:
        print("ERROR: el ledger RECHAZÓ D-HYB-2: {}".format(e))
        raise

    return ledger, hyps, ceilings, record, notes, status, acc


def _to_plain(obj):
    from cognia_x.research.schema import to_dict
    import dataclasses
    if dataclasses.is_dataclass(obj):
        return to_dict(obj)
    return dict(obj)


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(
        prog='python -m cognia_x.research.cycles.cycle28_hybrid_dscale',
        description='CYCLE 28 (H-HYB-2: el hibrido recupera al subir d?) a través del Investigation Engine.')
    p.add_argument('--store', default=DEFAULT_STORE)
    p.add_argument('--results', default=DEFAULT_RESULTS)
    p.add_argument('--reset', dest='reset', action='store_true', default=True)
    p.add_argument('--no-reset', dest='reset', action='store_false')
    args = p.parse_args(argv)

    store = os.path.abspath(args.store)
    if args.reset and os.path.isdir(store):
        shutil.rmtree(store)
    os.makedirs(store, exist_ok=True)

    ledger, hyps, ceilings, record, notes, status, acc = run(store, os.path.abspath(args.results))
    res = record.verify_no_loss()

    print("=" * 78)
    print("RESUMEN — CYCLE 28: H-HYB-2 (el hibrido recupera al subir d?) [Investigation Engine]")
    print("=" * 78)
    print("store: {}".format(store))
    print("veredicto H-HYB-2: {}  ({})".format(status.upper(),
          ", ".join("{}={}".format(k, _fmt(v)) for k, v in acc.items())))
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
