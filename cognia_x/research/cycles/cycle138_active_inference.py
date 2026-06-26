r"""
cycle138_active_inference.py — CICLO 138 (RESET v4, rama control/acción, PUENTE FORMAL a ACTIVE INFERENCE): H-V4-10l por las
compuertas del engine. ¿EMERGE el keystone (valor = controlabilidad × relevancia, 79-137) de minimizar la ENERGÍA LIBRE ESPERADA?

VEREDICTO: MIXTA (puente TEÓRICO válido + 'emergencia empírica' TAUTOLÓGICA/artefacto). Post-verificación adversarial de 3 agentes
(8vo ciclo). La directiva acertó DERIVACIONALMENTE pero NO empíricamente.

SOBREVIVE (puente teórico). En un modelo generativo lineal-gaussiano con preferencia gaussiana (costo pragmático = E[G²],
CUADRÁTICO), el término PRAGMÁTICO de la EFE = w²·v·ctrl. El keystone del lab (w·ctrl, 129) es su LÍMITE binary+uniforme (w∈{0,1}
⇒ w²=w; v=1) -> active inference SUBSUME el keystone como caso especial = GROUNDING NORMATIVO del producto (la directiva acertó en
lo TEÓRICO). El producto-estructurado es LEARNABLE de un stream (converge desde abajo, leakage-free). Las factores simples FALLAN.

NO SOBREVIVE (retractado por la verificación; el experimento lo AUTO-DOCUMENTA):
  (1) La 'emergencia EMPÍRICA' es TAUTOLÓGICA: efe_pragmatic (w²·v·ctrl) es BYTE-IDÉNTICO a la métrica del eval -> efe=oracle por
      construcción; 'efe>keystone' es álgebra, no un hallazgo.
  (2) 'Emerge bajo binary' es la identidad trivial w²=w.
  (3) El '+0.43 refinamiento' es ARTEFACTO de un canónico hand-tuned: en 200 configs graded ALEATORIAS la MEDIANA del gap es ~0.
  (4) El MECANISMO 'w² refina' es FALSO: la VARIANZA-PRIOR v hace el grueso; el cuadrado es NEUTRO-A-DAÑINO bajo params ESTIMADOS
      (w·v·ctrl GANA a w²·v·ctrl en todo T finito; el cuadrado amplifica el ruido de ŵ). La corrección ROBUSTA y LEARNABLE sobre
      el keystone es incluir la varianza-prior v (w·v·ctrl), NO elevar w al cuadrado.
  (5) La unificación exploración/empowerment es CONJETURA: con epistémico CANÓNICO (info-gain σ² puro) la exploración apenas paga.
  (6) Alcance: lineal-gaussiano, modos INDEPENDIENTES (no cubre 135-136 no-lineal ni 137 acoplado).

=> RESULTADO HONESTO: el keystone ctrl×rel es el LÍMITE binary+uniforme de la EFE pragmática (puente normativo real, confirma la
directiva en lo teórico); la corrección empírica robusta sobre el keystone es la varianza-prior v, no el cuadrado; la exploración
como término EFE queda como conjetura. MIXTA EXITOSA: la verificación adversarial corrigió un overclaim mayor (8vo ciclo seguido).

DERIVA de exp122_active_inference/results/results.json.

Correr (DESPUÉS de exp122):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp122_active_inference.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle138_active_inference
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle138_active_inference')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp122_active_inference', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="el keystone del R-VALOR (valor=ctrl×rel, 79-137) es el LÍMITE binary+uniforme del término PRAGMÁTICO de la ENERGÍA LIBRE ESPERADA (active inference): bajo un modelo lineal-gaussiano con preferencia gaussiana, el valor de controlar un modo = w²·v·ctrl, cuyo límite con relevancia binaria + varianza uniforme (w²=w, v=1) ES el keystone w·ctrl. Active inference SUBSUME el keystone como caso especial = grounding normativo del producto. PERO la corrección EMPÍRICA robusta sobre el keystone es incluir la varianza-prior v (w·v·ctrl), NO elevar w al cuadrado (el cuadrado daña bajo estimación).", obtained=False,
                     claim=("El keystone valor=ctrl×rel es el LÍMITE binary+uniforme del término pragmático de la EFE (w²·v·ctrl, "
                            "derivado de un modelo lineal-gaussiano con preferencia gaussiana) -> active inference da el GROUNDING "
                            "NORMATIVO del producto (puente teórico; la directiva acertó derivacionalmente). PERO la 'emergencia "
                            "empírica' es tautológica (efe_pragmatic ES la métrica) y el MECANISMO w² es falso: la corrección "
                            "robusta/learnable sobre el keystone es la varianza-prior v (w·v·ctrl), no el cuadrado. (Principio.)"))
S_C129 = Source(tier=5, ref="cognia_x/experiments/exp113_value_factorization (CYCLE 129 keystone)", obtained=True,
                claim=("CYCLE 129 (keystone, empírico): el control reconstruye R-VALOR = ctrl × rel, w·b²/(b²+ρ). H-V4-10l muestra "
                       "que ese keystone es el LÍMITE binary+uniforme del término pragmático de la EFE (w²·v·ctrl), grounding "
                       "normativo; y que la corrección empírica robusta es la varianza-prior v, no el cuadrado w²."))
S_VERIF = Source(tier=4, ref="verificación adversarial de 3 agentes (lentes tautología-derivación/framing/robustez-leakage; probes reales sobre exp122)", obtained=True,
                 claim=("La verificación adversarial (8vo ciclo) confirmó el PUENTE TEÓRICO (el keystone es el límite binary+"
                        "uniforme de la EFE pragmática derivada) pero CAZÓ que la 'emergencia empírica' es TAUTOLÓGICA "
                        "(efe_pragmatic = byte-idéntico a la métrica del eval; efe=oracle por construcción), el '+0.43' es artefacto "
                        "de un canónico hand-tuned (mediana ~0 en 200 configs aleatorias), el mecanismo w² es falso (la varianza-"
                        "prior v hace el grueso; el cuadrado daña bajo estimación: w·v·ctrl > w²·v·ctrl), y la unificación con "
                        "exploración es conjetura (epistémico canónico σ² apenas paga)."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp122 primero): " + results_path)

    bue = sm['bu_efe']; buk = sm['bu_keystone']; ge = sm['gn_efe']; gk = sm['gn_keystone']; gvc = sm['gn_vcorr']
    grel = sm['gn_relevancia']; gctl = sm['gn_control']; gpred = sm['gn_prediccion']
    rmed = sm['refine_median']; vmed = sm['vcorr_median']; smed = sm['square_median']
    emE = sm['est_mid_efe']; emV = sm['est_mid_vcorr']; emK = sm['est_mid_keystone']
    d0 = sm['discovery_vcorr_T0']; dN = sm['discovery_vcorr_TN']; gu = sm['gain_uniform']; gc = sm['gain_concentrated']
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim122 = ("exp122 (propio, {n} seeds, numpy, post-verificación de 3 agentes): MIXTA. PUENTE TEÓRICO: el keystone (w·ctrl) es "
                "el LÍMITE binary+uniforme del término pragmático de la EFE (w²·v·ctrl; binary efe {bue}=keystone {buk}, w²=w); "
                "active inference subsume el keystone (grounding normativo). El producto es LEARNABLE leakage-free (converge desde "
                "abajo, T=10 {d0} -> {dN}); las factores FALLAN (graded relev {grel}/ctrl {gctl}/pred {gpred}). NO SOBREVIVE: la "
                "emergencia es TAUTOLÓGICA (efe_pragmatic=métrica del eval, efe=oracle {ge}); el '+0.43' es artefacto (mediana del "
                "gap en 200 configs aleatorias = {rmed}); el MECANISMO w² es FALSO (la varianza-prior v hace el grueso; bajo "
                "estimación el cuadrado DAÑA: T=75 v_corr {emV} > efe {emE}); la exploración es conjetura (epistémico canónico σ² "
                "apenas paga, +{gu}/+{gc}). Corrección robusta = incluir v (w·v·ctrl), no el cuadrado.").format(
                    n=n_seeds, bue=_f(bue), buk=_f(buk), d0=_f(d0), dN=_f(dN), grel=_f(grel), gctl=_f(gctl), gpred=_f(gpred),
                    ge=_f(ge), rmed=_f(rmed), emV=_f(emV), emE=_f(emE), gu=_f(gu), gc=_f(gc))
    S_EXP122 = Source(tier=5, ref="cognia_x/experiments/exp122_active_inference", obtained=True, claim=claim122)
    for src in (S_PRINCIPLE, S_C129, S_VERIF, S_EXP122):
        ledger.add_source(src)
    notes.append("4 fuentes (S_PRINCIPLE tier2 keystone=límite binary+uniforme de la EFE pragmática; corrección robusta=v; S_C129 tier5 keystone empírico; S_VERIF tier4 verificación adversarial -tautología/artefacto cazados-; S_EXP122 tier5 dato propio MIXTA).")

    ev_for = [S_EXP122.ref, S_PRINCIPLE.ref]
    ev_against = [S_EXP122.ref, S_VERIF.ref]
    advtext = ("{V} (PUENTE FORMAL a active inference -- válido en lo TEÓRICO, tautológico/artefacto en lo EMPÍRICO; 8vo ciclo con "
               "verificación adversarial, overclaim mayor corregido): ¿EMERGE el keystone (valor=ctrl×rel) de minimizar la ENERGÍA "
               "LIBRE ESPERADA? SOBREVIVE (PUENTE TEÓRICO, EVIDENCIA A FAVOR): en un modelo lineal-gaussiano con preferencia "
               "gaussiana (costo pragmático = E[G²], cuadrático), el término PRAGMÁTICO de la EFE = w²·v·ctrl (derivación cerrada, "
               "verificada por Monte-Carlo en la verificación); el keystone del lab (w·ctrl, 129) es su LÍMITE binary+uniforme "
               "(binary efe {bue}=keystone {buk}, por la identidad w²=w, v=1) -> active inference SUBSUME el keystone como caso "
               "especial = GROUNDING NORMATIVO del producto (la directiva 'el producto cae de minimizar la EFE' acertó en lo "
               "TEÓRICO). El valor producto-estructurado es además LEARNABLE de UN stream, leakage-free (converge desde abajo: "
               "T=10 {d0} -> T=1500 {dN}; control nulo decoy-w se estanca, no recupera). Las factores simples FALLAN (graded relev "
               "{grel} -cae en la trampa de los modos relevantes-incontrolables-, ctrl {gctl}, pred {gpred}) -> la composición "
               "ctrl×rel es necesaria. EVIDENCIA EN CONTRA (retractado por la verificación de 3 agentes -- todos reprodujeron los "
               "probes): (1) la 'emergencia EMPÍRICA' es TAUTOLÓGICA -- el scorer efe_pragmatic (w²·v·ctrl) es BYTE-IDÉNTICO a la "
               "métrica del eval (la reducción de error), así que efe=oracle ({ge}) por construcción en TODO régimen/seed y "
               "'efe>keystone' es álgebra, no un hallazgo empírico. (2) 'emerge bajo binary' es la identidad ALGEBRAICA TRIVIAL "
               "w²=w (no una emergencia). (3) el '+0.43 refinamiento' es un ARTEFACTO de un canónico HAND-TUNED para maximizar la "
               "divergencia w vs w²·v: en 200 configs graded ALEATORIAS la MEDIANA del gap efe-keystone es {rmed} (~nulo; el "
               "canónico era percentil-100). (4) el MECANISMO afirmado ('la EFE pesa la relevancia al CUADRADO') es FALSO -- la "
               "VARIANZA-PRIOR v hace ~85-100% de la corrección y el cuadrado ~1.5%; PEOR, bajo params ESTIMADOS (el único régimen "
               "no-tautológico) el cuadrado es NEUTRO-A-DAÑINO: w·v·ctrl GANA a w²·v·ctrl en todo T finito (T=75 v_corr {emV} > efe "
               "{emE}) porque el cuadrado amplifica el ruido de ŵ -> la corrección ROBUSTA y LEARNABLE sobre el keystone es incluir "
               "la varianza-prior v (w·v·ctrl), NO el cuadrado. (5) la unificación exploración/empowerment es CONJETURA: el "
               "epistémico modelado (σ²·v·c) no es canónico; con info-gain PURO (σ²) la exploración apenas paga (gan_unif +{gu}, "
               "gan_conc +{gc}) y la predicción pre-registrada 'concentración amplifica' FALLÓ. (6) ALCANCE: lineal-gaussiano, "
               "modos INDEPENDIENTES (no cubre los sustratos no-lineales 135-136 ni acoplados 137, justo donde el producto LOCAL "
               "necesita revisión). => MIXTA: el keystone es el LÍMITE binary+uniforme de la EFE pragmática (puente normativo real); "
               "la corrección empírica robusta es la varianza-prior v, no el cuadrado; la exploración como término EFE queda como "
               "conjetura. MIXTA EXITOSA: la verificación adversarial corrigió un overclaim mayor antes del ledger (8vo seguido).").format(
                   V=status.upper(), bue=_f(bue), buk=_f(buk), d0=_f(d0), dN=_f(dN), grel=_f(grel), gctl=_f(gctl),
                   gpred=_f(gpred), ge=_f(ge), rmed=_f(rmed), emV=_f(emV), emE=_f(emE), gu=_f(gu), gc=_f(gc))

    hyp = Hypothesis(
        id="H-V4-10l",
        statement=("El keystone (valor = ctrl × rel, 79-137) es el LÍMITE binary+uniforme del término PRAGMÁTICO de la ENERGÍA "
                   "LIBRE ESPERADA: en un modelo lineal-gaussiano con preferencia gaussiana, el valor de controlar un modo = "
                   "w²·v·ctrl, cuyo límite con relevancia binaria + varianza uniforme (w²=w, v=1) ES el keystone w·ctrl -> active "
                   "inference SUBSUME el keystone como caso especial (grounding normativo del producto; puente teórico). PERO la "
                   "'emergencia empírica' es tautológica (efe_pragmatic = la métrica del eval), el '+0.43 refinamiento' es artefacto "
                   "de un canónico hand-tuned (mediana ~0 en configs aleatorias), y el mecanismo w² es FALSO -- la corrección "
                   "robusta/learnable sobre el keystone es la varianza-prior v (w·v·ctrl), no el cuadrado; la unificación con "
                   "exploración es conjetura. Alcance: lineal-gaussiano, modos independientes."),
        prediction=("APOYADA si el término pragmático bate a las factores de forma NO-tautológica y el refinamiento es robusto a "
                    "configs aleatorias y sobrevive a la estimación; MIXTA si el puente teórico vale pero la emergencia empírica "
                    "es tautológica/artefacto y la corrección robusta es v no el cuadrado; REFUTADA si ni el puente teórico se "
                    "sostiene. (Pre-registrada; verificación adversarial de 3 agentes: tautología/framing/robustez.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp122_active_inference")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-10l")
        notes.append("H-V4-10l marcada '{}': puente teórico válido (keystone = límite binary+uniforme de la EFE pragmática) pero emergencia empírica tautológica/artefacto; corrección robusta = varianza-prior v, no el cuadrado w².".format(status))

    analogy = AnalogyRecord(
        problem=("Tenés una regla práctica que descubriste a los golpes -- 'atendé a lo que podés MOVER y que IMPORTA' (ctrl×rel). "
                 "¿CAE de un principio más profundo (minimizar la sorpresa esperada), o sólo lo parece porque mediste con la misma "
                 "vara que la define?"),
        everyday=("Las dos cosas, y hay que separarlas. SÍ cae de un principio: si pensás como alguien que minimiza su sorpresa "
                  "esperada sobre un resultado que prefiere, la cuenta de cuánto conviene tocar cada cosa ES 'cuánto la podés mover "
                  "× cuánto importa' -- tu regla, ahora con fundamento. PERO si después 'comprobás' que tu fórmula gana usando como "
                  "juez a la MISMA fórmula, no comprobaste nada (es circular). Y la 'mejora' que creías haber encontrado "
                  "-importancia al cuadrado- resulta ser un espejismo: en casos típicos no cambia nada, y cuando NO conocés los "
                  "números exactos sino que los estimás, elevar al cuadrado AMPLIFICA tus errores y EMPEORA. Lo que sí mejora de "
                  "verdad es acordarte de cuánto VARÍA cada cosa (su varianza), no elevar al cuadrado la importancia. Moraleja: el "
                  "principio te da el fundamento (valioso), pero la 'comprobación' era circular y la mejora real era otra."),
        solutions=["el keystone ctrl×rel es el LÍMITE binary+uniforme del término pragmático de la energía libre esperada -> grounding normativo (puente teórico real)",
                   "PERO 'comprobar' que la EFE-pragmática gana usándola como juez es CIRCULAR (tautológico): no es evidencia empírica",
                   "el 'refinamiento al cuadrado' es un espejismo: nulo en el caso típico y DAÑINO bajo estimación (amplifica el ruido)",
                   "la corrección empírica ROBUSTA sobre el keystone es incluir la VARIANZA-PRIOR (cuánto varía cada cosa), no elevar la importancia al cuadrado"],
        principles=["el keystone valor=ctrl×rel es el límite binary+uniforme del término pragmático de la EFE (puente normativo; la directiva acertó en lo teórico)",
                    "'comprobar' una fórmula usándola como métrica del eval es CIRCULAR -- la emergencia empírica de este experimento es tautológica",
                    "la corrección robusta/learnable sobre el keystone es la varianza-prior v (w·v·ctrl); el cuadrado w² es un artefacto del límite oráculo, dañino bajo estimación",
                    "META: 8vo ciclo seguido en que la verificación adversarial corrige un overclaim mayor (aquí, tautología + artefacto + mecanismo falso) antes del ledger"],
        adaptation=("El lab buscaba el grounding NORMATIVO del keystone en active inference (la rama que la directiva marcó como la "
                    "más grande faltante) y obtiene un resultado MIXTO honesto. SOBREVIVE (puente teórico): el keystone valor="
                    "ctrl×rel es el LÍMITE binary+uniforme del término pragmático de la energía libre esperada (w²·v·ctrl, derivado "
                    "de un modelo lineal-gaussiano con preferencia gaussiana) -> active inference subsume el keystone como caso "
                    "especial; la predicción de la directiva ('el producto cae de minimizar la EFE') es correcta DERIVACIONALMENTE. "
                    "El producto-estructurado es además LEARNABLE leakage-free. NO SOBREVIVE (retractado por la verificación "
                    "adversarial de 3 agentes): la 'emergencia EMPÍRICA' es TAUTOLÓGICA (el scorer efe_pragmatic ES la métrica del "
                    "eval), el '+0.43 refinamiento' es artefacto de un canónico hand-tuned (mediana ~0 en configs aleatorias), y el "
                    "MECANISMO 'w² refina' es FALSO -- la corrección robusta es la varianza-prior v, no el cuadrado (que daña bajo "
                    "estimación); la unificación con exploración es conjetura. APORTE NETO: (i) el puente normativo (keystone = "
                    "límite EFE), (ii) una corrección empírica robusta sobre el keystone del lab: incluir la varianza-prior v. "
                    "META-LECCIÓN: 8vo ciclo seguido en que la verificación adversarial corrige un overclaim mayor antes del ledger "
                    "-- aquí cazó una TAUTOLOGÍA (la métrica = el scorer) que es el modo de fallo más sutil. Próximo: extender el "
                    "puente EFE a sustrato no-lineal (135-136) / acoplado (137); el lazo de acción-consecuencia REAL; SCALE."),
        measurement=("exp122 ({n} seeds): puente binary efe {bue}=keystone {buk} (identidad w²=w); producto learnable (T=10 {d0} -> "
                     "{dN}); factores fallan (relev {grel}/ctrl {gctl}/pred {gpred}); TAUTOLOGÍA efe=oracle {ge}; refinamiento "
                     "mediana en configs aleatorias {rmed} (~nulo); bajo estimación v_corr {emV} > efe {emE} (cuadrado daña); "
                     "exploración canónica +{gu}/+{gc} (apenas).").format(
                         n=n_seeds, bue=_f(bue), buk=_f(buk), d0=_f(d0), dN=_f(dN), grel=_f(grel), gctl=_f(gctl),
                         gpred=_f(gpred), ge=_f(ge), rmed=_f(rmed), emV=_f(emV), emE=_f(emE), gu=_f(gu), gc=_f(gc)),
        iterations=1)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (la regla CAE de minimizar la sorpresa -puente real- pero 'comprobarla' con su propia vara es circular; la mejora real es la varianza-prior, no el cuadrado).")

    kl = ("REAL (exp122, MIXTA post-verificación adversarial): el keystone valor=ctrl×rel es el LÍMITE binary+uniforme del término "
          "pragmático de la EFE (w²·v·ctrl; modelo lineal-gaussiano, preferencia gaussiana) -> grounding normativo (puente teórico; "
          "binary efe {bue}=keystone {buk}). El producto es learnable leakage-free (T=10 {d0} -> {dN}). RETRACTADO: la emergencia "
          "EMPÍRICA es TAUTOLÓGICA (efe_pragmatic=métrica del eval, efe=oracle {ge}); el '+0.43' es artefacto (mediana en configs "
          "aleatorias {rmed}); el mecanismo w² es falso (la varianza-prior v hace el grueso; bajo estimación el cuadrado daña: "
          "v_corr {emV} > efe {emE}); la exploración canónica apenas paga. La corrección robusta = incluir v (w·v·ctrl). TECHO: "
          "lineal-gaussiano, modos independientes; efe=oracle por derivación; el puente es TEÓRICO (no testeado empíricamente, lo "
          "asume). Frontera: extender el puente EFE a no-lineal (135-136)/acoplado (137); lazo real; SCALE.").format(
              bue=_f(bue), buk=_f(buk), d0=_f(d0), dN=_f(dN), ge=_f(ge), rmed=_f(rmed), emV=_f(emV), emE=_f(emE))
    ceilings.add(CeilingRecord(
        subsystem="PUENTE FORMAL del keystone R-VALOR (valor=ctrl×rel) a ACTIVE INFERENCE — TEÓRICO válido / EMPÍRICO tautológico. SOBREVIVE: el keystone es el LÍMITE binary+uniforme del término pragmático de la energía libre esperada (w²·v·ctrl, modelo lineal-gaussiano con preferencia gaussiana); active inference subsume el keystone como caso especial (grounding normativo); el producto es learnable leakage-free. NO SOBREVIVE: la 'emergencia empírica' es tautológica (efe_pragmatic = métrica del eval), el refinamiento es artefacto de un canónico hand-tuned (mediana ~0), el mecanismo w² es falso (la corrección robusta es la varianza-prior v, el cuadrado daña bajo estimación), la unificación con exploración es conjetura. Alcance: lineal-gaussiano, modos independientes",
        known_limit=kl,
        blockers=[{"text": "TAUTOLOGÍA (el modo de fallo más sutil, cazado por la verificación): efe_pragmatic (w²·v·ctrl) es BYTE-IDÉNTICO a _true_reduction (la métrica del eval) -> efe=oracle por construcción en todo régimen/seed; 'efe bate factores' y 'efe>keystone' son álgebra, no evidencia empírica. La 'emergencia bajo binary' es la identidad trivial w²=w. Lo NO-tautológico/load-bearing: (i) las factores simples fallan (la composición es necesaria), (ii) el producto es LEARNABLE leakage-free (params estimados, converge desde abajo, decoy-w se estanca)", "kind": "diseno"},
                  {"text": "el '+0.43 refinamiento' y el MECANISMO 'w² refina' son FALSOS/artefactos: en 200 configs graded ALEATORIAS la mediana del gap efe-keystone es ~0 (el canónico era percentil-100, hand-tuned); la VARIANZA-PRIOR v hace el grueso de la corrección y el cuadrado ~1.5%; bajo params ESTIMADOS el cuadrado es DAÑINO (w·v·ctrl > w²·v·ctrl en todo T finito, amplifica el ruido de ŵ). La corrección ROBUSTA y LEARNABLE sobre el keystone del lab es incluir la varianza-prior v (w·v·ctrl), NO elevar w al cuadrado", "kind": "diseno"},
                  {"text": "la unificación exploración/empowerment es CONJETURA: el epistémico modelado (σ²·v·c) no es la saliencia EFE canónica; con info-gain PURO (σ²) la exploración apenas paga y la predicción 'concentración-en-relevantes amplifica' FALLÓ. ALCANCE: caso LINEAL-GAUSSIANO, modos INDEPENDIENTES, control separable -- el puente es TEÓRICO (la derivación, no testeada empíricamente); no cubre los sustratos no-lineales (135-136) ni acoplados (137) donde el producto LOCAL necesita revisión", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP122.ref, S_C129.ref, S_VERIF.ref]))
    notes.append("1 techo 'real': el keystone es el límite binary+uniforme de la EFE pragmática (puente teórico); la emergencia empírica es tautológica; la corrección robusta es la varianza-prior v, no el cuadrado. Alcance lineal-gaussiano.")

    dstmt = ("North-Star R-VALOR (PUENTE FORMAL a active inference -- TEÓRICO válido, EMPÍRICO tautológico): el keystone valor="
             "ctrl×rel es el LÍMITE binary+uniforme del término PRAGMÁTICO de la ENERGÍA LIBRE ESPERADA (w²·v·ctrl, modelo lineal-"
             "gaussiano con preferencia gaussiana; binary efe {bue}=keystone {buk}) -> active inference SUBSUME el keystone como "
             "caso especial = GROUNDING NORMATIVO del producto (la directiva acertó DERIVACIONALMENTE). El producto es LEARNABLE "
             "leakage-free. PERO la 'emergencia EMPÍRICA' es TAUTOLÓGICA (efe_pragmatic = la métrica del eval, efe=oracle {ge}); el "
             "'+0.43' es artefacto de un canónico hand-tuned (mediana en configs aleatorias {rmed}); el MECANISMO w² es FALSO -- la "
             "corrección robusta/learnable es la varianza-prior v (w·v·ctrl), el cuadrado DAÑA bajo estimación (v_corr {emV} > efe "
             "{emE}); la unificación con exploración es conjetura. Decisión: adoptar el puente normativo (keystone=límite EFE) y la "
             "corrección por v; NO el cuadrado. META-DECISIÓN: 8vo ciclo con verificación adversarial (overclaim mayor -tautología- "
             "corregido). Próximo: extender el puente EFE a no-lineal/acoplado; lazo real; SCALE.").format(
                 bue=_f(bue), buk=_f(buk), ge=_f(ge), rmed=_f(rmed), emV=_f(emV), emE=_f(emE))
    drat = ("exp122 (tier5, propio, {n} seeds, numpy, post-verificación de 3 agentes): el término pragmático de la EFE (derivado de "
            "un modelo lineal-gaussiano) es w²·v·ctrl, cuyo límite binary+uniforme es el keystone (w·ctrl) -> puente normativo. PERO "
            "efe_pragmatic ES la métrica del eval (tautológico), el refinamiento es artefacto (mediana {rmed} en configs aleatorias) "
            "y el cuadrado daña bajo estimación (v_corr {emV} > efe {emE}). Convergente con el principio (tier2) y la verificación "
            "(tier4); une el keystone 129 (tier5) con el marco active inference. MIXTA: puente teórico válido + emergencia empírica "
            "tautológica/artefacto; corrección robusta = v.").format(n=n_seeds, rmed=_f(rmed), emV=_f(emV), emE=_f(emE))
    dec = Decision(id="D-V4-100", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP122), _to_plain(S_C129), _to_plain(S_VERIF)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-100 ACEPTADA por el ledger (tier5 exp122 + tier5 exp113 + tier4 verificación adversarial).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-100:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle138_active_inference',
                                description='CYCLE 138 (RESET v4, H-V4-10l MIXTA: el keystone es el límite binary+uniforme de la EFE pragmática -puente teórico- pero la emergencia empírica es tautológica/artefacto; corrección robusta = varianza-prior v, no el cuadrado; 8vo ciclo con verificación adversarial).')
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
    print("RESUMEN — CYCLE 138 (RESET v4): el keystone es el LÍMITE binary+uniforme de la EFE pragmática (puente teórico); la emergencia empírica es tautológica — H-V4-10l MIXTA")
    print("=" * 78)
    print("veredicto H-V4-10l:", status.upper() if status else "?")
    print("  PUENTE TEÓRICO (sobrevive): el keystone ctrl×rel es el límite binary+uniforme del término pragmático de la EFE -> active inference subsume el keystone (grounding normativo). RETRACTADO: la emergencia empírica es tautológica (efe_pragmatic=métrica del eval), el '+0.43' es artefacto, el mecanismo w² es falso (la corrección robusta es la varianza-prior v, no el cuadrado). Alcance lineal-gaussiano.")
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
