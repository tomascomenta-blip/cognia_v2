r"""
cycle106_calibration_decisions.py — CICLO 106 (RESET v4, rama R-VALOR, ata CALIBRACIÓN con el arco de asignación):
H-V4-8k por las compuertas del engine. APOYADA: la CALIBRACIÓN (la ESCALA correcta) del valor estimado importa EXACTAMENTE
para decisiones valor-vs-escala-externa -- ABSTENCIÓN/umbral (CYCLE 104) y costo-vs-valor (CYCLE 101) -- NO para RANKING
(top-k, donde sólo cuenta el ORDEN). Un estimador MISCALIBRADO pero bien-ORDENADO rankea igual que uno calibrado pero
abstiene/actúa MAL (mide la escala contra el costo). Distingue qué propiedad del estimador R-VALOR (orden vs escala)
importa para qué decisión del arco, y conecta con la confianza calibrada de CYCLE 57/60.

DERIVA de exp090_calibration_decisions/results/results.json.

Correr (DESPUÉS de exp090):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp090_calibration_decisions.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle106_calibration_decisions
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle106_calibration_decisions')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp090_calibration_decisions', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="teoría de decisión: el RANKING (elegir top-k) requiere sólo valor ORDINAL; el UMBRAL (actuar sii valor>costo) requiere valor CARDINAL/CALIBRADO (la escala debe alinearse con el costo). Calibración (proper scoring) importa para decisiones de umbral, no de orden", obtained=False,
                     claim=("En teoría de decisión, elegir el mejor (ranking/argmax) requiere sólo el ORDEN del valor; "
                            "decidir SI actuar comparando el valor con un costo/umbral externo requiere el valor en la "
                            "ESCALA correcta (cardinal/calibrado). Una transformación monótona del valor preserva el "
                            "ranking pero rompe el umbral. La calibración importa exactamente para decisiones de "
                            "umbral/costo, no de orden. (Principio.)"))
S_ARC = Source(tier=5, ref="cognia_x/experiments/exp088_abstention_timing", obtained=True,
               claim=("El arco de asignación usa el valor estimado de dos formas: RANKEAR (top-k, 83-103) y comparar con "
                      "una ESCALA externa (costo 101, umbral/abstención 104). H-V4-8k distingue qué propiedad del "
                      "estimador (orden vs escala/calibración 57/60) importa para cada una."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp090 primero): " + results_path)

    rg = sm['rank_gap']
    ag = sm['abstain_gain']
    g = sm['grid']
    rk, ab = g['rank'], g['abstain']
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim090 = ("exp090 (propio, {n} seeds, numpy): RANK (top-k) calibrado={rc} ≈ miscalibrado={rm} (Δ {rg}: calibración "
                "irrelevante, sólo cuenta el orden); ABSTAIN (actuar sii v_est>c) calibrado={ac} >> miscalibrado={am} "
                "(+{ag}: la escala mal hace abstener/actuar mal). La calibración importa para valor-vs-escala, no para "
                "ranking.").format(n=n_seeds, rc=_f(rk['calibrated']), rm=_f(rk['miscalibrated']), rg=_f(rg),
                                   ac=_f(ab['calibrated']), am=_f(ab['miscalibrated']), ag=_f(ag))
    S_EXP090 = Source(tier=5, ref="cognia_x/experiments/exp090_calibration_decisions", obtained=True, claim=claim090)
    for src in (S_PRINCIPLE, S_ARC, S_EXP090):
        ledger.add_source(src)
    notes.append("3 fuentes (S_PRINCIPLE tier2 decisión orden-vs-escala; S_ARC tier5 usos del valor en el arco; S_EXP090 tier5 dato propio).")

    ev_for = [S_EXP090.ref]
    ev_against = [S_EXP090.ref, S_ARC.ref, S_PRINCIPLE.ref]
    advtext = ("{V} (ata la CALIBRACIÓN con el arco de asignación): el lab mostró que la confianza endógena CALIBRADA es "
               "señal de valor (CYCLE 57/60), pero el arco de asignación usa el valor de DOS formas: RANKEAR (top-k, "
               "83-103) y compararlo con una ESCALA EXTERNA (costo 101, umbral/abstención 104). ¿Cuándo importa la "
               "CALIBRACIÓN (la escala) vs sólo el RANKING (el orden)? RESULTADO: la calibración importa EXACTAMENTE para "
               "las decisiones valor-vs-escala. RANK (top-k, sólo orden): un estimador CALIBRADO ({rc}) y uno "
               "MISCALIBRADO pero bien-ordenado (g(v)=v², ={rm}) rankean IGUAL (Δ {rg}<=0.03) -- la calibración es "
               "IRRELEVANTE, el orden basta. ABSTAIN (actuar sii v_est>c, c=costo externo en la escala real): el "
               "calibrado ({ac}) DOMINA al miscalibrado ({am}) por +{ag} -- la escala mal corre el umbral efectivo y "
               "hace actuar/abstener mal. => para ELEGIR (qué) sólo se necesita el ORDEN del valor; para DECIDIR SI "
               "actuar (abstención) o comparar con un costo se necesita la ESCALA correcta (calibración). Esto distingue "
               "qué propiedad del estimador R-VALOR importa para qué decisión del arco y precisa el rol de la calibración "
               "(57/60): no es un lujo general, es NECESARIA exactamente para las decisiones de umbral/costo (101/104) e "
               "INNECESARIA para la asignación por ranking (83-103). EVIDENCIA EN CONTRA / caveats: miscalibración "
               "monótona sintética (g=v²); el umbral c es fijo y conocido; valor escalar; numpy/juguete. Un agente que "
               "SUPIERA su miscalibración podría recalibrar el umbral -- el punto es que SIN calibración la decisión de "
               "umbral falla.").format(
                   V=status.upper(), rc=_f(rk['calibrated']), rm=_f(rk['miscalibrated']), rg=_f(rg),
                   ac=_f(ab['calibrated']), am=_f(ab['miscalibrated']), ag=_f(ag))

    hyp = Hypothesis(
        id="H-V4-8k",
        statement=("La CALIBRACIÓN (escala) del valor estimado importa exactamente para decisiones valor-vs-escala-externa "
                   "(abstención/umbral CYCLE 104, costo-vs-valor CYCLE 101), NO para ranking (top-k, donde sólo cuenta el "
                   "orden): un estimador miscalibrado pero bien-ordenado rankea igual pero abstiene/actúa mal."),
        prediction=("APOYADA si para RANK calibrado ≈ miscalibrado (|Δ|<=0.03) Y para ABSTAIN calibrado >> miscalibrado "
                    "(+>0.05); REFUTADA si la calibración no separa las decisiones; MIXTA en otro caso. (Pre-registrada, "
                    "numpy, 48 seeds, miscalibración monótona g(v)=v².)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp090_calibration_decisions")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-8k")
        notes.append("H-V4-8k marcada '{}' con DoD completo (calibración: orden vs escala).".format(status))

    analogy = AnalogyRecord(
        problem=("Tengo un termómetro de 'qué tan buena' es cada opción, pero está MAL CALIBRADO (ordena bien pero los "
                 "números están corridos). ¿Me sirve para ELEGIR la mejor? ¿Y para decidir si una opción supera el "
                 "mínimo aceptable?"),
        everyday=("Para ELEGIR la mejor: sí, me sirve igual -- como ordena bien, la mejor sigue siendo la de número más "
                  "alto. Para decidir si una opción SUPERA el mínimo aceptable (un umbral): NO -- si los números están "
                  "corridos, comparo contra el mínimo y me equivoco (rechazo buenas o acepto malas). El termómetro mal "
                  "calibrado sirve para rankear, no para comparar contra una vara externa."),
        solutions=["rankear (elegir top-k): el orden basta -> la calibración es irrelevante",
                   "abstención/umbral (actuar sii valor>costo): la escala debe ser correcta -> calibración necesaria",
                   "miscalibrado pero bien-ordenado: rankea igual, abstiene/actúa mal",
                   "la calibración (57/60) importa exactamente para decisiones valor-vs-escala (101/104)"],
        principles=["el RANKING (argmax/top-k) requiere sólo valor ORDINAL (orden)",
                    "el UMBRAL/costo (actuar sii valor>costo) requiere valor CARDINAL/CALIBRADO (escala)",
                    "una transformación monótona preserva el ranking pero rompe el umbral",
                    "la calibración del valor R-VALOR es necesaria para umbral/costo (101/104), no para ranking (83-103)"],
        adaptation=("El lab PRECISA el rol de la calibración del valor: la confianza calibrada (57/60) NO es un requisito "
                    "general de la asignación; es NECESARIA exactamente para las decisiones valor-vs-escala-externa "
                    "(abstención/timing 104, costo-vs-valor 101) e INNECESARIA para la asignación por ranking (83-103, "
                    "donde el orden basta). Política: invertir en calibrar el valor SÓLO cuando la decisión compara con "
                    "una escala externa. Próximo: recalibración endógena del umbral cuando el estimador es miscalibrado; "
                    "integrar en el lazo cerrado real; y SCALE."),
        measurement=("exp090 ({n} seeds): RANK Δcalib-miscal={rg} (irrelevante); ABSTAIN calib={ac} vs miscal={am} "
                     "(+{ag}, necesaria).").format(n=n_seeds, rg=_f(rg), ac=_f(ab['calibrated']), am=_f(ab['miscalibrated']), ag=_f(ag)),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (termómetro mal calibrado: sirve para elegir, no para comparar con un mínimo).")

    kl = ("REAL (exp090): la CALIBRACIÓN (escala) del valor estimado importa EXACTAMENTE para decisiones valor-vs-escala "
          "(abstención/umbral 104, costo-vs-valor 101): ABSTAIN calibrado={ac} >> miscalibrado={am} (+{ag}); para RANKING "
          "(top-k) es IRRELEVANTE (Δ {rg}: sólo cuenta el orden). Precisa el rol de la confianza calibrada (57/60). "
          "TECHO: miscalibración monótona sintética (v²), umbral fijo/conocido, valor escalar, numpy/juguete.").format(
              ac=_f(ab['calibrated']), am=_f(ab['miscalibrated']), ag=_f(ag), rg=_f(rg))
    ceilings.add(CeilingRecord(
        subsystem="Calibración del valor R-VALOR — necesaria para decisiones valor-vs-escala (abstención/costo, 101/104), irrelevante para ranking (83-103)",
        known_limit=kl,
        blockers=[{"text": "miscalibración MONÓTONA sintética (g(v)=v²); un agente que conociera su miscalibración podría recalibrar el umbral -- el punto es que SIN calibración la decisión de umbral falla", "kind": "diseno"},
                  {"text": "el umbral/costo c es FIJO y conocido en la escala real; valor escalar; numpy/juguete; no integrado con el lazo cerrado real ni SCALE", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP090.ref, S_ARC.ref]))
    notes.append("1 techo 'real': la calibración importa para umbral/costo, no para ranking; precisa el rol de 57/60.")

    dstmt = ("North-Star R-VALOR (precisa el rol de la CALIBRACIÓN en el arco de asignación): la calibración (escala "
             "correcta) del valor estimado es NECESARIA exactamente para decisiones valor-vs-escala-externa "
             "(abstención/timing 104, costo-vs-valor 101) e INNECESARIA para la asignación por RANKING (top-k, 83-103, "
             "donde sólo cuenta el orden). Decisión: invertir en calibrar la confianza/valor (57/60) SÓLO cuando la "
             "decisión compara el valor con una escala externa (costo/umbral); para rankear basta el orden. Conecta la "
             "calibración endógena (57/60) con el arco de asignación. Próximo: recalibración endógena del umbral; lazo "
             "cerrado real; y SCALE.")
    drat = ("exp090 (tier5, propio, {n} seeds, numpy): RANK calib≈miscal (Δ {rg}<=0.03); ABSTAIN calib={ac} >> miscal={am} "
            "(+{ag}>0.05). Convergente con teoría de decisión orden-vs-escala (tier2) y con los usos del valor en el arco "
            "(tier5). APOYADA: la calibración importa para umbral/costo, no para ranking.").format(
                n=n_seeds, rg=_f(rg), ac=_f(ab['calibrated']), am=_f(ab['miscalibrated']), ag=_f(ag))
    dec = Decision(id="D-V4-68", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP090), _to_plain(S_ARC)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-68 ACEPTADA por el ledger (tier5 exp090 + tier5 exp088).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-68:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle106_calibration_decisions',
                                description='CYCLE 106 (RESET v4, H-V4-8k: la calibración del valor importa para umbral/costo, no para ranking -- APOYADA).')
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
    print("RESUMEN — CYCLE 106 (RESET v4): la calibración del valor importa para umbral/costo, no para ranking (H-V4-8k)")
    print("=" * 78)
    print("veredicto H-V4-8k:", status.upper() if status else "?")
    print("  RANK: calib≈miscal (sólo orden); ABSTAIN: calib>>miscal (la escala importa). Precisa el rol de 57/60.")
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
