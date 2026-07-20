r"""
cycle87_action_gated_feedback.py — CICLO 87 (RESET v4, rama R-VALOR, puente hacia gaps #1/#3): H-V4-7e por las compuertas
del engine. REFUTADA (informativa, robustez positiva): bajo feedback ACTION-GATED (el agente sólo observa el valor de lo
que selecciona) la explotación GREEDY del combinador aprendido (bootstrap del producto) NO se auto-atrapa por sesgo de
selección -- ya recupera la forma de sustitutos SIN explorar, igualando al buffer INSESGADO (feedback libre). La
exploración es INNECESARIA en este régimen. Mecanismo: la selección top-k por un score continuo igual ABARCA suficiente
del espacio de features (ctrl,rel) como para que el ridge-poly2 GENERALICE max(). => acota R-INTERVENCIÓN ("hay que
explorar para aprender el valor") -- NO hace falta aquí; y REFUERZA la política del gap #2 (CYCLE 86): la reconstrucción
always-learn es robusta también bajo feedback de acción-consecuencia.

DERIVA de exp071_action_gated_feedback/results/results.json.

Correr (DESPUÉS de exp071):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp071_action_gated_feedback.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle87_action_gated_feedback
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle87_action_gated_feedback')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp071_action_gated_feedback', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_SHIFT = Source(tier=2, ref="covariate shift / overlap de soporte: un aprendiz generaliza de una muestra sesgada pero que ABARCA el espacio de features; sin overlap suficiente, falla por extrapolación", obtained=False,
                 claim=("Un modelo aprendido de una muestra SESGADA pero con SOPORTE solapado sobre el espacio de "
                        "features generaliza al resto; el sesgo de selección sólo atrapa si el soporte observado se "
                        "concentra tanto que el target debe EXTRAPOLARSE. La selección top-k por un score continuo "
                        "abarca un rango 2D, no un punto -> overlap suficiente. (Principio.)"))
S_EXP070 = Source(tier=5, ref="cognia_x/experiments/exp070_regime_policy", obtained=True,
                  claim=("CYCLE 86 estableció la política gap #2 (always-learn domina con feedback LIBRE). H-V4-7e prueba "
                         "si esa política sobrevive con feedback ACTION-GATED (sólo se observa lo que se selecciona)."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp071 primero): " + results_path)

    prod = sm['subs_product']
    greedy = sm['subs_greedy']
    explore = sm['subs_explore']
    rnd = sm['subs_random']
    trap = sm['trap']
    expl_resc = sm['explore_rescues']
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim071 = ("exp071 (propio, {n} seeds, numpy): bajo feedback ACTION-GATED (observar sólo lo seleccionado, ítems "
                "frescos por ronda, calidad q2) la explotación GREEDY del combinador aprendido recupera sustitutos "
                "(learned_greedy {g}) IGUAL que el buffer insesgado/feedback libre (learned_random {r}) y que ε-explore "
                "({e}); todos vencen al producto ({p}). NO hay trampa de sesgo de selección (trap={t}); la exploración es "
                "innecesaria (explore_rescues={er}). La selección top-k abarca suficiente espacio de features para "
                "generalizar max().").format(
                    n=n_seeds, g=_f(greedy), r=_f(rnd), e=_f(explore), p=_f(prod), t=trap, er=expl_resc)
    S_EXP071 = Source(tier=5, ref="cognia_x/experiments/exp071_action_gated_feedback", obtained=True, claim=claim071)
    for src in (S_SHIFT, S_EXP070, S_EXP071):
        ledger.add_source(src)
    notes.append("3 fuentes (S_SHIFT tier2 covariate-shift/overlap; S_EXP070 tier5 política gap #2; S_EXP071 tier5 dato propio).")

    ev_for = [S_EXP071.ref]
    ev_against = [S_EXP071.ref, S_EXP070.ref, S_SHIFT.ref]
    advtext = ("{V} (informativa; robustez POSITIVA de la política gap #2): la hipótesis predecía que bajo feedback "
               "ACTION-GATED la explotación greedy del prior se AUTO-ATRAPA (sólo observa both-high -> no aprende max) y "
               "que la EXPLORACIÓN la rescata (R-INTERVENCIÓN). exp071 lo REFUTA: learned_greedy {g} recupera sustitutos "
               "SIN explorar, IGUALANDO al buffer insesgado/feedback-libre (learned_random {r}) y a ε-explore ({e}); "
               "todos vencen al producto ({p}). NO hay trampa (trap={t}), la exploración NO aporta (explore_rescues={er}). "
               "MECANISMO: la selección top-k por un score continuo igual ABARCA un rango 2D del espacio (ctrl,rel) -- "
               "overlap de soporte suficiente -- y el ridge-poly2 GENERALIZA max() desde ahí; el sesgo de selección sólo "
               "atraparía con concentración EXTREMA del soporte. CONSECUENCIAS: (1) ACOTA R-INTERVENCIÓN -- 'hay que "
               "explorar para aprender el valor' NO se sostiene en este régimen (cf. CYCLE 77-78, donde la intervención "
               "tampoco pagaba). (2) REFUERZA la política del gap #2 (CYCLE 86): la reconstrucción always-learn es robusta "
               "TAMBIÉN bajo feedback de acción-consecuencia, sin maquinaria de exploración. EVIDENCIA EN CONTRA / "
               "caveats: NO se probó concentración EXTREMA (k muy chico, colocación adversarial del valor lejos del "
               "prior) -- ahí el trap podría aparecer; juguete (g=max sintético, objetivo escalar, feedback sin costo de "
               "muestreo). CONCLUSIÓN: REFUTADA la necesidad de explorar; la política gap #2 sobrevive el action-gating.").format(
                   V=status.upper(), g=_f(greedy), r=_f(rnd), e=_f(explore), p=_f(prod), t=trap, er=expl_resc)

    hyp = Hypothesis(
        id="H-V4-7e",
        statement=("Bajo feedback action-gated la explotación greedy del prior se auto-atrapa por sesgo de selección y la "
                   "exploración (actuar más allá del prior) es necesaria para aprender R-VALOR no-factorizable."),
        prediction=("APOYADA si trap (learned_greedy <= product+0.02) Y explore rescata (>greedy+0.03 y >= random-0.03); "
                    "REFUTADA si no hay trampa o la exploración no ayuda; MIXTA en otro caso. (Pre-registrada, "
                    "sustitutos, q2.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp071_action_gated_feedback")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-7e")
        notes.append("H-V4-7e marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("Sólo puedo conocer el valor de lo que ELIJO (no me dan muestras gratis). Si elijo siempre por mi "
                 "corazonada (el prior), ¿me quedo ciego a las opciones buenas que mi corazonada descarta, o igual "
                 "aprendo la regla real?"),
        everyday=("Igual la aprendés. Un comprador que sólo prueba lo que su corazonada marca como mejor IGUAL prueba una "
                  "VARIEDAD ancha (su corazonada no apunta a un solo punto sino a una zona), y de esa variedad infiere la "
                  "regla verdadera -- aun la que dice 'a veces basta UNA cualidad alta'. No necesita probar cosas al azar. "
                  "Sólo se quedaría atrapado si su corazonada fuera EXTREMADAMENTE estrecha (probara casi siempre lo mismo). "
                  "Explorar a ciegas no hizo falta."),
        solutions=["greedy (explotar el combinador/prior) -> recupera sustitutos sin explorar: NO se atrapa",
                   "ε-explore -> no aporta sobre greedy (la exploración extra no hace falta)",
                   "random/insesgado (feedback libre) -> mismo techo que greedy",
                   "el trap sólo aparecería con concentración EXTREMA del soporte observado"],
        principles=["la selección top-k por un score continuo abarca suficiente espacio de features para generalizar",
                    "el sesgo de selección NO atrapa si hay overlap de soporte (covariate shift benigno)",
                    "ACOTA R-INTERVENCIÓN: explorar para aprender el valor NO siempre es necesario",
                    "la política gap #2 (always-learn) es robusta también bajo feedback de acción-consecuencia"],
        adaptation=("El lab mantiene la política gap #2 (always-learn con feedback adecuado) TAL CUAL bajo feedback "
                    "action-gated: no agrega maquinaria de exploración (no paga). Vigila sólo el régimen de concentración "
                    "EXTREMA del soporte (k muy chico / valor adversarialmente lejos del prior), donde el trap podría "
                    "reaparecer. Próximo: el salto a un lazo de acción-consecuencia REAL con verificador chequeable "
                    "(sandbox exp018, gaps #1/#3), donde el feedback tiene costo y la dinámica es secuencial real."),
        measurement=("exp071 ({n} seeds): sustitutos learned_greedy {g} = learned_random {r} = explore {e} > product {p}; "
                     "trap={t}, explore_rescues={er}.").format(
                         n=n_seeds, g=_f(greedy), r=_f(rnd), e=_f(explore), p=_f(prod), t=trap, er=expl_resc),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (el comprador que sólo prueba su corazonada igual abarca variedad y aprende la regla).")

    kl = ("REAL (exp071): bajo feedback ACTION-GATED (observar sólo lo seleccionado, q2) la explotación greedy del "
          "combinador aprendido recupera sustitutos (learned_greedy {g}) IGUAL que el buffer insesgado (learned_random "
          "{r}) y que ε-explore ({e}); todos > producto ({p}). NO hay trampa de sesgo de selección; la exploración es "
          "INNECESARIA. La selección top-k abarca suficiente espacio de features para generalizar max(). Acota "
          "R-INTERVENCIÓN y refuerza la política gap #2 (robusta al action-gating).").format(
              g=_f(greedy), r=_f(rnd), e=_f(explore), p=_f(prod))
    ceilings.add(CeilingRecord(
        subsystem="R-VALOR bajo feedback action-gated — la explotación greedy ya recupera; exploración innecesaria (no trap)",
        known_limit=kl,
        blockers=[{"text": "no se probó concentración EXTREMA del soporte (k muy chico / valor adversarialmente lejos del prior); ahí el trap de sesgo de selección podría reaparecer", "kind": "diseno"},
                  {"text": "feedback sin costo de muestreo y dinámica no-secuencial real; falta el lazo de acción-consecuencia REAL (sandbox exp018, verificador chequeable)", "kind": "diseno"},
                  {"text": "g=max sintético, objetivo escalar, base poly2 que nesta el producto; la generalización depende del overlap de soporte de top-k, que podría no valer en espacios de features de mayor dimensión", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP071.ref, S_EXP070.ref]))
    notes.append("1 techo 'real': greedy recupera bajo action-gating sin explorar; no trap; acota R-INTERVENCIÓN, refuerza gap #2.")

    dstmt = ("North-Star R-VALOR (puente a gaps #1/#3; robustez de la política gap #2): bajo feedback ACTION-GATED la "
             "explotación GREEDY del combinador aprendido recupera la forma no-factorizable (sustitutos) SIN explorar, "
             "igual que el feedback libre -- NO hay trampa de sesgo de selección. Decisión: el lab NO agrega maquinaria de "
             "exploración a la reconstrucción de R-VALOR (no paga en este régimen); mantiene la política gap #2 "
             "(always-learn) bajo feedback de acción-consecuencia. Acota R-INTERVENCIÓN ('explorar para aprender el valor' "
             "no siempre hace falta). Vigilar sólo concentración extrema del soporte. Próximo: lazo de acción-consecuencia "
             "REAL con verificador chequeable (sandbox exp018).")
    drat = ("exp071 (tier5, propio, {n} seeds): sustitutos learned_greedy {g} = learned_random {r} = explore {e} > "
            "product {p}; trap={t}, explore_rescues={er}. Convergente con covariate-shift/overlap (tier2) y con la "
            "política gap #2 de CYCLE 86 (tier5). REFUTADA la necesidad de explorar.").format(
                n=n_seeds, g=_f(greedy), r=_f(rnd), e=_f(explore), p=_f(prod), t=trap, er=expl_resc)
    dec = Decision(id="D-V4-49", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP071), _to_plain(S_EXP070)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-49 ACEPTADA por el ledger (tier5 exp071 + tier5 exp070).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-49:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle87_action_gated_feedback',
                                description='CYCLE 87 (RESET v4, H-V4-7e: feedback action-gated no atrapa; exploración innecesaria -- REFUTADA).')
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
    print("RESUMEN — CYCLE 87 (RESET v4): feedback action-gated no atrapa (H-V4-7e) — puente a gaps #1/#3")
    print("=" * 78)
    print("veredicto H-V4-7e:", status.upper() if status else "?")
    print("  greedy recupera bajo action-gating sin explorar (= feedback libre); no hay trampa; acota R-INTERVENCIÓN.")
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
