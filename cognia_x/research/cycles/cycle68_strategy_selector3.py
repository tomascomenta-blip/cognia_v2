r"""
cycle68_strategy_selector3.py — CICLO 68 (RESET v4): H-V4-1j por las compuertas del engine. North-Star R-VALOR x
memoria — selector de 3 estrategias (capstone del arco memoria).

H-V4-1j: un selector de 3 estrategias clasifica 3 regímenes (estacionario/aislado/recurrente) de su sorpresa en
2 escalas y elige la estrategia de memoria correcta. DERIVA de exp053_strategy_selector3/results/results.json.

Correr (DESPUÉS de exp053):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp053_strategy_selector3.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle68_strategy_selector3
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle68_strategy_selector3')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp053_strategy_selector3', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_HIER = Source(tier=1, ref="hierarchical change-point / regime classification (multi-timescale)", obtained=False,
                claim=("Distinguir un cambio AISLADO de uno RECURRENTE exige estimar la TASA de cambio en una "
                       "escala lenta además de detectar el shift en una rápida; clasificar 3 regímenes es más "
                       "difícil que 2. (Principio.)"))
S_EXP052 = Source(tier=5, ref="cognia_x/experiments/exp052 (CYCLE 66)", obtained=True,
                  claim=("exp052 (H-V4-1i): un selector de 2 estrategias alcanza el óptimo en estacionario y "
                         "recurrente; falta el régimen INTERMEDIO (aislado, surprise-gate óptimo)."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp053 primero): " + results_path)
    bg = sm['by_regime']
    n_ok = sm['n_optimal']
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    def reg_line(r):
        v = bg[r]
        return "{}: selector3 {} (committed {}, fixed {}, sgate {})".format(
            r, _f(v['selector3']), _f(v['committed']), _f(v['fixed']), _f(v['surprise_gate']))

    S_EXP053 = Source(tier=5, ref="cognia_x/experiments/exp053_strategy_selector3", obtained=True,
                      claim=("exp053 (propio, {n} seeds, bayesiano numpy): un selector de 3 estrategias clasifica "
                             "3 regímenes en 2 escalas de sorpresa y acierta {nok}/3 -- {e} ; {a} ; {r}.").format(
                                 n=n_seeds, nok=n_ok, e=reg_line('estacionario'), a=reg_line('aislado'),
                                 r=reg_line('recurrente')))
    for src in (S_HIER, S_EXP052, S_EXP053):
        ledger.add_source(src)
    notes.append("3 fuentes (S_HIER tier1 clasificación multi-escala; S_EXP052 tier5 CYCLE66; S_EXP053 tier5 dato propio).")

    ev_for = [S_EXP053.ref, S_EXP052.ref]
    ev_against = [S_EXP053.ref]
    adv = ("{V} (capstone del arco memoria, {nok}/3 regímenes): extiende el selector del CYCLE 66 a TRES "
           "regímenes -- ESTACIONARIO (committear), AISLADO ([48,12] commit largo + adapt corto, surprise-gate "
           "óptimo) y RECURRENTE (olvidar-fuerte) -- clasificando de su propia sorpresa en DOS escalas (lenta = "
           "tasa de cambio de largo plazo, distingue aislado de recurrente; rápida = detecta el shift). "
           "RESULTADO: el selector3 acierta {nok}/3. {e}. {r}. PERO {a}: en el AISLADO el selector3 supera a "
           "committed (atascado {ac}) y a fixed pero NO alcanza al surprise_gate óptimo ({as_}) -- distinguir y "
           "disparar limpio la estrategia de surprise-gate en el régimen intermedio es genuinamente más difícil "
           "(la frontera aislado<->recurrente en la escala lenta es sutil; con sólo 12 pasos de adaptación el "
           "surprise-gate del selector no re-identifica del todo). => clasificar 3 regímenes y elegir la "
           "estrategia es PARCIALMENTE posible de la sorpresa endógena: 2/3 limpio, el intermedio direccional "
           "pero subóptimo. EVIDENCIA EN CONTRA (caveats honestos): (1) el régimen AISLADO no se clasifica/"
           "atiende limpio (MIXTA, no forzado). (2) umbrales de las 2 escalas (slow/fast) y tasas de EMA son "
           "hiperparámetros sensibles. (3) mundo de juguete. CONCLUSIÓN: confirma la tesis del CYCLE 66 (elegir "
           "la ESTRATEGIA de memoria) y la EXTIENDE a 3 regímenes con éxito PARCIAL -- la clasificación de "
           "régimen es la pieza difícil; el valor endógeno puede seleccionar la estrategia cuando los regímenes "
           "son separables, y el intermedio exige un clasificador mejor.").format(
               V=status.upper(), nok=n_ok, e=reg_line('estacionario'), r=reg_line('recurrente'),
               a=reg_line('aislado'), ac=_f(bg['aislado']['committed']), as_=_f(bg['aislado']['surprise_gate']))

    hyp = Hypothesis(
        id="H-V4-1j",
        statement=("Un selector de 3 estrategias clasifica 3 regímenes (estacionario/aislado/recurrente) de su "
                   "sorpresa en 2 escalas y elige la estrategia de memoria correcta, alcanzando el óptimo en los tres."),
        prediction=("APOYADA si el selector3 es ~óptimo en los 3 regímenes; REFUTADA si falla en >=2; MIXTA si "
                    "acierta 2 de 3. (Pre-registrada.)"),
        status='abierta', confidence='alta' if status == 'apoyada' else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=adv, experiment_ref="exp053_strategy_selector3")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-1j")
        notes.append("H-V4-1j marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("¿Podés distinguir TRES situaciones de tus errores -- temario estable, un cambio puntual, o "
                 "cambios todo el tiempo -- y usar la estrategia de estudio correcta para cada una?"),
        everyday=("Las dos primeras (estable, cambio puntual) y la tercera (cambios seguidos) se separan mirando "
                  "tu sorpresa en dos escalas: una lenta (¿cuán seguido te sorprendés en general?) y una rápida "
                  "(¿te sorprendés AHORA?). Funciona para estable y para 'cambios seguidos', pero el 'cambio "
                  "puntual' es el más difícil de clasificar y atender bien: lo hacés mejor que ignorarlo, pero "
                  "no perfecto."),
        solutions=["estacionario -> committear (acertado por el selector3)",
                   "recurrente -> olvidar-fuerte (acertado)",
                   "aislado -> surprise-gate (PARCIAL: mejor que committed/fixed, no alcanza el óptimo)",
                   "=> clasificar 3 regímenes de la sorpresa es 2/3 limpio; el intermedio es la pieza difícil"],
        principles=["clasificar 3 regímenes exige 2 escalas de sorpresa (lenta para la tasa, rápida para el shift)",
                    "el régimen AISLADO (intermedio) es el más difícil de separar de recurrente y atender limpio",
                    "el valor endógeno puede seleccionar la estrategia cuando los regímenes son separables",
                    "extender de 2 a 3 estrategias confirma la tesis del CYCLE 66 con éxito PARCIAL"],
        adaptation=("El lab reconoce que la pieza difícil es la CLASIFICACIÓN del régimen (no la selección de "
                    "estrategia). Próximos: un clasificador de régimen mejor (p.ej. estimar la frecuencia de "
                    "spikes, no sólo el nivel del EMA lento); presupuesto de adaptación variable; ligar el "
                    "selector al lazo de auto-mejora."),
        measurement=("exp053 ({nok}/3): {e}; {a}; {r}. {n} seeds.").format(
            nok=n_ok, e=reg_line('estacionario'), a=reg_line('aislado'), r=reg_line('recurrente'), n=n_seeds),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (distinguir 3 situaciones de tus errores en 2 escalas; el intermedio es el difícil).")

    ceilings.add(CeilingRecord(
        subsystem="R-VALOR x MEMORIA — selector de 3 ESTRATEGIAS (clasificación de régimen en 2 escalas; éxito parcial)",
        known_limit=("REAL (exp053): un selector de 3 estrategias clasifica 3 regímenes en 2 escalas de sorpresa "
                     "y acierta {nok}/3 (estacionario y recurrente sí; el AISLADO direccional pero subóptimo -- "
                     "selector3 {a} vs surprise_gate {b}). La CLASIFICACIÓN del régimen intermedio es la pieza "
                     "difícil.").format(nok=n_ok, a=_f(bg['aislado']['selector3']),
                                        b=_f(bg['aislado']['surprise_gate'])),
        blockers=[{"text": "el régimen AISLADO (intermedio) no se clasifica/atiende limpio: la frontera aislado<->recurrente en la escala lenta es sutil", "kind": "diseno"},
                  {"text": "umbrales de las 2 escalas + tasas de EMA son hiperparámetros sensibles; un clasificador mejor (frecuencia de spikes) podría separar mejor", "kind": "diseno"},
                  {"text": "mundo de juguete; presupuesto de adaptación fijo (12 pasos) limita el surprise-gate del selector en aislado", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP053.ref, S_EXP052.ref]))
    notes.append("1 techo 'real': clasificar 3 regímenes de la sorpresa y elegir la estrategia es 2/3 limpio; el intermedio (aislado) es la pieza difícil.")

    dstmt = ("North-Star R-VALOR x MEMORIA (capstone, éxito parcial): un selector de 3 estrategias clasifica 3 "
             "regímenes de no-estacionariedad (estacionario/aislado/recurrente) de su sorpresa en DOS escalas "
             "(lenta=tasa de cambio, rápida=shift) y elige la estrategia de memoria; acierta {nok}/3 -- "
             "estacionario (committear) y recurrente (olvidar-fuerte) limpios, el AISLADO direccional pero "
             "subóptimo (selector3 {a} vs surprise_gate {b}; mejor que committed atascado {c}). Decisión: la "
             "tesis del CYCLE 66 (el valor endógeno elige la ESTRATEGIA de memoria) se EXTIENDE a 3 regímenes con "
             "éxito parcial; la pieza difícil es la CLASIFICACIÓN del régimen intermedio. Próximos: clasificador "
             "de régimen mejor (frecuencia de spikes), presupuesto de adaptación variable.").format(
                 nok=n_ok, a=_f(bg['aislado']['selector3']), b=_f(bg['aislado']['surprise_gate']),
                 c=_f(bg['aislado']['committed']))
    drat = ("exp053 (tier5, propio, {n} seeds): selector3 acierta {nok}/3 (estacionario {e}, recurrente {r} sí; "
            "aislado {a} subóptimo vs sgate {b}). Convergente con clasificación multi-escala (tier1); extiende "
            "CYCLE 66. {V}.").format(n=n_seeds, nok=n_ok, e=_f(bg['estacionario']['selector3']),
                                     r=_f(bg['recurrente']['selector3']), a=_f(bg['aislado']['selector3']),
                                     b=_f(bg['aislado']['surprise_gate']), V=status.upper())
    dec = Decision(id="D-V4-31", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP053), _to_plain(S_EXP052)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-31 ACEPTADA por el ledger (tier5 exp053 + tier5 exp052).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-31:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle68_strategy_selector3',
                                description='CYCLE 68 (RESET v4, H-V4-1j: selector de 3 estrategias de memoria).')
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
    print("RESUMEN — CYCLE 68 (RESET v4): selector de 3 ESTRATEGIAS de memoria (H-V4-1j)")
    print("=" * 78)
    print("veredicto H-V4-1j:", status.upper() if status else "?")
    print("  clasificar 3 regímenes de la sorpresa y elegir la estrategia es 2/3 limpio; el aislado es el difícil.")
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
