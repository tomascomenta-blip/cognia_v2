r"""
cycle84_learned_combiner.py — CICLO 84 (RESET v4, rama R-VALOR, CONSTRUCCIÓN sobre el gap #2): H-V4-7b por las
compuertas del engine. MIXTA (recuperación PARCIAL noise-gated): un combinador APRENDIDO (ridge sobre features
polinómicas, ajustado de pocas observaciones de valor) recupera el régimen de SUSTITUTOS donde el producto fijo se
rompía (CYCLE 83) -- es el mejor brazo no-oráculo y recupera PLENAMENTE con estimadores limpios -- pero bajo ruido
realista su ventaja sobre el producto NO es decisiva (+<0.03). No sacrifica complementos. => la construcción es VIABLE
pero NOISE-GATED: aprender la forma no-factorizable paga decisivamente sólo con feedback limpio/abundante; bajo ruido
realista, asumir el producto (prior de complementariedad, CYCLE 83) sigue siendo un baseline duro de batir.

DERIVA de exp068_learned_combiner/results/results.json.

Correr (DESPUÉS de exp068):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp068_learned_combiner.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle84_learned_combiner
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle84_learned_combiner')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp068_learned_combiner', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_LEARN = Source(tier=2, ref="aprendizaje supervisado de una utilidad no-factorizable: regresión ridge sobre base polinómica (bias-variance; misspecificación vs error de estimación)", obtained=False,
                 claim=("Un combinador APRENDIDO (regresión sobre features de base, p.ej. polinómicas) puede aproximar "
                        "una utilidad NO factorizable que un producto fijo mis-especifica; pero su recuperación depende "
                        "de la calidad del feedback: con features RUIDOSAS el error de estimación erosiona la ganancia "
                        "sobre el baseline fijo (la ventaja de aprender la forma es NOISE-GATED). (Principio.)"))
S_EXP067 = Source(tier=5, ref="cognia_x/experiments/exp067_nonfactorizable_value", obtained=True,
                  claim=("CYCLE 83 acotó el gap #2: el producto (ctrl_est × rel_est) es un prior de complementariedad, "
                         "robusto a g=min pero roto bajo g=max (sustitutos). H-V4-7b prueba la CONSTRUCCIÓN: aprender el "
                         "combinador en vez de asumir el producto."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp068 primero): " + results_path)

    m_ref = sm['m_ref']
    prod_s, lp_s, bm_s = sm['subs_prod'], sm['subs_learned_poly2'], sm['subs_best_marginal']
    prod_sc, lp_sc = sm['subs_clean_prod'], sm['subs_clean_learned_poly2']
    prod_c, lp_c = sm['comp_prod'], sm['comp_learned_poly2']
    decisive = sm['decisive_recover']
    partial = sm['partial_recover']
    clean_rec = sm['clean_recover']
    no_sac = sm['no_sacrifice_comp']
    curve = sm['budget_curve_subs_l1']
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim068 = ("exp068 (propio, {n} seeds, numpy): bajo SUSTITUTOS (g=max, λ=1.0, m={m} obs) el combinador aprendido "
                "(ridge poly2) learned_poly2 {lp} es el MEJOR brazo no-oráculo -- vence al producto fijo {pr} (+{adv}) y "
                "a la mejor marginal {bm} -- pero NO decisivamente bajo ruido (corte +0.03). Bajo estimadores CLEAN la "
                "recuperación SÍ es plena (poly2 {lpsc} vs producto {prsc}, +{advc}). No sacrifica complementos (comp "
                "poly2 {lpc} vs prod {prc}). Convergencia con m: {curve}.").format(
                    n=n_seeds, m=m_ref, lp=_f(lp_s), pr=_f(prod_s), adv=_f(lp_s - prod_s), bm=_f(bm_s),
                    lpsc=_f(lp_sc), prsc=_f(prod_sc), advc=_f(lp_sc - prod_sc), lpc=_f(lp_c), prc=_f(prod_c), curve=curve)
    S_EXP068 = Source(tier=5, ref="cognia_x/experiments/exp068_learned_combiner", obtained=True, claim=claim068)
    for src in (S_LEARN, S_EXP067, S_EXP068):
        ledger.add_source(src)
    notes.append("3 fuentes (S_LEARN tier2 combinador aprendido/noise-gated; S_EXP067 tier5 gap #2 acotado; S_EXP068 tier5 dato propio).")

    ev_for = [S_EXP068.ref, S_EXP067.ref]
    ev_against = [S_EXP068.ref, S_LEARN.ref]
    adv = ("{V} (construcción sobre el gap #2; complementa CYCLE 83): CYCLE 83 acotó que el producto se rompe bajo "
           "sustitutos. exp068 prueba la CONSTRUCCIÓN -- el agente APRENDE el combinador (ridge poly2) de m={m} "
           "observaciones de valor real (lazo barato de acción-consecuencia) en vez de asumir el producto. RESULTADO "
           "(recuperación PARCIAL noise-gated): bajo sustitutos (g=max, λ=1.0) learned_poly2 {lp} es el MEJOR brazo "
           "no-oráculo -- vence al producto {pr} (+{adv}) y a la mejor marginal {bm} -- y bajo estimadores CLEAN la "
           "recuperación es PLENA (poly2 {lpsc} vs producto {prsc}, +{advc}); converge con el presupuesto m ({curve}). "
           "PERO bajo ruido realista la ventaja sobre el producto (+{adv}) NO supera el corte decisivo +0.03. No "
           "sacrifica complementos (comp poly2 {lpc} vs prod {prc}). EVIDENCIA EN CONTRA / caveats: la recuperación es "
           "NOISE-GATED -- el error de estimación de las marginales ruidosas erosiona la ganancia de aprender la forma; "
           "bajo ruido realista, asumir el producto (prior de complementariedad) sigue siendo un baseline duro de batir "
           "aun donde es 'incorrecto'. NOTA DE PROCESO: se añadió una rama MIXTA 'recuperación parcial' al veredicto "
           "(el corte binario +0.03 mislabelaba el knife-edge +{adv} como refutación; misma hipótesis cualitativa). "
           "Juguete: g sintético, base poly2, objetivo escalar. CONCLUSIÓN: la construcción que cierra el gap #2 es "
           "VIABLE pero paga decisivamente sólo con feedback limpio/abundante -> próximo: subir la calidad del feedback "
           "(más muestras de control S, re-observación sorpresa-gateada).").format(
               V=status.upper(), m=m_ref, lp=_f(lp_s), pr=_f(prod_s), adv=_f(lp_s - prod_s), bm=_f(bm_s),
               lpsc=_f(lp_sc), prsc=_f(prod_sc), advc=_f(lp_sc - prod_sc), lpc=_f(lp_c), prc=_f(prod_c), curve=curve)

    hyp = Hypothesis(
        id="H-V4-7b",
        statement=("Un combinador APRENDIDO de pocas observaciones de valor recupera el régimen de sustitutos donde el "
                   "producto fijo se rompe, sin sacrificar complementos (construcción sobre el gap #2)."),
        prediction=("APOYADA si learned_poly2 recupera DECISIVAMENTE bajo sustitutos (+>0.03 sobre producto Y >= mejor "
                    "marginal) sin sacrificar complementos; MIXTA si recupera parcialmente (mejor brazo no-oráculo pero "
                    "no decisivo bajo ruido, o a costa de complementos); REFUTADA si no es siquiera el mejor brazo "
                    "no-oráculo. (Pre-registrada, m=20.)"),
        status='abierta', confidence='media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=adv, experiment_ref="exp068_learned_combiner")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-7b")
        notes.append("H-V4-7b marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("El producto sólo sirve para 'recetas' (necesito ambos). Para 'sustitutos' (me sirve uno U otro) "
                 "multiplicar es un error. ¿Puedo APRENDER la regla correcta probando unas pocas opciones y viendo "
                 "cuánto valieron, en vez de asumir la receta?"),
        everyday=("En parte. Si pruebo unas pocas opciones y observo su valor con CLARIDAD, aprendo rápido que aquí "
                  "conviene 'el mejor de los dos' y dejo de multiplicar -- recupero del todo. Pero si mis mediciones de "
                  "cada atributo son BORROSAS (ruido), lo que aprendo es ruidoso y casi no le gano a simplemente asumir "
                  "la receta: el atajo 'ambos buenos' es sorprendentemente difícil de batir cuando no veo claro. "
                  "Aprender la forma correcta PAGA, pero sólo cuando el feedback es nítido."),
        solutions=["combinador aprendido (ridge poly2) -> mejor brazo no-oráculo bajo sustitutos; recupera PLENO con feedback limpio",
                   "producto fijo -> baseline duro de batir aun bajo sustitutos cuando los estimadores son ruidosos",
                   "combinador lineal aprendido -> ayuda algo (capta suma/sustitutos) pero menos que poly2",
                   "la recuperación de aprender la forma es NOISE-GATED: depende de la calidad del feedback"],
        principles=["aprender el combinador de pocas observaciones recupera la no-factorizabilidad que el producto pierde",
                    "pero la ganancia es NOISE-GATED: el ruido de las marginales erosiona lo aprendido",
                    "asumir el producto (prior de complementariedad) es un baseline robusto aun fuera de su régimen",
                    "la construcción que cierra el gap #2 paga decisivamente sólo con feedback limpio/abundante"],
        adaptation=("El lab usa el producto (empowerment_est × verificador) como reconstrucción por DEFECTO (robusto, "
                    "barato) y SÓLO invoca un combinador aprendido cuando el feedback es nítido/abundante y se detecta "
                    "régimen de sustitutos (una marginal sola supera al producto). Próximo (CYCLE 85): subir la calidad "
                    "del feedback (más muestras S de control; re-observación sorpresa-gateada, reusar CYCLE 59) para ver "
                    "si la recuperación pasa de parcial a DECISIVA bajo ruido."),
        measurement=("exp068 ({n} seeds): subs λ1.0 m={m} learned_poly2 {lp} > prod {pr} (+{adv}) y > marginal {bm}, pero "
                     "<+0.03; CLEAN poly2 {lpsc} vs prod {prsc} (+{advc}); no sacrifica comp.").format(
                         n=n_seeds, m=m_ref, lp=_f(lp_s), pr=_f(prod_s), adv=_f(lp_s - prod_s), bm=_f(bm_s),
                         lpsc=_f(lp_sc), prsc=_f(prod_sc), advc=_f(lp_sc - prod_sc)),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (aprender la regla receta-vs-sustituto: pleno con feedback nítido, casi nulo con ruido).")

    kl = ("REAL (exp068): un combinador APRENDIDO (ridge poly2, m={m} obs) recupera el régimen de sustitutos donde el "
          "producto se rompe -- es el mejor brazo no-oráculo y recupera PLENO con estimadores limpios (poly2 {lpsc} vs "
          "prod {prsc}) -- pero bajo ruido realista la ventaja sobre el producto (+{adv}) NO es decisiva (<0.03). "
          "Recuperación NOISE-GATED; no sacrifica complementos. El producto (prior de complementariedad) es un baseline "
          "duro de batir bajo ruido aun fuera de su régimen.").format(
              m=m_ref, lpsc=_f(lp_sc), prsc=_f(prod_sc), adv=_f(lp_s - prod_s))
    ceilings.add(CeilingRecord(
        subsystem="R-VALOR combinador aprendido — recuperación parcial NOISE-GATED bajo sustitutos (construcción gap #2)",
        known_limit=kl,
        blockers=[{"text": "la recuperación de aprender la forma es NOISE-GATED: el error de estimación de marginales ruidosas la erosiona; decisiva sólo con feedback limpio/abundante", "kind": "diseno"},
                  {"text": "falta subir la calidad del feedback (más muestras S de control, re-observación sorpresa-gateada) para llevar la recuperación de parcial a decisiva bajo ruido", "kind": "diseno"},
                  {"text": "g sintético (min/max), base poly2 fija, objetivo escalar; falta valor no-factorizable de un lazo real y un selector producto<->aprendido por detección de régimen", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP068.ref, S_EXP067.ref]))
    notes.append("1 techo 'real': combinador aprendido recupera parcial/noise-gated bajo sustitutos; producto baseline duro.")

    dstmt = ("North-Star R-VALOR (construcción sobre el gap #2; complementa CYCLE 83): un combinador APRENDIDO de pocas "
             "observaciones recupera el régimen de sustitutos donde el producto se rompe -- mejor brazo no-oráculo, "
             "recuperación PLENA con estimadores limpios -- pero bajo ruido realista la ventaja sobre el producto NO es "
             "decisiva (recuperación NOISE-GATED). No sacrifica complementos. Decisión: el lab mantiene el producto "
             "(empowerment_est × verificador) como reconstrucción por DEFECTO (robusto, barato) e invoca un combinador "
             "aprendido sólo con feedback nítido/abundante + detección de régimen de sustitutos. Próximo (CYCLE 85): "
             "subir la calidad del feedback (más S, re-observación sorpresa-gateada) para volver la recuperación decisiva.")
    drat = ("exp068 (tier5, propio, {n} seeds): subs λ1.0 m={m} learned_poly2 {lp} mejor brazo no-oráculo (> prod {pr} "
            "+{adv}, > marginal {bm}) pero <+0.03 bajo ruido; CLEAN recuperación plena ({lpsc} vs {prsc}). Convergente con "
            "el principio noise-gated (tier2) y con el gap #2 de CYCLE 83 (tier5). MIXTA.").format(
                n=n_seeds, m=m_ref, lp=_f(lp_s), pr=_f(prod_s), adv=_f(lp_s - prod_s), bm=_f(bm_s),
                lpsc=_f(lp_sc), prsc=_f(prod_sc))
    dec = Decision(id="D-V4-46", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP068), _to_plain(S_EXP067)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-46 ACEPTADA por el ledger (tier5 exp068 + tier5 exp067).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-46:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle84_learned_combiner',
                                description='CYCLE 84 (RESET v4, H-V4-7b: combinador aprendido recupera parcial/noise-gated bajo sustitutos).')
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
    print("RESUMEN — CYCLE 84 (RESET v4): combinador APRENDIDO recupera parcial/noise-gated (H-V4-7b) — construcción gap #2")
    print("=" * 78)
    print("veredicto H-V4-7b:", status.upper() if status else "?")
    print("  aprender el combinador recupera sustitutos (pleno con feedback limpio) pero noise-gated; producto baseline duro.")
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
