r"""
cycle104_abstention_timing.py — CICLO 104 (RESET v4, rama R-VALOR, dimensión NUEVA: TIMING del presupuesto / ABSTENCIÓN):
H-V4-8i por las compuertas del engine. APOYADA: R-VALOR gobierna CUÁNDO gastar el presupuesto GLOBAL (timing/abstención),
no sólo QUÉ elegir dentro de una ronda (83-103). Bajo rondas de RIQUEZA heterogénea, asignar el presupuesto por el VALOR
estimado de cada ronda -- gastar donde rinde, ABSTENERSE donde no -- supera MASIVAMENTE a gastar uniforme (≈ oracle); bajo
riqueza FLAT coinciden. El valor de NO actuar (abstenerse en rondas pobres para guardar presupuesto) es REAL.

DERIVA de exp088_abstention_timing/results/results.json.

Correr (DESPUÉS de exp088):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp088_abstention_timing.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle104_abstention_timing
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle104_abstention_timing')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp088_abstention_timing', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="asignación de presupuesto entre oportunidades heterogéneas / valor de la abstención (optimal stopping, knapsack-sobre-tiempo): concentrar un presupuesto global en las oportunidades de mayor valor y abstenerse en las pobres domina al gasto uniforme", obtained=False,
                     claim=("Con un presupuesto GLOBAL acotado y oportunidades (rondas) de valor HETEROGÉNEO, concentrar "
                            "el gasto en las de mayor valor y ABSTENERSE en las pobres domina al gasto uniforme "
                            "(knapsack-sobre-oportunidades / optimal stopping). El valor de NO actuar (guardar el "
                            "presupuesto) es real cuando las oportunidades varían. (Principio.)"))
S_ARC = Source(tier=5, ref="cognia_x/experiments/exp085_cost_aware_value", obtained=True,
               claim=("El arco de asignación (83-103) trató QUÉ elegir DENTRO de una ronda con presupuesto FIJO por ronda. "
                      "H-V4-8i añade la dimensión TEMPORAL: cómo asignar el presupuesto GLOBAL ENTRE rondas (timing/"
                      "abstención)."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp088 primero): " + results_path)

    vg = sm['varied_gain']
    vog = sm['varied_oracle_gap']
    fc = sm['flat_coincide']
    g = sm['grid']
    var = g['varied']
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim088 = ("exp088 (propio, {n} seeds, numpy): bajo rondas de riqueza VARIADA, asignar el presupuesto global por el "
                "valor estimado de cada ronda (gastar donde rinde, abstenerse donde no) threshold={th} ≈ oracle (gap {og}) "
                ">> uniform={un} (+{vg}); bajo riqueza FLAT coinciden (Δ {fc}). El timing/abstención del presupuesto es "
                "R-VALOR.").format(n=n_seeds, th=_f(var['threshold']), og=_f(vog), un=_f(var['uniform']), vg=_f(vg), fc=_f(fc))
    S_EXP088 = Source(tier=5, ref="cognia_x/experiments/exp088_abstention_timing", obtained=True, claim=claim088)
    for src in (S_PRINCIPLE, S_ARC, S_EXP088):
        ledger.add_source(src)
    notes.append("3 fuentes (S_PRINCIPLE tier2 presupuesto-entre-oportunidades/abstención; S_ARC tier5 within-round del arco; S_EXP088 tier5 dato propio).")

    ev_for = [S_EXP088.ref]
    ev_against = [S_EXP088.ref, S_ARC.ref, S_PRINCIPLE.ref]
    advtext = ("{V} (dimensión NUEVA del arco: TIMING del presupuesto / ABSTENCIÓN): todo el arco de asignación (83-103) "
               "trató QUÉ elegir DENTRO de una ronda, con presupuesto FIJO por ronda. H-V4-8i añade la dimensión TEMPORAL: "
               "con un presupuesto GLOBAL acotado sobre T rondas de RIQUEZA heterogénea, ¿cuándo gastar? RESULTADO: bajo "
               "riquezas VARIADAS (algunas rondas ricas, muchas pobres), asignar el presupuesto global por el VALOR "
               "estimado de cada ronda -- gastar donde rinde, ABSTENERSE donde no -- SUPERA MASIVAMENTE a gastar uniforme: "
               "threshold={th} ≈ oracle (gap {og}) >> uniform={un} (+{vg}: el gasto uniforme malgasta la mayor parte del "
               "presupuesto en rondas pobres). Bajo riqueza FLAT coinciden (Δ {fc}: cuando todas las rondas rinden igual, "
               "el timing no importa) -> el efecto es ESPECÍFICO de la heterogeneidad temporal, no del método. => R-VALOR "
               "gobierna CUÁNDO gastar el presupuesto (timing/abstención), no sólo QUÉ elegir; el VALOR DE NO ACTUAR "
               "(abstenerse en rondas pobres para guardar el presupuesto para las ricas) es REAL. Es la dimensión TEMPORAL "
               "del arco de asignación, y conecta con la ABSTENCIÓN del razonamiento (CYCLE 46) y el costo (101): el "
               "presupuesto es un recurso que se asigna ENTRE oportunidades, no sólo dentro. EVIDENCIA EN CONTRA / "
               "caveats: el efecto es grande pero CONDICIONAL a la heterogeneidad de riqueza (bajo flat no aporta); "
               "rendimiento lineal k·riqueza (sin saturación intra-ronda -- con saturación el óptimo repartiría más); "
               "riqueza estimada ruidosa pero observable antes de gastar; numpy/juguete. La abstención supone poder "
               "GUARDAR el presupuesto entre rondas (presupuesto fungible global).").format(
                   V=status.upper(), th=_f(var['threshold']), og=_f(vog), un=_f(var['uniform']), vg=_f(vg), fc=_f(fc))

    hyp = Hypothesis(
        id="H-V4-8i",
        statement=("R-VALOR gobierna CUÁNDO gastar el presupuesto GLOBAL (timing/abstención), no sólo qué elegir: bajo "
                   "rondas de riqueza heterogénea, asignar el presupuesto por el valor estimado de cada ronda (gastar "
                   "donde rinde, abstenerse donde no) supera a gastar uniforme; bajo riqueza flat coinciden. El valor de "
                   "NO actuar es real."),
        prediction=("APOYADA si bajo riquezas VARIADAS threshold >> uniform (+>0.05) Y ≈ oracle, Y bajo FLAT coinciden; "
                    "REFUTADA si threshold ≈ uniform bajo variadas; MIXTA en otro caso. (Pre-registrada, numpy, 48 "
                    "seeds.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp088_abstention_timing")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-8i")
        notes.append("H-V4-8i marcada '{}' con DoD completo (dimensión temporal: timing/abstención del presupuesto).".format(status))

    analogy = AnalogyRecord(
        problem=("Tengo poca nafta y voy a pasar por varios pueblos; en algunos hay buenas oportunidades y en otros casi "
                 "nada. ¿Paro y gasto un poco en CADA pueblo, o guardo la nafta para los pueblos buenos?"),
        everyday=("Guardo la nafta para los pueblos buenos y me SALTEO los pobres. Parar en cada pueblo (uniforme) me "
                  "gasta la nafta en lugares que casi no rinden y llego sin nada a los buenos. Estimar qué pueblo vale la "
                  "pena y concentrar ahí (abstenerme en los pobres) rinde casi como si supiera de antemano cuáles eran "
                  "los buenos. Sólo da igual si TODOS los pueblos rinden parecido."),
        solutions=["asignar el presupuesto por valor de la oportunidad + abstenerse en las pobres: ≈ óptimo",
                   "gastar uniforme: malgasta el presupuesto en oportunidades pobres",
                   "el valor de NO actuar (guardar para mejores oportunidades) es real bajo heterogeneidad",
                   "si todas las oportunidades rinden igual (flat), el timing no importa"],
        principles=["R-VALOR gobierna CUÁNDO gastar (timing), no sólo qué elegir (within-round)",
                    "concentrar un presupuesto global en las oportunidades ricas + abstenerse en las pobres domina al uniforme",
                    "el valor de NO actuar (abstención) es real cuando las oportunidades varían en valor",
                    "el efecto es específico de la heterogeneidad temporal (bajo flat no aporta)"],
        adaptation=("El lab añade la dimensión TEMPORAL al arco de asignación R-VALOR: además de QUÉ elegir dentro de una "
                    "ronda (83-103), el agente decide CUÁNDO gastar su presupuesto global -- gastar en oportunidades ricas, "
                    "ABSTENERSE en las pobres. Junto con el within-round, la asignación R-VALOR completa es: estimar el "
                    "valor de cada oportunidad, gastar el presupuesto donde rinde (entre y dentro de rondas), abstenerse "
                    "donde no. Conecta con la abstención del razonamiento (CYCLE 46). Próximo: timing bajo riqueza "
                    "NO-observable a priori (optimal stopping real); saturación intra-ronda; integrar en el lazo cerrado "
                    "real; y SCALE."),
        measurement=("exp088 ({n} seeds): VARIED threshold={th} ≈ oracle (gap {og}) >> uniform={un} (+{vg}); FLAT coincide "
                     "(Δ {fc}).").format(n=n_seeds, th=_f(var['threshold']), og=_f(vog), un=_f(var['uniform']), vg=_f(vg), fc=_f(fc)),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (guardar la nafta para los pueblos buenos, saltear los pobres).")

    kl = ("REAL (exp088): R-VALOR gobierna el TIMING del presupuesto / la ABSTENCIÓN: bajo rondas de riqueza heterogénea, "
          "gastar donde rinde + abstenerse donde no (threshold={th} ≈ oracle, +{vg} sobre uniforme); bajo riqueza flat el "
          "timing no importa (Δ {fc}). El valor de NO actuar es real. TECHO: condicional a la heterogeneidad temporal; "
          "rendimiento lineal sin saturación intra-ronda; riqueza estimada observable antes de gastar; presupuesto "
          "fungible global; numpy/juguete.").format(th=_f(var['threshold']), vg=_f(vg), fc=_f(fc))
    ceilings.add(CeilingRecord(
        subsystem="R-VALOR — dimensión TEMPORAL: timing/abstención del presupuesto global entre oportunidades heterogéneas (gastar donde rinde, abstenerse donde no)",
        known_limit=kl,
        blockers=[{"text": "efecto CONDICIONAL a la heterogeneidad de riqueza entre rondas (bajo flat no aporta)", "kind": "diseno"},
                  {"text": "la riqueza estimada es OBSERVABLE antes de gastar; bajo riqueza NO-observable a priori sería optimal stopping real (decidir sin ver el futuro) -- no testeado", "kind": "diseno"},
                  {"text": "rendimiento LINEAL k·riqueza (sin saturación intra-ronda -- con saturación el óptimo repartiría más); presupuesto fungible global; numpy/juguete, no integrado con el lazo real ni SCALE", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP088.ref, S_ARC.ref]))
    notes.append("1 techo 'real': el timing/abstención del presupuesto es R-VALOR (dimensión temporal del arco de asignación).")

    dstmt = ("North-Star R-VALOR (dimensión TEMPORAL del arco de asignación: timing/abstención): R-VALOR gobierna CUÁNDO "
             "gastar el presupuesto global, no sólo qué elegir -- bajo oportunidades (rondas) de valor heterogéneo, gastar "
             "donde rinde y ABSTENERSE donde no supera masivamente al gasto uniforme (≈ oracle); el valor de NO actuar es "
             "real. Decisión: la asignación R-VALOR completa = estimar el valor de cada oportunidad y gastar el "
             "presupuesto donde rinde, ENTRE rondas (timing/abstención) y DENTRO de cada ronda (83-103); abstenerse en "
             "oportunidades pobres para guardar el presupuesto. Conecta con la abstención del razonamiento (CYCLE 46). "
             "Próximo: timing bajo riqueza no-observable a priori (optimal stopping); saturación intra-ronda; lazo cerrado "
             "real; y SCALE.")
    drat = ("exp088 (tier5, propio, {n} seeds, numpy): VARIED threshold={th} ≈ oracle (gap {og}) >> uniform={un} (+{vg}); "
            "FLAT coincide (Δ {fc}). Convergente con presupuesto-entre-oportunidades/abstención (tier2) y con el "
            "within-round del arco (tier5). APOYADA: el timing/abstención del presupuesto es R-VALOR.").format(
                n=n_seeds, th=_f(var['threshold']), og=_f(vog), un=_f(var['uniform']), vg=_f(vg), fc=_f(fc))
    dec = Decision(id="D-V4-66", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP088), _to_plain(S_ARC)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-66 ACEPTADA por el ledger (tier5 exp088 + tier5 exp085).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-66:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle104_abstention_timing',
                                description='CYCLE 104 (RESET v4, H-V4-8i: R-VALOR gobierna el timing/abstención del presupuesto -- APOYADA; dimensión temporal del arco de asignación).')
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
    print("RESUMEN — CYCLE 104 (RESET v4): R-VALOR gobierna el TIMING/ABSTENCIÓN del presupuesto (H-V4-8i) — dimensión temporal")
    print("=" * 78)
    print("veredicto H-V4-8i:", status.upper() if status else "?")
    print("  bajo riquezas variadas: gastar-donde-rinde + abstenerse >> uniforme (≈ oracle); bajo flat coinciden. El valor de NO actuar es real.")
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
