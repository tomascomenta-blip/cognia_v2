r"""
cycle102_meta_allocation.py — CICLO 102 (RESET v4, rama R-VALOR, META-ALLOCATION; converso de CYCLE 92): H-V4-8g por las
compuertas del engine. APOYADA: NINGUNA estrategia de asignación FIJA domina todos los regímenes -- per-costo ayuda bajo
ADITIVO (CYCLE 101) pero ESTORBA bajo COBERTURA que satura (cubrir manda); la mejor estrategia DIFIERE por régimen. Un
BANDIT (ε-greedy) sobre las estrategias DESCUBRE la correcta del FEEDBACK de outcomes con NO-REGRET (≈ oracle_selector por
régimen) y SUPERA a cualquier estrategia fija única. A diferencia de CYCLE 92 (donde un prior flexible dominaba y la
selección era innecesaria), AQUÍ la selección de la política de asignación ES NECESARIA y el agente la APRENDE -> la
meta-decisión (qué política de asignación usar) también es R-VALOR-aprendible.

DERIVA de exp086_meta_allocation/results/results.json.

Correr (DESPUÉS de exp086):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp086_meta_allocation.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle102_meta_allocation
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle102_meta_allocation')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp086_meta_allocation', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="aprendizaje no-regret sobre POLÍTICAS (bandit/experts): cuando ninguna política única domina todos los regímenes, un bandit sobre políticas converge a la mejor por régimen del reward observado; selección NECESARIA (a diferencia de cuando un default domina)", obtained=False,
                     claim=("Cuando NINGUNA política fija domina todos los regímenes (la mejor difiere), un bandit/experts "
                            "sobre las políticas, guiado por el reward observado, converge a la mejor por régimen "
                            "(no-regret) y supera a cualquier política fija única. La selección es NECESARIA (a diferencia "
                            "del caso donde un default flexible domina, CYCLE 92). (Principio.)"))
S_EXP085 = Source(tier=5, ref="cognia_x/experiments/exp085_cost_aware_value", obtained=True,
                  claim=("CYCLE 101 mostró que per-costo (ratio) ayuda bajo objetivo ADITIVO pero ESTORBA bajo COBERTURA "
                         "que satura (objeto-dependiente) -> el mejor brazo DIFIERE por régimen. H-V4-8g testea si el "
                         "agente puede descubrir la política correcta sin conocer el régimen."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp086 primero): " + results_path)

    ba = sm['best_add']; bc = sm['best_cov']
    bav = sm['bandit_avg']; bsf = sm['best_single_fixed']
    fav = sm['fixed_avg'][bsf]
    ra = sm['regret_add']; rc = sm['regret_cov']
    bbf = sm['bandit_beats_fixed']
    g = sm['grid']
    ah, ch = g['additive_hetero'], g['coverage_hetero']
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim086 = ("exp086 (propio, {n} seeds, numpy): la mejor estrategia de asignación DIFIERE por régimen (ADITIVO+hetero "
                "'{ba}'={ahb}; COBERTURA+hetero '{bc}'={chb}); ningún brazo domina. El bandit DESCUBRE la correcta con "
                "no-regret (regret ADD={ra}/COV={rc}) y supera a la mejor fija única ({bsf}={fav}) por {bbf}.").format(
                    n=n_seeds, ba=ba, ahb=_f(ah[ba]), bc=bc, chb=_f(ch[bc]), ra=_f(ra), rc=_f(rc), bsf=bsf, fav=_f(fav), bbf=_f(bbf))
    S_EXP086 = Source(tier=5, ref="cognia_x/experiments/exp086_meta_allocation", obtained=True, claim=claim086)
    for src in (S_PRINCIPLE, S_EXP085, S_EXP086):
        ledger.add_source(src)
    notes.append("3 fuentes (S_PRINCIPLE tier2 no-regret sobre políticas; S_EXP085 tier5 mejor-difiere de CYCLE 101; S_EXP086 tier5 dato propio).")

    ev_for = [S_EXP086.ref]
    ev_against = [S_EXP086.ref, S_EXP085.ref, S_PRINCIPLE.ref]
    advtext = ("{V} (META-ALLOCATION; converso de CYCLE 92): los ciclos 95/100/101 dieron la política de asignación "
               "correcta SUPONIENDO que el agente conoce la estructura del objetivo. Pero el mejor brazo DIFIERE por "
               "régimen -- per-costo (ratio) ayuda bajo ADITIVO (CYCLE 101) pero ESTORBA bajo COBERTURA que satura (cubrir "
               "manda) -- así que NINGÚN brazo único domina. H-V4-8g testea si un agente que NO conoce el régimen DESCUBRE "
               "la política correcta del FEEDBACK de outcomes. RESULTADO: la mejor estrategia DIFIERE (ADITIVO+hetero la "
               "mejor es '{ba}'={ahb}; COBERTURA+hetero la mejor es '{bc}'={chb}); el BANDIT (ε-greedy sobre el reward "
               "medio por estrategia) logra NO-REGRET -- regret vs oracle_selector ADD={ra}/COV={rc} (≈0) -- y en "
               "promedio SUPERA a cualquier estrategia FIJA única ({bsf}={fav}) por {bbf}. => a diferencia de CYCLE 92 "
               "(meta-PRIOR: un prior flexible -rbf- casi dominaba, la selección era INNECESARIA), AQUÍ ninguna política "
               "de asignación domina y la selección ES NECESARIA -- y el agente la DESCUBRE del feedback de outcomes. La "
               "META-DECISIÓN (qué política de asignación) es ella misma R-VALOR-aprendible (un bandit sobre políticas). "
               "EVIDENCIA EN CONTRA / caveats HONESTOS: el margen del bandit sobre la mejor fija es modesto ({bbf}: gana "
               "por agarrar la mejor en cada régimen, no por ser mágico); 2 regímenes / 4 estrategias, bandit estacionario "
               "(no detecta CAMBIO de régimen -- eso requeriría el surprise-gating de CYCLE 99); objetivos sintéticos, "
               "numpy/juguete.").format(
                   V=status.upper(), ba=ba, ahb=_f(ah[ba]), bc=bc, chb=_f(ch[bc]), ra=_f(ra), rc=_f(rc),
                   bsf=bsf, fav=_f(fav), bbf=_f(bbf))

    hyp = Hypothesis(
        id="H-V4-8g",
        statement=("Ninguna estrategia de asignación FIJA domina todos los regímenes (per-costo ayuda en aditivo, estorba "
                   "en cobertura que satura); un bandit sobre estrategias DESCUBRE la correcta por régimen del feedback de "
                   "outcomes con no-regret y supera a cualquier fija única -> la meta-decisión de asignación es "
                   "R-VALOR-aprendible (converso de CYCLE 92, donde un default dominaba)."),
        prediction=("APOYADA si la mejor estrategia DIFIERE por régimen (ningún brazo domina) Y el bandit logra no-regret "
                    "(regret <= 0.06 por régimen) Y supera (o iguala) a la mejor fija única en promedio; REFUTADA si una "
                    "estrategia fija domina ambos (selección innecesaria); MIXTA en otro caso. (Pre-registrada, numpy, "
                    "48 seeds, bandit ε-greedy.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp086_meta_allocation")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-8g")
        notes.append("H-V4-8g marcada '{}' con DoD completo (meta-allocation; converso de CYCLE 92).".format(status))

    analogy = AnalogyRecord(
        problem=("Tengo varias REGLAS para comprar (por valor, por valor-por-peso, por cubrir la lista) y no sé qué tipo "
                 "de compra es la de hoy. ¿Me caso con una regla o pruebo y me quedo con la que mejor me resulta?"),
        everyday=("Pruebo y me quedo con la que mejor resulta HOY. Ninguna regla gana siempre: 'valor-por-peso' es genial "
                  "para acumular pero pésima cuando sólo tengo que cubrir una lista (ahí compro lo que falte sin importar "
                  "el precio). Como ninguna gana siempre, me conviene ELEGIR la regla según cómo me fue (el feedback). Si "
                  "una regla ganara siempre, ni me molestaría en elegir -- pero no es el caso."),
        solutions=["bandit sobre reglas de asignación: descubre la mejor por régimen del feedback (no-regret)",
                   "casarse con 'valor-por-peso': falla cuando hay que cubrir (cobertura satura)",
                   "casarse con 'por valor': desperdicia presupuesto en lo caro (aditivo+hetero)",
                   "si una regla dominara siempre, elegir sería innecesario (caso de CYCLE 92, no este)"],
        principles=["ninguna política de asignación domina todos los regímenes (per-costo objeto-dependiente, CYCLE 101)",
                    "un bandit sobre políticas converge a la mejor por régimen del reward observado (no-regret)",
                    "la meta-decisión (qué política de asignación) es ella misma R-VALOR-aprendible",
                    "converso de CYCLE 92: la selección es NECESARIA cuando ningún default domina"],
        adaptation=("El lab cierra la pregunta meta de la asignación: cuando ninguna política de asignación domina (caso "
                    "real, dado que la política correcta es objeto-dependiente, 95/100/101), el agente la DESCUBRE del "
                    "feedback de outcomes con un bandit no-regret. Combinado con CYCLE 92 (cuando un default flexible "
                    "domina, la selección es innecesaria), la regla meta es: ELEGIR la política de asignación del feedback "
                    "sólo cuando ninguna domina. Para regímenes que CAMBIAN, el bandit debería ser surprise-gated (CYCLE "
                    "99). Próximo: bandit de políticas bajo CAMBIO de régimen; integrar en el lazo cerrado real; y SCALE."),
        measurement=("exp086 ({n} seeds): mejor difiere (ADD '{ba}'={ahb}, COV '{bc}'={chb}); bandit no-regret (regret "
                     "ADD={ra}/COV={rc}); bandit supera a la mejor fija única ({bsf}={fav}) por {bbf}.").format(
                         n=n_seeds, ba=ba, ahb=_f(ah[ba]), bc=bc, chb=_f(ch[bc]), ra=_f(ra), rc=_f(rc), bsf=bsf, fav=_f(fav), bbf=_f(bbf)),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (probar reglas de compra y quedarse con la que mejor resulta hoy).")

    kl = ("REAL (exp086): ninguna estrategia de asignación FIJA domina todos los regímenes (la mejor difiere: ADITIVO "
          "'{ba}', COBERTURA '{bc}'; per-costo objeto-dependiente); un bandit sobre estrategias DESCUBRE la correcta del "
          "feedback de outcomes con NO-REGRET (regret ADD={ra}/COV={rc}) y supera a la mejor fija única (+{bbf}). La "
          "meta-decisión de asignación es R-VALOR-aprendible. TECHO: margen del bandit modesto; bandit ESTACIONARIO (no "
          "detecta cambio de régimen -> requeriría surprise-gating de CYCLE 99); 2 regímenes, objetivos sintéticos.").format(
              ba=ba, bc=bc, ra=_f(ra), rc=_f(rc), bbf=_f(bbf))
    ceilings.add(CeilingRecord(
        subsystem="META-ALLOCATION — el agente descubre la política de asignación correcta del feedback (bandit no-regret) cuando ninguna domina; converso de CYCLE 92",
        known_limit=kl,
        blockers=[{"text": "el margen del bandit sobre la mejor estrategia fija única es MODESTO (gana por agarrar la mejor en cada régimen, no por superar al per-regime-best)", "kind": "diseno"},
                  {"text": "el bandit es ESTACIONARIO (converge a una estrategia); bajo CAMBIO de régimen necesitaría re-explorar -> surprise-gating (CYCLE 99); no testeado", "kind": "diseno"},
                  {"text": "2 regímenes / 4 estrategias, objetivos sintéticos (aditivo Σq, cobertura), numpy/juguete; no integrado con el lazo cerrado real ni SCALE", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP086.ref, S_EXP085.ref]))
    notes.append("1 techo 'real': la meta-decisión de asignación es aprendible del feedback (bandit no-regret); selección necesaria cuando ningún brazo domina.")

    dstmt = ("North-Star R-VALOR (META-ALLOCATION; cierra la pregunta meta de la asignación): cuando ninguna política de "
             "asignación domina todos los regímenes (caso real -- la política correcta es objeto-dependiente, 95/100/101), "
             "el agente la DESCUBRE del feedback de outcomes con un bandit NO-REGRET, superando a cualquier política fija. "
             "Decisión: la meta-regla del lab = ELEGIR la política de asignación del feedback sólo cuando ningún default "
             "domina (converso de CYCLE 92, donde un prior flexible dominaba y la selección era innecesaria). Para "
             "regímenes que CAMBIAN, el bandit debería ser surprise-gated (CYCLE 99). La meta-decisión es ella misma "
             "R-VALOR-aprendible. Próximo: bandit de políticas bajo cambio de régimen; integrar en el lazo cerrado real; "
             "y SCALE.")
    drat = ("exp086 (tier5, propio, {n} seeds, numpy): mejor difiere (ADD '{ba}', COV '{bc}'); bandit no-regret (regret "
            "ADD={ra}/COV={rc}) y supera a la mejor fija única ({bsf}) por {bbf}. Convergente con no-regret sobre políticas "
            "(tier2) y con el mejor-difiere de CYCLE 101 (tier5). APOYADA: la meta-asignación es aprendible.").format(
                n=n_seeds, ba=ba, bc=bc, ra=_f(ra), rc=_f(rc), bsf=bsf, bbf=_f(bbf))
    dec = Decision(id="D-V4-64", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP086), _to_plain(S_EXP085)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-64 ACEPTADA por el ledger (tier5 exp086 + tier5 exp085).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-64:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle102_meta_allocation',
                                description='CYCLE 102 (RESET v4, H-V4-8g: la meta-decisión de asignación es R-VALOR-aprendible (bandit no-regret) cuando ningún brazo domina -- APOYADA; converso de CYCLE 92).')
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
    print("RESUMEN — CYCLE 102 (RESET v4): la meta-decisión de asignación es aprendible del feedback (H-V4-8g) — converso de CYCLE 92")
    print("=" * 78)
    print("veredicto H-V4-8g:", status.upper() if status else "?")
    print("  ningún brazo de asignación domina (per-costo objeto-dependiente); el bandit lo descubre con no-regret. Selección NECESARIA aquí.")
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
