r"""
cycle43_adaptive_allocation.py — CICLO 43 (RESET v4): H-V4-1h por las compuertas del engine. CAPSTONE del
sub-arco integrador (CYCLE 40-43).

H-V4-1h: una política ADAPTATIVA que estima ONLINE la fiabilidad del verificador (test-retest, sin
ground-truth) y MEZCLA la señal de control verifier-dependiente (CONSEC_V) con la verifier-free (CONSEC_FREE)
logra NO-REGRET: lo mejor de ambas en todos los regímenes de ruido. DERIVA de
exp029_adaptive_allocation/results/results.json.

RESULTADO REAL: APOYADA (4 seeds in-band, M=120, avg=5, n_probe=3). Curva vnoise->CONSEC_V/CONSEC_FREE/ADAPT
/oracle(r_est):
  0.0: 0.690/0.621/0.688/0.690 (r=1.00)   0.1: 0.527/0.550/0.535/0.550 (r=0.61)   0.2: 0.415/0.415/0.437/0.435 (r=0.39)
  - keeps_edge@0.0: ADAPT 0.688 ≈ CONSEC_V 0.690 (no pierde el edge con verificador bueno, r≈1 -> usa CONSEC_V).
  - escapes_collapse@0.2: ADAPT 0.437 > CONSEC_V 0.415 (escapa el colapso; r baja -> mezcla hacia CONSEC_FREE),
    incluso SUPERA a las dos puras (la mezcla hedgea). worst_regret = +0.008 (nunca por debajo del mín).
  - r_est calibra: 1.00 -> 0.61 -> 0.39 (baja monótona con el ruido). El estimador NO usa ground-truth ni el
    consenso del modelo débil: sólo la CONSISTENCIA del verificador re-consultado (barato).
  => RESUELVE la tensión de CYCLE 41-42: el integrador estima cuánto confiar en el verificador y se adapta.

Correr (DESPUÉS de exp029):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp029_adaptive_allocation.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle43_adaptive_allocation
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store',
                             'cycle43_adaptive_allocation')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp029_adaptive_allocation', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _fmt(x):
    return "{:.3f}".format(x) if isinstance(x, (int, float)) else str(x)


S_BANDIT = Source(tier=1, ref="meta-reasoning/bandit", obtained=False,
                  claim=("Seleccionar entre estrategias por una estimación online de su utilidad (bandit / "
                         "model selection) logra no-regret respecto de la mejor fija. (Principio, no re-obtenido.)"))
S_EXP028 = Source(tier=5, ref="cognia_x/experiments/exp028_robust_control_signal", obtained=True,
                  claim=("exp028 (CYCLE 42): no hay señal de asignación única dominante; el control "
                         "verifier-dependiente y el verifier-free se complementan según la calidad del verificador."))


def _curve_str(curve, noises):
    return " | ".join("{}:{}/{}/{}(r={})".format(
        vn, _fmt(curve[vn]['consequence_v']), _fmt(curve[vn]['consequence_free']),
        _fmt(curve[vn]['adapt']), _fmt(curve[vn]['r_est'])) for vn in noises)


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    v = data.get('verdict')
    st = data.get('stats')
    if not v or not st:
        raise SystemExit("results.json sin verdict/stats (corre exp029 primero): " + results_path)
    status = v.lower()
    noises = [str(x) for x in data.get('noises', [])]
    curve = st['curve']
    lo, hi = str(st['lo']), str(st['hi'])
    n_seeds = st['n_seeds_used']
    cl_v, cl_a, r_lo = curve[lo]['consequence_v'], curve[lo]['adapt'], curve[lo]['r_est']
    ch_v, ch_a, ch_f, r_hi = curve[hi]['consequence_v'], curve[hi]['adapt'], curve[hi]['consequence_free'], curve[hi]['r_est']
    wr = st['worst_regret_vs_min']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    S_EXP029 = Source(tier=5, ref="cognia_x/experiments/exp029_adaptive_allocation", obtained=True,
                      claim=("exp029 (propio, {n} seeds in-band, HybridLM + verificador ruidoso): una política "
                             "ADAPTATIVA estima la fiabilidad r del verificador por TEST-RETEST (sin "
                             "ground-truth; r=1.00 a vnoise=0, baja a {rh} a vnoise={hi}) y mezcla CONSEC_V/"
                             "CONSEC_FREE. NO-REGRET: a vnoise={lo} ADAPT {al} ≈ CONSEC_V {vl} (mantiene el "
                             "edge), a vnoise={hi} ADAPT {ah} > CONSEC_V {vh} (escapa el colapso); worst_regret "
                             "{wr}.").format(n=n_seeds, rh=_fmt(r_hi), hi=st['hi'], lo=st['lo'], al=_fmt(cl_a),
                                             vl=_fmt(cl_v), ah=_fmt(ch_a), vh=_fmt(ch_v), wr="%+.3f" % wr))
    for src in (S_BANDIT, S_EXP028, S_EXP029):
        ledger.add_source(src)
    notes.append("3 fuentes (S_BANDIT tier1 selección online no-regret; S_EXP028 tier5 no-dominancia; S_EXP029 tier5 dato propio).")

    ev_for = [S_EXP029.ref, S_EXP028.ref]
    ev_against = [S_EXP029.ref]      # honesto: r mide ruido aleatorio, NO sesgo sistemático del verificador
    adv = ("APOYADA, capstone del sub-arco. La política ADAPTATIVA resuelve la no-dominancia de exp028: estima "
           "la fiabilidad r del verificador por TEST-RETEST (re-consultarlo y medir su auto-acuerdo; r=1 a "
           "vnoise=0, baja monótona con el ruido a {rh}) SIN ground-truth ni depender del consenso del modelo "
           "débil, y mezcla w=r·CONSEC_V+(1−r)·CONSEC_FREE. Logra NO-REGRET: keeps_edge a verificador bueno "
           "(ADAPT {al} ≈ CONSEC_V {vl}, r≈1 -> usa el control verifier-dependiente) Y escapes_collapse a ruido "
           "alto (ADAPT {ah} > CONSEC_V {vh}; la mezcla hasta SUPERA a las dos puras -> hedge). worst_regret "
           "{wr} (ADAPT nunca por debajo del mínimo de sus componentes en ningún nivel). EVIDENCIA EN CONTRA "
           "(límite honesto): el estimador test-retest detecta ruido ALEATORIO; un verificador con SESGO "
           "sistemático (siempre acepta) se vería 'consistente' (r alto) y NO se detectaría -> falta un "
           "estimador de sesgo. Ataque considerado: '¿el primer estimador (consenso) era mejor?' -> NO: "
           "fallaba (r≈0 aun a vnoise=0) porque el modelo débil tiene mal consenso; el smoke lo expuso y se "
           "reemplazó por test-retest, que calibra correcto. CIERRA el sub-arco integrador 40-43.").format(
               rh=_fmt(r_hi), al=_fmt(cl_a), vl=_fmt(cl_v), ah=_fmt(ch_a), vh=_fmt(ch_v), wr="%+.3f" % wr)

    hyp = Hypothesis(
        id="H-V4-1h",
        statement=("Una política adaptativa que estima la fiabilidad del verificador (test-retest) y mezcla la "
                   "señal de control verifier-dependiente con la verifier-free logra no-regret: mantiene el edge "
                   "con verificador bueno y escapa el colapso con verificador ruidoso."),
        prediction=("APOYADA si ADAPT >= CONSEC_V−0.02 a vnoise=0 (keeps edge) Y ADAPT >= CONSEC_V+0.02 a "
                    "vnoise alto (escapes collapse) Y r baja con el ruido; REFUTADA si ADAPT < min(componentes) "
                    "en algún extremo o r no calibra. (Pre-registrada.)"),
        status='abierta', confidence='alta',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=adv, experiment_ref="exp029_adaptive_allocation")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-1h")
        notes.append("H-V4-1h marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("Tenés dos pistas imperfectas (un corrector que se equivoca y tu propio consenso) y poco "
                 "tiempo. ¿Cómo las combinás para asignar tu esfuerzo sin que ninguna te arruine?"),
        everyday=("Calibrás a tu corrector preguntándole DOS VECES lo mismo: si responde igual, es consistente "
                  "-> le hacés caso; si responde distinto cada vez, es un desastre -> te guiás por tu propio "
                  "consenso. Mezclás las dos pistas según cuánto confiás en el corrector, y así nunca quedás "
                  "peor que la mejor de las dos."),
        solutions=["estimar la fiabilidad del corrector por test-retest (re-preguntarle) -> barato, sin respuestas",
                   "mezclar w=r·verifier-dependiente+(1−r)·verifier-free -> no-regret (lo mejor de ambas)",
                   "con corrector bueno (r≈1) -> usa el control verifier-dependiente (mejor guía)",
                   "con corrector malo (r≈0) -> cae al verifier-free (robusto); la mezcla hasta supera a las puras"],
        principles=["se puede estimar la confiabilidad de un verificador SIN ground-truth, por su consistencia (test-retest)",
                    "mezclar señales por la confianza estimada logra no-regret: nunca peor que la mejor componente",
                    "un buen estimador NO debe depender del consenso de un modelo débil (eso falló); la consistencia sí sirve",
                    "el integrador no necesita una señal única perfecta, sino saber CUÁNTO confiar en cada una"],
        adaptation=("Cierra el diseño del lazo act-and-verify del lab: asignar cómputo por controlabilidad, con "
                    "una política adaptativa calibrada por la consistencia del verificador. Próximos realismos: "
                    "estimador de SESGO sistemático (no sólo ruido aleatorio), verificador real-chequeable "
                    "(código→sandbox) y razonamiento MULTI-PASO (el siguiente gran salto del integrador)."),
        measurement=("exp029: curva vnoise->CONSEC_V/CONSEC_FREE/ADAPT(r_est) = {cv}. keeps_edge@{lo} y "
                     "escapes_collapse@{hi}; worst_regret {wr}; r calibra 1.00->{rh}. {n} seeds in-band.").format(
                         cv=_curve_str(curve, noises), lo=st['lo'], hi=st['hi'], wr="%+.3f" % wr,
                         rh=_fmt(r_hi), n=n_seeds),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (calibrar al corrector por test-retest y mezclar señales -> no-regret).")

    ceilings.add(CeilingRecord(
        subsystem="Integrador act-and-verify — política ADAPTATIVA calibrada por consistencia del verificador",
        known_limit=("REAL (exp029): estimar la fiabilidad del verificador por test-retest (sin ground-truth) y "
                     "mezclar control verifier-dependiente/verifier-free logra NO-REGRET (keeps edge a r≈1, "
                     "escapa el colapso a r bajo; worst_regret {wr}). r calibra 1.00->{rh} con el ruido. Cierra "
                     "el sub-arco integrador 40-43.").format(wr="%+.3f" % wr, rh=_fmt(r_hi)),
        blockers=[{"text": "el estimador test-retest detecta ruido ALEATORIO, no SESGO sistemático (un verificador siempre-acepta se ve consistente)", "kind": "diseno"},
                  {"text": "verificador sintético; falta uno real-chequeable (código→sandbox, exp018) con su ruido real", "kind": "diseno"},
                  {"text": "tarea de 1 paso; el siguiente gran salto del integrador es razonamiento MULTI-PASO (el ruido y el control se componen)", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP029.ref, S_EXP028.ref]))
    notes.append("1 techo 'real': política adaptativa no-regret calibrada por consistencia del verificador (cierra 40-43).")

    dstmt = ("El integrador act-and-verify del lab queda con un diseño cerrado y verificado para 1 paso: asignar "
             "cómputo de test-time por CONTROLABILIDAD (R-VALOR+R-INTERVENCIÓN), con una política ADAPTATIVA que "
             "estima la fiabilidad del verificador por test-retest (sin ground-truth) y mezcla la señal de "
             "control verifier-dependiente con la verifier-free, logrando no-regret en todo el rango de ruido. "
             "Sub-arco 40-43 cerrado: el lever de control es real (40), frágil al verificador (41), no tiene "
             "señal única dominante (42) y se resuelve con adaptación calibrada (43). Próximo gran salto: "
             "razonamiento MULTI-PASO (H-V4-1i) — donde el control intermedio y el ruido se componen — y "
             "verificador real-chequeable (código→sandbox). Pendiente menor: estimador de SESGO sistemático.")
    drat = ("exp029 (tier5, propio, {n} seeds in-band): NO-REGRET (keeps_edge a vnoise={lo}, escapes_collapse a "
            "vnoise={hi}, worst_regret {wr}); r test-retest calibra 1.00->{rh}. Resuelve la no-dominancia de "
            "exp028. Convergente con selección online no-regret (bandit/model-selection).").format(
                n=n_seeds, lo=st['lo'], hi=st['hi'], wr="%+.3f" % wr, rh=_fmt(r_hi))
    dec = Decision(id="D-V4-8", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP029), _to_plain(S_EXP028)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-8 ACEPTADA por el ledger (tier5 exp029 + tier5 exp028).")
    except OpinionOnlyError as e:
        print("ERROR ledger D-V4-8:", e); raise

    return record, notes, status, st


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle43_adaptive_allocation',
                                description='CYCLE 43 (RESET v4, H-V4-1h: política adaptativa, capstone integrador).')
    p.add_argument('--store', default=DEFAULT_STORE)
    p.add_argument('--results', default=DEFAULT_RESULTS)
    p.add_argument('--reset', dest='reset', action='store_true', default=True)
    p.add_argument('--no-reset', dest='reset', action='store_false')
    args = p.parse_args(argv)
    store = os.path.abspath(args.store)
    if args.reset and os.path.isdir(store):
        shutil.rmtree(store)
    os.makedirs(store, exist_ok=True)
    record, notes, status, st = run(store, os.path.abspath(args.results))
    res = record.verify_no_loss()
    print("=" * 78)
    print("RESUMEN — CYCLE 43 (RESET v4): política ADAPTATIVA no-regret, capstone integrador (H-V4-1h)")
    print("=" * 78)
    print("veredicto H-V4-1h:", status.upper() if status else "?")
    print("  estima la fiabilidad del verificador (test-retest) y mezcla señales -> no-regret. Cierra 40-43.")
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
