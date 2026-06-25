r"""
cycle75_value_vs_frequency.py — CICLO 75 (RESET v4, arco "R-VALOR bajo realismo", capstone CONCEPTUAL): H-V4-5e por
las compuertas del engine. El VALOR != FRECUENCIA. El valor de recordar es task-definido (frecuencia × COSTO de
fallar), no la frecuencia. Cuando el valor diverge de la frecuencia, estimar el VALOR vence a estimar la FRECUENCIA
(LFU), que optimiza la señal equivocada; cuando valor proporcional a frecuencia, convergen. Rebate "esto es sólo LFU".

H-V4-5e separa lo que el sub-arco 72-74 había juntado (valor = prob de consulta). DERIVA de
exp059_value_vs_frequency/results/results.json.

Correr (DESPUÉS de exp059):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp059_value_vs_frequency.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle75_value_vs_frequency
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle75_value_vs_frequency')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp059_value_vs_frequency', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_COSTAWARE = Source(tier=1, ref="value-of-information / cost-aware caching (GreedyDual-Size-Frequency)", obtained=False,
                     claim=("El valor de retener un item bajo capacidad finita es su frecuencia de acceso × el COSTO "
                            "de no tenerlo, no la frecuencia sola; las políticas cost-aware DOMINAN a LFU cuando los "
                            "costos VARÍAN entre items. (Principio; converge con value-of-information.)"))
S_TREE = Source(tier=5, ref="cognia_x/manager/decomposition_tree.md (R-VALOR task-definido; caveat frecuencia-pura 72-74)", obtained=True,
                claim=("El thesis v4 (R-VALOR): el valor de una traza = su información mutua con consultas/RECOMPENSAS "
                       "FUTURAS, task-definido, NO un proxy de frecuencia. El sub-arco 72-74 usó valor=frecuencia "
                       "(prob de consulta); H-V4-5e separa frecuencia de valor (frecuencia × costo)."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp059 primero): " + results_path)
    uni, var = sm['uniform'], sm['varying']
    o_v, lfu_v, val_v, rnd_v = (var['oracle_value'], var['lfu_freq'], var['value_est'], var['random'])
    lfu_u, val_u = uni['lfu_freq'], uni['value_est']
    frac = sm['fraction_recovered_varying']
    n, m = data['args']['n'], data['args']['m']
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim059 = ("exp059 (propio, {n} seeds, numpy): memoria online m={m}/{N}; valor = frecuencia × costo de fallar. "
                "COST_VARYING (v!=f): value_est {vv} recupera {p}% del oráculo ({ov}); lfu_freq {lv} (LFU deja {sub} "
                "sobre la mesa). COST_UNIFORM (v~f): value_est {vu} ~ lfu_freq {lu}. => estimar la FRECUENCIA falla "
                "cuando el valor diverge; hay que estimar el VALOR de la tarea.").format(
                    n=n_seeds, m=m, N=n, vv=_f(val_v), p=int(round(frac * 100)), ov=_f(o_v), lv=_f(lfu_v),
                    sub=_f(o_v - lfu_v), vu=_f(val_u), lu=_f(lfu_u))
    S_EXP059 = Source(tier=5, ref="cognia_x/experiments/exp059_value_vs_frequency", obtained=True, claim=claim059)
    for src in (S_COSTAWARE, S_TREE, S_EXP059):
        ledger.add_source(src)
    notes.append("3 fuentes (S_COSTAWARE tier1 cost-aware caching/VoI; S_TREE tier5 thesis R-VALOR task-definido; S_EXP059 tier5 dato propio).")

    ev_for = [S_EXP059.ref, S_TREE.ref]
    ev_against = [S_EXP059.ref]
    adv = ("{V} (capstone CONCEPTUAL del arco realismo; eleva el arco más allá de 'LFU textbook'): el sub-arco 72-74 "
           "estimó el valor por FRECUENCIA -- pero ahí el valor ERA la frecuencia (prob de consulta), así que la "
           "frecuencia era un estimador perfecto. El thesis dice que el valor es task-definido (info mutua con "
           "consultas/recompensas FUTURAS), no un proxy de frecuencia. exp059 lo SEPARA: cada item tiene frecuencia "
           "f_i Y costo-de-fallar c_i (independiente); el valor es v=f×c. COST_VARYING (v!=f): value_est (estima el "
           "costo acumulado observado = MC de f×c) {vv} recupera {p}% de la ventaja del oráculo ({ov}); lfu_freq "
           "(sólo frecuencia) se queda en {lv} (+{adv}) -- LFU deja {sub} de valor sobre la mesa porque guarda lo "
           "frecuente-BARATO y falla lo raro-CARO: optimiza la señal EQUIVOCADA. COST_UNIFORM (v~f): value_est {vu} ~ "
           "lfu_freq {lu} (|dif| {difu}) -- SIN divergencia NO hay ventaja, así que la ventaja la DRIVE que el valor "
           "diverja de la frecuencia, no que value_est sea genéricamente mejor (control limpio). EVIDENCIA EN CONTRA "
           "(caveats honestos): (1) el costo se OBSERVA en cada consulta (stakes reveladas); la versión dura sólo lo "
           "revela al FALLAR (tensión exploración: hay que fallar para aprender el costo) -- queda como hija. (2) "
           "costo INDEPENDIENTE de la frecuencia (divergencia máxima); correlación parcial atenuaría la ventaja. (3) "
           "estacionario; juguete (Pareto, n=50). CONCLUSIÓN: R-VALOR es task-definido -- estimar un PROXY (frecuencia) "
           "falla cuando el valor diverge; el agente debe estimar el VALOR de la tarea de sus consecuencias "
           "(frecuencia × costo observado). Conecta el arco memoria con R-INTERVENCIÓN (aprender valor de "
           "consecuencias, CYCLE 40-48). Rebate 'esto es sólo LFU': LFU es óptimo SÓLO cuando valor=frecuencia.").format(
               V=status.upper(), vv=_f(val_v), p=int(round(frac * 100)), ov=_f(o_v), lv=_f(lfu_v),
               adv=_f(val_v - lfu_v), sub=_f(o_v - lfu_v), vu=_f(val_u), lu=_f(lfu_u), difu=_f(abs(val_u - lfu_u)))

    hyp = Hypothesis(
        id="H-V4-5e",
        statement=("El valor de recordar es task-definido (frecuencia × costo de fallar), no la frecuencia: cuando el "
                   "valor diverge de la frecuencia, estimar el VALOR vence a estimar la frecuencia (LFU)."),
        prediction=("APOYADA si en cost-varying value_est supera a lfu (+>0.05) Y recupera >=70% del oráculo Y en "
                    "cost-uniform value_est ~ lfu (|dif|<0.04: la ventaja la DRIVE la divergencia); REFUTADA si value "
                    "no supera a lfu o daña en uniform; MIXTA si ayuda parcial. (Pre-registrada.)"),
        status='abierta', confidence='alta' if status == 'apoyada' else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=adv, experiment_ref="exp059_value_vs_frequency")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-5e")
        notes.append("H-V4-5e marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("Tu mochila entra m de n cosas. Algunas las usás SEGUIDO; otras casi nunca PERO si te falta una de "
                 "esas te cuesta carísimo. ¿Guardás lo que más usás, o lo que más te CUESTA no tener?"),
        everyday=("Lo que más te CUESTA no tener. Si guardás sólo lo frecuente, dejás afuera el paraguas que usás dos "
                  "veces al año pero cuya falta te empapa: pagás caro por optimizar 'frecuencia' en vez de 'valor'. "
                  "Cuando todo cuesta IGUAL, frecuencia y valor coinciden y da lo mismo. Cuando los costos VARÍAN, "
                  "tenés que estimar el VALOR (cuánto te cuesta fallarlo × cuán seguido), no sólo contar usos."),
        solutions=["value_est (frecuencia × costo observado) -> recupera ~el oráculo cuando valor != frecuencia",
                   "lfu_freq (sólo frecuencia) -> óptimo SÓLO si todo cuesta igual; deja valor sobre la mesa si no",
                   "oracle_value (sabe f×c verdadero) -> cota superior",
                   "value~lfu cuando el costo es uniforme -> la ventaja la DRIVE la divergencia, no value_est per se"],
        principles=["el valor de recordar es task-definido (frecuencia × costo), NO la frecuencia",
                    "estimar un PROXY (frecuencia) falla cuando el valor diverge de él; hay que estimar el VALOR de la tarea",
                    "LFU es óptimo SÓLO cuando valor=frecuencia; el caso general necesita el costo/consecuencia",
                    "el agente aprende el valor de sus CONSECUENCIAS (costo observado) -> liga memoria con R-INTERVENCIÓN"],
        adaptation=("El lab estima el valor de la tarea (frecuencia × costo de consecuencia observado), no un proxy de "
                    "frecuencia. Próximo: costo revelado SÓLO al fallar (exploración: actuar para aprender el valor, "
                    "R-INTERVENCIÓN); valor endógeno aún más rico (info-gain/confianza, CYCLE 56-57); downstream no-IID."),
        measurement=("exp059 (m={m}/{N}): COST_VARYING value_est {vv} (recupera {p}%) vs lfu {lv} (oráculo {ov}); "
                     "COST_UNIFORM value {vu} ~ lfu {lu}. {n} seeds.").format(
                         m=m, N=n, vv=_f(val_v), p=int(round(frac * 100)), lv=_f(lfu_v), ov=_f(o_v), vu=_f(val_u),
                         lu=_f(lfu_u), n=n_seeds),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (guardá lo que más te CUESTA no tener, no lo que más usás).")

    kl = ("REAL (exp059): el valor de recordar es task-definido (frecuencia × costo), NO la frecuencia. Cuando v!=f "
          "(cost-varying), value_est {vv} recupera {p}% del oráculo ({ov}) y lfu_freq {lv} deja {sub} sobre la mesa "
          "(optimiza la señal equivocada); cuando v~f (cost-uniform), value_est {vu} ~ lfu {lu}. R-VALOR es "
          "task-definido: estimar un proxy de frecuencia falla; hay que estimar el VALOR de sus consecuencias.").format(
              vv=_f(val_v), p=int(round(frac * 100)), ov=_f(o_v), lv=_f(lfu_v), sub=_f(o_v - lfu_v), vu=_f(val_u), lu=_f(lfu_u))
    ceilings.add(CeilingRecord(
        subsystem="R-VALOR task-definido — el valor de recordar es frecuencia × costo, NO la frecuencia (LFU falla si v!=f)",
        known_limit=kl,
        blockers=[{"text": "el costo se OBSERVA en cada consulta; la versión dura lo revela sólo al FALLAR (exploración: actuar para aprender el valor, R-INTERVENCIÓN) -- hija", "kind": "diseno"},
                  {"text": "costo INDEPENDIENTE de la frecuencia (divergencia máxima); correlación parcial atenuaría la ventaja", "kind": "diseno"},
                  {"text": "estacionario; valor endógeno = frecuencia×costo (falta info-gain/confianza, CYCLE 56-57); juguete (Pareto, n=50, IID)", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP059.ref, S_TREE.ref]))
    notes.append("1 techo 'real': el valor de recordar es task-definido (frecuencia×costo); estimar la frecuencia sola falla cuando v!=f.")

    dstmt = ("North-Star R-VALOR bajo realismo (capstone CONCEPTUAL; eleva el arco más allá de 'LFU textbook'): el "
             "valor de recordar es task-definido (frecuencia × costo de fallar), NO la frecuencia. Cuando v!=f, "
             "value_est (estima el costo acumulado observado) recupera {p}% del oráculo ({ov}) y lfu_freq {lv} deja "
             "{sub} sobre la mesa (señal equivocada); cuando v~f, value_est {vu} ~ lfu {lu} (la ventaja la DRIVE la "
             "divergencia). Decisión: el lab estima el VALOR de la tarea (frecuencia × costo de consecuencia "
             "observado), no un proxy de frecuencia. R-VALOR es task-definido -> liga el arco memoria con "
             "R-INTERVENCIÓN (aprender valor de consecuencias, CYCLE 40-48). Próximo: costo revelado sólo al fallar "
             "(exploración); valor endógeno más rico (info-gain/confianza).").format(
                 p=int(round(frac * 100)), ov=_f(o_v), lv=_f(lfu_v), sub=_f(o_v - lfu_v), vu=_f(val_u), lu=_f(lfu_u))
    drat = ("exp059 (tier5, propio, {n} seeds): COST_VARYING value_est {vv} recupera {p}% del oráculo {ov}, +{adv} "
            "sobre lfu {lv}; COST_UNIFORM value {vu} ~ lfu {lu}. Convergente con cost-aware caching/VoI (tier1) y con "
            "el thesis R-VALOR task-definido (tier5). {V}.").format(
                n=n_seeds, vv=_f(val_v), p=int(round(frac * 100)), ov=_f(o_v), adv=_f(val_v - lfu_v), lv=_f(lfu_v),
                vu=_f(val_u), lu=_f(lfu_u), V=status.upper())
    dec = Decision(id="D-V4-37", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP059), _to_plain(S_TREE)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-37 ACEPTADA por el ledger (tier5 exp059 + tier5 thesis R-VALOR task-definido).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-37:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle75_value_vs_frequency',
                                description='CYCLE 75 (RESET v4, H-V4-5e: el valor != frecuencia, task-definido).')
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
    print("RESUMEN — CYCLE 75 (RESET v4): el VALOR != FRECUENCIA, task-definido (H-V4-5e) — capstone conceptual")
    print("=" * 78)
    print("veredicto H-V4-5e:", status.upper() if status else "?")
    print("  el valor de recordar es frecuencia×costo, no la frecuencia; estimar el proxy falla cuando v!=f.")
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
