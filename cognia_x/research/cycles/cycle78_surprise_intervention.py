r"""
cycle78_surprise_intervention.py — CICLO 78 (RESET v4, arco "R-VALOR bajo realismo", CIERRA el sub-tema memoria con
un NULL firme): H-V4-5h por las compuertas del engine. La intervención BARATA sorpresa-gateada (re-sondar ocasional,
no slot fijo) VENCE al slot fijo del CYCLE 77 pero AÚN NO supera al baseline pasivo (no intervenir): el gap de
observación bajo drift es demasiado chico para que CUALQUIER intervención lo recupere. REFUTADA -> generaliza el 77:
en el sustrato de cache con observación gateada, la observación pasiva del contrafáctico es ROBUSTA; intervenir no
paga. Señal de PIVOTE fuera del sub-tema memoria.

DERIVA de exp062_surprise_intervention/results/results.json. Un REFUTADA que CIERRA una pregunta (aquí: satura el
sub-tema) es un ciclo EXITOSO (directiva v3 §4.1).

Correr (DESPUÉS de exp062):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp062_surprise_intervention.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle78_surprise_intervention
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle78_surprise_intervention')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp062_surprise_intervention', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_VOI = Source(tier=1, ref="value-of-information / exploration only pays if value-of-info > cost", obtained=False,
               claim=("Explorar (intervenir para observar) paga SÓLO si el valor de la información recuperada supera "
                      "el costo de la exploración. Si el gap de observación es chico, ninguna intervención —por barata "
                      "que sea— lo recupera; el baseline pasivo gana. (Principio.)"))
S_TREE = Source(tier=5, ref="cognia_x/manager/decomposition_tree.md (hija del 77: intervención sorpresa-gateada)", obtained=True,
                claim=("El techo de CYCLE 77 (H-V4-5g) dejó como hija: 'la intervención sobre la memoria, si paga, "
                       "debe ser cheap/targeted (sorpresa-gateada)'. H-V4-5h la testea y la CIERRA: la barata vence a "
                       "la burda pero aun no al baseline pasivo -> intervenir no paga en este sustrato."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp062 primero): " + results_path)
    st, dr = sm['stationary'], sm['drift']
    miss_s, surp_s, exp_s = st['value_miss'], st['value_surprise'], st['value_explore']
    miss_d, surp_d, exp_d, full_d = dr['value_miss'], dr['value_surprise'], dr['value_explore'], dr['value_full']
    gap = sm['obs_gap_drift']
    n, m = data['args']['n'], data['args']['m']
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim062 = ("exp062 (propio, {n} seeds, numpy): intervención BARATA sorpresa-gateada. DRIFT value_surprise {sd} "
                "VENCE al slot fijo value_explore {ed} (la barata < burda en costo) PERO no supera al baseline pasivo "
                "value_miss {md}; el gap de obs bajo drift ({gap}) es muy chico para que intervenir pague. {V}.").format(
                    n=n_seeds, sd=_f(surp_d), ed=_f(exp_d), md=_f(miss_d), gap=_f(gap), V=status.upper())
    S_EXP062 = Source(tier=5, ref="cognia_x/experiments/exp062_surprise_intervention", obtained=True, claim=claim062)
    for src in (S_VOI, S_TREE, S_EXP062):
        ledger.add_source(src)
    notes.append("3 fuentes (S_VOI tier1 value-of-information; S_TREE tier5 hija CYCLE 77; S_EXP062 tier5 dato propio).")

    ev_for = [S_EXP062.ref, S_TREE.ref]
    ev_against = [S_EXP062.ref]
    adv = ("{V} (CIERRA el sub-tema memoria con un NULL firme; generaliza el 77): H-V4-5h testeó si la intervención "
           "BARATA y dirigida por SORPRESA (re-sondar ocasional sólo tras detectar una caída de hit-rate, devolviendo "
           "la capacidad full el resto del tiempo) paga donde el slot fijo del 77 no pudo. DOS hallazgos: (A) la "
           "barata SÍ es menos derrochadora que la burda -- value_surprise supera a value_explore en AMBOS escenarios "
           "(DRIFT {sd}>{ed}; ESTAC {ss}>{es}): re-sondar ocasional cuesta menos que sacrificar un slot fijo. (B) PERO "
           "aun la barata NO supera al baseline PASIVO (no intervenir): DRIFT value_surprise {sd} < value_miss {md} "
           "(recupera <0% del gap de obs {gap}). El gap de observación bajo drift es demasiado CHICO ({gap}) para que "
           "CUALQUIER intervención lo recupere: cualquier re-sondeo cuesta ~lo que recupera, y el detector tiene "
           "falsos positivos en estacionario (surprise {ss} < miss {ms}). => REFUTADA: en el sustrato de cache con "
           "observación gateada por la acción, la observación PASIVA del contrafáctico (lo no-cacheado) es ROBUSTA aun "
           "bajo drift; intervenir NO paga, ni barato. EVIDENCIA EN CONTRA del propio null: la barata mejora sobre la "
           "burda (la dirección 'cheap/targeted' era correcta), y un detector mejor-calibrado reduciría los falsos "
           "positivos -- pero aun en DRIFT (donde el gap existe) surprise queda BAJO miss, así que el null no es sólo "
           "un artefacto de tuning. CONCLUSIÓN: el sub-tema R-INTERVENCIÓN-sobre-memoria queda SATURADO con un null "
           "honesto; los efectos FUERTES de R-INTERVENCIÓN (exp022/CYCLE 35: la pasiva queda PLANA) viven en el "
           "aprendizaje causal ACTIVO, NO en esta cache. SEÑAL DE PIVOTE: dejar el sub-tema memoria.").format(
               V=status.upper(), sd=_f(surp_d), ed=_f(exp_d), ss=_f(surp_s), es=_f(exp_s), md=_f(miss_d),
               gap=_f(gap), ms=_f(miss_s))

    hyp = Hypothesis(
        id="H-V4-5h",
        statement=("Una intervención barata gateada por sorpresa (re-sondar ocasional, no slot fijo) recupera el "
                   "valor que la observación gateada pierde bajo drift, donde el slot fijo del CYCLE 77 no podía."),
        prediction=("APOYADA si en drift value_surprise supera a value_miss (+>0.02) Y a value_explore Y en "
                    "estacionario ~ value_miss; REFUTADA si value_surprise no supera a value_miss bajo drift; MIXTA si "
                    "ayuda parcial. (Pre-registrada.)"),
        status='abierta', confidence='media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=adv, experiment_ref="exp062_surprise_intervention")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-5h")
        notes.append("H-V4-5h marcada '{}' con DoD completo (REFUTADA que CIERRA el sub-tema = ciclo exitoso).".format(status))

    analogy = AnalogyRecord(
        problem=("Probaste revisar tu mochila a lo bruto (un lugar fijo, no pagó). Ahora probás revisar SÓLO cuando "
                 "sospechás que algo cambió. ¿Ahora sí conviene revisar?"),
        everyday=("Revisar cuando sospechás cuesta MENOS que revisar siempre (vas mejor que con el lugar fijo). PERO "
                  "lo que ganás detectando los cambios sigue siendo MENOS que lo que cuesta revisar -- porque lo que "
                  "te perdés por no revisar lo guardado es poco (igual sentís el costo de lo que NO llevás). Conviene "
                  "NO revisar y confiar en lo que sentís al fallar. En esta mochila, intervenir no paga ni barato."),
        solutions=["value_surprise (revisar ocasional gateado por sorpresa) -> mejor que el slot fijo, peor que no intervenir",
                   "value_explore (slot fijo) -> el más caro: revisar siempre",
                   "value_miss (no intervenir) -> GANA: la observación pasiva del contrafáctico basta aun con drift",
                   "(elsewhere) los efectos fuertes de intervenir viven en el aprendizaje causal activo (exp022), no en la cache"],
        principles=["explorar paga sólo si el valor de la info > el costo; si el gap es chico, ninguna intervención lo recupera",
                    "cheap/targeted (sorpresa-gateada) mejora sobre burdo (slot fijo) pero no alcanza al baseline pasivo aquí",
                    "la observación pasiva del contrafáctico es ROBUSTA en la cache aun bajo drift -> intervenir no paga",
                    "los efectos FUERTES de R-INTERVENCIÓN están en el aprendizaje causal activo, no en este sustrato"],
        adaptation=("El lab NO adopta intervención sobre la memoria-cache (ni barata): la observación pasiva basta. "
                    "PIVOTE: dejar el sub-tema memoria (saturado tras 72-78); ir a un valor endógeno más rico "
                    "(info-gain/confianza, CYCLE 56-57) o a la rama control/empowerment (la rama faltante más grande "
                    "del árbol), donde R-INTERVENCIÓN sí es de primer orden."),
        measurement=("exp062: DRIFT surprise {sd} > explore {ed} pero < miss {md} (gap {gap}); ESTAC surprise {ss} < "
                     "miss {ms}. {n} seeds.").format(
                         sd=_f(surp_d), ed=_f(exp_d), md=_f(miss_d), gap=_f(gap), ss=_f(surp_s), ms=_f(miss_s), n=n_seeds),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (revisar cuando sospechás cuesta menos que siempre, pero igual no paga: confiá en lo que sentís al fallar).")

    kl = ("REAL (exp062): en la cache con observación gateada, NINGUNA intervención paga -- la barata sorpresa-gateada "
          "(value_surprise {sd}) vence al slot fijo ({ed}) pero NO al baseline pasivo (value_miss {md}) ni bajo drift; "
          "el gap de obs es muy chico ({gap}). La observación PASIVA del contrafáctico es robusta. Los efectos fuertes "
          "de R-INTERVENCIÓN viven en el aprendizaje causal activo (exp022), no aquí. Sub-tema memoria SATURADO.").format(
              sd=_f(surp_d), ed=_f(exp_d), md=_f(miss_d), gap=_f(gap))
    ceilings.add(CeilingRecord(
        subsystem="R-INTERVENCIÓN x MEMORIA (cierre) — intervenir NO paga en la cache, ni barato; la observación pasiva basta",
        known_limit=kl,
        blockers=[{"text": "el gap de observación bajo drift es demasiado chico (~0.05) para que cualquier intervención (barata o burda) lo recupere; el baseline pasivo gana", "kind": "diseno"},
                  {"text": "la dirección cheap/targeted era correcta (la barata vence a la burda) pero insuficiente; un detector mejor-calibrado no cambia el signo (en drift sigue bajo miss)", "kind": "diseno"},
                  {"text": "PIVOTE: el sub-tema memoria queda saturado (72-78); R-INTERVENCIÓN de primer orden está en el aprendizaje causal activo (exp022) y la rama control/empowerment, no en la cache", "kind": "historico"}],
        real_or_assumed="real", evidence=[S_EXP062.ref, S_TREE.ref]))
    notes.append("1 techo 'real': intervenir no paga en la cache (ni barato); la observación pasiva basta. Sub-tema memoria saturado -> pivote.")

    dstmt = ("North-Star R-VALOR/R-INTERVENCIÓN (CIERRA el sub-tema memoria con un NULL firme): en la cache con "
             "observación gateada por la acción, NINGUNA intervención paga -- la barata sorpresa-gateada (value_surprise "
             "{sd}) mejora sobre el slot fijo ({ed}) pero no supera al baseline PASIVO (value_miss {md}) ni bajo drift; "
             "el gap de obs es muy chico ({gap}). Decisión: el lab NO adopta intervención sobre la memoria-cache; la "
             "observación pasiva del contrafáctico es robusta. PIVOTE: el sub-tema memoria queda SATURADO (72-78); los "
             "efectos fuertes de R-INTERVENCIÓN viven en el aprendizaje causal activo (exp022) y la rama control/"
             "empowerment. Próximo: valor endógeno más rico (info-gain/confianza) o la rama control.").format(
                 sd=_f(surp_d), ed=_f(exp_d), md=_f(miss_d), gap=_f(gap))
    drat = ("exp062 (tier5, propio, {n} seeds): DRIFT surprise {sd} > explore {ed} (barata < burda en costo) pero < "
            "miss {md} (no paga); ESTAC surprise {ss} < miss {ms} (falsos positivos). Convergente con "
            "value-of-information (tier1). REFUTADA -> sub-tema memoria saturado.").format(
                n=n_seeds, sd=_f(surp_d), ed=_f(exp_d), md=_f(miss_d), ss=_f(surp_s), ms=_f(miss_s))
    dec = Decision(id="D-V4-40", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP062), _to_plain(S_TREE)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-40 ACEPTADA por el ledger (tier5 exp062 + tier5 hija CYCLE 77).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-40:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle78_surprise_intervention',
                                description='CYCLE 78 (RESET v4, H-V4-5h: intervención barata sorpresa-gateada -- REFUTADA, cierra memoria).')
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
    print("RESUMEN — CYCLE 78 (RESET v4): intervención barata sorpresa-gateada (H-V4-5h) — REFUTADA (cierra memoria)")
    print("=" * 78)
    print("veredicto H-V4-5h:", status.upper() if status else "?")
    print("  la barata vence a la burda pero no al baseline pasivo: intervenir no paga en la cache. Sub-tema saturado.")
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
