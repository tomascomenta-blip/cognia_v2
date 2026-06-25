r"""
cycle77_intervention_value.py — CICLO 77 (RESET v4, arco "R-VALOR bajo realismo"): H-V4-5g por las compuertas del
engine. REFUTADA (con matiz informativo): bajo costos NO-estacionarios + observación gateada por la acción, el
PROBLEMA es real (la ceguera al drift de lo cacheado duele) PERO la intervención NAIVE (re-sondar sacrificando un
slot entero) NO lo resuelve -- es demasiado burda. R-INTERVENCIÓN sobre la memoria NO se logra con este mecanismo.

H-V4-5g testeaba la intuición que el CYCLE 76 dejó abierta: ¿con drift de costos la intervención (re-sondar) se
vuelve necesaria? Respuesta: el efecto que la motiva existe, pero el mecanismo propuesto no paga.
DERIVA de exp061_intervention_value/results/results.json. Un REFUTADA que afila la próxima pregunta es un ciclo
EXITOSO (directiva v3 §4.1: fracaso-es-información).

Correr (DESPUÉS de exp061):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp061_intervention_value.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle77_intervention_value
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle77_intervention_value')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp061_intervention_value', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PM = Source(tier=1, ref="partial monitoring / cost-of-exploration (active sensing)", obtained=False,
              claim=("Bajo observación gateada por la acción, la exploración deliberada paga sólo si su COSTO es "
                     "menor que la información que recupera; una exploración burda (sacrificar capacidad fija) puede "
                     "costar más de lo que vale aunque el problema de observación exista. (Principio.)"))
S_TREE = Source(tier=5, ref="cognia_x/manager/decomposition_tree.md (hija CYCLE 76: drift+obs gateada -> ¿intervenir?)", obtained=True,
                claim=("El techo de CYCLE 76 (H-V4-5f) dejó como hija: 'R-INTERVENCIÓN sobre la memoria aparecería "
                       "con costos NO-estacionarios cacheados-no-observados'. H-V4-5g la testea: el efecto existe pero "
                       "el mecanismo naive de intervención no paga."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp061 primero): " + results_path)
    st, dr = sm['stationary'], sm['drift']
    miss_s, full_s, exp_s = st['value_miss'], st['value_full'], st['value_explore']
    o_d, full_d, miss_d, exp_d, lfu_d = (dr['oracle_value'], dr['value_full'], dr['value_miss'], dr['value_explore'], dr['lfu_freq'])
    obs_gap = sm['obs_gap_drift']
    n, m = data['args']['n'], data['args']['m']
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim061 = ("exp061 (propio, {n} seeds, numpy): obs gateada + drift de costos. ESTAC value_miss {ms} = value_full "
                "{fs} (obs gateada inocua sin drift). DRIFT value_miss {md} pierde {gap} vs value_full {fd} (la "
                "ceguera al drift de lo cacheado es REAL) PERO value_explore {ed} (re-sonda sacrificando un slot) NO "
                "supera a value_miss -> la intervención burda no paga. {V}.").format(
                    n=n_seeds, ms=_f(miss_s), fs=_f(full_s), md=_f(miss_d), gap=_f(obs_gap), fd=_f(full_d),
                    ed=_f(exp_d), V=status.upper())
    S_EXP061 = Source(tier=5, ref="cognia_x/experiments/exp061_intervention_value", obtained=True, claim=claim061)
    for src in (S_PM, S_TREE, S_EXP061):
        ledger.add_source(src)
    notes.append("3 fuentes (S_PM tier1 partial-monitoring/costo-exploración; S_TREE tier5 hija CYCLE 76; S_EXP061 tier5 dato propio).")

    # evidence_for = el efecto que motiva la hipótesis SÍ existe (gap real bajo drift); evidence_against = el mecanismo no paga.
    ev_for = [S_EXP061.ref, S_TREE.ref]
    ev_against = [S_EXP061.ref]
    adv = ("{V} (con matiz informativo; afila la próxima pregunta -- ciclo EXITOSO): H-V4-5g predijo que con drift de "
           "costos la intervención (re-sondar lo cacheado) se vuelve NECESARIA. DOS hallazgos: (A) el PROBLEMA que la "
           "motiva es REAL -- bajo drift value_miss {md} pierde {gap} vs value_full {fd}, mientras en ESTACIONARIO "
           "miss=full ({ms}={fs}): la ceguera al drift de lo CACHEADO (cacheado=nunca falla=nunca se re-observa su "
           "costo nuevo) es un efecto medible que NO existía sin drift. (B) PERO la intervención propuesta (re-sondar "
           "sacrificando 1 de m={m} slots de forma permanente) NO paga: value_explore {ed} ni siquiera supera a "
           "value_miss {md} bajo drift (recupera ~0% del gap de observación) y cuesta {stc} en estacionario. El "
           "slot-sacrifice permanente cuesta más capacidad (~1/{m}) de la que recupera (gap {gap}). => la hipótesis "
           "(este mecanismo de intervención es necesario/útil) queda REFUTADA, PERO el efecto subyacente (drift+obs "
           "gateada degrada) es real. LECCIÓN: la intervención sobre la memoria, si paga, debe ser CHEAP/TARGETED "
           "(re-sondar OCASIONAL gateado por SORPRESA -- usar el detector de cambio de CYCLE 59 para disparar un "
           "re-sondeo puntual -- no un slot fijo). NO se sobre-vende R-INTERVENCIÓN sobre la memoria: con este "
           "mecanismo burdo NO aparece. Próxima hija: intervención dirigida por sorpresa (barata).").format(
               V=status.upper(), md=_f(miss_d), gap=_f(obs_gap), fd=_f(full_d), ms=_f(miss_s), fs=_f(full_s),
               m=m, ed=_f(exp_d), stc=_f(exp_s - miss_s))

    hyp = Hypothesis(
        id="H-V4-5g",
        statement=("Bajo costos NO-estacionarios + observación gateada por la acción, la intervención (re-sondar lo "
                   "cacheado sacrificando un slot) se vuelve necesaria/útil para aprender el valor que la observación "
                   "pasiva no ve."),
        prediction=("APOYADA si con drift value_explore supera a value_miss (+>0.05) con el control de que sin drift "
                    "value_explore<=value_miss; REFUTADA si value_explore no supera a value_miss ni con drift; MIXTA "
                    "si ayuda pero el control no separa. (Pre-registrada.)"),
        status='abierta', confidence='media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=adv, experiment_ref="exp061_intervention_value")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-5g")
        notes.append("H-V4-5g marcada '{}' con DoD completo (REFUTADA = ciclo exitoso, fracaso-es-información).".format(status))

    analogy = AnalogyRecord(
        problem=("Lo que llevás en la mochila puede 'echarse a perder' sin que lo notes (no lo sacás, no lo revisás). "
                 "¿Conviene sacar cosas a propósito para revisarlas, si los precios cambian?"),
        everyday=("El problema es REAL: si lo que llevás cambió de valor y no lo revisás, cargás con cosas que ya no "
                  "sirven. PERO revisar sacando una cosa fija TODO el tiempo te deja siempre con un lugar menos -- "
                  "perdés más por el lugar vacío que lo que ganás detectando los cambios. Revisar a lo bruto no paga; "
                  "habría que revisar SÓLO cuando sospechás que algo cambió (puntual), no sacrificar un lugar fijo."),
        solutions=["value_miss (no revisa lo cacheado) -> pierde algo con drift, pero poco (el grueso del valor se observa al fallar lo no-cacheado)",
                   "value_full (revisa todo) -> cota; el gap con miss bajo drift es real pero chico",
                   "value_explore (sacrifica 1 slot fijo a revisar) -> NO paga: el slot perdido cuesta más que el drift detectado",
                   "(hija) re-sondar OCASIONAL gateado por sorpresa -> revisar puntual sólo cuando se sospecha cambio"],
        principles=["el problema (drift + obs gateada degrada lo cacheado-no-observado) es REAL y medible",
                    "una intervención BURDA (sacrificar capacidad fija) puede costar más de lo que recupera aunque el problema exista",
                    "la intervención sobre la memoria, si paga, debe ser CHEAP/TARGETED (gateada por sorpresa), no un slot fijo",
                    "fracaso-es-información: REFUTAR el mecanismo naive afila la pregunta (R-INTERVENCIÓN barata)"],
        adaptation=("El lab NO adopta el re-sondeo por slot fijo. Próxima hija: re-sondeo OCASIONAL disparado por la "
                    "SORPRESA (reusar el detector de cambio endógeno de CYCLE 59): cuando el hit-rate ponderado por "
                    "costo cae, disparar un re-sondeo puntual de lo cacheado-viejo; medir si ESA intervención barata "
                    "paga bajo drift."),
        measurement=("exp061: ESTAC miss {ms}=full {fs}; DRIFT miss {md} pierde {gap} vs full {fd}, explore {ed} no "
                     "recupera. {n} seeds.").format(
                         ms=_f(miss_s), fs=_f(full_s), md=_f(miss_d), gap=_f(obs_gap), fd=_f(full_d), ed=_f(exp_d),
                         n=n_seeds),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (revisar a lo bruto no paga; el problema es real, el mecanismo burdo no).")

    kl = ("REAL (exp061): bajo obs gateada + DRIFT de costos, el problema es REAL (value_miss {md} pierde {gap} vs "
          "value_full {fd}; en estac. miss=full {ms}) PERO la intervención NAIVE (re-sondar por slot fijo) NO paga "
          "(value_explore {ed} no supera a value_miss). R-INTERVENCIÓN sobre la memoria NO se logra con este "
          "mecanismo burdo; necesita ser cheap/targeted (sorpresa-gateada).").format(
              md=_f(miss_d), gap=_f(obs_gap), fd=_f(full_d), ms=_f(miss_s), ed=_f(exp_d))
    ceilings.add(CeilingRecord(
        subsystem="R-INTERVENCIÓN x MEMORIA — el problema (drift+obs gateada) es real, pero la intervención naive (slot fijo) NO paga",
        known_limit=kl,
        blockers=[{"text": "la intervención por slot fijo cuesta ~1/m de capacidad permanente > el gap de observación que recupera; hace falta re-sondeo OCASIONAL gateado por sorpresa (CYCLE 59)", "kind": "diseno"},
                  {"text": "el efecto de drift sobre lo cacheado-no-observado es REAL pero CHICO (gap ~0.05) -> la observación pasiva del contrafáctico sigue siendo casi suficiente aun con drift", "kind": "diseno"},
                  {"text": "drift abrupto recurrente; valor = frecuencia×costo; juguete (Pareto, n=50)", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP061.ref, S_TREE.ref]))
    notes.append("1 techo 'real': el problema drift+obs-gateada es real pero la intervención naive (slot fijo) no paga; afila a intervención sorpresa-gateada.")

    dstmt = ("North-Star R-VALOR/R-INTERVENCIÓN sobre la memoria (REFUTA el mecanismo naive; afila la pregunta): bajo "
             "obs gateada + DRIFT de costos el problema es REAL (value_miss {md} pierde {gap} vs full {fd}; en estac. "
             "miss=full {ms}) PERO la intervención por slot fijo NO paga (value_explore {ed} no supera a miss). "
             "Decisión: el lab NO adopta re-sondeo por slot fijo; la intervención sobre la memoria, si paga, debe ser "
             "CHEAP/TARGETED (sorpresa-gateada, reusar CYCLE 59). HONESTO: no se sobre-vende R-INTERVENCIÓN sobre la "
             "memoria -- con mecanismo burdo NO aparece. Próxima hija: re-sondeo ocasional disparado por sorpresa.").format(
                 md=_f(miss_d), gap=_f(obs_gap), fd=_f(full_d), ms=_f(miss_s), ed=_f(exp_d))
    drat = ("exp061 (tier5, propio, {n} seeds): DRIFT value_miss {md} pierde {gap} vs full {fd} (problema real); "
            "value_explore {ed} no supera a miss (mecanismo burdo no paga); ESTAC miss {ms}=full {fs} (control). "
            "Convergente con costo-de-exploración/partial-monitoring (tier1). REFUTADA.").format(
                n=n_seeds, md=_f(miss_d), gap=_f(obs_gap), fd=_f(full_d), ed=_f(exp_d), ms=_f(miss_s), fs=_f(full_s))
    dec = Decision(id="D-V4-39", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP061), _to_plain(S_TREE)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-39 ACEPTADA por el ledger (tier5 exp061 + tier5 hija CYCLE 76).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-39:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle77_intervention_value',
                                description='CYCLE 77 (RESET v4, H-V4-5g: intervención sobre la memoria bajo drift -- REFUTADA).')
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
    print("RESUMEN — CYCLE 77 (RESET v4): intervención sobre la memoria bajo drift (H-V4-5g) — REFUTADA (informativa)")
    print("=" * 78)
    print("veredicto H-V4-5g:", status.upper() if status else "?")
    print("  el problema (drift+obs gateada) es real, pero la intervención naive (slot fijo) NO paga.")
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
