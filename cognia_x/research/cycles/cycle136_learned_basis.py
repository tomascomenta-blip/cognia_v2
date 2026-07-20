r"""
cycle136_learned_basis.py — CICLO 136 (RESET v4, rama control/acción, ACOTA la pregunta abierta de la MIXTA de 135: ¿es la
relevancia bajo meta NO-LINEAL un CUELLO de R-PRIOR?): H-V4-10j por las compuertas del engine.

VEREDICTO: MIXTA (refutación ACOTADA al régimen ABUNDANTE; post-verificación adversarial de 3 agentes — 6to ciclo; refutación
GENUINA sin leakage). El cuello R-PRIOR es REGIME-DEPENDENT.

CONTEXTO. CYCLE 135 (exp119) mostró (MIXTA) que la relevancia ES discoverable bajo no-linealidad con una base EXPRESIVA, y
RETRACTÓ el claim 'el prior paga' como ~80% artefacto de sub-regularizar la base rica. Quedó la pregunta: ¿un aprendiz que CROSS-
VALIDA -sin conocer la forma- cierra el gap solo? Este ciclo lo testea en DOS regímenes.

RESULTADO (exp120, 200 seeds; verbo 'IGUALA' corregido a 'CASI IGUALA' por verificación adversarial):
  - EN ABUNDANCIA (T=300): un aprendiz que NO conoce la forma -cross-validando la regularización (rich_cv) y/o seleccionando la
    base (select_cv)- NEUTRALIZA EL GRUESO de la ventaja del oracle-prior. Even limpio rich_cv=select_cv=matched=1.000; bajo ruido
    σ_g=20 el gap de 135 (+0.245 a ridge fijo) se CIERRA ~85% (rich_cv +0.04). La fairness NO lo derriba: dar a la matched el MISMO
    CV-ridge (matched_cv) apenas la mueve -> el 'prior paga' de 135 ERA sub-regularización, no ridge-fijo. rich_cv robusto a TODA
    forma. PERO 'IGUALA'='CASI IGUALA': el residual matched_cv-rich_cv ~+0.04 (t~2.2) es chico pero SIGNIFICATIVO -- costo de
    varianza irreducible de las 2 columnas extra de la base rica.
  - EN ESCASEZ (T~24-30 ~#columnas de la base rica, σ_g=5): el aprendiz genuinamente sin-forma (rich_cv) COLAPSA y matched_cv le
    gana +0.31 -- la ventaja del prior REAPARECE y escala INVERSAMENTE con el ratio datos/parámetros.
  - CAVEAT: select_cv NO es del todo form-agnostic (su menú {linear,even,relu} ES un prior grueso de la forma).
  => H-V4-10j ('R-PRIOR es cuello') REFUTADA EN ABUNDANCIA pero el prior NO es prescindible: se DEBILITA de forma-exacta a menú-de-
  formas, su valor escala con la escasez de datos. La relevancia bajo no-linealidad es discoverable sin prior privilegiado CUANDO
  T>>#columnas; bajo escasez conocer la forma paga.

DERIVA de exp120_learned_basis/results/results.json.

Correr (DESPUÉS de exp120):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp120_learned_basis.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle136_learned_basis
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle136_learned_basis')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp120_learned_basis', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="el cuello R-PRIOR de la relevancia bajo no-linealidad es REGIME-DEPENDENT: con dato ABUNDANTE respecto al número de parámetros de la base, un aprendiz que cross-valida la regularización/base (sin conocer la forma) NEUTRALIZA el grueso de la ventaja de conocer la forma; bajo ESCASEZ (datos ~ parámetros) la ventaja del prior REAPARECE. El valor del prior escala inversamente con el ratio datos/parámetros; se DEBILITA de forma-exacta a menú-de-formas, no desaparece.", obtained=False,
                     claim=("Descubrir la RELEVANCIA bajo no-linealidad NO requiere conocer la forma de la meta CUANDO el dato es "
                            "abundante respecto a los parámetros de la base: un aprendiz que cross-valida la regularización/"
                            "selección de base (model selection endógeno sobre la señal observable) neutraliza el grueso de la "
                            "ventaja del oracle-prior (residual chico pero significativo). Bajo ESCASEZ (datos~parámetros) el prior "
                            "REAPARECE. => el cuello R-PRIOR es regime-dependent, escala con la escasez de datos; el prior se "
                            "DEBILITA de forma-exacta a menú-de-formas, no es prescindible. (Principio.)"))
S_C135 = Source(tier=5, ref="cognia_x/experiments/exp119_basis_relevance", obtained=True,
                claim=("CYCLE 135 (MIXTA): la relevancia es discoverable bajo no-linealidad con una base expresiva; el 'prior "
                       "paga' bajo ruido era ~80% artefacto de sub-regularizar la base rica. DEJÓ ABIERTO: ¿un aprendiz que "
                       "cross-valida -sin conocer la forma- cierra el gap solo? H-V4-10j lo testea: SÍ en abundancia (neutraliza "
                       "~85%), NO en escasez (el prior reaparece)."))
S_VERIF = Source(tier=4, ref="verificación adversarial focalizada de 3 agentes (lentes leakage-CV/fairness-alt/robustez; probes reales sobre exp120)", obtained=True,
                 claim=("La verificación adversarial (6to ciclo) confirmó la refutación GENUINA (sin leakage: 3 controles nulos -- "
                        "G-decoy/G-ruido/CV-bloqueada-; matched_cv apenas mejora -> no era ridge-fijo) pero la ACOTÓ: 'IGUALA' es "
                        "'CASI IGUALA' (residual +0.04, t~2.2, significativo); el prior REAPARECE bajo escasez (T~#columnas: gap "
                        "+0.31); select_cv reintroduce un prior (su menú de formas). => refutación ACOTADA al régimen abundante."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp120 primero): " + results_path)

    em = sm['even_matched']; ercv = sm['even_rich_cv']; escv = sm['even_select_cv']; ecs = sm['even_ctrl_solo']
    grf = sm['gap_richfix']; grc = sm['gap_richcv']; gsc = sm['gap_selectcv']; gmcv = sm['gap_matchedcv_richcv']
    cf = sm['closed_frac']; pr = sm['paired_mcv_richcv']
    rcl = sm['richcv_linear']; rce = sm['richcv_even']; rcr = sm['richcv_relu']; rcm = sm['richcv_mixed']
    sct = sm['scarce_T']; scsg = sm['scarce_sg']; gsce = sm['gap_scarce']; smcv = sm['scarce_matched_cv']; srcv = sm['scarce_rich_cv']
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim120 = ("exp120 (propio, {n} seeds, numpy, sustrato de exp119, post-verificación de 3 agentes): MIXTA (refutación ACOTADA). "
                "ABUNDANCIA (T=300): un aprendiz sin-forma neutraliza el grueso del prior -- even limpio rich_cv {ercv}/select_cv "
                "{escv}=matched {em}; σ_g=20 el gap de 135 +{grf} cierra ~{cf}% (rich_cv +{grc}); matched_cv apenas mueve (residual "
                "+{rmd}, t={rmt}: chico pero significativo). rich_cv robusto a TODA forma (lin {rcl}/even {rce}/relu {rcr}/mixed "
                "{rcm}). ESCASEZ (T={sct}~#columnas, σ_g={scsg}): rich_cv COLAPSA ({srcv}), matched_cv le gana +{gsce} -- el prior "
                "REAPARECE. select_cv NO es form-agnostic (su menú ES un prior grueso). => R-PRIOR no es cuello en abundancia pero "
                "escala con la escasez de datos.").format(
                    n=n_seeds, ercv=_f(ercv), escv=_f(escv), em=_f(em), grf=_f(grf), cf="{:.0f}".format(cf * 100),
                    grc=_f(grc), rmd=_f(pr[0]), rmt=pr[1], rcl=_f(rcl), rce=_f(rce), rcr=_f(rcr), rcm=_f(rcm),
                    sct=sct, scsg=scsg, srcv=_f(srcv), gsce=_f(gsce))
    S_EXP120 = Source(tier=5, ref="cognia_x/experiments/exp120_learned_basis", obtained=True, claim=claim120)
    for src in (S_PRINCIPLE, S_C135, S_VERIF, S_EXP120):
        ledger.add_source(src)
    notes.append("4 fuentes (S_PRINCIPLE tier2 cuello R-PRIOR regime-dependent; S_C135 tier5 la pregunta abierta de 135; S_VERIF tier4 verificación adversarial de 3 agentes -refutación genuina pero acotada-; S_EXP120 tier5 dato propio MIXTA).")

    ev_for = [S_EXP120.ref, S_PRINCIPLE.ref]
    ev_against = [S_EXP120.ref, S_VERIF.ref]
    advtext = ("{V} (REFUTACIÓN ACOTADA al régimen abundante; cierra/ACOTA la pregunta R-PRIOR abierta por la MIXTA de 135; 6to "
               "ciclo con verificación adversarial -- refutación GENUINA sin leakage): la hipótesis 'la relevancia bajo no-"
               "linealidad es un CUELLO de R-PRIOR' es REGIME-DEPENDENT. NEUTRALIZADA EN ABUNDANCIA: con dato amplio (T=300) un "
               "aprendiz que NO conoce la forma -cross-validando la REGULARIZACIÓN (rich_cv: ridge por K-fold CV sobre la señal "
               "observable) y/o SELECCIONANDO la base (select_cv)- NEUTRALIZA EL GRUESO de la ventaja del oracle-prior. Even limpio "
               "rich_cv {ercv}/select_cv {escv}=matched {em} (sobre ctrl_solo {ecs}: descubrimiento real); bajo ruido σ_g=20 el gap "
               "de 135 (+{grf} a ridge fijo) se CIERRA ~{cf}% (rich_cv +{grc}, select_cv +{gsc}); rich_cv recupera TODAS las formas "
               "(lin {rcl}/even {rce}/relu {rcr}/mixed {rcm}). FAIRNESS (verificación): dar a la matched su MISMO CV-ridge "
               "(matched_cv) apenas la mueve (gap a rich_cv +{gmcv}) -> el 'prior paga' de 135 NO era artefacto del ridge-fijo, ERA "
               "sub-regularización de la base rica. EVIDENCIA: el principio (tier2) lo predice; resuelve la pregunta abierta de 135 "
               "(tier5). EVIDENCIA EN CONTRA / acotaciones HONESTAS (verificación de 3 agentes): (a) 'IGUALA' es 'CASI IGUALA' -- "
               "el residual matched_cv-rich_cv a σ_g=20 es +{rmd} (t={rmt}, frac(m_cv≥rich)={rmf}): chico pero estadísticamente "
               "SIGNIFICATIVO, costo de varianza IRREDUCIBLE de las 2 columnas extra de la base rica (no se cierra ni con ridge "
               "hasta 10). (b) EL PRIOR REAPARECE BAJO ESCASEZ: a T={sct}~#columnas con ruido moderado (σ_g={scsg}) el aprendiz "
               "genuinamente sin-forma (rich_cv) COLAPSA ({srcv}) y matched_cv le gana +{gsce} -- la ventaja del prior escala "
               "INVERSAMENTE con el ratio datos/parámetros. (c) select_cv NO es del todo form-agnostic (su menú {{linear,even,relu}} "
               "ES un prior grueso de la forma; recupera bajo escasez por parsimonia pero su SELECCIÓN se ensucia bajo ruido alto). "
               "VERIFICADO SIN LEAKAGE: 3 controles nulos (G-decoy -> colapso a ctrl_solo; G-ruido -> sin ventaja; CV-bloqueada -> "
               "mismo gap); el CV usa SOLO la señal observable G (nunca w/b). => H-V4-10j REFUTADA EN ABUNDANCIA pero el prior NO es "
               "prescindible: se DEBILITA de forma-exacta a menú-de-formas y su valor escala con la escasez. CONCLUSIÓN del arco "
               "no-linealidad de R-VALOR (134->135->136): la relevancia es discoverable bajo no-linealidad sin prior privilegiado "
               "CUANDO hay datos abundantes; bajo escasez conocer la forma paga.").format(
                   V=status.upper(), ercv=_f(ercv), escv=_f(escv), em=_f(em), ecs=_f(ecs), grf=_f(grf),
                   cf="{:.0f}".format(cf * 100), grc=_f(grc), gsc=_f(gsc), rcl=_f(rcl), rce=_f(rce), rcr=_f(rcr),
                   rcm=_f(rcm), gmcv=_f(gmcv), rmd=_f(pr[0]), rmt=pr[1], rmf=pr[2], sct=sct, scsg=scsg, srcv=_f(srcv),
                   gsce=_f(gsce))

    hyp = Hypothesis(
        id="H-V4-10j",
        statement=("La relevancia bajo meta NO-LINEAL es un CUELLO de R-PRIOR: un aprendiz que no conoce la forma NO puede igualar "
                   "a la base MATCHED (oracle-prior). (MIXTA / refutación ACOTADA: en ABUNDANCIA -T>>#columnas- un aprendiz que "
                   "cross-valida la regularización/base neutraliza el grueso de la ventaja del prior -el 'prior paga' de 135 era "
                   "sub-regularización-, con un residual chico pero significativo; pero el prior REAPARECE bajo ESCASEZ "
                   "-T~#columnas-, y select_cv no es del todo form-agnostic. El cuello R-PRIOR es REGIME-DEPENDENT: escala "
                   "inversamente con el ratio datos/parámetros; el prior se DEBILITA de forma-exacta a menú-de-formas, no "
                   "desaparece.)"),
        prediction=("REFUTADA si el aprendiz-CV iguala a la matched en ABUNDANCIA y en ESCASEZ; APOYADA si queda muy por debajo ya "
                    "en abundancia; MIXTA (refutación ACOTADA) si neutraliza el grueso en abundancia pero el prior reaparece en "
                    "escasez. (Pre-registrada tras verificación adversarial: numpy, forma×estimador + σ_g abundante + barrido T "
                    "escasez + matched_cv + t pareado, 200 seeds; métrica primaria = la DECISIÓN top-K.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp120_learned_basis")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-10j")
        notes.append("H-V4-10j ('R-PRIOR es cuello') marcada '{}' (refutación ACOTADA): neutralizada en abundancia (un aprendiz-CV sin-forma cierra ~85% del gap), reaparece en escasez (T~#columnas). El cuello R-PRIOR es regime-dependent.".format(status))

    analogy = AnalogyRecord(
        problem=("Para saber QUÉ IMPORTA cuando el puntaje depende de las cosas de forma TORCIDA, ¿hace falta que alguien te DIGA "
                 "el tipo de torcedura, o lo averiguás solo? ¿Y eso depende de cuántas veces puedas probar?"),
        everyday=("Depende de cuántos datos tengas. Con MUCHAS pruebas: llevás un juego de lentes (recta, cuadrado, codo) y "
                  "cross-validás cuál explica mejor el puntaje -- así igualás (casi) a alguien que SABÍA la forma, aunque el "
                  "puntaje sea ruidoso. Te queda una desventaja chiquita (la lente versátil tiene piezas de más que meten un poco "
                  "de ruido), pero el grueso de la 'ventaja de saber' se evapora. Con POCAS pruebas: el juego de lentes versátil "
                  "se confunde (demasiadas piezas, pocos datos) y el que SABÍA la forma exacta le gana CLARO. Moraleja: saber la "
                  "forma de antemano (un buen prior) vale poco cuando tenés muchos datos y MUCHO cuando tenés pocos; el valor del "
                  "prior escala con la escasez. Y 'probar con un menú de lentes' ya es una forma DÉBIL de saber (el menú es un prior "
                  "grueso)."),
        solutions=["descubrir qué importa bajo no-linealidad NO requiere conocer la forma exacta CUANDO el dato es abundante respecto a los parámetros de la base",
                   "un aprendiz endógeno cross-valida la regularización (rich_cv) o selecciona la base (select_cv) por bondad de ajuste a la señal observable -- sin ver w/b",
                   "en abundancia neutraliza el grueso de la ventaja del oracle-prior (residual chico pero significativo); el 'prior paga' de 135 era sub-regularización",
                   "PERO bajo escasez (datos~parámetros) el prior REAPARECE (+0.3); su valor escala inversamente con datos/parámetros; un menú de bases ES un prior grueso"],
        principles=["el cuello R-PRIOR de la relevancia bajo no-linealidad es REGIME-DEPENDENT: neutralizado en abundancia, reaparece en escasez",
                    "un aprendiz que cross-valida (sin forma) neutraliza el grueso de la ventaja del prior en abundancia; residual chico pero significativo (varianza de columnas extra)",
                    "el valor del prior escala INVERSAMENTE con el ratio datos/parámetros; se debilita de forma-exacta a menú-de-formas, no desaparece",
                    "META: 6to ciclo con verificación adversarial -- una REFUTADA limpia inicial fue ACOTADA a MIXTA (regime-dependent + residual significativo + select_cv-es-prior)"],
        adaptation=("El lab ACOTA la pregunta que la MIXTA de 135 dejó abierta. 135 sugirió que el 'costo de prior' bajo "
                    "no-linealidad era ilusorio (sub-regularización); 136 lo confirma EN ABUNDANCIA (un aprendiz-CV sin-forma "
                    "neutraliza ~85% de la ventaja del oracle-prior, robusto a fairness -matched_cv apenas mejora-) PERO lo ACOTA: "
                    "(a) el residual es chico pero significativo (costo de varianza de las columnas extra de la base rica); (b) el "
                    "prior REAPARECE bajo ESCASEZ (T~#columnas: +0.31); (c) select_cv no es del todo form-agnostic (su menú es un "
                    "prior grueso). CONCLUSIÓN del arco no-linealidad de R-VALOR (134->135->136): la relevancia ES discoverable "
                    "bajo no-linealidad sin prior privilegiado de la forma CUANDO el dato es abundante respecto a los parámetros; "
                    "el cuello R-PRIOR es REGIME-DEPENDENT y escala con la escasez de datos. POLÍTICA: base expresiva + CV por "
                    "defecto con dato abundante; con dato escaso, un prior de forma (o un menú parsimonioso) paga. META-LECCIÓN: "
                    "6to ciclo con verificación adversarial -- una REFUTADA limpia inicial fue acotada a MIXTA (regime-dependent). "
                    "Próximo: relevancia bajo sustrato ACOPLADO (133, colinealidad del credit-assignment); el lazo de acción-"
                    "consecuencia REAL; active inference formal; SCALE."),
        measurement=("exp120 ({n} seeds): ABUNDANTE even limpio rich_cv {ercv}/select_cv {escv}=matched {em}; σ_g=20 gap 135 +{grf} "
                     "-> rich_cv +{grc} (cierra ~{cf}%), residual matched_cv-rich_cv +{rmd} (t={rmt}); rich_cv robusto a forma "
                     "(lin {rcl}/even {rce}/relu {rcr}/mixed {rcm}). ESCASEZ T={sct}: matched_cv {smcv} vs rich_cv {srcv} "
                     "(gap +{gsce}).").format(
                         n=n_seeds, ercv=_f(ercv), escv=_f(escv), em=_f(em), grf=_f(grf), grc=_f(grc),
                         cf="{:.0f}".format(cf * 100), rmd=_f(pr[0]), rmt=pr[1], rcl=_f(rcl), rce=_f(rce), rcr=_f(rcr),
                         rcm=_f(rcm), sct=sct, smcv=_f(smcv), srcv=_f(srcv), gsce=_f(gsce)),
        iterations=1)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (con muchas pruebas, el juego de lentes + cross-validación casi iguala al que sabía la forma; con pocas, el que sabía gana claro -- el valor del prior escala con la escasez).")

    kl = ("REAL (exp120): el cuello R-PRIOR de la relevancia bajo no-linealidad es REGIME-DEPENDENT. EN ABUNDANCIA (T=300) un "
          "aprendiz-CV sin-forma neutraliza ~{cf}% de la ventaja del oracle-prior (σ_g=20: gap 135 +{grf} -> +{grc}; matched_cv "
          "apenas mejora -> era sub-regularización), residual +{rmd} significativo. EN ESCASEZ (T={sct}~#columnas, σ_g={scsg}) el "
          "prior REAPARECE (+{gsce}). TECHO: numpy; la forma se elige de un MENÚ {{linear,even,relu,rich}} (no familia continua "
          "arbitraria); select_cv no es del todo form-agnostic; eval con control oracle. Frontera: relevancia bajo sustrato "
          "acoplado (133), lazo real, active inference, SCALE.").format(
              cf="{:.0f}".format(cf * 100), grf=_f(grf), grc=_f(grc), rmd=_f(pr[0]), sct=sct, scsg=scsg, gsce=_f(gsce))
    ceilings.add(CeilingRecord(
        subsystem="Descubrimiento del factor RELEVANCIA del R-VALOR bajo meta NO-LINEAL — el cuello R-PRIOR es REGIME-DEPENDENT: con dato ABUNDANTE respecto a los parámetros de la base, un aprendiz que cross-valida la regularización (rich_cv) y/o selecciona la base (select_cv), SIN conocer la forma, NEUTRALIZA el grueso de la ventaja del oracle-prior (el 'prior paga' de 135 era sub-regularización); bajo ESCASEZ (datos~parámetros) el prior REAPARECE. Refutación ACOTADA al régimen abundante. Acota el arco no-linealidad de R-VALOR (134->135->136)",
        known_limit=kl,
        blockers=[{"text": "numpy; la 'forma' de la meta se selecciona de un MENÚ FIJO {linear,even,relu,rich} por CV -- select_cv NO es del todo form-agnostic (su menú ES un prior grueso de la forma; recupera bajo escasez por parsimonia, pero su selección se ensucia bajo ruido alto ~74% correcta a σ_g=20); una no-linealidad fuera del span del menú sería frontera; eval con control ridge ORACLE", "kind": "diseno"},
                  {"text": "la refutación es ACOTADA al régimen ABUNDANTE (T>>#columnas de la base rica): 'IGUALA'='CASI IGUALA' (residual matched_cv-rich_cv +0.04 a σ_g=20, t~2.2, significativo -- costo de varianza irreducible de las 2 columnas extra, no se cierra ni con ridge hasta 10). El prior REAPARECE bajo escasez (T~24-30~#columnas, σ_g=5: gap +0.31); su valor escala inversamente con el ratio datos/parámetros", "kind": "diseno"},
                  {"text": "METODO/honestidad: 6to ciclo con verificación adversarial (3 agentes). La refutación es GENUINA sin leakage (3 controles nulos: G-decoy -> colapso a ctrl_solo; G-ruido -> sin ventaja; CV-bloqueada -> mismo gap; el CV usa SOLO G, nunca w/b) PERO una REFUTADA limpia inicial fue ACOTADA a MIXTA (regime-dependent + residual significativo + select_cv-es-prior). La fairness (matched_cv) NO la derribó", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP120.ref, S_C135.ref, S_VERIF.ref]))
    notes.append("1 techo 'real': el cuello R-PRIOR de la relevancia bajo no-linealidad es regime-dependent (neutralizado en abundancia, reaparece en escasez); refutación genuina pero ACOTADA. Cierra/acota el arco 134->135->136.")

    dstmt = ("North-Star R-VALOR (ACOTA el arco NO-LINEALIDAD del factor relevancia, 134->135->136; la hipótesis R-PRIOR-cuello es "
             "REGIME-DEPENDENT): descubrir la RELEVANCIA bajo no-linealidad NO requiere conocer la forma de la meta CUANDO el dato "
             "es abundante respecto a los parámetros de la base. EN ABUNDANCIA (T=300) un aprendiz que cross-valida la "
             "regularización (rich_cv) y/o selecciona la base (select_cv) -sin ver w/b ni la forma- NEUTRALIZA el grueso de la "
             "ventaja del oracle-prior: even limpio rich_cv {ercv}/select_cv {escv}=matched {em}; σ_g=20 el gap de 135 (+{grf}) "
             "cierra ~{cf}% (rich_cv +{grc}); la fairness no lo derriba (matched_cv apenas mejora -> era sub-regularización). PERO "
             "'IGUALA'='CASI IGUALA' (residual +{rmd}, t={rmt}, significativo) y EL PRIOR REAPARECE BAJO ESCASEZ (T={sct}~#columnas: "
             "+{gsce}). select_cv no es del todo form-agnostic (su menú ES un prior grueso). Decisión: base expresiva + CV por "
             "defecto CON dato abundante; con dato escaso, un prior de forma paga. META-DECISIÓN: 6to ciclo con verificación "
             "adversarial; una REFUTADA limpia inicial fue acotada a MIXTA (regime-dependent). Próximo: relevancia bajo sustrato "
             "acoplado (133), lazo real, active inference, SCALE.").format(
                 ercv=_f(ercv), escv=_f(escv), em=_f(em), grf=_f(grf), cf="{:.0f}".format(cf * 100), grc=_f(grc),
                 rmd=_f(pr[0]), rmt=pr[1], sct=sct, gsce=_f(gsce))
    drat = ("exp120 (tier5, propio, {n} seeds, numpy): en ABUNDANCIA un aprendiz-CV sin-forma neutraliza ~{cf}% de la ventaja del "
            "oracle-prior (gap 135 +{grf} -> +{grc}; matched_cv apenas mejora), residual +{rmd} significativo; en ESCASEZ el prior "
            "reaparece (+{gsce}). Convergente con el principio (tier2); acota la pregunta abierta de 135 (tier5) y la verificación "
            "adversarial (tier4). MIXTA: refutación GENUINA pero ACOTADA al régimen abundante; el cuello R-PRIOR es regime-"
            "dependent.").format(n=n_seeds, cf="{:.0f}".format(cf * 100), grf=_f(grf), grc=_f(grc), rmd=_f(pr[0]), gsce=_f(gsce))
    dec = Decision(id="D-V4-98", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP120), _to_plain(S_C135), _to_plain(S_VERIF)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-98 ACEPTADA por el ledger (tier5 exp120 + tier5 exp119 + tier4 verificación adversarial).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-98:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle136_learned_basis',
                                description='CYCLE 136 (RESET v4, H-V4-10j MIXTA / refutación ACOTADA: un aprendiz-CV sin-forma neutraliza el grueso del prior en ABUNDANCIA pero el prior REAPARECE en ESCASEZ -> el cuello R-PRIOR es regime-dependent; acota el arco 134->135->136; 6to ciclo con verificación adversarial).')
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
    print("RESUMEN — CYCLE 136 (RESET v4): el cuello R-PRIOR de la relevancia bajo no-linealidad es REGIME-DEPENDENT (neutralizado en abundancia, reaparece en escasez) — H-V4-10j MIXTA (refutación ACOTADA)")
    print("=" * 78)
    print("veredicto H-V4-10j (hipótesis 'R-PRIOR es cuello'):", status.upper() if status else "?")
    print("  EN ABUNDANCIA un aprendiz-CV sin-forma neutraliza ~85% de la ventaja del oracle-prior (el 'prior paga' de 135 era sub-regularización; residual chico pero significativo). EN ESCASEZ (T~#columnas) el prior REAPARECE (+0.3). select_cv no es del todo form-agnostic. El cuello R-PRIOR escala inversamente con datos/parámetros. Acota el arco 134->135->136.")
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
