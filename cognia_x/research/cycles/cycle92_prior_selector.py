r"""
cycle92_prior_selector.py — CICLO 92 (RESET v4, rama R-PRIOR, hija de CYCLE 91; cierra su caveat central de diseño):
H-V4-3b por las compuertas del engine. MIXTA (no-regret SÍ, pero selección INNECESARIA): el META-PRIOR FUNCIONA -- el
agente ELIGE la base/prior de SUS PROPIOS datos por CV held-out (sin aviso de régimen) con NO-REGRET (iguala a la mejor
base por régimen y a un oracle_selector PERFECTO: poly2 en smooth, rbf en band), CERRANDO el caveat de diseño de CYCLE 91
(el prior ya no se matchea a mano, se DESCUBRE). PERO la selección es PRÁCTICAMENTE INNECESARIA: una base FLEXIBLE
suficiente (rbf) casi DOMINA ambos regímenes (nesta c·r de smooth Y band(c)·r de band), así que always-rbf ≈ selector
(+0.002). ESPEJA CYCLE 86 al nivel meta: un prior flexible que nesta los regímenes hace innecesaria la selección/
detección explícita; la selección sólo paga cuando NINGUNA base domina.

DERIVA de exp076_prior_selector/results/results.json.

Correr (DESPUÉS de exp076):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp076_prior_selector.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle92_prior_selector
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle92_prior_selector')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp076_prior_selector', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="selección de modelo por validación cruzada; una clase de hipótesis flexible que NESTA los regímenes hace innecesaria la conmutación/detección explícita (cf. CYCLE 86)", obtained=False,
                     claim=("La validación cruzada held-out es selección de modelo estándar y SIN oráculo: elige la base "
                            "que mejor predice held-out. Logra no-regret vs la mejor base si la señal alcanza. PERO si "
                            "una base es FLEXIBLE suficiente para NESTAR todos los regímenes en juego, 'usar siempre esa "
                            "base' iguala a un selector perfecto -> la selección/detección explícita es innecesaria "
                            "(mismo patrón que CYCLE 86: el combinador que nesta el producto hizo innecesario el detector "
                            "de régimen). La selección sólo paga cuando NINGUNA base única domina. (Principio.)"))
S_EXP075 = Source(tier=5, ref="cognia_x/experiments/exp075_matched_prior", obtained=True,
                  claim=("CYCLE 91 mostró que un prior MATCHEADO recupera barato PERO se matcheó por conocimiento de "
                         "DISEÑO; dejó abierto de DÓNDE viene el prior correcto. H-V4-3b lo cierra dejando que el agente "
                         "ELIJA la base de sus datos por CV."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp076 primero): " + results_path)

    rs = sm['regret_smooth']
    rb = sm['regret_band']
    ros = sm['regret_vs_oracle_smooth']
    rob = sm['regret_vs_oracle_band']
    sel_avg = sm['selector_avg']
    fixed_avg = sm['fixed_avg']
    bsf = sm['best_single_fixed']
    beat = sm['selector_beats_best_fixed']
    g = sm['grid']
    bf_sm = sm['best_fixed_smooth'].replace('always_', '')
    bf_bd = sm['best_fixed_band'].replace('always_', '')
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim076 = ("exp076 (propio, {n} seeds, numpy + sandbox exp018): el selector por CV held-out logra NO-REGRET (regret "
                "vs mejor base por régimen S={rs}/B={rb}; vs oracle_selector S={ros}/B={rob}) -- elige poly2 en smooth, "
                "rbf en band SIN aviso. PERO la base flexible {bsf} casi domina (avg={fa}); el selector la supera sólo "
                "+{beat}. Selección no-regret pero innecesaria dado un prior flexible.").format(
                    n=n_seeds, rs=_f(rs), rb=_f(rb), ros=_f(ros), rob=_f(rob), bsf=bsf, fa=_f(fixed_avg[bsf]), beat=_f(beat))
    S_EXP076 = Source(tier=5, ref="cognia_x/experiments/exp076_prior_selector", obtained=True, claim=claim076)
    for src in (S_PRINCIPLE, S_EXP075, S_EXP076):
        ledger.add_source(src)
    notes.append("3 fuentes (S_PRINCIPLE tier2 CV/clase-flexible-nesta; S_EXP075 tier5 caveat de diseño de CYCLE 91; S_EXP076 tier5 dato propio).")

    ev_for = [S_EXP076.ref]
    ev_against = [S_EXP076.ref, S_EXP075.ref, S_PRINCIPLE.ref]
    advtext = ("{V} (cierra el caveat de diseño de CYCLE 91; META-PRIOR): CYCLE 91 dejó que el prior se matcheó por "
               "conocimiento de DISEÑO y abrió 'de dónde viene el prior correcto'. H-V4-3b da al agente un MENÚ de bases "
               "{{poly2, rbf, bin}} y lo deja ELEGIR por CV held-out (split 70/30, rankea el fold held-out por cada base "
               "ajustada en train, perf_of held-out, elige la mejor), sobre DOS regímenes que NO conoce a priori (SMOOTH "
               "conjuntivo E[v]=c·r donde poly2 es barato/óptimo; BAND multi-banda E[v]=band(c)·r donde rbf es matcheado), "
               "con el valor decidido por el sandbox REAL exp018. DOS HALLAZGOS: (1) el META-PRIOR FUNCIONA -- NO-REGRET: "
               "el selector iguala a la mejor base POR RÉGIMEN (regret S={rs}/B={rb}) y a un oracle_selector PERFECTO "
               "(regret S={ros}/B={rob}, <= 0.03); elige poly2 en smooth y rbf en band SIN aviso de régimen -> el agente "
               "DESCUBRE el prior correcto de sus datos, cerrando el caveat de diseño de CYCLE 91. (2) PERO la selección "
               "es PRÁCTICAMENTE INNECESARIA: una base FLEXIBLE suficiente ({bsf}) casi DOMINA ambos regímenes (avg={fa}) "
               "porque NESTA tanto c·r (smooth, rbf={rsm}≈poly2={psm}) como band(c)·r (band, rbf mejor) -> always-{bsf} ≈ "
               "selector (el selector la supera sólo +{beat} < 0.03). EVIDENCIA EN CONTRA / matiz HONESTO: NO es APOYADA "
               "limpia -- la maquinaria de selección no compra ventaja neta sobre un buen default flexible (y a "
               "presupuesto MUY bajo la CV ruidosa puede incluso restar). NO es REFUTADA -- el selector SÍ logra "
               "no-regret (el mecanismo meta-prior funciona) y elige correctamente por régimen. => ESPEJA CYCLE 86 al "
               "nivel meta: un prior flexible que NESTA los regímenes hace innecesaria la selección/detección explícita; "
               "la selección sólo paga cuando NINGUNA base única domina. SHARPENS R-PRIOR: el lever es TENER un prior "
               "flexible-suficiente en el menú, no la maquinaria de selección. Caveats: g sintético, 2 regímenes, base "
               "binned cuadrada; un régimen donde rbf falle (estructura fuera de su span) haría la selección "
               "necesaria.").format(
                   V=status.upper(), rs=_f(rs), rb=_f(rb), ros=_f(ros), rob=_f(rob), bsf=bsf, fa=_f(fixed_avg[bsf]),
                   rsm=_f(g['smooth']['always_rbf']), psm=_f(g['smooth']['always_poly2']), beat=_f(beat))

    hyp = Hypothesis(
        id="H-V4-3b",
        statement=("El agente puede SELECCIONAR la base/prior correcta de SUS PROPIOS datos por CV held-out (sin aviso de "
                   "régimen) con no-regret a través de regímenes de estructura del valor, y la selección SUPERA a "
                   "cualquier base fija única. (Hija de H-V4-3a; cierra el caveat de diseño de CYCLE 91.)"),
        prediction=("APOYADA si no-regret (regret vs mejor base por régimen y vs oracle_selector <= 0.03) Y el selector "
                    "SUPERA a cualquier base fija única en promedio (+>0.03); REFUTADA si el selector no adapta / pierde "
                    "vs una base fija; MIXTA si logra no-regret pero NO supera a una base fija (un default flexible "
                    "domina). (Pre-registrada, sandbox real exp018, 48 seeds, 2 regímenes.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp076_prior_selector")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-3b")
        notes.append("H-V4-3b marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("¿Vale la pena un experto que elija la herramienta correcta para cada terreno, o me basta con traer una "
                 "navaja suiza que sirve casi igual en todos?"),
        everyday=("El experto que ELIGE de lo que ve (sin que le digan el terreno) acierta -- iguala a elegir con "
                  "información perfecta. PERO si tengo una navaja suiza lo bastante buena que sirve casi igual en TODOS "
                  "los terrenos, usarla siempre rinde lo mismo que el experto: la maquinaria de elegir no me compra nada "
                  "extra. El experto sólo paga cuando NINGUNA herramienta única sirve para todo. (Y si elijo con muy "
                  "pocas pistas, a veces me equivoco y pierdo.)"),
        solutions=["selector por CV: elige la herramienta correcta por terreno, no-regret (= experto perfecto)",
                   "navaja suiza flexible (rbf): casi domina todos los terrenos -> usarla siempre ≈ selector",
                   "herramienta especializada equivocada (poly2 en band): falla -> por eso elegir mal cuesta",
                   "la selección paga sólo cuando ninguna herramienta única sirve para todos los terrenos"],
        principles=["la CV held-out elige la base sin oráculo, no-regret si la señal alcanza (meta-prior funciona)",
                    "una clase de hipótesis flexible que NESTA los regímenes hace innecesaria la conmutación explícita",
                    "el lever es TENER un prior flexible-suficiente en el menú, no la maquinaria de selección",
                    "la selección sólo paga cuando ninguna base única domina; a presupuesto bajo la CV ruidosa puede restar"],
        adaptation=("El lab CIERRA el caveat de diseño de CYCLE 91: el prior correcto se DESCUBRE de los datos (CV "
                    "no-regret), no hace falta matchearlo a mano. PERO refina la política: en vez de una maquinaria de "
                    "selección, basta un prior FLEXIBLE-suficiente (rbf) que nesta los regímenes esperados -- always-rbf "
                    "≈ selector (espeja CYCLE 86). La selección explícita se reserva para cuando ninguna base domine. "
                    "Próximo: un régimen FUERA del span de rbf (donde la selección SÍ pague); el generador de MODELO real "
                    "(lazo cerrado exp018); y SCALE."),
        measurement=("exp076 ({n} seeds): regret vs mejor-por-régimen S={rs}/B={rb}; vs oracle_selector S={ros}/B={rob}; "
                     "selector_avg={sa} vs mejor fija {bsf}={fa} (+{beat}); best_fixed smooth={bsm}/band={bbd}.").format(
                         n=n_seeds, rs=_f(rs), rb=_f(rb), ros=_f(ros), rob=_f(rob), sa=_f(sel_avg), bsf=bsf,
                         fa=_f(fixed_avg[bsf]), beat=_f(beat), bsm=bf_sm, bbd=bf_bd),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (el experto que elige vs la navaja suiza flexible que casi domina).")

    kl = ("REAL (exp076): el META-PRIOR funciona -- el agente ELIGE la base de sus datos por CV held-out con NO-REGRET "
          "(vs mejor base por régimen S={rs}/B={rb}; vs oracle_selector S={ros}/B={rob}), cerrando el caveat de diseño de "
          "CYCLE 91. PERO la selección es PRÁCTICAMENTE INNECESARIA: un prior flexible suficiente ({bsf}) casi domina "
          "ambos regímenes (always-{bsf} ≈ selector, +{beat}). TECHO/INSIGHT: el lever es TENER un prior flexible en el "
          "menú, no la maquinaria de selección; ésta sólo paga cuando ninguna base única domina.").format(
              rs=_f(rs), rb=_f(rb), ros=_f(ros), rob=_f(rob), bsf=bsf, beat=_f(beat))
    ceilings.add(CeilingRecord(
        subsystem="META-PRIOR — selección de base por CV held-out: no-regret (descubre el prior de los datos) pero innecesaria dado un prior flexible que nesta los regímenes (espeja CYCLE 86)",
        known_limit=kl,
        blockers=[{"text": "la selección no compra ventaja neta sobre un buen default flexible (rbf) que nesta los regímenes en juego; sólo pagaría con un régimen FUERA del span de rbf (no testeado)", "kind": "diseno"},
                  {"text": "a presupuesto MUY bajo la CV held-out es ruidosa y puede restar (mis-selecciona); el no-regret depende de suficiente feedback", "kind": "fisico"},
                  {"text": "g sintético, 2 regímenes, base binned cuadrada; falta un régimen no-nesteable por rbf, el generador de MODELO real (lazo cerrado exp018) y SCALE (GPU)", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP076.ref, S_EXP075.ref]))
    notes.append("1 techo 'real': la selección por CV es no-regret pero innecesaria dado un prior flexible; espeja CYCLE 86.")

    dstmt = ("North-Star R-PRIOR (cierra el caveat de diseño de CYCLE 91; META-PRIOR): el agente puede DESCUBRIR el prior "
             "correcto de sus datos por CV held-out con NO-REGRET (iguala a un selector perfecto, elige poly2 en smooth y "
             "rbf en band sin aviso) -- el prior no hace falta matchearlo a mano. PERO la selección es PRÁCTICAMENTE "
             "INNECESARIA dado un prior FLEXIBLE-suficiente (rbf) que nesta los regímenes esperados (always-rbf ≈ "
             "selector). Decisión: política de R-PRIOR = TENER en el menú un prior flexible-suficiente para los regímenes "
             "esperados (rbf por defecto), no una maquinaria de selección; reservar la selección para cuando ninguna base "
             "domine. Espeja CYCLE 86 al nivel meta. Próximo: un régimen fuera del span de rbf (donde la selección SÍ "
             "pague); el generador de MODELO real (lazo cerrado exp018); y SCALE.")
    drat = ("exp076 (tier5, propio, {n} seeds, numpy + sandbox exp018): no-regret (regret vs mejor-por-régimen S={rs}/"
            "B={rb}; vs oracle_selector S={ros}/B={rob} <= 0.03) PERO selector_avg={sa} ≈ mejor fija {bsf}={fa} (+{beat} "
            "< 0.03). Convergente con CV/clase-flexible-nesta (tier2) y con el caveat de diseño de CYCLE 91 (tier5). "
            "MIXTA: el meta-prior funciona pero un default flexible lo hace innecesario.").format(
                n=n_seeds, rs=_f(rs), rb=_f(rb), ros=_f(ros), rob=_f(rob), sa=_f(sel_avg), bsf=bsf, fa=_f(fixed_avg[bsf]), beat=_f(beat))
    dec = Decision(id="D-V4-54", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP076), _to_plain(S_EXP075)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-54 ACEPTADA por el ledger (tier5 exp076 + tier5 exp075).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-54:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle92_prior_selector',
                                description='CYCLE 92 (RESET v4, H-V4-3b: el meta-prior por CV es no-regret pero innecesario dado un prior flexible -- MIXTA; cierra caveat de diseño de CYCLE 91).')
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
    print("RESUMEN — CYCLE 92 (RESET v4): meta-prior por CV = no-regret pero innecesario dado un prior flexible (H-V4-3b)")
    print("=" * 78)
    print("veredicto H-V4-3b:", status.upper() if status else "?")
    print("  el selector por CV descubre el prior (no-regret vs oracle_selector) PERO always-rbf ≈ selector; espeja CYCLE 86.")
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
