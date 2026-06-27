r"""
cycle141_decisional_powered.py — CICLO 141 (RESET v4, rama R-VALOR, SALIR DEL ORÁCULO, POWERED): H-V4-9h por las compuertas del
engine. INTENTÓ resolver el caveat de poder que la MIXTA del CYCLE 140 (exp124) dejó abierto -- la ventaja de RANKING base-rate-
INVARIANTE del durable (cura de unlikelihood 119) en el lazo torch REAL era positiva (AUROC +0.083, 4/4 seeds) pero UNDERPOWERED a
N=4 -- corriendo el MISMO lazo real (reusa run_seed de exp124) a N=8.

VEREDICTO: MIXTA (núcleo real + 5 sub-claims retractados por VERIFICACIÓN ADVERSARIAL de 3 agentes; 11mo ciclo seguido). El
experimento AUTO-DOCUMENTA el veredicto corregido.

QUÉ SOBREVIVE (limpio): la ventaja de RANKING del durable EXISTE y es base-rate-INVARIANTE -- AUROC durable > naive, signo-
consistente (7/8 seeds); NO es un confound de base-rate (corr(nc,AUROC) DENTRO de cada brazo ≈ 0 -> invariancia EMPÍRICA, la
defensa correcta).

QUÉ NO SOBREVIVE (retractado/acotado por la verificación de 3 agentes -- el experimento lo AUTO-DOCUMENTA):
  (1) la SIGNIFICANCIA es FRÁGIL: el t pareado apenas cruza el umbral PERO el SIGN-TEST (no-paramétrico, robusto, 7/8) da p≈0.07
      -> NO significativo a 0.05; y ese es JUSTO el test que definió el 'underpowered' de 140 -> el underpowered NO se resolvió,
      sólo se migró al t-paramétrico (el más sensible). Jackknife tumba la significancia al sacar 2 de 8 seeds.
  (2) la magnitud se DILUYE con N (winner's curse): los 4 seeds nuevos son ~4× más débiles; de +0.083 a N=4 bajó a +0.050 a N=8.
  (3) el 'base-rate emparejado' es FALSO (el durable genera MENOS correctas, trade-off de generación); la defensa válida es la
      INVARIANCIA empírica, no el emparejamiento.
  (4) el MECANISMO 'el gap crece / la cura PREVIENE el colapso' es un ARTEFACTO del cero-estructural de la ronda-1 (ambos brazos
      idénticos pre-divergencia); la pendiente per-seed SIN la ronda-1 FLIPEA a negativa/plana (no significativa); AMBOS brazos
      COLAPSAN su AUROC y el corr-gap converge a ~0. El efecto real es una VENTAJA INMEDIATA (gap máximo en rondas 2-3) que se
      EROSIONA.
  (5) casi-TAUTOLÓGICO + STRAWMAN: el unlikelihood optimiza DIRECTAMENTE la separación confianza-correcto/incorrecto que AUROC
      mide (no es ranking emergente, es supresión de confident-wrong), y sólo se probó contra el baseline-que-COLAPSA (eco del 139).

=> RESULTADO HONESTO: existe una ventaja de ranking del unlikelihood REAL y base-rate-invariante pero MODESTA, FRÁGIL, DILUYÉNDOSE,
INMEDIATA-no-acumulada, casi-tautológica y sólo vs el baseline que colapsa. El underpowered de 140 NO se resuelve limpio. MIXTA
EXITOSA: la verificación cazó significancia-frágil + mecanismo-artefacto + premisa-falsa antes del ledger (11mo ciclo).

DERIVA de exp125_decisional_powered/results/results.json.

Correr (DESPUÉS de exp125):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp125_decisional_powered.run --seeds 0,1,2,3,4,5,6,7
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle141_decisional_powered
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle141_decisional_powered')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp125_decisional_powered', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="POTENCIAR (más seeds) un hallazgo borderline de un ciclo previo es una compuerta honesta tan importante como un control nulo: revela si la significancia era robusta o frágil. Aquí, la ventaja de RANKING (AUROC, base-rate-invariante) de prevenir el colapso de calibración (cura 119) en un lazo de auto-entrenamiento REAL EXISTE pero su significancia es FRÁGIL (el sign-test no-paramétrico no la sostiene; la magnitud se diluye con N -- winner's curse), su 'mecanismo creciente' es un ARTEFACTO del cero-estructural de la ronda-1 (el efecto real es una ventaja INMEDIATA que se erosiona, no prevención acumulada del colapso), y es casi-tautológica (el unlikelihood optimiza lo que AUROC mide).", obtained=False,
                     claim=("Al potenciar a N=8 la ventaja de ranking de la cura 119 en el lazo real, EXISTE y es base-rate-"
                            "invariante pero su significancia es FRÁGIL (sign-test no la sostiene, magnitud diluyéndose) y el "
                            "'mecanismo creciente' es artefacto del cero de la ronda-1 (el efecto es inmediato, no acumulado). "
                            "(Principio metodológico.)"))
S_C140 = Source(tier=5, ref="cognia_x/experiments/exp124_decisional_real_loop (CYCLE 140)", obtained=True,
                claim=("CYCLE 140 (exp124, MIXTA): en el lazo torch REAL la decisión es endógena + verificador real, y hay una "
                       "ventaja de RANKING base-rate-INVARIANTE del durable (AUROC +0.083, 4/4 seeds) PERO UNDERPOWERED a N=4. "
                       "H-V4-9h potencia a N=8: la ventaja EXISTE pero su significancia es FRÁGIL y el 'mecanismo' es artefacto -> "
                       "el underpowered NO se resuelve limpio."))
S_VERIF = Source(tier=4, ref="verificación adversarial de 3 agentes (lentes significancia/poder, base-rate-residual/invariancia, mecanismo-trayectoria/fairness; probes reales sobre el log de exp125)", obtained=True,
                 claim=("La verificación adversarial (11mo ciclo) CONFIRMÓ que la ventaja de ranking EXISTE y es base-rate-INVARIANTE "
                        "(corr(nc,auroc) dentro de brazo ≈0) PERO CAZÓ: la SIGNIFICANCIA es FRÁGIL (sign-test p≈0.07 NO sig -el test "
                        "que definió el underpowered de 140-; jackknife tumba 2/8; magnitud diluyéndose con N); el 'base-rate "
                        "emparejado' es FALSO (la defensa es invariancia empírica); el 'mecanismo crece/previene colapso' es "
                        "ARTEFACTO del cero-estructural de la ronda-1 (sin ella la pendiente flipea; ambos brazos colapsan; el "
                        "efecto es INMEDIATO no acumulado); casi-tautológico (el unlikelihood optimiza lo que AUROC mide) y solo vs "
                        "el baseline-que-colapsa."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp125 primero): " + results_path)

    au = sm['auroc_gap_stats']; br = sm['baserate_gap_stats']; sl = sm['perseed_slope_no_r1']
    aun, aud = sm['auroc_naive'], sm['auroc_durable']
    ncd, ncn = sm['mean_ncorrect_durable'], sm['mean_ncorrect_naive']
    sp = sm['sign_test_p']; d1 = sm['dilution_first_half']; d2 = sm['dilution_second_half']
    cnad, cnan = sm['corr_nc_auroc_durable'], sm['corr_nc_auroc_naive']
    ge, gl = sm['gap_early'], sm['gap_late']; tcrit = sm['tcrit_df']; n_seeds = sm['n_seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim125 = ("exp125 (propio, {n} seeds, PyTorch CPU, lazo cerrado REAL -reusa run_seed de exp124-, post-verificación de 3 "
                "agentes): {V}. POWERED a N={n}. SOBREVIVE: la ventaja de RANKING del durable EXISTE (AUROC {aud} vs naive {aun}, "
                "gap +{am}, {ap}/{an} seeds) y es base-rate-INVARIANTE (corr(nc,auroc) dentro de brazo ≈0: durable {cnad}, naive "
                "{cnan}). RETRACTADO: significancia FRÁGIL (sign-test p={sp} NO sig; t apenas cruza); magnitud DILUYÉNDOSE (1ra "
                "mitad +{d1} vs 2da +{d2}); 'base-rate emparejado' FALSO (gap {brm}); 'mecanismo crece' ARTEFACTO (pendiente sin "
                "ronda-1 {slm}, t={slt}; efecto INMEDIATO gap_temprano {ge} vs tardío {gl}); casi-tautológico + strawman.").format(
                    n=n_seeds, V=status.upper(), aud=_f(aud), aun=_f(aun), am=_f(au['mean']), ap=au['n_positive'], an=au['n'],
                    cnad=_f(cnad), cnan=_f(cnan), sp=_f(sp), d1=_f(d1), d2=_f(d2), brm=_f(br['mean']), slm=_f(sl['mean']),
                    slt=sl['tstat'], ge=_f(ge), gl=_f(gl))
    S_EXP125 = Source(tier=5, ref="cognia_x/experiments/exp125_decisional_powered", obtained=True, claim=claim125)
    for src in (S_PRINCIPLE, S_C140, S_VERIF, S_EXP125):
        ledger.add_source(src)
    notes.append("4 fuentes (S_PRINCIPLE tier2 potenciar revela si la significancia era robusta o frágil; S_C140 tier5 la MIXTA underpowered; S_VERIF tier4 verificación adversarial -5 sub-claims retractados-; S_EXP125 tier5 dato propio {}).".format(status.upper()))

    ev_for = [S_EXP125.ref, S_PRINCIPLE.ref]
    ev_against = [S_EXP125.ref, S_VERIF.ref]
    advtext = ("{V} (SALIR DEL ORÁCULO, POWERED -- intento de resolver el caveat de poder de la MIXTA de 140; caracterización "
               "honesta tras verificación adversarial de 3 agentes, 11mo ciclo seguido): ¿la ventaja de RANKING base-rate-"
               "INVARIANTE del durable (cura 119) en el lazo torch REAL es REAL y ROBUSTAMENTE significativa, o era ruido de N "
               "chico? DISEÑO: el MISMO lazo cerrado real de 140 (HybridLM genera 'N=a*b' -> verificador REAL sandbox -> confianza "
               "ENDÓGENA -> self-train; durable agrega unlikelihood=cura 119) a N={n}. QUÉ SOBREVIVE (EVIDENCIA A FAVOR): la "
               "ventaja de RANKING EXISTE y es base-rate-INVARIANTE -- AUROC(confianza,correcto) durable {aud} vs naive {aun}, gap "
               "+{am} ({ap}/{an} seeds positivos, mediana +{amed}, jackknife-min +{ajk}); NO es un confound de base-rate: corr(nc,"
               "AUROC) DENTRO de cada brazo ≈ 0 (durable {cnad}, naive {cnan}) -> invariancia EMPÍRICA (la defensa correcta). QUÉ NO "
               "SOBREVIVE (retractado por la verificación de 3 agentes -- el experimento lo AUTO-DOCUMENTA): (1) la SIGNIFICANCIA es "
               "FRÁGIL -- el t pareado {at} apenas cruza tcrit(df={df})={tc}, PERO el SIGN-TEST (no-paramétrico, robusto, {ap}/{an}) "
               "da p={sp} -> NO significativo a 0.05; y ese es JUSTO el test cuyo tope (p=0.125 a N=4) definió el 'underpowered' de "
               "140 -> el underpowered NO está resuelto, sólo se migró al t-paramétrico (el más sensible a 2 seeds fuertes); el "
               "jackknife tumba la significancia al sacar 2 de 8 seeds. (2) la magnitud se DILUYE con N (winner's curse): 1ra mitad "
               "de seeds +{d1} vs 2da mitad +{d2} (los seeds nuevos ~4× más débiles); de +0.083 a N=4 bajó a +{am} a N=8 -> doblar "
               "N ENCOGIÓ el efecto, no lo robusteció. (3) el 'base-rate emparejado' es FALSO (gap {brm}, el durable genera MENOS "
               "correctas -> trade-off de generación); la defensa válida es la INVARIANCIA empírica, NO el emparejamiento (premisa "
               "contradictoria de la 1ra versión). (4) el MECANISMO 'el gap crece / la cura PREVIENE el colapso' es un ARTEFACTO "
               "del cero-estructural de la ronda-1 (ambos brazos idénticos pre-divergencia -> gap=0 por construcción): la pendiente "
               "per-seed SIN la ronda-1 es {slm} (t={slt}, NO significativa, flipea/plana); AMBOS brazos COLAPSAN su AUROC y el "
               "corr-gap converge a ~0; el efecto REAL es una VENTAJA INMEDIATA (gap máximo temprano, rondas 2-3 {ge}, vs tardío "
               "{gl}) que se EROSIONA -- el unlikelihood limpia los confident-wrong en la 1ra tanda (bump inmediato), no previene "
               "un colapso acumulado. (5) casi-TAUTOLÓGICO + STRAWMAN: el unlikelihood optimiza DIRECTAMENTE la separación "
               "confianza-correcto/incorrecto que AUROC mide (es supresión de confident-wrong, no ranking emergente), y sólo se "
               "probó contra el baseline-que-COLAPSA (no contra un regularizador de calibración alternativo -temperature scaling, "
               "penalización de entropía- eco del CYCLE 139 'la forma no era privilegiada'). => RESULTADO HONESTO: existe una "
               "ventaja de ranking del unlikelihood REAL y base-rate-invariante pero MODESTA, FRÁGIL (sign-test p={sp}), "
               "DILUYÉNDOSE con N, INMEDIATA-no-acumulada, casi-tautológica y sólo vs el baseline que colapsa. El underpowered de "
               "140 NO se resuelve limpio. APORTE: la honestidad de que potenciar NO rescató el efecto (se diluyó) + el mecanismo "
               "corregido (inmediato, no acumulado). MIXTA EXITOSA: la verificación cazó significancia-frágil + mecanismo-artefacto "
               "+ premisa-falsa antes del ledger (11mo ciclo seguido). Frontera: N=16 para zanjar la dilución; baseline "
               "regularizador-de-calibración alternativo; SCALE.").format(
                   V=status.upper(), n=n_seeds, aud=_f(aud), aun=_f(aun), am=_f(au['mean']), ap=au['n_positive'], an=au['n'],
                   amed=_f(au['median']), ajk=_f(au['jackknife_min']), cnad=_f(cnad), cnan=_f(cnan), at=au['tstat'],
                   df=n_seeds - 1, tc=_f(tcrit), sp=_f(sp), d1=_f(d1), d2=_f(d2), brm=_f(br['mean']), slm=_f(sl['mean']),
                   slt=sl['tstat'], ge=_f(ge), gl=_f(gl))

    hyp = Hypothesis(
        id="H-V4-9h",
        statement=("La ventaja de RANKING base-rate-INVARIANTE (AUROC) del brazo durable (cura 119) en el lazo torch REAL -- que el "
                   "CYCLE 140 halló positiva pero UNDERPOWERED a N=4 -- ¿es REAL y ROBUSTAMENTE significativa a N=8 (t pareado Y "
                   "sign-test), con base-rate invariante, y CRECE a lo largo de las rondas (la cura previene el colapso)? Alcance: "
                   "sustrato chico, tarea aritmética, sólo el ranking (AUROC) es limpio, CPU."),
        prediction=("APOYADA si el AUROC gap es positivo, ROBUSTAMENTE significativo (t Y sign-test) a N=8, base-rate-invariante, "
                    "no-diluyente y con mecanismo acumulado real. REFUTADA si NO hay ventaja. MIXTA si la ventaja existe pero la "
                    "significancia es frágil (sign-test no la sostiene) / se diluye / el mecanismo es artefacto. (Pre-registrada; "
                    "verificación adversarial de 3 agentes.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp125_decisional_powered")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-9h")
        notes.append("H-V4-9h marcada '{}': la ventaja de ranking AUROC de la cura 119 en el lazo real EXISTE y es base-rate-invariante, pero potenciar a N={} reveló que su significancia es FRÁGIL (sign-test no la sostiene, magnitud diluyéndose) y el 'mecanismo creciente' es un artefacto del cero-estructural de la ronda-1 (el efecto es inmediato, no acumulado). El underpowered de 140 no se resuelve limpio.".format(status, n_seeds))

    analogy = AnalogyRecord(
        problem=("En el lazo real el modelo que cuida su olfato ordenaba mejor las respuestas, pero con 4 corridas no alcanzaba. "
                 "Lo corriste 8 veces para estar seguro. ¿Quedó confirmado, y crecía la ventaja como pensabas?"),
        everyday=("Ni una cosa ni la otra, y ser honesto acá es el resultado. Con el doble de corridas la ventaja NO se afirmó: el "
                  "test robusto (contar cuántas veces ganó: 7 de 8) todavía da 'podría ser suerte' (p≈0.07), y las 4 corridas "
                  "nuevas fueron MUCHO más flojas que las primeras -- o sea la ventaja se está DILUYENDO, no robusteciendo (el "
                  "típico espejismo de quedarse con la primera muestra optimista). Y el 'la brecha crece ronda a ronda' era un "
                  "engaño: la primera ronda vale cero por definición (los dos modelos son idénticos antes de divergir), y eso solo "
                  "INFLABA la cuenta; sacando esa ronda, la brecha NO crece, se ACHICA -- la ventaja es un golpe INMEDIATO del "
                  "primer ajuste que después se gasta, no una protección que se acumula. Encima, 'cuidar el olfato' es casi hacer "
                  "trampa: el ajuste optimiza EXACTAMENTE lo que medís. Moraleja honesta: la ventaja existe y es real (no es por "
                  "cuántas respuestas hay), pero es chica, frágil, inmediata, y sólo se midió contra el peor rival."),
        solutions=["potenciar a N=8 NO confirmó la ventaja: el sign-test robusto sigue no-significativo (p≈0.07) y la magnitud se DILUYE con N (winner's curse)",
                   "la ventaja EXISTE y es base-rate-INVARIANTE (corr(nc,auroc) dentro de brazo ≈0), pero MODESTA y FRÁGIL",
                   "el 'mecanismo crece/previene el colapso' es ARTEFACTO del cero-estructural de la ronda-1; el efecto real es INMEDIATO (un golpe del 1er ajuste que se erosiona)",
                   "casi-tautológico (el unlikelihood optimiza lo que AUROC mide) y sólo vs el baseline que colapsa (strawman para el claim de mecanismo)"],
        principles=["potenciar (más seeds) un hallazgo borderline es una compuerta honesta: aquí reveló que la significancia era frágil y el efecto se diluye (winner's curse), no que se robustece",
                    "un 'mecanismo creciente' por trayectoria debe excluir los ceros ESTRUCTURALES (ronda-1: brazos idénticos) y testear la pendiente per-seed; incluir el cero la infla artificialmente",
                    "ventaja INMEDIATA (golpe del 1er paso que se erosiona) != ventaja ACUMULADA (prevención de colapso): la trayectoria distingue, el nivel no",
                    "META: 11mo ciclo seguido con verificación adversarial -- aquí cazó significancia-frágil + mecanismo-artefacto + una premisa-falsa (base-rate emparejado) antes del ledger"],
        adaptation=("El CYCLE 140 dejó la ventaja de ranking del durable como MIXTA por UNDERPOWERED (N=4). Este ciclo la POTENCIA a "
                    "N=8 para resolverlo y el resultado honesto es que NO se resuelve limpio: la ventaja EXISTE y es base-rate-"
                    "invariante (corr(nc,auroc)≈0), pero su significancia es FRÁGIL (el sign-test robusto sigue no-significativo "
                    "p≈0.07, el mismo test que originó el rótulo underpowered), la magnitud se DILUYE con N (winner's curse), el "
                    "'mecanismo creciente' es un artefacto del cero-estructural de la ronda-1 (el efecto es INMEDIATO, no acumulado; "
                    "ambos brazos colapsan), y es casi-tautológico (el unlikelihood optimiza lo que AUROC mide) y sólo vs el "
                    "baseline-que-colapsa. APORTE: la honestidad de que potenciar NO rescató el efecto + el mecanismo corregido "
                    "(inmediato, no acumulado) + la invariancia empírica como defensa correcta (no el 'emparejamiento' falso). "
                    "META-LECCIÓN: 11mo ciclo seguido con verificación adversarial; potenciar es una compuerta tan reveladora como "
                    "un control nulo. Próximo: N=16 para zanjar la dilución; baseline regularizador-de-calibración alternativo "
                    "(¿es la cura 119 privilegiada o cualquier regularización sirve?); SCALE."),
        measurement=("exp125 ({n} seeds, lazo torch REAL): AUROC durable {aud} vs naive {aun} (gap +{am}, {ap}/{an} seeds, t={at} "
                     "vs tcrit(df={df})={tc}); SIGN-TEST p={sp}; dilución 1ra mitad +{d1} vs 2da +{d2}; invariancia corr(nc,auroc) "
                     "durable {cnad}/naive {cnan}; pendiente sin ronda-1 {slm} (t={slt}); gap temprano {ge} vs tardío {gl}.").format(
                         n=n_seeds, aud=_f(aud), aun=_f(aun), am=_f(au['mean']), ap=au['n_positive'], an=au['n'], at=au['tstat'],
                         df=n_seeds - 1, tc=_f(tcrit), sp=_f(sp), d1=_f(d1), d2=_f(d2), cnad=_f(cnad), cnan=_f(cnan),
                         slm=_f(sl['mean']), slt=sl['tstat'], ge=_f(ge), gl=_f(gl)),
        iterations=1)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (potenciar NO confirmó la ventaja -el test robusto sigue dando 'podría ser suerte' y se diluye-; el 'crece' era un engaño del cero de la ronda-1; el efecto es un golpe inmediato que se gasta).")

    kl = ("REAL (exp125, {V} post-verificación adversarial de 3 agentes): POWERED a N={n} NO resuelve limpio el underpowered de la "
          "MIXTA de 140. La ventaja de RANKING del durable (cura 119) en el lazo torch REAL EXISTE y es base-rate-INVARIANTE "
          "(corr(nc,auroc) dentro de brazo ≈0: durable {cnad}, naive {cnan}; AUROC gap +{am}, {ap}/{an} seeds) PERO: significancia "
          "FRÁGIL (sign-test p={sp} NO sig; t apenas cruza; jackknife tumba 2/8); magnitud DILUYÉNDOSE (1ra mitad +{d1} vs 2da "
          "+{d2}); 'base-rate emparejado' FALSO (gap {brm}); el 'mecanismo crece' es ARTEFACTO del cero de la ronda-1 (pendiente "
          "sin ronda-1 {slm}, efecto INMEDIATO {ge} vs tardío {gl}); casi-tautológico + strawman. TECHO/ALCANCE: el oráculo "
          "supervisa el lazo (sólo el ranking AUROC es limpio); sustrato chico/tarea aritmética/N=8/CPU. Frontera: N=16 para la "
          "dilución; baseline regularizador alternativo; SCALE.").format(
              V=status.upper(), n=n_seeds, cnad=_f(cnad), cnan=_f(cnan), am=_f(au['mean']), ap=au['n_positive'], an=au['n'],
              sp=_f(sp), d1=_f(d1), d2=_f(d2), brm=_f(br['mean']), slm=_f(sl['mean']), ge=_f(ge), gl=_f(gl))
    ceilings.add(CeilingRecord(
        subsystem="VENTAJA DE RANKING (calibración) de la cura 119 en un LAZO CERRADO REAL — POWERED a N=8 (intento de resolver el underpowered de la MIXTA de 140). SOBREVIVE: la ventaja de ranking base-rate-INVARIANTE del durable (AUROC) EXISTE (corr(nc,auroc) dentro de brazo ≈0 = invariancia empírica). NO SOBREVIVE: significancia FRÁGIL (sign-test no-paramétrico no la sostiene, magnitud diluyéndose con N = winner's curse), 'base-rate emparejado' FALSO (la defensa es invariancia empírica), 'mecanismo crece/previene colapso' ARTEFACTO del cero-estructural de la ronda-1 (el efecto es INMEDIATO no acumulado; ambos brazos colapsan), casi-tautológico (el unlikelihood optimiza lo que AUROC mide) + strawman (sólo vs baseline-que-colapsa). El underpowered de 140 NO se resuelve limpio. Alcance: sustrato chico, N=8, sólo el ranking es limpio",
        known_limit=kl,
        blockers=[{"text": "SIGNIFICANCIA FRÁGIL + DILUCIÓN (el modo de fallo central, cazado por la verificación): el t pareado apenas cruza tcrit PERO el SIGN-TEST (no-paramétrico, robusto, {ap}/{an}) da p={sp} -> NO significativo a 0.05; y ese es JUSTO el test cuyo tope (p=0.125 a N=4) definió el 'underpowered' de 140 -> el underpowered NO se resolvió, sólo se migró al t-paramétrico. El jackknife tumba la significancia al sacar 2 de 8 seeds. PEOR: la magnitud se DILUYE (1ra mitad +{d1} vs 2da +{d2}; de +0.083 a N=4 a +{am} a N=8) -> winner's curse: doblar N encogió el efecto. Lo NO-frágil/load-bearing: la EXISTENCIA de la ventaja (signo {ap}/{an}, base-rate-invariante)".format(ap=au['n_positive'], an=au['n'], sp=_f(sp), d1=_f(d1), d2=_f(d2), am=_f(au['mean'])), "kind": "diseno"},
        {"text": "MECANISMO ARTEFACTO + PREMISA FALSA (cazados): (a) el 'gap crece / la cura PREVIENE el colapso' es ARTEFACTO del cero-estructural de la ronda-1 (ambos brazos idénticos pre-divergencia); la pendiente per-seed SIN la ronda-1 es {slm} (t={slt}, no sig, flipea); AMBOS brazos colapsan su AUROC y el corr-gap converge a ~0; el efecto REAL es una VENTAJA INMEDIATA (gap temprano {ge} vs tardío {gl}) que se erosiona -> el unlikelihood limpia los confident-wrong en la 1ra tanda (bump inmediato), no previene un colapso acumulado. (b) el 'base-rate emparejado' es FALSO (gap {brm}, trade-off de generación); la defensa CORRECTA es la INVARIANCIA empírica (corr(nc,auroc)≈0), no el emparejamiento".format(slm=_f(sl['mean']), slt=sl['tstat'], ge=_f(ge), gl=_f(gl), brm=_f(br['mean'])), "kind": "diseno"},
        {"text": "casi-TAUTOLÓGICO + STRAWMAN + ALCANCE: el unlikelihood (cura 119) optimiza DIRECTAMENTE la separación confianza-correcto/incorrecto que AUROC mide -> la ganancia de AUROC es supresión-de-confident-wrong, no ranking emergente; y sólo se probó contra el baseline-que-COLAPSA (no contra un regularizador de calibración alternativo -temperature scaling, penalización de entropía- eco del 139 'la forma no era privilegiada'). ALCANCE: el oráculo supervisa el lazo (sólo el ranking AUROC es limpio; el payoff precision@m sigue confundido, 140); sustrato CHICO (HybridLM ~200k), tarea aritmética, N=8, CPU. NO cubre: N>=16, baseline alternativo, SCALE, verificador rico, lazo secuencial", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP125.ref, S_C140.ref, S_VERIF.ref]))
    notes.append("1 techo 'real': la ventaja de ranking AUROC de la cura 119 en el lazo real EXISTE y es base-rate-invariante PERO su significancia es frágil (sign-test no la sostiene, diluyéndose), el 'mecanismo creciente' es artefacto del cero de la ronda-1 (efecto inmediato no acumulado), casi-tautológico + strawman. El underpowered de 140 no se resuelve limpio.")

    dstmt = ("North-Star R-VALOR (SALIR DEL ORÁCULO, POWERED -- intento de resolver el caveat de poder de la MIXTA de 140): {V}. La "
             "ventaja de RANKING base-rate-INVARIANTE del durable (cura 119) en el lazo torch REAL, potenciada a N={n}: EXISTE "
             "(AUROC {aud} vs {aun}, gap +{am}, {ap}/{an} seeds; corr(nc,auroc) dentro de brazo ≈0 = invariancia empírica) PERO su "
             "significancia es FRÁGIL (sign-test p={sp} NO sig -el test que definió el underpowered de 140-), la magnitud se DILUYE "
             "con N (winner's curse), el 'mecanismo crece' es ARTEFACTO del cero de la ronda-1 (efecto INMEDIATO no acumulado), "
             "casi-tautológico + strawman. Decisión: NO declarar resuelto el underpowered de 140; adoptar que la ventaja de ranking "
             "de la cura 119 EXISTE pero es modesta/frágil/inmediata, y que potenciar reveló DILUCIÓN (no robustez). META-DECISIÓN: "
             "11mo ciclo con verificación adversarial. Próximo: N=16 para la dilución; baseline regularizador-de-calibración "
             "alternativo; SCALE.").format(
                 V=status.upper(), n=n_seeds, aud=_f(aud), aun=_f(aun), am=_f(au['mean']), ap=au['n_positive'], an=au['n'],
                 sp=_f(sp))
    drat = ("exp125 (tier5, propio, {n} seeds, PyTorch CPU, lazo cerrado REAL -reusa run_seed de exp124-, post-verificación de 3 "
            "agentes): la ventaja de ranking base-rate-invariante del durable EXISTE (corr(nc,auroc)≈0) pero su significancia es "
            "FRÁGIL (sign-test p={sp} no la sostiene), se DILUYE con N, el 'mecanismo crece' es artefacto del cero de la ronda-1 "
            "(efecto inmediato), y es casi-tautológico + strawman. Convergente con el principio (tier2) y la verificación (tier4); "
            "potencia (sin resolver) exp124/CYCLE140 (tier5). MIXTA: existe pero frágil; el underpowered no se resuelve limpio.").format(
                n=n_seeds, sp=_f(sp))
    dec = Decision(id="D-V4-103", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP125), _to_plain(S_C140), _to_plain(S_VERIF)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-103 ACEPTADA por el ledger (tier5 exp125 + tier5 exp124/C140 + tier4 verificación adversarial).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-103:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle141_decisional_powered',
                                description='CYCLE 141 (RESET v4, H-V4-9h MIXTA: POWERED a N=8 NO resuelve limpio el underpowered de 140 -- la ventaja de ranking AUROC de la cura 119 EXISTE y es base-rate-invariante pero su significancia es frágil -sign-test no la sostiene, diluyéndose- y el mecanismo es artefacto del cero de la ronda-1; 11mo ciclo con verificación adversarial).')
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
    print("RESUMEN — CYCLE 141 (RESET v4): SALIR DEL ORÁCULO POWERED (N=8) NO resuelve limpio el underpowered de 140 — H-V4-9h " + (status.upper() if status else "?"))
    print("=" * 78)
    print("veredicto H-V4-9h:", status.upper() if status else "?")
    print("  SOBREVIVE: la ventaja de RANKING base-rate-INVARIANTE del durable (cura 119) EXISTE (corr(nc,auroc) dentro de brazo ≈0). NO SOBREVIVE: significancia FRÁGIL (sign-test no la sostiene, magnitud diluyéndose con N); 'base-rate emparejado' FALSO (la defensa es invariancia empírica); 'mecanismo crece/previene colapso' ARTEFACTO del cero-estructural de la ronda-1 (efecto INMEDIATO no acumulado); casi-tautológico + strawman. El underpowered de 140 NO se resuelve limpio.")
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
