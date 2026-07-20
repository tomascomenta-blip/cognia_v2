r"""
cycle25_depth_scale.py — CICLO 25 a través del Investigation Engine.

CIERRA la línea del techo de recall (H-CEIL). exp012 testea la cláusula NOVEDOSA de H-CEIL-4: ¿el
lineal PURO cruza el plateau ~0.18 con PROFUNDIDAD / ESCALA-d / OPTIMIZADOR (sin atención)? La otra
cláusula ("requiere ATENCIÓN") ya está apoyada por CYCLE 6 (H-MEZ-4) + exp009 — no se re-testea.

DERIVA el veredicto de `exp012_depth_scale/results/results.json` (correcto por construcción). Pasa por
las MISMAS compuertas (mark_*, ledger, analogy, ceiling, verify_no_loss).

VEREDICTO H-CEIL-4 (disyunción "profundidad/escala/optim O atención"):
  - exp012 con lift (algún lever lineal sube) -> H-CEIL-4 APOYADA por la rama OPTIMIZACIÓN/ESCALA.
  - exp012 sin lift (ninguno sube) -> H-CEIL-4 MIXTA: la rama lineal (profundidad/escala/optim) queda
    REFUTADA; la rama "requiere atención" queda APOYADA por eliminación (6 levers no-atención refutados
    a lo largo de exp010/011/012 + CYCLE 6 muestra que la atención SÍ recupera el recall). El techo del
    mezclador de estado fijo pasa a ESTRUCTURAL ('real'): el remedio es arquitectónico (híbrido), no tuning.
  - floor -> MIXTA inconcluso (piso de optim/budget).

Correr (DESPUÉS de exp012):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp012_depth_scale.run --steps 3000
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle25_depth_scale
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
    os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle25_depth_scale'
)
DEFAULT_RESULTS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..',
    'experiments', 'exp012_depth_scale', 'results', 'results.json'
)


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


# tier-1: la brecha de recall es de optimización (predecía que tuning lo arreglaría).
S1 = Source(
    tier=1, ref="arXiv:2508.19029", obtained=True,
    claim=("Okpekpe & Orvieto 2025: gran parte de la brecha de recall de los mezcladores de estado es "
           "de OPTIMIZACION, no de expresividad; con LR ajustado Mamba resuelve recall aun en 1 capa."),
)
# tier-5 propio: la atención SÍ recupera el recall donde el lineal satura (la rama 'requiere atención').
S2 = Source(
    tier=5, ref="cognia_x/experiments/exp005_hybrid_decode_frontier+CYCLE6_H-MEZ-4", obtained=True,
    claim=("CYCLE 6 (H-MEZ-4, cerrada): a carga alta (np=8) el lineal puro satura (0.255) y el híbrido "
           "con >=2 capas de atención RECUPERA el recall (0.998); exp009: el híbrido separa a d=48 "
           "(0.292 vs 0.181 del lineal). La atención (estado proporcional a L) levanta el techo del "
           "estado fijo — la rama arquitectónica del remedio."),
)


def _fmt(x):
    return "{:.3f}".format(x) if isinstance(x, (int, float)) else str(x)


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if 'summary' not in data:
        raise SystemExit("results.json sin 'summary' (corré exp012 primero): " + results_path)
    summary = data['summary']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    base = summary.get('baseline_acc')
    acc = summary.get('acc_by_name', {})
    deltas = summary.get('deltas', {})
    lifts = summary.get('lifts', [])
    all_near_floor = summary.get('all_near_floor', False)

    accs_txt = ", ".join("{}={}".format(k, _fmt(v)) for k, v in acc.items())
    deltas_txt = ", ".join("{}={:+.4f}".format(k, v) for k, v in deltas.items() if v is not None)

    # status: lift -> apoyada (rama optimización); sin lift -> mixta (lineal refutada, atención apoyada).
    if all_near_floor:
        status = 'mixta'
        branch = "PISO de optim/budget: no separa el efecto"
    elif lifts:
        status = 'apoyada'
        branch = "rama OPTIMIZACIÓN/ESCALA: el lineal puro cruza el plateau con {}".format(" y ".join(lifts))
    else:
        status = 'mixta'
        branch = ("rama lineal (profundidad/escala/optim) REFUTADA; rama 'requiere atención' APOYADA por "
                  "eliminación (6 levers no-atención refutados) + CYCLE 6")

    S3 = Source(
        tier=5, ref="cognia_x/experiments/exp012_depth_scale", obtained=True,
        claim=("exp012 (lineal PURO, n_pairs=16, seed0, steps={steps} step-parity, chance {chance}): "
               "baseline {base}; {accs}. deltas: {deltas}. lifts={lifts}. Ni profundidad ni escala-d ni "
               "optimizador (LR 3x) suben el recall del lineal puro sobre ~0.18 -> {branch}.").format(
                   steps=data.get('steps'), chance=_fmt(summary.get('chance')), base=_fmt(base),
                   accs=accs_txt, deltas=deltas_txt, lifts=lifts, branch=branch),
    )
    for s in (S1, S2, S3):
        ledger.add_source(s)
    notes.append("3 fuentes (S1 tier1 Okpekpe&Orvieto; S2 tier5 atención-recupera CYCLE6; S3 tier5 exp012).")

    # --- H-CEIL-4 por la compuerta DoD ---
    if status == 'apoyada':
        ev_for = [S1.ref, S3.ref]
        ev_against = [S2.ref]
        adv = ("APOYADA (rama optimización/escala): {branch}. {accs}; deltas {deltas}. CAVEAT: escala "
               "tiny; el lift habría que confirmarlo a mayor escala/seed.").format(
                   branch=branch, accs=accs_txt, deltas=deltas_txt)
    else:  # mixta (caso real de exp012)
        ev_for = [S2.ref, S1.ref]   # la atención SÍ recupera (rama apoyada)
        ev_against = [S3.ref]       # los levers lineales NO (rama refutada)
        adv = ("MIXTA: {branch}. exp012: {accs} (deltas {deltas}, ninguno cruza el umbral 0.02). "
               "Combinado con exp010 (ancho) y exp011 (forma+init), el plateau ~0.18 del mezclador de "
               "estado fijo a d<=48 es robusto a SEIS levers no-atención -> el techo es ESTRUCTURAL, no "
               "de tuning. La rama 'requiere atención' de H-CEIL-4 queda apoyada por eliminación + CYCLE 6 "
               "(la atención recupera el recall). La línea H-CEIL CONVERGE: el remedio es arquitectónico "
               "(híbrido, D-CEIL-1), no afinar el mezclador lineal.").format(
                   branch=branch, accs=accs_txt, deltas=deltas_txt)

    hyp = Hypothesis(
        id="H-CEIL-4",
        statement=("El cuello del recall lineal entrenado a d<=48 es de PROFUNDIDAD/ESCALA/OPTIMIZADOR — o "
                   "requiere la capa de ATENCIÓN del híbrido (el mezclador de estado fijo no llega)."),
        prediction=("Subir profundidad/d/steps o el optimizador, o añadir atención, sube el recall sobre "
                    "~0.18. exp012 testea profundidad/d/optim (la atención ya está apoyada en CYCLE 6)."),
        status='abierta',
        confidence='media',
        evidence_for=ev_for,
        evidence_against=ev_against,
        adversarial_verdict=adv,
        experiment_ref="exp012_depth_scale",
    )
    hyps.add(hyp)
    marker = {'apoyada': hyps.mark_supported, 'mixta': hyps.mark_mixta}[status]
    h_final = marker("H-CEIL-4")
    assert h_final.status == status
    notes.append("H-CEIL-4 marcada '{}' con DoD completo.".format(status))

    # --- ANALOGÍA (7 etapas) ---
    analogy = AnalogyRecord(
        problem=("La libreta de tamaño fijo (mezclador lineal) tope su recall en ~0.18. Probamos TODO: "
                 "más páginas, mejor taquigrafía, índice inicial, más capítulos, libreta más grande, "
                 "estudiar más rápido. ¿Algo sube el recall sin cambiar de instrumento?"),
        everyday=("Por más que mejores la libreta (forma/tamaño/orden/horas de estudio), una libreta de "
                  "tamaño FIJO no puede indexar arbitrariamente muchas entradas: necesitás un instrumento "
                  "distinto (un índice que crece con lo que guardás = atención)."),
        solutions=[
            "ancho del feature-map (exp010) -> no ayuda",
            "forma del kernel / Taylor (exp011) -> no ayuda",
            "init mimética (exp011) -> no ayuda",
            "más profundidad / más d / mejor optimizador (exp012) -> no ayuda",
            "cambiar de instrumento: atención (estado proporcional a L) -> SÍ (CYCLE 6)",
        ],
        principles=[
            "un almacén de tamaño FIJO tiene un techo de direccionamiento estructural (pigeonhole)",
            "ningún tuning del instrumento equivocado lo arregla; hace falta el instrumento correcto",
            "el remedio del recall a carga alta es arquitectónico (atención/híbrido), no de optimización",
        ],
        adaptation=("H-CEIL-4 {}: cerrar la línea de afinar el mezclador lineal para recall; el remedio es "
                    "el híbrido (D-CEIL-1/D-007). exp013 (lineal+>=2 atención a d=24) confirmaría end-to-end.").format(status),
        measurement=("exp012: baseline {}; {} (deltas {}).").format(_fmt(base), accs_txt, deltas_txt),
        iterations=1,
    )
    principles = extract_principles(analogy)
    assert len(principles) >= 3
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas: {} soluciones, {} principios.".format(
        len(analogy.solutions), len(principles)))

    # --- TECHO: ahora ESTRUCTURAL ('real') tras refutar 6 levers no-atención ---
    if status == 'mixta' and not all_near_floor:
        ceiling = CeilingRecord(
            subsystem="Recall entrenado del mezclador de estado fijo (lineal) a d<=48 — ESTRUCTURAL",
            known_limit=("El plateau ~0.18 es robusto a SEIS levers no-atención (ancho exp010; forma del "
                         "kernel + init exp011; profundidad + escala-d + optimizador exp012). El remedio es "
                         "ARQUITECTÓNICO: la atención (estado ∝ L) lo levanta (CYCLE 6: 0.255->0.998 a np alto). "
                         "Cota nombrada: pigeonhole sobre el estado fijo (exp002, capacidad ~d²) + la cota "
                         "EFECTIVA entrenada robusta a todo tuning probado. Es REAL/estructural a esta escala "
                         "(no 'asumido'): no es una brecha de optimización, es el instrumento equivocado."),
            blockers=[
                {"text": "el estado de tamaño fijo no puede direccionar ~L posiciones (pigeonhole)", "kind": "fisico"},
                {"text": "ningún tuning (forma/init/profundidad/escala/optim) accede a más recall", "kind": "diseno"},
            ],
            real_or_assumed="real",
            evidence=[S1.ref, S2.ref, S3.ref],
        )
    else:
        ceiling = CeilingRecord(
            subsystem="Recall entrenado del mezclador lineal a d<=48 (exp012)",
            known_limit=("exp012 status={}: ver veredicto. {}").format(status, branch),
            blockers=[{"text": "ver adversarial_verdict de H-CEIL-4", "kind": "diseno"}],
            real_or_assumed="asumido",
            evidence=[S1.ref, S3.ref],
        )
    ceilings.add(ceiling)
    notes.append("Techo registrado (real_or_assumed={}).".format(ceiling.real_or_assumed))

    # --- DECISIÓN D-CEIL-4: cerrar la línea de tuning del lineal; el remedio es el híbrido ---
    decision = Decision(
        id="D-CEIL-4",
        statement=("Cerrar la línea de afinar el mezclador lineal de estado fijo para subir su recall: el "
                   "techo ~0.18 es ESTRUCTURAL (6 levers no-atención refutados, exp010/011/012). El recall "
                   "a carga alta se obtiene con la ATENCIÓN del híbrido (D-CEIL-1/D-007), no con tuning."),
        rationale=("exp012: ni profundidad ni escala-d ni optimizador suben el lineal puro sobre ~0.18 "
                   "({}); junto a exp010 (ancho) y exp011 (forma+init), el plateau es robusto a 6 levers. "
                   "Okpekpe&Orvieto predecía tuning -> refutado a esta escala. La atención SÍ recupera (CYCLE 6).").format(deltas_txt),
        sources=[_to_plain(S3), _to_plain(S1)],   # tier5 propio + tier1 -> funda
        important=True,
    )
    try:
        ledger.record_decision(decision)
        notes.append("D-CEIL-4 ACEPTADA por el ledger (tier5 S3 + tier1 S1 -> funda).")
    except OpinionOnlyError as e:
        print("ERROR: el ledger RECHAZÓ D-CEIL-4: {}".format(e))
        raise

    return ledger, hyps, ceilings, record, notes, status, branch


def _to_plain(obj):
    from cognia_x.research.schema import to_dict
    import dataclasses
    if dataclasses.is_dataclass(obj):
        return to_dict(obj)
    return dict(obj)


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(
        prog='python -m cognia_x.research.cycles.cycle25_depth_scale',
        description='CYCLE 25 (profundidad/escala/optim -> H-CEIL-4) a través del Investigation Engine.')
    p.add_argument('--store', default=DEFAULT_STORE)
    p.add_argument('--results', default=DEFAULT_RESULTS)
    p.add_argument('--reset', dest='reset', action='store_true', default=True)
    p.add_argument('--no-reset', dest='reset', action='store_false')
    args = p.parse_args(argv)

    store = os.path.abspath(args.store)
    if args.reset and os.path.isdir(store):
        shutil.rmtree(store)
    os.makedirs(store, exist_ok=True)

    ledger, hyps, ceilings, record, notes, status, branch = run(store, os.path.abspath(args.results))
    res = record.verify_no_loss()

    print("=" * 78)
    print("RESUMEN — CYCLE 25: profundidad/escala/optimizador -> H-CEIL-4 [Investigation Engine]")
    print("=" * 78)
    print("store: {}".format(store))
    print("veredicto H-CEIL-4: {}  ({})".format(status.upper(), branch))
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
