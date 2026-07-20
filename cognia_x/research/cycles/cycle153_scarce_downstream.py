r"""
cycle153_scarce_downstream.py — CICLO 153 (RESET v4, FRONTERA REAL §4.2): H-V4-9m por las compuertas del engine. El diseño CORRECTO
del pago downstream que el 152 sembró (su pool balanceado SATURÓ y NO era escaso). Pool fijo COMPARTIDO ESCASO (base-rate ~0.125) +
precision@top-m POR f=m/#correct, barriendo el régimen DISCRIMINANTE f≈1 (recall de las pocas correctas). ¿El residuo de calibración
GENÉRICO (ls_lo, único superviviente del 151) PAGA en una decisión bajo ESCASEZ GENUINA (la tesis brújula-decisional 123)?

VEREDICTO: <SE COMPLETA TRAS LA VERIFICACIÓN ADVERSARIAL — este script es verdict-driven; lee results.json>.

DERIVA de exp135_scarce_downstream/results/results.json (lazo torch REAL, N=6). Compuerta HONESTA: el veredicto descansa en el f
PRE-REGISTRADO 1.0, NO en el max-t (anti cherry-pick). PRIMER positivo-leaning del arco -> verificación EXTRA dura contra overclaim.
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle153_scarce_downstream')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp135_scarce_downstream', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


def _g_f1(sm, pool):
    """gap ls_lo−naive en el f PRE-REGISTRADO 1.0 (claves de payoff_gap son strings por JSON)."""
    return sm['payoff_gap'][pool]['ls_lo'][str(sm['prereg_f'])]


def _g_durable_f1(sm, pool):
    return sm['payoff_gap'][pool]['durable'][str(sm['prereg_f'])]


VERIF_CLAIM = (
    "verificación adversarial (4 sondas + síntesis; recomendó MIXTA, design_valid=True, signal_is_real=FALSE, overclaim_risk=ALTO): "
    "1 CONFIRMA + 3 ACOTA. CONFIRMA (sonda-D, sev baja): MIXTA es la etiqueta honesta -APOYADA sería overclaim (5/6, N=6 smoke, "
    "multiple-f), REFUTADA sería deflación deshonesta (hay señal positiva real desconfundida)-. Las 3 ACOTA desinflan el positivo: "
    "(A-leave-one-out, sev media): el +0.054 a f=1.0 NO sobrevive quitar su seed más favorable en NINGUNO de los dos pools (INDIST "
    "t→1.83, HELDOUT t→1.77, ambos < t_crit 2.015); el headline INDIST lo cargan 2/6 seeds (~77%) y uno de ellos se INVIERTE en "
    "heldout (corr per-seed indist↔heldout ≈ −0.19) -> 'no es artefacto de 1-2 seeds' es FALSO para indist; lo defendible es sólo un "
    "piso común diminuto (~+0.03, 5/6 seeds). (B-multiple-comparison, sev media): la familia real es 7 f × 2 pools = 14 gaps; "
    "Bonferroni one-tail df=5 t_crit = 4.382; f=1.0 (t=2.29/2.36) sólo pasa SIN corregir (2.015), falla Bonf/7 (3.681) y Bonf/14 "
    "(4.382); f=1.0 coincide con el t-MAX global en ambos pools (firma de selección por grilla); el monótono que lo rescataría NO "
    "replica en heldout (pico en f=0.5, decrece). Lo ÚNICO multiplicity-robust es el NEGATIVO del durable (t=−8.58). (C-mecanismo, "
    "sev media -el hallazgo load-bearing-): ERROR DE CATEGORÍA -> precision@top-m (vía np.argsort) es RANK-ONLY, invariante a "
    "transformaciones monótonas de la confianza, IGUAL que AUROC -> NO testea CALIBRACIÓN, testea RANKING; la ventaja del ls_lo a "
    "f≈1 es la MISMA ventaja AUROC del 151 (+0.018) RE-EXPRESADA en el punto recall (R-precision), co-moviéndose round-level r=0.87 "
    "-> 0 información decisional independiente del 151; NO prueba la tesis-123 (calibración paga downstream), sólo la APUNTA. ERRORES "
    "CAZADOS: el t_crit Bonferroni estaba subestimado (4.382 no ~3.0); el framing 'calibración' es un error de categoría (la métrica "
    "es rank-only); 'no es artefacto de 1-2 seeds' falso para indist. WHAT-WOULD-MAKE-IT-APOYADA: N≥12; LOO-robusto; sobrevivir "
    "Bonferroni; réplica out-of-sample; y CRÍTICO -una métrica decisional NO invariante-a-monótonas (cost-weighted/umbral-abstención) "
    "que separe calibración de ranking-, si no sigue siendo AUROC re-expresado.")


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp135 primero): " + results_path)

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    nb = finalize_narrative(status, sm)
    for src in nb['sources']:
        ledger.add_source(src)
    notes.append(nb['sources_note'])

    hyp = Hypothesis(id="H-V4-9m", statement=nb['hyp_statement'], prediction=nb['hyp_prediction'],
                     status='abierta', confidence=nb['confidence'], evidence_for=nb['ev_for'],
                     evidence_against=nb['ev_against'], adversarial_verdict=nb['advtext'],
                     experiment_ref="exp135_scarce_downstream")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-9m")
        notes.append(nb['mark_note'])

    analogy = nb['analogy']
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append(nb['analogy_note'])

    ceilings.add(nb['ceiling'])
    notes.append(nb['ceiling_note'])

    try:
        ledger.record_decision(nb['decision'])
        notes.append(nb['decision_note'])
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-113:", ex); raise

    return record, notes, status, sm


def finalize_narrative(status, sm):
    """status='mixta' (1er positivo-leaning del arco, NO APOYADA): señal positiva sugestiva a f=1.0 pre-registrado en ambos pools,
    pero NO robusta (LOO/Bonferroni/5-de-6) y RANK-ONLY (re-expresa el AUROC del 151, no testea calibración); durable robusto NEG."""
    au = sm['auroc']; tcrit = sm.get('t_crit_one_tail_05', 0.0); br = sm['base_rate']
    gi = _g_f1(sm, 'indist'); gh = _g_f1(sm, 'heldout'); di = _g_durable_f1(sm, 'indist')
    mono = sm['monotone_pos']

    S_PRINCIPLE = Source(tier=2, ref=(
        "en el lazo real desconfundido, sobre un pool fijo COMPARTIDO ESCASO y en el régimen decisional discriminante (f=m/#correct≈1, "
        "recall de las pocas correctas), el residuo de calibración GENÉRICO del 151 muestra una ventaja decisional POSITIVA SUGESTIVA "
        "pero NO robusta -- y como la métrica (precision@top-m) es RANK-ONLY, esa ventaja RE-EXPRESA la ventaja de ranking AUROC del 151, "
        "NO es evidencia independiente de que la calibración pague; testear la tesis 123 (calibración paga) exige una métrica decisional "
        "sensible a magnitudes de confianza (no invariante-a-monótonas)."), obtained=False,
        claim=("Diseño escaso (f≈1): ls_lo−naive a f=1.0 es positivo t-significativo SIN corregir en ambos pools (indist {gim} t={git}, "
               "heldout {ghm} t={ght}) pero NO robusto (LOO/Bonferroni/5-de-6). RANK-ONLY -> re-expresa el AUROC del 151 (r round-level "
               "~0.87), NO testea calibración. APUNTA a la brújula-123 pero no la prueba. (Principio acotado.)").format(
                   gim=_f(gi['mean']), git=_f(gi['tstat']), ghm=_f(gh['mean']), ght=_f(gh['tstat'])))
    S_151 = Source(tier=5, ref="cognia_x/experiments/exp133 (CYCLE 151) — el residuo cuyo pago se mide + la inversión que se confirma", obtained=True,
        claim=("El 151 halló que sólo sobrevive un residuo genérico (ls_lo) en AUROC (no robusto) y que la cura 119 (durable) se "
               "INVIERTE. H-V4-9m mide el pago DOWNSTREAM en escasez genuina: el residuo APUNTA a pagar (positivo sugestivo a f≈1) "
               "PERO la métrica rank-only RE-EXPRESA el AUROC del 151 (no info nueva); y el durable se INVIERTE TAMBIÉN downstream "
               "(robusto, multiplicity-survivor, indist f=1.0 {dim} t={dit}).").format(dim=_f(di['mean']), dit=_f(di['tstat'])))
    S_152 = Source(tier=5, ref="cognia_x/experiments/exp134 (CYCLE 152) — el diseño saturado que este ciclo CORRIGE", obtained=True,
        claim=("El 152 intentó el pago downstream pero su pool balanceado SATURÓ precision@top-m y NO era escaso (tesis 123 sin testear). "
               "H-V4-9m lo CORRIGE: pool fijo COMPARTIDO ESCASO (base-rate {br}) + f=m/#correct -> el régimen discriminante f≈1 ahora SÍ "
               "informa (pools no saturados). El diseño es válido; el resultado es sugestivo-positivo no robusto.").format(br=_f(br['indist'])))
    S_VERIF = Source(tier=4, ref="verificación adversarial (workflow, 4 sondas con probes reales sobre los datos crudos + síntesis)", obtained=True,
        claim=VERIF_CLAIM)
    claim135 = ("exp135 (propio, lazo torch REAL, N={n}, pool fijo COMPARTIDO ESCASO base-rate {br}, desconfound del 151 preservado, 2 "
                "pools INDIST/HELDOUT; precision@top-m por f=m/#correct; compuerta HONESTA en f PRE-REGISTRADO 1.0 anti cherry-pick). "
                "Pools NO saturados (informativos): AUROC indist naive {ani} ls_lo {ali}; heldout naive {anh} ls_lo {alh}. f=1.0: "
                "ls_lo−naive indist {gim} (CI {gici}, t={git}, {gip}/{gin}+), heldout {ghm} (CI {ghci}, t={ght}). Monótono hacia f≈1 "
                "indist={moi} heldout={moh}. durable−naive f=1.0 indist {dim} (t={dit}, robusto NEG). VEREDICTO MIXTA: positivo "
                "sugestivo no robusto + rank-only (re-expresa AUROC del 151).").format(
                    n=sm['n'], br=_f(br['indist']), ani=_f(au['indist']['naive']), ali=_f(au['indist']['ls_lo']),
                    anh=_f(au['heldout']['naive']), alh=_f(au['heldout']['ls_lo']), gim=_f(gi['mean']), gici=gi['ci95'],
                    git=_f(gi['tstat']), gip=gi['n_positive'], gin=gi['n'], ghm=_f(gh['mean']), ghci=gh['ci95'], ght=_f(gh['tstat']),
                    moi=mono['indist'], moh=mono['heldout'], dim=_f(di['mean']), dit=_f(di['tstat']))
    S_EXP135 = Source(tier=5, ref="cognia_x/experiments/exp135_scarce_downstream", obtained=True, claim=claim135)

    ev_for = [S_EXP135.ref, S_151.ref, S_152.ref, S_VERIF.ref]
    ev_against = [S_PRINCIPLE.ref]

    advtext = (
        "{V}-downstream-ESCASO (1er positivo-leaning del arco tras 4 deflacionarios -> verificación EXTRA dura contra overclaim; "
        "design_valid=True, signal_is_real=FALSE, overclaim_risk=ALTO; recomendó MIXTA): el 152 dejó EXPLÍCITO que su pool balanceado "
        "SATURABA y NO era escaso (tesis 123 sin testear). exp135 lo CORRIGE: pool fijo COMPARTIDO ESCASO (base-rate {br}, 1 pos + 7 "
        "neg por prompt, etiquetado por el verificador real, desconfound del 151 preservado) + precision@top-m por f=m/#correct, "
        "barriendo el régimen DISCRIMINANTE f≈1 (recall de las pocas correctas); compuerta HONESTA en el f PRE-REGISTRADO 1.0 (no el "
        "max-t, anti cherry-pick). QUÉ SE ESTABLECE (tres capas): (a) EL DISEÑO FUNCIONA -- los pools NO saturan (informativos), "
        "el régimen f≈1 ahora discrimina (a diferencia del 152). (b) HAY UNA SEÑAL POSITIVA SUGESTIVA -- ls_lo−naive a f=1.0 es "
        "positivo y t-significativo SIN corregir en AMBOS pools (indist {gim}, CI {gici}, t={git}, {gip}/{gin}+; heldout {ghm}, CI "
        "{ghci}, t={ght}) y MONÓTONO hacia f≈1 en indist -- la PRIMERA traza positiva del arco. (c) PERO NO ES ROBUSTA, Y NO TESTEA "
        "CALIBRACIÓN -- (c1) falla el bar 6/6 (5/6, un seed casi-cero), NO sobrevive leave-one-out de su seed más favorable en NINGÚN "
        "pool (t→1.83 indist / 1.77 heldout, < t_crit 2.015) ni Bonferroni (familia 14 gaps, t_crit 4.382); el headline indist lo "
        "cargan 2/6 seeds (~77%) con correlación cruzada ~0 y el monótono NO replica en heldout; N={n} SMOKE. (c2) ERROR DE CATEGORÍA "
        "load-bearing (sonda-mecanismo): precision@top-m (vía np.argsort) es RANK-ONLY -invariante a transformaciones monótonas de la "
        "confianza, IGUAL que AUROC- -> NO testea CALIBRACIÓN, testea RANKING; la ventaja del ls_lo a f≈1 es la MISMA ventaja AUROC del "
        "151 (+0.018) RE-EXPRESADA en el punto recall (co-mueven round-level r~0.87) -> CERO información decisional independiente del "
        "151. (d) LO ROBUSTO (multiplicity-survivor): el durable (cura 119) es NEGATIVO robusto downstream (indist f=1.0 {dim}, "
        "t={dit}, 0/{gin}+) -> ratifica su INVERSIÓN del 151/152, también en la decisión y fuera-de-forma. RESULTADO HONESTO: el 153 "
        "es el 1er positivo-leaning -el residuo APUNTA a pagar bajo escasez genuina (f≈1) en ambos pools- PERO sugestivo no "
        "concluyente (no robusto) y, crucialmente, RANK-ONLY -> re-expresa el ranking del 151, NO prueba que la calibración pague (la "
        "tesis 123 sigue SIN testear como mecanismo de calibración). ACOTACIÓN: N={n} smoke; toy-real. PRÓXIMO (154): una métrica "
        "decisional NO invariante-a-monótonas (cost-weighted / umbral-abstención) que separe CALIBRACIÓN de RANKING -el test que de "
        "verdad tocaría la 123-; N≥12; LOO + Bonferroni; réplica out-of-sample.").format(
            V=status.upper(), br=_f(br['indist']), gim=_f(gi['mean']), gici=gi['ci95'], git=_f(gi['tstat']), gip=gi['n_positive'],
            gin=gi['n'], ghm=_f(gh['mean']), ghci=gh['ci95'], ght=_f(gh['tstat']), n=sm['n'], dim=_f(di['mean']), dit=_f(di['tstat']))

    hyp_statement = ("¿El residuo de calibración GENÉRICO (ls_lo, único superviviente del 151) PAGA en una decisión bajo ESCASEZ "
                     "GENUINA (precision@top-m a f=m/#correct≈1 sobre un pool fijo COMPARTIDO ESCASO base-rate {br}, desconfound del 151 "
                     "preservado; el diseño correcto que el 152 -saturado/no-escaso- sembró)? RESULTADO: MIXTA -- 1er positivo-leaning "
                     "del arco: positivo t-significativo SIN corregir a f=1.0 pre-registrado en AMBOS pools (indist {gim} t={git}, "
                     "heldout {ghm} t={ght}) y monótono en indist, PERO NO robusto (falla 6/6, LOO, Bonferroni; N={n} smoke) y RANK-ONLY "
                     "(re-expresa el AUROC del 151, NO testea calibración -> no prueba la tesis 123). El durable es robusto NEG (confirma "
                     "su inversión). Alcance: lazo torch real CPU, N={n} smoke, tarea a*b.").format(
                         br=_f(br['indist']), gim=_f(gi['mean']), git=_f(gi['tstat']), ghm=_f(gh['mean']), ght=_f(gh['tstat']), n=sm['n'])
    hyp_prediction = ("APOYADA si el residuo paga ROBUSTO (CI excl 0 + t-test + 6/6 + LOO + Bonferroni) a f≈1 en un pool informativo Y "
                      "con una métrica que separe calibración de ranking. REFUTADA si no paga en ningún f informativo. MIXTA si positivo "
                      "sugestivo no robusto / rank-only. (Pre-registrada en f=1.0 -anti cherry-pick-; verificación adversarial.)")

    mark_note = ("H-V4-9m marcada 'mixta' (1er positivo-leaning del arco, NO APOYADA): señal positiva sugestiva a f=1.0 en ambos pools "
                 "(t-sig SIN corregir) y monótona en indist, PERO no robusta (5/6, falla LOO t→1.8<2.015 y Bonferroni t_crit 4.382) y "
                 "RANK-ONLY (re-expresa el AUROC del 151, NO testea calibración). APOYADA sería overclaim; REFUTADA, deflación. El "
                 "durable robusto NEG confirma su inversión (multiplicity-survivor).")

    analogy = AnalogyRecord(
        problem=("El 152 no pudo medir si la pizca de criterio del residuo sirve para decidir porque el examen era demasiado fácil "
                 "(saturado) y no escaso. Lo rehicimos ESCASO (pocas respuestas correctas entre muchas) y medimos en el punto donde "
                 "hay que recuperarlas todas. ¿Ahora sí sirve la pizca para decidir?"),
        everyday=("Asoma un poquito -por primera vez en el arco- pero no es firme, y además no es lo que creíamos medir. Con el examen "
                  "escaso y mirando 'cuántas de las pocas correctas recuperás', el método genérico (ls_lo) quedó un pelín por encima "
                  "del base en los dos exámenes -la primera señal positiva tras cuatro intentos que daban cero o negativo-. PERO: si "
                  "sacás el alumno que más ayudaba, la ventaja se cae; dos de seis alumnos la sostienen casi solos; y con la corrección "
                  "estadística estricta no pasa. Y lo más importante: la forma de 'decidir' que usamos sólo mira el ORDEN de las "
                  "respuestas, no qué tan seguro está el modelo -así que NO mide 'mejor calibrado', mide 'mejor ordenadas', que es "
                  "exactamente lo que ya sabíamos del 151-. O sea: apunta a que la pizca podría servir, pero ni es firme ni prueba que "
                  "sea por estar mejor calibrado. (El alumno 'curado' siguió decidiendo peor en todo, firme: confirma su problema.)"),
        solutions=["el DISEÑO escaso funciona: los pools NO saturan, el régimen f≈1 ahora discrimina (a diferencia del 152)",
                   "señal positiva sugestiva a f=1.0: ls_lo−naive indist {gim} (t={git}), heldout {ghm} (t={ght}) -t-sig sin corregir, 1er positivo del arco-".format(gim=_f(gi['mean']), git=_f(gi['tstat']), ghm=_f(gh['mean']), ght=_f(gh['tstat'])),
                   "NO robusto: falla 6/6 (5/6), leave-one-out (t→1.8<2.015) y Bonferroni (t_crit 4.382); indist cargado por 2 seeds, monótono no replica en heldout",
                   "RANK-ONLY: precision@top-m es invariante a transformaciones monótonas -> re-expresa el AUROC del 151 (r~0.87), NO testea calibración",
                   "durable robusto NEG (indist f=1.0 {dim}, t={dit}) -> confirma su inversión del 151/152 downstream (multiplicity-survivor)".format(dim=_f(di['mean']), dit=_f(di['tstat']))],
        principles=["una métrica decisional rank-only (precision@top-m, argsort) NO testea CALIBRACIÓN -invariante a monótonas, como "
                    "AUROC-; re-expresa el ranking ya medido. Para tocar 'la calibración paga' hace falta una métrica sensible a "
                    "magnitudes de confianza (cost-weighted / umbral-abstención)",
                    "el PRIMER positivo tras una racha deflacionaria es el de mayor riesgo de overclaim -> bar más alto: LOO, "
                    "Bonferroni, réplica out-of-sample, y separación mecanismo (no re-expresión)",
                    "una compuerta pre-registrada (f=1.0) contiene la multiplicidad PERO no rescata la robustez: el efecto puede ser "
                    "t-sig sin corregir y aun así no sobrevivir LOO -> 'significativo' no es 'firme'",
                    "META: un ciclo cuyo DISEÑO es correcto (corrige el defecto del 152) y cuyo RESULTADO es sugestivo-no-concluyente "
                    "+ un error-de-categoría cazado (rank-only) es progreso honesto: deja la pregunta bien planteada para el 154"],
        adaptation=("FRONTERA REAL §4.2 (el diseño correcto del downstream). El 152 saturó/no-escaso; el 153 lo corrige (pool escaso, "
                    "f≈1) y obtiene el 1er positivo-leaning, pero no robusto y rank-only (re-expresa el 151). PRÓXIMO (154): métrica "
                    "decisional NO invariante-a-monótonas (cost-weighted / umbral-abstención) que separe CALIBRACIÓN de RANKING -el "
                    "test que de verdad tocaría la tesis 123-; N≥12; LOO + Bonferroni; réplica out-of-sample."),
        measurement=("exp135 (lazo torch real, N={n}, pool escaso base-rate {br}): ls_lo−naive f=1.0 indist {gim} (CI {gici}, t={git}, "
                     "{gip}/{gin}+), heldout {ghm} (t={ght}); monótono indist={moi}/heldout={moh}; durable indist f=1.0 {dim} "
                     "(t={dit}); AUROC indist {ani}/{ali}, heldout {anh}/{alh}.").format(
                         n=sm['n'], br=_f(br['indist']), gim=_f(gi['mean']), gici=gi['ci95'], git=_f(gi['tstat']), gip=gi['n_positive'],
                         gin=gi['n'], ghm=_f(gh['mean']), ght=_f(gh['tstat']), moi=mono['indist'], moh=mono['heldout'], dim=_f(di['mean']),
                         dit=_f(di['tstat']), ani=_f(au['indist']['naive']), ali=_f(au['indist']['ls_lo']), anh=_f(au['heldout']['naive']),
                         alh=_f(au['heldout']['ls_lo'])),
        iterations=4)
    analogy_note = ("Analogía 7 etapas registrada (asoma el 1er positivo del arco -el residuo apunta a servir para decidir bajo escasez- "
                    "pero no firme y rank-only -no prueba que sea por calibración, re-expresa el ranking del 151-; el durable confirma su problema).")

    kl = ("REAL (exp135, MIXTA 1er positivo-leaning + verificación adversarial signal_is_real=FALSE): el DISEÑO escaso (f≈1) FUNCIONA "
          "(corrige el 152). El residuo genérico APUNTA a pagar bajo escasez (positivo t-sig sin corregir a f=1.0 en ambos pools, "
          "monótono indist) PERO NO robusto (LOO/Bonferroni/5-de-6) y RANK-ONLY (re-expresa el AUROC del 151, no testea calibración). "
          "El durable robusto NEG (confirma inversión). TECHO/ALCANCE: N={n} smoke; métrica rank-only. NO cubre: una métrica que "
          "separe CALIBRACIÓN de ranking (la que tocaría la 123) -> CYCLE 154; N≥12; LOO+Bonferroni.").format(n=sm['n'])
    ceiling = CeilingRecord(
        subsystem=("PAGO DOWNSTREAM del residuo del 151 bajo ESCASEZ GENUINA (el diseño correcto del 152): pool fijo COMPARTIDO ESCASO "
                   "+ precision@top-m por f≈1. RESULTADO: MIXTA -- 1er positivo-leaning (sugestivo, no robusto) PERO rank-only (re-expresa "
                   "el AUROC del 151, no testea calibración); el durable robusto NEG. El diseño funciona; falta una métrica de calibración"),
        known_limit=kl,
        blockers=[{"text": ("EL POSITIVO NO ES ROBUSTO: t-sig SIN corregir a f=1.0 en ambos pools (indist {gim} t={git}, heldout {ghm} "
                            "t={ght}) PERO 5/6 (no 6/6), falla leave-one-out del seed más favorable (t→1.8<2.015) y Bonferroni (t_crit "
                            "4.382); el headline indist lo cargan 2 seeds; N={n} smoke.").format(
                                gim=_f(gi['mean']), git=_f(gi['tstat']), ghm=_f(gh['mean']), ght=_f(gh['tstat']), n=sm['n']), "kind": "fisico"},
                  {"text": ("ERROR DE CATEGORÍA (load-bearing): precision@top-m es RANK-ONLY (invariante a transformaciones monótonas de "
                            "la confianza, como AUROC) -> NO testea CALIBRACIÓN, testea RANKING; la ventaja del ls_lo RE-EXPRESA el AUROC "
                            "del 151 (r round-level ~0.87) -> 0 información decisional independiente. NO prueba la tesis 123."), "kind": "diseno"},
                  {"text": ("FRONTERA ABIERTA (CYCLE 154): una métrica decisional NO invariante-a-monótonas (cost-weighted / umbral-"
                            "abstención) que separe CALIBRACIÓN de RANKING -el test que de verdad tocaría la 123-; N≥12; LOO + "
                            "Bonferroni; réplica out-of-sample. La inversión robusta del durable downstream SÍ es firme."), "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP135.ref, S_151.ref, S_VERIF.ref])
    ceiling_note = ("1 techo 'real': el pago downstream bajo escasez genuina es MIXTA -- 1er positivo-leaning del arco (sugestivo, no "
                    "robusto) pero RANK-ONLY (re-expresa el AUROC del 151, no testea calibración); durable robusto NEG. Falta métrica de "
                    "calibración (CYCLE 154).")

    dstmt = ("North-Star R-VALOR (FRONTERA REAL §4.2 -- el diseño correcto del downstream): {V}. ¿El residuo genérico PAGA bajo ESCASEZ "
             "GENUINA? exp135 (pool fijo COMPARTIDO ESCASO base-rate {br}, f=m/#correct, f≈1 discriminante; corrige la saturación del "
             "152): 1er positivo-leaning del arco -- ls_lo−naive a f=1.0 positivo t-significativo SIN corregir en AMBOS pools (indist "
             "{gim} t={git}, heldout {ghm} t={ght}), monótono en indist. Verificación adversarial (signal_is_real=FALSE, overclaim_risk="
             "ALTO, recomendó MIXTA). Decisión: ADOPTAR que (1) el DISEÑO escaso/f≈1 es válido (corrige el 152), (2) hay una señal "
             "positiva SUGESTIVA pero NO robusta (falla LOO/Bonferroni/6-de-6, N smoke), (3) CRÍTICO: la métrica es RANK-ONLY -> "
             "re-expresa el AUROC del 151, NO testea calibración -> NO prueba la tesis 123 (sólo la apunta), (4) el durable robusto NEG "
             "confirma su inversión. Próximo (154): métrica decisional NO invariante-a-monótonas (cost-weighted/umbral-abstención) que "
             "separe calibración de ranking; N≥12; LOO+Bonferroni.").format(
                 V=status.upper(), br=_f(br['indist']), gim=_f(gi['mean']), git=_f(gi['tstat']), ghm=_f(gh['mean']), ght=_f(gh['tstat']))
    drat = ("exp135 (tier5, propio, lazo torch real, N={n}, pool escaso, post-verificación adversarial que recomendó MIXTA, "
            "signal_is_real=FALSE): 1er positivo-leaning -ls_lo−naive a f=1.0 positivo t-sig sin corregir en ambos pools, monótono "
            "indist- PERO no robusto (LOO/Bonferroni/5-de-6) y RANK-ONLY (re-expresa el AUROC del 151, r~0.87, no testea calibración); "
            "el durable robusto NEG (multiplicity-survivor). Convergente con el principio (tier2), el 151/152 (tier5) y la verificación "
            "(tier4). MIXTA: sugestivo no concluyente; el test de calibración real queda para el 154.").format(n=sm['n'])
    decision = Decision(id="D-V4-113", statement=dstmt, rationale=drat,
                        sources=[_to_plain(S_EXP135), _to_plain(S_151), _to_plain(S_VERIF)], important=True)

    return {
        "sources": [S_PRINCIPLE, S_151, S_152, S_VERIF, S_EXP135],
        "sources_note": ("5 fuentes (S_PRINCIPLE tier2 positivo sugestivo rank-only; S_151 tier5 el residuo + la inversión confirmada; "
                         "S_152 tier5 el diseño saturado corregido; S_VERIF tier4 verificación recomendó MIXTA signal_is_real=FALSE; "
                         "S_EXP135 tier5 dato propio MIXTA 1er positivo-leaning)."),
        "hyp_statement": hyp_statement, "hyp_prediction": hyp_prediction, "confidence": "media",
        "ev_for": ev_for, "ev_against": ev_against, "advtext": advtext, "mark_note": mark_note,
        "analogy": analogy, "analogy_note": analogy_note, "ceiling": ceiling, "ceiling_note": ceiling_note,
        "decision": decision, "decision_note": "D-V4-113 ACEPTADA por el ledger (tier5 exp135 + tier5 151/152 + tier4 verificación adversarial)."}


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle153_scarce_downstream',
                                description='CYCLE 153 (RESET v4, H-V4-9m: ¿el residuo paga DOWNSTREAM bajo escasez GENUINA?).')
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
    print("RESUMEN — CYCLE 153 (RESET v4): ¿el residuo paga DOWNSTREAM bajo escasez GENUINA? — H-V4-9m " + (status.upper() if status else "?"))
    print("=" * 78)
    print("veredicto H-V4-9m:", status.upper() if status else "?")
    for n_ in notes:
        print("  CHECK ", n_)
    print("")
    for name in ('sources', 'hypotheses', 'analogies', 'ceilings', 'decisions'):
        print("  {:<12}: {}".format(name, count_lines(record.store_path(name))))
    print("  verify_no_loss =", "OK" if res['ok'] else "FAIL")
    print("=" * 78)
    return 0 if res['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
