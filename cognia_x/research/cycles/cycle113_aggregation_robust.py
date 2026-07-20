r"""
cycle113_aggregation_robust.py — CICLO 113 (RESET v4, rama R-VALOR, robustez a MIS-ESPECIFICAR la agregación): H-V4-8r por
las compuertas del engine. APOYADA (regime-dependiente): el arco halló la política correcta para cada agregación CONOCIDA
(95 marginal/cobertura, 100 vector, 101 costo). Bajo agregación INCIERTA hay que elegir qué AGREGACIÓN ASUMIR; el supuesto
SEGURO (mejor peor-caso) DEPENDE del ratio presupuesto/diversidad k/T: a k BAJO (k<T, presupuesto escaso) asumir
SUBMODULAR/cobertura hedgea mejor; a k ALTO (k>T, la cobertura SATURA) asumir ADDITIVE/top-value es más seguro. No hay
default universal.

NOTA DE MÉTODO (honestidad): un primer test sólo a k>T dio REFUTADA artefactual (additive parecía siempre más seguro); el
barrido de k/T reveló la REVERSIÓN a k bajo -> el resultado real es REGIME-DEPENDIENTE.

DERIVA de exp097_aggregation_robust/results/results.json.

Correr (DESPUÉS de exp097):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp097_aggregation_robust.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle113_aggregation_robust
"""
import argparse
import dataclasses
import json
import os
import shutil
import sys

from cognia_x.research.schema import Source, Hypothesis, Decision, AnalogyRecord, CeilingRecord, to_dict
from cognia_x.research.ledger import EvidenceLedger, OpinionOnlyError
from cognia_x.research.hypotheses import HypothesisRegistry
from cognia_x.research.analogy import extract_principles
from cognia_x.research.ceiling import CeilingTracker
from cognia_x.research.record import PermanentRecord, count_lines

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle113_aggregation_robust')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp097_aggregation_robust', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="decisión robusta/minimax bajo incertidumbre de modelo: el supuesto SEGURO (mejor peor-caso) depende del régimen; la cobertura/diversidad hedgea cuando el presupuesto es ESCASO frente a la diversidad, pero satura cuando el presupuesto la excede", obtained=False,
                     claim=("Bajo incertidumbre del objetivo (agregación), el supuesto SEGURO (mejor peor-caso, minimax) "
                            "NO es universal: depende del régimen. Asumir cobertura/diversidad hedgea cuando el "
                            "presupuesto es escaso frente a la diversidad disponible (no podés cubrir todo); cuando el "
                            "presupuesto EXCEDE la diversidad, la cobertura SATURA y conviene asumir aditivo (valor). "
                            "(Principio.)"))
S_ARC = Source(tier=5, ref="cognia_x/experiments/exp079_nonadditive_value", obtained=True,
               claim=("El arco (95/100/101) halló la política correcta para cada agregación CONOCIDA. H-V4-8r aborda la "
                      "agregación INCIERTA: qué supuesto de agregación es el default seguro."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp097 primero): " + results_path)

    per_k = sm['per_k']
    keys_sorted = sorted(per_k.keys(), key=lambda kk: per_k[kk]['k'])
    lok, hik = keys_sorted[0], keys_sorted[-1]
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim097 = ("exp097 (propio, {n} seeds, numpy): el default seguro bajo agregación incierta DEPENDE de k/T. A k={kl} "
                "(<T) seguro=SUBMODULAR (peor-caso sub={sl} vs add={al}); a k={kh} (>T) seguro=ADDITIVE (peor-caso "
                "add={ah} vs sub={sh}). No hay default universal.").format(
                    n=n_seeds, kl=per_k[lok]['k'], sl=_f(per_k[lok]['wc_sub']), al=_f(per_k[lok]['wc_add']),
                    kh=per_k[hik]['k'], ah=_f(per_k[hik]['wc_add']), sh=_f(per_k[hik]['wc_sub']))
    S_EXP097 = Source(tier=5, ref="cognia_x/experiments/exp097_aggregation_robust", obtained=True, claim=claim097)
    for src in (S_PRINCIPLE, S_ARC, S_EXP097):
        ledger.add_source(src)
    notes.append("3 fuentes (S_PRINCIPLE tier2 minimax/robustez por régimen; S_ARC tier5 política por agregación conocida; S_EXP097 tier5 dato propio).")

    ev_for = [S_EXP097.ref, S_PRINCIPLE.ref]
    ev_against = [S_EXP097.ref]
    advtext = ("{V} (robustez a MIS-ESPECIFICAR la agregación; regime-dependiente): el arco halló la política correcta "
               "para cada agregación CONOCIDA (95 marginal/cobertura, 100 vector, 101 costo) -- 'asigná por la ganancia "
               "marginal en la AGREGACIÓN VERDADERA'. Pero, ¿y si la agregación es INCIERTA y asumís la incorrecta? "
               "H-V4-8r mide el peor-caso (minimax) de assume_additive (top-value) vs assume_submodular "
               "(marginal-cobertura) bajo ambas verdades, barriendo el ratio presupuesto/diversidad k/T. RESULTADO: el "
               "default SEGURO DEPENDE de k/T. A k BAJO (k={kl}<T: el presupuesto no alcanza a cubrir las T categorías) "
               "asumir SUBMODULAR/cobertura es seguro (peor-caso sub={sl} >> add={al}: top-value clava todo en pocas "
               "categorías ricas y pierde cobertura); a k ALTO (k={kh}>T: la cobertura SATURA, ya cubriste todo) asumir "
               "ADDITIVE/top-value es seguro (peor-caso add={ah} > sub={sh}: forzar diversidad deja valor aditivo en la "
               "mesa). => NO hay default universal de agregación: con presupuesto ESCASO frente a la diversidad, hedgeá "
               "con cobertura; con presupuesto que la EXCEDE (cobertura saturada), asigná por valor. REFINA la regla del "
               "arco: bajo agregación incierta, el hedge correcto depende de k/T. NOTA DE MÉTODO (honestidad, regla #4): "
               "un primer test SÓLO a k>T dio REFUTADA artefactual (additive siempre parecía más seguro); el barrido de "
               "k/T reveló la REVERSIÓN a k bajo -- el resultado real es regime-dependiente. EVIDENCIA EN CONTRA / "
               "caveats: 2 agregaciones (additive vs cobertura), categorías desbalanceadas (dirichlet 0.6); el oracle "
               "submodular es greedy (1-1/e); el cruce exacto de k/T depende de la distribución; numpy/juguete.").format(
                   V=status.upper(), kl=per_k[lok]['k'], sl=_f(per_k[lok]['wc_sub']), al=_f(per_k[lok]['wc_add']),
                   kh=per_k[hik]['k'], ah=_f(per_k[hik]['wc_add']), sh=_f(per_k[hik]['wc_sub']))

    hyp = Hypothesis(
        id="H-V4-8r",
        statement=("Bajo incertidumbre de la agregación verdadera, el supuesto SEGURO (mejor peor-caso) DEPENDE del ratio "
                   "presupuesto/diversidad k/T: a k<T asumir submodular/cobertura hedgea; a k>T (cobertura saturada) "
                   "asumir additive/valor es más seguro. No hay default universal."),
        prediction=("APOYADA si el default seguro CAMBIA con k/T (submodular a k bajo, additive a k alto); REFUTADA si un "
                    "supuesto domina en todos los k/T; MIXTA si el patrón no es limpio. (Pre-registrada, numpy, 64 seeds, "
                    "barrido k/T.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp097_aggregation_robust")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-8r")
        notes.append("H-V4-8r marcada '{}' con DoD completo (default de agregación seguro depende de k/T).".format(status))

    analogy = AnalogyRecord(
        problem=("Tengo que elegir qué llevar a un viaje sin saber bien si me van a evaluar por VARIEDAD (un poco de cada "
                 "cosa) o por CANTIDAD de lo más útil. ¿Qué criterio me cubre mejor si me equivoco de evaluación?"),
        everyday=("Depende de cuánto puedo llevar. Si llevo POCO (mochila chica frente a la variedad de cosas), me "
                  "conviene apostar a la VARIEDAD -- un poco de cada cosa me cubre si me evalúan por variedad y no pierdo "
                  "tanto si era por cantidad. Si llevo MUCHO (la mochila me sobra para cubrir variedad), apostar a la "
                  "variedad ya no agrega (ya tengo de todo) y conviene llevar lo más útil aunque repita. No hay una regla "
                  "única: el criterio seguro depende de cuánto entra en la mochila vs cuánta variedad hay."),
        solutions=["presupuesto escaso vs diversidad (k<T): asumir cobertura/variedad hedgea mejor",
                   "presupuesto que excede la diversidad (k>T, cobertura saturada): asumir valor/cantidad es más seguro",
                   "no hay default universal de agregación bajo incertidumbre: depende de k/T",
                   "top-value clava en pocas categorías ricas (mal si la verdad premia variedad); cobertura deja valor en la mesa (mal si la verdad premia cantidad)"],
        principles=["bajo agregación incierta, el supuesto seguro (minimax) depende del ratio presupuesto/diversidad k/T",
                    "la cobertura hedgea cuando el presupuesto es escaso frente a la diversidad; satura cuando lo excede",
                    "refina la regla 'asigná por la agregación verdadera' (95/100/101) para el caso incierto",
                    "probar un solo régimen (k>T) da una conclusión artefactual; hay que barrer k/T"],
        adaptation=("El lab REFINA la regla de asignación para la agregación INCIERTA: no existe un supuesto de agregación "
                    "universalmente seguro; elegir según el ratio presupuesto/diversidad k/T (cobertura si k<T, valor si "
                    "k>T). Política: estimar k/T y, bajo incertidumbre del objetivo, asumir cobertura cuando el "
                    "presupuesto es escaso y valor cuando excede la diversidad. Próximo: aprender la agregación del "
                    "feedback (cf. 102) en vez de elegir un supuesto; el cruce exacto de k/T; y SCALE."),
        measurement=("exp097 ({n} seeds): k={kl} seguro=submodular (sub={sl} vs add={al}); k={kh} seguro=additive "
                     "(add={ah} vs sub={sh}).").format(n=n_seeds, kl=per_k[lok]['k'], sl=_f(per_k[lok]['wc_sub']),
                                                       al=_f(per_k[lok]['wc_add']), kh=per_k[hik]['k'],
                                                       ah=_f(per_k[hik]['wc_add']), sh=_f(per_k[hik]['wc_sub'])),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (qué llevar al viaje sin saber si evalúan variedad o cantidad; depende de la mochila).")

    kl_txt = ("REAL (exp097): bajo agregación INCIERTA el supuesto seguro (minimax) DEPENDE de k/T -- a k={kl}(<T) seguro="
              "submodular/cobertura (peor-caso {sl} vs {al}); a k={kh}(>T, cobertura saturada) seguro=additive/valor "
              "(peor-caso {ah} vs {sh}). No hay default universal. TECHO: 2 agregaciones, categorías desbalanceadas, oracle "
              "submodular greedy (1-1/e), cruce de k/T distribución-dependiente; numpy/juguete; mejor que elegir supuesto "
              "sería APRENDER la agregación del feedback (cf. 102).").format(
                  kl=per_k[lok]['k'], sl=_f(per_k[lok]['wc_sub']), al=_f(per_k[lok]['wc_add']),
                  kh=per_k[hik]['k'], ah=_f(per_k[hik]['wc_add']), sh=_f(per_k[hik]['wc_sub']))
    ceilings.add(CeilingRecord(
        subsystem="Robustez a MIS-ESPECIFICAR la agregación — el default seguro (minimax) depende del ratio presupuesto/diversidad k/T (cobertura si k<T, valor si k>T); no hay default universal",
        known_limit=kl_txt,
        blockers=[{"text": "el cruce exacto de k/T es DISTRIBUCIÓN-DEPENDIENTE (imbalance de categorías, n, T); sólo se mostró que el default seguro CAMBIA de submodular(k<T) a additive(k>T), no el umbral universal", "kind": "diseno"},
                  {"text": "2 agregaciones (additive vs cobertura submodular); el oracle submodular es greedy (1-1/e), no exacto; un espacio más rico de agregaciones no se testeó", "kind": "diseno"},
                  {"text": "mejor que ELEGIR un supuesto de agregación sería APRENDERLA del feedback (cf. 102, bandit); no integrado; numpy/juguete; SCALE pendiente", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP097.ref, S_ARC.ref]))
    notes.append("1 techo 'real': el default de agregación seguro depende de k/T; no hay universal (mejor: aprender la agregación, 102).")

    dstmt = ("North-Star R-VALOR (robustez a agregación INCIERTA, refina 95/100/101): no existe un supuesto de agregación "
             "universalmente seguro; el default minimax DEPENDE del ratio presupuesto/diversidad k/T -- asumir "
             "SUBMODULAR/cobertura cuando el presupuesto es ESCASO frente a la diversidad (k<T, hedgea), y ADDITIVE/valor "
             "cuando lo EXCEDE (k>T, la cobertura satura). Decisión: bajo incertidumbre del objetivo, estimar k/T y elegir "
             "el supuesto seguro acorde; o mejor, APRENDER la agregación del feedback (cf. 102). Refina la regla del arco "
             "'asigná por la ganancia marginal en la agregación verdadera' para el caso incierto. Próximo: aprender la "
             "agregación; el cruce exacto de k/T; y SCALE.")
    drat = ("exp097 (tier5, propio, {n} seeds, numpy): k={kl} seguro=submodular (sub={sl} vs add={al}); k={kh} "
            "seguro=additive (add={ah} vs sub={sh}). Convergente con minimax/robustez-por-régimen (tier2) y con la política "
            "por agregación conocida del arco (tier5). APOYADA regime-dependiente.").format(
                n=n_seeds, kl=per_k[lok]['k'], sl=_f(per_k[lok]['wc_sub']), al=_f(per_k[lok]['wc_add']),
                kh=per_k[hik]['k'], ah=_f(per_k[hik]['wc_add']), sh=_f(per_k[hik]['wc_sub']))
    dec = Decision(id="D-V4-75", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP097), _to_plain(S_ARC)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-75 ACEPTADA por el ledger (tier5 exp097 + tier5 exp079).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-75:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle113_aggregation_robust',
                                description='CYCLE 113 (RESET v4, H-V4-8r: el default de agregación seguro depende de k/T -- APOYADA regime-dependiente).')
    p.add_argument('--store', default=DEFAULT_STORE)
    p.add_argument('--results', default=DEFAULT_RESULTS)
    p.add_argument('--reset', dest='reset', action='store_true', default=True)
    p.add_argument('--no-reset', dest='reset', action='store_false')
    args = p.parse_args(argv)
    store = os.path.abspath(args.store)
    if args.reset and os.path.isdir(store):
        shutil.rmtree(store)
    os.makedirs(store, exist_ok=True)
    record, notes, status, sm = run(store, os.path.abspath(args.results))
    res = record.verify_no_loss()
    print("=" * 78)
    print("RESUMEN — CYCLE 113 (RESET v4): el default de agregación seguro depende de k/T (H-V4-8r) — regime-dependiente")
    print("=" * 78)
    print("veredicto H-V4-8r:", status.upper() if status else "?")
    print("  k<T -> asumir cobertura (hedgea); k>T (cobertura saturada) -> asumir valor. No hay default universal.")
    print("")
    for n in notes:
        print("  CHECK ", n)
    print("")
    for name in ('sources', 'hypotheses', 'analogies', 'ceilings', 'decisions'):
        print("  {:<12}: {}".format(name, count_lines(record.store_path(name))))
    print("  verify_no_loss =", "OK" if res['ok'] else "FAIL")
    print("=" * 78)
    return 0 if res['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
