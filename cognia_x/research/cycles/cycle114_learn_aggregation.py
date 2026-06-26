r"""
cycle114_learn_aggregation.py — CICLO 114 (RESET v4, rama R-VALOR, cierra el pointer de CYCLE 113): H-V4-8s por las
compuertas del engine. APOYADA: bajo agregación INCIERTA, en vez de ELEGIR un supuesto (hedge fijo, 113), el agente puede
APRENDER cuál agregación es la verdadera del FEEDBACK con un bandit -- logra no-regret (≈ best_fixed) y VENCE al hedge
fijo (promediado sobre ambas verdades, porque el hedge acierta en una y falla en la otra mientras el learner se adapta).
Converso de 113, igual que CYCLE 102 fue converso de 92: cuando ningún supuesto domina, DESCUBRIRLO del feedback es mejor
que comprometerse.

DERIVA de exp098_learn_aggregation/results/results.json.

Correr (DESPUÉS de exp098):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp098_learn_aggregation.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle114_learn_aggregation
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle114_learn_aggregation')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp098_learn_aggregation', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="aprendizaje online / bandits: con feedback, un algoritmo no-regret converge a la mejor acción FIJA; aprender el modelo (agregación) del feedback domina a comprometerse a un supuesto bajo incertidumbre de modelo", obtained=False,
                     claim=("Con feedback repetido, un bandit no-regret converge al rendimiento de la mejor acción FIJA en "
                            "retrospectiva. Bajo incertidumbre de modelo (qué agregación es la verdadera), APRENDER el "
                            "modelo del feedback domina a comprometerse a un supuesto fijo, que acierta en un modelo y "
                            "falla en otro. (Principio.)"))
S_C113 = Source(tier=5, ref="cognia_x/experiments/exp097_aggregation_robust", obtained=True,
                claim=("CYCLE 113: bajo agregación incierta no hay supuesto universalmente seguro (depende de k/T). "
                       "H-V4-8s cierra el pointer: aprender la agregación del feedback en vez de hedgear."))
S_C102 = Source(tier=5, ref="cognia_x/experiments/exp086_endogenous_rvalue", obtained=True,
                claim=("CYCLE 102 mostró que cuando ningún brazo de asignación domina, un bandit DESCUBRE la política del "
                       "feedback (no-regret). H-V4-8s aplica el mismo principio a la AGREGACIÓN (converso de 113)."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp098 primero): " + results_path)

    learn = sm['learn']; hedge = sm['hedge']; best = sm['best_fixed']
    nr = sm['no_regret_gap']; lvh = sm['learn_vs_hedge']
    pt = sm['grid']['per_truth']
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim098 = ("exp098 (propio, {n} seeds, numpy): promediado sobre ambas verdades, un bandit que APRENDE la agregación "
                "del feedback learn={l} ≈ best_fixed={b} (no-regret, gap {nr}) y > hedge fijo={h} (+{lvh}). El hedge acierta "
                "en una verdad y falla en la otra; el learner se adapta. Cierra 113.").format(
                    n=n_seeds, l=_f(learn), b=_f(best), nr=_f(nr), h=_f(hedge), lvh=_f(lvh))
    S_EXP098 = Source(tier=5, ref="cognia_x/experiments/exp098_learn_aggregation", obtained=True, claim=claim098)
    for src in (S_PRINCIPLE, S_C113, S_C102, S_EXP098):
        ledger.add_source(src)
    notes.append("4 fuentes (S_PRINCIPLE tier2 bandits/no-regret; S_C113 tier5 hedge depende de k/T; S_C102 tier5 mismo principio en la política; S_EXP098 tier5 dato propio).")

    ev_for = [S_EXP098.ref, S_PRINCIPLE.ref, S_C102.ref]
    ev_against = [S_EXP098.ref]
    advtext = ("{V} (cierra el pointer de CYCLE 113: APRENDER la agregación vence al HEDGE): 113 mostró que bajo agregación "
               "INCIERTA no hay supuesto universalmente seguro (el default minimax depende de k/T). H-V4-8s cierra el hilo "
               "como 102 cerró 92: en vez de ELEGIR un supuesto (hedge fijo), el agente APRENDE cuál agregación es la "
               "verdadera del FEEDBACK con un bandit ε-greedy (reward = valor-verdadero de su selección). RESULTADO: "
               "promediado sobre ambas verdades, learn={l} ≈ best_fixed={b} (NO-REGRET, gap {nr}) y > hedge fijo={h} "
               "(+{lvh}). MECANISMO: el hedge fijo (regla k/T -> aquí submodular) ACIERTA bajo la verdad submodular "
               "(learn {sl} vs hedge {hs}) pero FALLA bajo la verdad additive (hedge {ha} mientras el learner alcanza "
               "{la}); el learner se ADAPTA a la verdad real y gana en ambas. => bajo agregación incierta, DESCUBRIR la "
               "agregación del feedback domina a comprometerse a un supuesto. Junto con 102 (aprender la política de "
               "asignación) y 92 (aprender el prior), confirma el patrón general del lab: cuando ningún default domina, la "
               "META-DECISIÓN (política / prior / agregación) es APRENDIBLE del feedback con no-regret. EVIDENCIA: el "
               "principio de bandits/no-regret (tier2) lo predice; convergente con 102 (tier5). EVIDENCIA EN CONTRA / "
               "caveats: 2 agregaciones, agregación verdadera FIJA (no drift); bandit ε-greedy simple; el margen sobre el "
               "hedge depende de cuán 'equivocado' esté el hedge (aquí k<T -> el hedge elige submodular, por eso pierde en "
               "additive); numpy/juguete. La afirmación robusta es no-regret + dominar al hedge promediado, no el margen "
               "exacto.").format(V=status.upper(), l=_f(learn), b=_f(best), nr=_f(nr), h=_f(hedge), lvh=_f(lvh),
                                 sl=_f(pt['submodular']['learn']), hs=_f(pt['submodular']['hedge']),
                                 ha=_f(pt['additive']['hedge']), la=_f(pt['additive']['learn']))

    hyp = Hypothesis(
        id="H-V4-8s",
        statement=("Bajo agregación incierta, APRENDER la agregación verdadera del feedback (bandit) logra no-regret (≈ "
                   "best_fixed) y vence a comprometerse a un supuesto (hedge fijo), promediado sobre ambas verdades. "
                   "Converso de 113."),
        prediction=("APOYADA si learn ≈ best_fixed (gap <= 0.05) Y learn > hedge (+>0.03); REFUTADA si learn no supera al "
                    "hedge o no alcanza best_fixed; MIXTA en otro caso. (Pre-registrada, numpy, 48 seeds, bandit "
                    "ε-greedy.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp098_learn_aggregation")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-8s")
        notes.append("H-V4-8s marcada '{}' con DoD completo (aprender la agregación vence al hedge; converso de 113).".format(status))

    analogy = AnalogyRecord(
        problem=("No sé si me evalúan por VARIEDAD o por CANTIDAD, pero después de cada intento veo mi PUNTAJE. ¿Me "
                 "comprometo a un criterio o voy AJUSTANDO según el puntaje?"),
        everyday=("Voy ajustando según el puntaje: pruebo, veo qué criterio rinde más, y me inclino hacia ese. Así, sea "
                  "cual sea la evaluación real, termino casi tan bien como si la hubiera sabido desde el principio. "
                  "Comprometerme a un criterio fijo me iría bien si adiviné la evaluación y mal si no -- en promedio, "
                  "peor que ir aprendiendo del puntaje."),
        solutions=["aprender del feedback (bandit): se adapta a la evaluación real -> casi óptimo en cualquier caso (no-regret)",
                   "hedge fijo (un criterio): acierta en una evaluación, falla en la otra -> peor en promedio",
                   "el puntaje observado es la señal que destraba aprender la agregación",
                   "patrón general (92/102/114): la meta-decisión (prior/política/agregación) es aprendible del feedback"],
        principles=["bajo agregación incierta, aprenderla del feedback domina a comprometerse a un supuesto",
                    "un bandit no-regret converge al rendimiento de la mejor acción fija en retrospectiva",
                    "converso de 113 (como 102 fue converso de 92): si ningún default domina, descubrirlo del feedback",
                    "la meta-decisión (prior/política/agregación) es aprendible cuando hay feedback evaluativo"],
        adaptation=("El lab CIERRA el sub-hilo de robustez de agregación: en vez de elegir un supuesto seguro (113), "
                    "APRENDER la agregación del feedback con un bandit (no-regret, vence al hedge). Unifica con 92 (prior) "
                    "y 102 (política): el patrón general es que la META-DECISIÓN es aprendible del feedback cuando ninguna "
                    "opción domina a priori. Política: usar un bandit sobre los supuestos de agregación cuando haya "
                    "feedback del valor-verdadero. Próximo: agregación verdadera con DRIFT (combinar con el olvido de 97); "
                    "espacio más rico de agregaciones; y SCALE."),
        measurement=("exp098 ({n} seeds): learn={l} ≈ best_fixed={b} (gap {nr}) > hedge={h} (+{lvh}).").format(
            n=n_seeds, l=_f(learn), b=_f(best), nr=_f(nr), h=_f(hedge), lvh=_f(lvh)),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (ajustar el criterio según el puntaje vs comprometerse a uno).")

    kl = ("REAL (exp098): bajo agregación INCIERTA, aprender la agregación del feedback (bandit) logra no-regret "
          "(learn={l} ≈ best_fixed={b}, gap {nr}) y vence al hedge fijo (+{lvh}), promediado sobre ambas verdades. Cierra "
          "113 (converso, como 102 cerró 92). TECHO: 2 agregaciones, verdad FIJA (no drift), bandit ε-greedy simple; el "
          "margen sobre el hedge depende de cuán equivocado esté el hedge; numpy/juguete.").format(
              l=_f(learn), b=_f(best), nr=_f(nr), lvh=_f(lvh))
    ceilings.add(CeilingRecord(
        subsystem="Agregación incierta — APRENDER la agregación del feedback (bandit, no-regret) vence al hedge fijo; cierra 113, unifica con 92/102 (la meta-decisión es aprendible)",
        known_limit=kl,
        blockers=[{"text": "agregación verdadera FIJA (no drift); bajo drift habría que combinar con el olvido (CYCLE 97) -- no testeado", "kind": "diseno"},
                  {"text": "2 agregaciones (additive/submodular), bandit ε-greedy simple; un espacio más rico de agregaciones / objetivos no se exploró", "kind": "diseno"},
                  {"text": "el margen sobre el hedge depende de cuán equivocado esté el hedge fijo (aquí k<T -> elige submodular); numpy/juguete; SCALE pendiente", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP098.ref, S_C113.ref, S_C102.ref]))
    notes.append("1 techo 'real': aprender la agregación del feedback vence al hedge (cierra 113; unifica con 92/102).")

    dstmt = ("North-Star R-VALOR (cierra el sub-hilo de robustez de agregación; unifica 92/102/114): bajo agregación "
             "INCIERTA, APRENDER la agregación verdadera del feedback con un bandit (no-regret) domina a comprometerse a "
             "un supuesto (hedge fijo de 113), promediado sobre ambas verdades. Decisión: cuando haya feedback del "
             "valor-verdadero, usar un bandit sobre los supuestos de agregación en vez de hedgear. Confirma el patrón "
             "general del lab: la META-DECISIÓN (prior 92 / política de asignación 102 / agregación 114) es APRENDIBLE del "
             "feedback cuando ninguna opción domina a priori. Próximo: agregación con DRIFT (combinar con el olvido 97); "
             "espacio más rico de agregaciones; y SCALE.")
    drat = ("exp098 (tier5, propio, {n} seeds, numpy): learn={l} ≈ best_fixed={b} (gap {nr}) > hedge={h} (+{lvh}). "
            "Convergente con bandits/no-regret (tier2), con el hedge-depende-de-k/T de 113 (tier5) y con aprender-la-"
            "política de 102 (tier5). APOYADA: aprender la agregación vence al hedge.").format(
                n=n_seeds, l=_f(learn), b=_f(best), nr=_f(nr), h=_f(hedge), lvh=_f(lvh))
    dec = Decision(id="D-V4-76", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP098), _to_plain(S_C113), _to_plain(S_C102)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-76 ACEPTADA por el ledger (tier5 exp098 + tier5 exp097 + tier5 exp086).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-76:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle114_learn_aggregation',
                                description='CYCLE 114 (RESET v4, H-V4-8s: aprender la agregación del feedback vence al hedge fijo -- APOYADA; cierra 113, unifica 92/102).')
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
    print("RESUMEN — CYCLE 114 (RESET v4): aprender la agregación del feedback vence al hedge fijo (H-V4-8s) — cierra 113")
    print("=" * 78)
    print("veredicto H-V4-8s:", status.upper() if status else "?")
    print("  un bandit que aprende la agregación logra no-regret y vence al hedge fijo; la meta-decisión (prior/política/agregación) es aprendible (92/102/114).")
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
