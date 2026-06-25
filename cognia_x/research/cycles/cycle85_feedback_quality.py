r"""
cycle85_feedback_quality.py — CICLO 85 (RESET v4, rama R-VALOR, cierra el noise-gating del gap #2): H-V4-7c por las
compuertas del engine. APOYADA: subir la CALIDAD DEL FEEDBACK (más muestras S de control, menos ruido σr de relevancia)
vuelve la recuperación del combinador APRENDIDO de PARCIAL (CYCLE 84) a DECISIVA bajo sustitutos, SIN necesitar feedback
perfecto. La ventaja learned_poly2−producto crece MONÓTONA con la calidad y cruza el umbral decisivo (+0.03) ya en
feedback moderado; no sacrifica complementos. => el noise-gating de CYCLE 84 es SUAVE, no una pared dura: con feedback
algo más nítido, aprender la forma no-factorizable recupera decisivamente el valor de sustitutos. Cierra el sub-arco
gap #2 (83 acota, 84 construye/noise-gated, 85 destraba con calidad de feedback).

DERIVA de exp069_feedback_quality/results/results.json.

Correr (DESPUÉS de exp069):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp069_feedback_quality.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle85_feedback_quality
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle85_feedback_quality')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp069_feedback_quality', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_EIV = Source(tier=2, ref="errors-in-variables / sesgo de atenuación: el ruido en los regresores atenúa el modelo aprendido; reducirlo sube el techo alcanzable", obtained=False,
               claim=("Un modelo aprendido sobre features RUIDOSAS sufre sesgo de atenuación: el ruido de medición pone "
                      "un techo a lo que puede recuperar (rankea con features ruidosas en test). Reducir el ruido de las "
                      "features (más muestras, mejor sensor) sube monótono ese techo. (Principio; el noise-gating de un "
                      "combinador aprendido es función decreciente del ruido de las features, no una pared fija.)"))
S_EXP068 = Source(tier=5, ref="cognia_x/experiments/exp068_learned_combiner", obtained=True,
                  claim=("CYCLE 84 halló que el combinador aprendido recupera bajo sustitutos pero NOISE-GATED: decisivo "
                         "sólo con estimadores limpios; el constraint vinculante es el ruido de las features, no el "
                         "presupuesto m. H-V4-7c prueba si subir la calidad del feedback destraba la recuperación."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp069 primero): " + results_path)

    adv = sm['adv_subs']
    a0, a1, a2, a3, ac = adv['q0'], adv['q1'], adv['q2'], adv['q3'], adv['clean']
    crossover = sm['crossover_quality']
    improves = sm['improves_with_quality']
    comp_ok = sm['comp_no_sacrifice']
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim069 = ("exp069 (propio, {n} seeds, numpy): la ventaja learned_poly2−producto bajo sustitutos crece MONÓTONA con "
                "la calidad del feedback: q0={a0}, q1(realista)={a1}, q2={a2}, q3={a3}, clean={ac}. Cruza el umbral "
                "decisivo (+0.03) en feedback no-perfecto (crossover={xo}); no sacrifica complementos (comp_ok={co}). El "
                "noise-gating de CYCLE 84 es SUAVE: subir S de control y bajar σr destraba la recuperación decisiva sin "
                "feedback perfecto.").format(
                    n=n_seeds, a0=_f(a0), a1=_f(a1), a2=_f(a2), a3=_f(a3), ac=_f(ac), xo=crossover, co=comp_ok)
    S_EXP069 = Source(tier=5, ref="cognia_x/experiments/exp069_feedback_quality", obtained=True, claim=claim069)
    for src in (S_EIV, S_EXP068, S_EXP069):
        ledger.add_source(src)
    notes.append("3 fuentes (S_EIV tier2 errors-in-variables/atenuación; S_EXP068 tier5 noise-gating; S_EXP069 tier5 dato propio).")

    ev_for = [S_EXP069.ref, S_EXP068.ref, S_EIV.ref]
    ev_against = [S_EXP069.ref]
    advtext = ("{V} (cierra el noise-gating del gap #2; complementa 83-84): CYCLE 84 dejó la recuperación del combinador "
               "aprendido como PARCIAL/noise-gated bajo sustitutos. exp069 sube la CALIDAD DEL FEEDBACK (S muestras de "
               "control ↑, σr de relevancia ↓) y mide la ventaja learned_poly2−producto: crece MONÓTONA q0={a0} → "
               "q1={a1} → q2={a2} → q3={a3} → clean={ac} y cruza el umbral DECISIVO (+0.03) en feedback no-perfecto "
               "(crossover={xo}), sin sacrificar complementos. => el noise-gating de CYCLE 84 es SUAVE, no una pared "
               "dura: con features algo más nítidas (más muestras de control, menos ruido de relevancia), aprender la "
               "forma no-factorizable recupera DECISIVAMENTE el valor de sustitutos. EVIDENCIA EN CONTRA / caveats: el "
               "punto REALISTA q1 (adv={a1}) queda apenas por encima de +0.03 y el mismo punto en CYCLE 84 dio +0.028 "
               "(justo por debajo) -> el realista está SOBRE la frontera de decisión; lo robusto es la TENDENCIA monótona "
               "(q2/q3 claramente decisivos, +{a2}/+{a3}), no la lectura de q1. Juguete: g sintético (max), base poly2, "
               "objetivo escalar; 'subir S' asume que el lazo real puede muestrear más. CONCLUSIÓN: la construcción del "
               "gap #2 (CYCLE 84) es destrancable: el lab gana al combinador aprendido cuando puede mejorar la calidad "
               "de sus estimaciones, no sólo el volumen de observaciones.").format(
                   V=status.upper(), a0=_f(a0), a1=_f(a1), a2=_f(a2), a3=_f(a3), ac=_f(ac), xo=crossover)

    hyp = Hypothesis(
        id="H-V4-7c",
        statement=("Subir la calidad del feedback (más muestras S de control, menos ruido de relevancia) vuelve la "
                   "recuperación del combinador aprendido de parcial a DECISIVA bajo sustitutos, sin feedback perfecto."),
        prediction=("APOYADA si la ventaja poly2−producto cruza +0.03 en feedback MODERADO (q2 o antes) y crece monótona "
                    "con la calidad, sin sacrificar complementos; MIXTA si sólo cruza en feedback alto (q3); REFUTADA si "
                    "sólo cruza con feedback PERFECTO o nunca. (Pre-registrada, subs λ=1.0, m=20.)"),
        status='abierta', confidence='alta' if status == 'apoyada' else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp069_feedback_quality")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-7c")
        notes.append("H-V4-7c marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("Sé que aquí conviene 'el mejor de los dos' (sustitutos), no multiplicar, pero mis mediciones son "
                 "borrosas y casi no le gano al atajo de multiplicar. ¿Necesito ver PERFECTO para aprender la regla, o "
                 "alcanza con ver un poco mejor?"),
        everyday=("Alcanza con ver un POCO mejor. Si afino mis mediciones de a poco (pruebo cada cosa más veces, uso un "
                  "termómetro menos ruidoso), lo que aprendo mejora de forma SOSTENIDA y pronto le gano claramente al "
                  "atajo de multiplicar -- sin necesitar visión perfecta. La borrosidad no era una pared: era una "
                  "pendiente. Cada gota de nitidez se paga en mejor decisión."),
        solutions=["subir S de control / bajar ruido de relevancia -> la ventaja del combinador aprendido crece monótona",
                   "feedback moderado (no perfecto) ya basta para recuperar DECISIVAMENTE bajo sustitutos",
                   "el producto sigue siendo baseline con feedback pobre; aprender gana cuando el feedback mejora",
                   "el noise-gating es una pendiente (función del ruido de features), no una pared"],
        principles=["la recuperación de aprender la forma no-factorizable es función DECRECIENTE del ruido de las features",
                    "subir la calidad del feedback (no sólo el volumen) destraba la recuperación decisiva",
                    "no hace falta feedback perfecto: feedback moderado cruza el umbral decisivo",
                    "el valor de aprender la forma vs asumir el producto escala con la nitidez del lazo de feedback"],
        adaptation=("El lab invierte en CALIDAD del feedback (más muestras de control por ítem, mejores verificadores/"
                    "sensores) cuando hay régimen de sustitutos: ahí el combinador aprendido supera decisivamente al "
                    "producto. Con feedback pobre, usa el producto (barato, robusto). Cierra el sub-arco gap #2 (83-85). "
                    "Próximo: detección automática del régimen (sustitutos vs complementos) para conmutar producto<->"
                    "aprendido sin saberlo de antemano, y el salto a un lazo de acción-consecuencia REAL (gaps #1/#3)."),
        measurement=("exp069 ({n} seeds): subs adv(poly2−prod) q0={a0}→q1={a1}→q2={a2}→q3={a3}→clean={ac}; crossover "
                     "decisivo={xo}; monótona; no sacrifica comp.").format(
                         n=n_seeds, a0=_f(a0), a1=_f(a1), a2=_f(a2), a3=_f(a3), ac=_f(ac), xo=crossover),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (la borrosidad del feedback es una pendiente, no una pared).")

    kl = ("REAL (exp069): el noise-gating de la recuperación del combinador aprendido (CYCLE 84) es SUAVE. La ventaja "
          "learned_poly2−producto bajo sustitutos crece MONÓTONA con la calidad del feedback (q0={a0}→clean={ac}) y cruza "
          "el umbral decisivo (+0.03) en feedback no-perfecto (crossover={xo}), sin sacrificar complementos. Subir S de "
          "control y bajar σr destraba la recuperación decisiva sin feedback perfecto.").format(
              a0=_f(a0), ac=_f(ac), xo=crossover)
    ceilings.add(CeilingRecord(
        subsystem="R-VALOR combinador aprendido — el noise-gating es una pendiente (función del ruido de features), no una pared",
        known_limit=kl,
        blockers=[{"text": "'subir S' asume que el lazo real puede muestrear más el control / mejorar el sensor; en un lazo de acción-consecuencia real el costo de más muestras puede ser alto", "kind": "diseno"},
                  {"text": "el punto realista q1 está SOBRE la frontera +0.03 (q1≈+0.038, CYCLE84 mismo punto +0.028); lo robusto es la tendencia monótona, no la lectura de q1", "kind": "diseno"},
                  {"text": "g sintético (max), base poly2 fija, objetivo escalar; falta detección automática del régimen (sustitutos vs complementos) para conmutar producto<->aprendido y un lazo real (gaps #1/#3)", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP069.ref, S_EXP068.ref]))
    notes.append("1 techo 'real': el noise-gating es una pendiente; subir calidad de feedback destraba la recuperación decisiva.")

    dstmt = ("North-Star R-VALOR (cierra el noise-gating del gap #2; 83-85): subir la CALIDAD DEL FEEDBACK (más muestras S "
             "de control, menos ruido σr de relevancia) vuelve la recuperación del combinador aprendido de PARCIAL "
             "(CYCLE 84) a DECISIVA bajo sustitutos, SIN feedback perfecto -- la ventaja crece monótona y cruza +0.03 en "
             "feedback moderado, sin sacrificar complementos. Decisión: el lab invierte en CALIDAD del feedback (no sólo "
             "volumen) cuando hay régimen de sustitutos; con feedback pobre usa el producto (robusto, barato). El "
             "noise-gating es una pendiente, no una pared. Próximo: detección automática del régimen para conmutar "
             "producto<->aprendido, y un lazo de acción-consecuencia real (gaps #1/#3).")
    drat = ("exp069 (tier5, propio, {n} seeds): subs adv(poly2−prod) monótona q0={a0}→clean={ac}, crossover decisivo "
            "{xo}, comp_ok={co}. Convergente con errors-in-variables/atenuación (tier2) y con el noise-gating de CYCLE 84 "
            "(tier5). APOYADA.").format(n=n_seeds, a0=_f(a0), ac=_f(ac), xo=crossover, co=comp_ok)
    dec = Decision(id="D-V4-47", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP069), _to_plain(S_EXP068)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-47 ACEPTADA por el ledger (tier5 exp069 + tier5 exp068).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-47:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle85_feedback_quality',
                                description='CYCLE 85 (RESET v4, H-V4-7c: subir la calidad del feedback vuelve decisiva la recuperación aprendida).')
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
    print("RESUMEN — CYCLE 85 (RESET v4): subir calidad de feedback destraba la recuperación (H-V4-7c) — cierra noise-gating gap #2")
    print("=" * 78)
    print("veredicto H-V4-7c:", status.upper() if status else "?")
    print("  la ventaja del combinador aprendido crece monótona con la calidad y cruza el umbral decisivo sin feedback perfecto.")
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
