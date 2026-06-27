r"""
cycle146_inductive_bias.py — CICLO 146 (RESET v4, PIVOTE fuera de la vena keystone/capacidad saturada): H-V4-10r por las compuertas
del engine. Pregunta DISTINTA y central al North Star ("¿un sistema CONSTRUYE una función de valor endógena?"): ¿es la estructura
PRODUCTO ctrl×rel un SESGO INDUCTIVO ÚTIL para un APRENDIZ que ESTIMA el valor desde experiencia ESCASA?

VEREDICTO: MIXTA (núcleo del ESTIMADOR robusto + RE-ACOTADO BIDIRECCIONALMENTE por verificación adversarial de 2 agentes; 16mo
ciclo). El experimento AUTO-DOCUMENTA.

NÚCLEO (robusto en λ-justo/δ/noise/grado/seeds): bajo ESCASEZ el aprendiz ESTRUCTURADO (asume w·ctrl, 2 params) tiene MENOR MSE de
test que el FLEXIBLE (polinomio grado-3, sobreajusta) y los separables (sin producto); FLEX lo alcanza bajo abundancia
(bias-variance); la MINIMALIDAD es load-bearing (FLEX con λ óptimo sigue ~3x peor; no es artefacto de regularización).

RE-ACOTADO (la verificación bajó de APOYADA a MIXTA):
  (1) CONDICIONAL a la ALINEACIÓN-CON-EL-PRODUCTO (caveat estándar de sesgo inductivo 'ayuda sólo si matchea'): con misespecificación
      ORTOGONAL al producto STRUCT es el PEOR en TODOS los N.
  (2) la 'anti-tautología' es DÉBIL: la misespecificación 'prod2' δ·(w·c)² está ~0.95 colineal con la única feature de STRUCT.
  (3) la DECISIÓN está CONFUNDIDA: el top-K perfecto es la SUFICIENCIA de w·c para el orden (v_true monótona en w·c), no robustez;
      en pairwise STRUCT gana bajo escasez con prod2 PERO colapsa con ortogonal.

=> el keystone ES un sesgo inductivo útil (minimalidad+producto) para ESTIMAR el valor bajo escasez CUANDO el valor está alineado con
el producto (no free lunch); con residuo ortogonal el prior HUNDE al estimador. MIXTA EXITOSA: la verificación cazó el over-framing
anti-tautología, la mis-caracterización de la decisión (suficiencia, no robustez) y la incondicionalidad. DERIVA de exp130/results.
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle146_inductive_bias')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp130_inductive_bias', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="la factorización PRODUCTO del keystone (valor≈ctrl×rel) es un sesgo inductivo de BAJA CAPACIDAD que ayuda a un aprendiz a ESTIMAR el valor bajo ESCASEZ de datos (bias-variance: bate a un flexible que sobreajusta y a separables sin producto; el flexible lo alcanza con datos) -- PERO esto es el caveat ESTÁNDAR 'no free lunch / ayuda sólo si matchea': es CONDICIONAL a que el valor verdadero esté alineado con el producto; con estructura residual ORTOGONAL al producto el prior de baja capacidad HUNDE al estimador en todos los N. La minimalidad (pocos params) es lo load-bearing.", obtained=False,
                     claim=("La factorización producto es un sesgo inductivo útil de baja capacidad para estimar el valor bajo "
                            "escasez SÓLO cuando el valor está alineado con el producto (no free lunch); con residuo ortogonal "
                            "hunde al estimador. (Principio; bias-variance.)"))
S_ARCO = Source(tier=5, ref="cognia_x/experiments/{arco 127-145} — el keystone valor=ctrl×rel como CRITERIO conocido (5 MIXTA seguidos en la vena selección/capacidad)", obtained=True,
                claim=("El arco 127-145 USÓ el keystone como criterio CONOCIDO y preguntó si bate a los factores al seleccionar "
                       "(rendimientos decrecientes: 5 MIXTA seguidos 141-145). H-V4-10r PIVOTA: ¿es el producto un sesgo inductivo "
                       "útil para APRENDER el valor con pocos datos? Sí para el estimador bajo escasez, pero condicional a la "
                       "alineación-con-el-producto (no free lunch)."))
S_VERIF = Source(tier=4, ref="verificación adversarial de 2 agentes (lentes comparación-justa/regularización + robustez/decisión; probes reales numpy)", obtained=True,
                 claim=("La verificación adversarial (16mo ciclo) CONFIRMÓ el núcleo del estimador (robusto en λ-justo -FLEX con λ "
                        "óptimo sigue ~3x peor a N chico-, δ/noise/grado/seeds; la minimalidad es load-bearing) PERO RE-ACOTÓ "
                        "BIDIRECCIONALMENTE: (1) la ventaja es CONDICIONAL a la alineación-con-el-producto (con misespecificación "
                        "ortogonal STRUCT se hunde en todos los N); (2) la 'anti-tautología' es débil (la misespecificación elegida "
                        "es ~0.95 colineal con la feature de STRUCT); (3) la decisión está confundida (el top-K perfecto es la "
                        "SUFICIENCIA de w·c para el orden, no robustez al MSE)."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp130 primero): " + results_path)

    ms0 = sm['mse_struct'][0]; mf0 = sm['mse_flex'][0]; ma0 = sm['mse_add'][0]; colin = sm['colinearity_prod2']
    n0 = sm['NS'][0]; n_seeds = data['args']['seeds']
    bm = sm['by_misspec']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim130 = ("exp130 (propio, {n} seeds, numpy, post-verificación de 2 agentes): {V}. NÚCLEO (robusto λ-justo/δ/noise/grado/"
                "seeds): la factorización PRODUCTO w·ctrl es un sesgo inductivo de BAJA CAPACIDAD útil para ESTIMAR el valor bajo "
                "ESCASEZ -- a N={n0} STRUCT (2 params) MSE {ms0} < FLEX {mf0} (sobreajusta) < ADD/separables {ma0} (sin producto); "
                "FLEX alcanza bajo abundancia (bias-variance); minimalidad load-bearing. RE-ACOTADO: CONDICIONAL a la alineación "
                "(misespecificación ORTOGONAL -> STRUCT el peor en todos los N: w_only struct {wo_s} vs flex {wo_f}); 'anti-"
                "tautología' débil (colinealidad prod2 {col}); decisión confundida (top-K = suficiencia de w·c, no robustez).").format(
                    n=n_seeds, V=status.upper(), n0=n0, ms0=_f(ms0), mf0=_f(mf0), ma0=_f(ma0),
                    wo_s=_f(bm['w_only']['mse']['struct']), wo_f=_f(bm['w_only']['mse']['flex']), col=_f(colin))
    S_EXP130 = Source(tier=5, ref="cognia_x/experiments/exp130_inductive_bias", obtained=True, claim=claim130)
    for src in (S_PRINCIPLE, S_ARCO, S_VERIF, S_EXP130):
        ledger.add_source(src)
    notes.append("4 fuentes (S_PRINCIPLE tier2 sesgo inductivo de baja capacidad condicional a la alineación; S_ARCO tier5 el pivote desde la vena saturada; S_VERIF tier4 verificación adversarial -re-acotó bidireccionalmente-; S_EXP130 tier5 dato propio {}).".format(status.upper()))

    ev_for = [S_EXP130.ref, S_PRINCIPLE.ref]
    ev_against = [S_EXP130.ref, S_VERIF.ref]
    advtext = ("{V} (PIVOTE fuera de la vena keystone/capacidad saturada -aprender el valor, no usarlo-; caracterización honesta "
               "tras verificación adversarial de 2 agentes, 16mo ciclo): el arco 127-145 usó el keystone como CRITERIO conocido y "
               "preguntó si bate a los factores al seleccionar (5 MIXTA seguidos, rendimientos decrecientes). Este ciclo pregunta "
               "algo distinto y central al North Star: ¿es la estructura PRODUCTO ctrl×rel un SESGO INDUCTIVO ÚTIL para un APRENDIZ "
               "que ESTIMA el valor desde experiencia ESCASA? NÚCLEO (robusto en λ-justo/δ/noise/grado/seeds): bajo ESCASEZ (N={n0}) "
               "el aprendiz ESTRUCTURADO (asume el producto w·ctrl, 2 params) tiene MENOR MSE de test ({ms0}) que el FLEXIBLE "
               "(polinomio grado-3, {mf0}: sobreajusta -> alta varianza) Y que el ADITIVO/separables ({ma0}: sin producto -> "
               "sesgo); la ventaja DECRECE con N (bias-variance limpio) y FLEX lo ALCANZA bajo ABUNDANCIA -> la factorización "
               "producto es un sesgo inductivo útil de BAJA CAPACIDAD para que un sistema CONSTRUYA su valor con pocos datos. La "
               "verificación CONFIRMÓ esto y blindó dos sub-claims: FLEX con λ ÓPTIMO sigue ~3x peor a N chico (NO es artefacto de "
               "regularización -comparación justa-) y la MINIMALIDAD (2 params) es lo load-bearing (un modelo de 4 params CON el "
               "producto, bilineal, es 5x peor -> no basta 'tener el producto', importa la baja capacidad). PERO RE-ACOTÓ "
               "BIDIRECCIONALMENTE y bajó a MIXTA: (1) la ventaja es CONDICIONAL a la ALINEACIÓN-CON-EL-PRODUCTO -- el caveat "
               "ESTÁNDAR de sesgo inductivo ('no free lunch / ayuda sólo si matchea'): con misespecificación ORTOGONAL al producto "
               "(v=w·c+δ·w o +δ·(w-c)²) STRUCT es el PEOR aprendiz en TODOS los N (w_only: struct {wo_s} > flex {wo_f}); el prior de "
               "baja capacidad se vuelve sesgo impagable. (2) la 'anti-tautología' que reivindiqué es DÉBIL: la misespecificación "
               "'prod2' δ·(w·c)² está ~{col} CORRELACIONADA con la única feature de STRUCT (w·c) -> su sesgo irreducible es minúsculo "
               "POR DISEÑO (la elegí favorable; 'fuera del span' es cierto pero vacuo en magnitud). (3) la DECISIÓN estaba MAL "
               "CARACTERIZADA: el top-K perfecto de TODOS (payoff ~1.0) NO es 'ranking robusto al error de MSE' como dije -- es la "
               "SUFICIENCIA de w·c para el ORDEN (v_true es monótona en w·c, así que el feature de STRUCT ordena perfecto POR "
               "CONSTRUCCIÓN; a N=100 STRUCT decide perfecto con MSE PEOR que flex, probando que es suficiencia, no robustez). En "
               "decisión DURA (pairwise) STRUCT SÍ gana bajo escasez con prod2 -> el 'no se traslada a la decisión' era artefacto "
               "del top-K fácil; PERO también COLAPSA con misespecificación ortogonal. => RESULTADO HONESTO: el keystone ES un "
               "sesgo inductivo útil (minimalidad + producto) para ESTIMAR el valor bajo escasez CUANDO el valor está alineado con "
               "el producto -- el resultado bias-variance estándar 'no free lunch'; con residuo ortogonal el prior HUNDE al "
               "estimador; y el pago decisional, donde existe, está mediado por la suficiencia de w·c (tautológica para v_true "
               "monótona en el producto). MIXTA EXITOSA: la verificación cazó el over-framing 'anti-tautología' (misespecificación "
               "~colineal), la mis-caracterización de la decisión (suficiencia, no robustez) y la incondicionalidad (es condicional "
               "a la alineación). Frontera: un sesgo inductivo APRENDIDO (no asumido) desde la experiencia; SCALE.").format(
                   V=status.upper(), n0=n0, ms0=_f(ms0), mf0=_f(mf0), ma0=_f(ma0), wo_s=_f(bm['w_only']['mse']['struct']),
                   wo_f=_f(bm['w_only']['mse']['flex']), col=_f(colin))

    hyp = Hypothesis(
        id="H-V4-10r",
        statement=("¿Es la factorización PRODUCTO ctrl×rel un SESGO INDUCTIVO ÚTIL para un aprendiz que ESTIMA el valor desde "
                   "experiencia ESCASA? Bajo escasez el aprendiz que asume el producto (2 params) generaliza mejor (MSE) que un "
                   "flexible (sobreajusta) y separables (sin producto); el flexible alcanza con datos (bias-variance) -- PERO es "
                   "CONDICIONAL a que el valor esté alineado con el producto (con residuo ortogonal el prior hunde al estimador, "
                   "no free lunch); la 'anti-tautología' es débil (misespecificación ~colineal) y el pago decisional está mediado "
                   "por la suficiencia de w·c. Alcance: numpy, ridge, sustrato lineal."),
        prediction=("APOYADA si el producto es un sesgo inductivo útil INCONDICIONAL y no-tautológico. REFUTADA si STRUCT no bate a "
                    "FLEX/separables bajo escasez. MIXTA si ayuda al estimador bajo escasez pero condicional a la alineación / "
                    "anti-tautología débil / decisión confundida. (Pre-registrada; verificación adversarial de 2 agentes.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp130_inductive_bias")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-10r")
        notes.append("H-V4-10r marcada '{}': la factorización producto es un sesgo inductivo útil de baja capacidad para estimar el valor bajo escasez (robusto λ-justo/δ/noise/grado/seeds; minimalidad load-bearing) PERO condicional a la alineación-con-el-producto (con residuo ortogonal hunde al estimador, no free lunch); anti-tautología débil; decisión confundida por suficiencia de w·c.".format(status))

    analogy = AnalogyRecord(
        problem=("Querías mostrar que la 'receta' valor=importancia×control no es sólo la forma de la respuesta, sino una BUENA "
                 "CORAZONADA para ADIVINAR el valor cuando tenés pocos ejemplos. ¿Lo es?"),
        everyday=("Sí, pero con el asterisco de siempre. Si le decís a alguien 'el valor es importancia POR control' y le das pocos "
                  "ejemplos, adivina mejor que alguien que prueba una fórmula súper flexible (que con pocos datos se va por las "
                  "ramas) o que alguien que asume 'importancia MÁS control' (fórmula equivocada). Y eso es porque la corazonada es "
                  "SIMPLE (pocas perillas). PERO: sólo gana si la verdad de veras se parece a 'por'; si la parte que se le escapa a "
                  "la verdad va en otra dirección, la corazonada simple se vuelve un ANCLA y pierde con todos. Encima, el caso que "
                  "elegí para 'probar que no era trampa' estaba 95% alineado con la corazonada, así que casi no la castigaba -- era "
                  "trampa suave. Y lo de 'elegir lo mejor' salía perfecto no porque la corazonada fuera robusta, sino porque "
                  "'importancia×control' alcanza para ORDENAR cuando la verdad sube con ese producto. Moraleja honesta: es una buena "
                  "corazonada de pocos-datos SÓLO si matchea la verdad (no hay almuerzo gratis)."),
        solutions=["la factorización producto es un sesgo inductivo de baja capacidad: bajo escasez bate a un flexible (sobreajusta) y a separables (sin producto), el flexible alcanza con datos (bias-variance)",
                   "PERO es CONDICIONAL a la alineación-con-el-producto: con residuo ortogonal el prior de baja capacidad hunde al estimador en todos los N (no free lunch)",
                   "la minimalidad (pocos params) es lo load-bearing, no sólo 'tener el producto' (un bilineal de 4 params es 5x peor); y FLEX con λ óptimo sigue 3x peor (comparación justa)",
                   "la 'anti-tautología' fue débil (misespecificación ~0.95 colineal) y el pago decisional está mediado por la suficiencia de w·c para el orden (tautológica)"],
        principles=["un sesgo inductivo (la factorización del valor) ayuda bajo escasez SÓLO si matchea la verdad -- el resultado bias-variance estándar 'no free lunch', no algo especial del keystone",
                    "al reivindicar 'no es tautología', MEDIR la colinealidad de la misespecificación con las features del modelo -- una misespecificación ~colineal no castiga al modelo (anti-tautología vacua)",
                    "un buen ranking puede venir de la SUFICIENCIA de un estadístico para el orden, NO de la calidad del estimador -> separar 'decide bien' de 'estima bien' (un modelo decide perfecto con MSE peor)",
                    "META: 16mo ciclo seguido con verificación adversarial -- cazó un overclaim TRIPLE (anti-tautología vacua + decisión mis-caracterizada + incondicionalidad)"],
        adaptation=("PIVOTE fuera de la vena keystone/capacidad saturada (5 MIXTA, rendimientos decrecientes): en vez de USAR el "
                    "valor conocido, preguntar si su FACTORIZACIÓN ayuda a APRENDERLO. MIXTA honesto: la factorización producto es un "
                    "sesgo inductivo útil de baja capacidad para ESTIMAR el valor bajo escasez (robusto λ-justo/δ/noise/grado/seeds; "
                    "minimalidad load-bearing) PERO condicional a la alineación-con-el-producto (con residuo ortogonal hunde al "
                    "estimador, el caveat estándar 'no free lunch'); la 'anti-tautología' fue débil (misespecificación ~0.95 "
                    "colineal) y el pago decisional está mediado por la suficiencia de w·c para el orden. APORTE: el resultado "
                    "bias-variance honesto (el keystone como prior útil-si-matchea) + la conexión con el arco (estimar≠decidir). "
                    "META-LECCIÓN: 16mo ciclo con verificación adversarial (cazó un overclaim triple). Próximo: un sesgo inductivo "
                    "APRENDIDO desde la experiencia (no asumido); SCALE."),
        measurement=("exp130 ({n} seeds): núcleo N={n0} struct {ms0} < flex {mf0} < add {ma0}; CONDICIONAL: w_only struct "
                     "{wo_s} > flex {wo_f} (se hunde); colinealidad prod2 {col}; pairwise gana con prod2, colapsa con ortogonal.").format(
                         n=n_seeds, n0=n0, ms0=_f(ms0), mf0=_f(mf0), ma0=_f(ma0), wo_s=_f(bm['w_only']['mse']['struct']),
                         wo_f=_f(bm['w_only']['mse']['flex']), col=_f(colin)),
        iterations=1)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (la factorización producto es una buena corazonada de pocos-datos SÓLO si matchea la verdad -no free lunch-; el caso 'anti-trampa' estaba 95% alineado; 'decide bien' vino de suficiencia para el orden, no de estimar bien).")

    kl = ("REAL (exp130, {V} post-verificación adversarial de 2 agentes): la factorización PRODUCTO ctrl×rel es un sesgo inductivo de "
          "BAJA CAPACIDAD útil para ESTIMAR el valor bajo ESCASEZ de datos (robusto λ-justo/δ/noise/grado/seeds; bate a un flexible "
          "que sobreajusta y a separables sin producto; minimalidad load-bearing). TECHO/ALCANCE: CONDICIONAL a la alineación-con-el-"
          "producto -- con residuo ORTOGONAL el prior HUNDE al estimador en todos los N (no free lunch); la 'anti-tautología' es "
          "débil (misespecificación ~{col} colineal con w·c); el pago decisional está mediado por la SUFICIENCIA de w·c para el "
          "orden (tautológica para v_true monótona en el producto); numpy/ridge/lineal. Frontera: un sesgo inductivo APRENDIDO (no "
          "asumido); SCALE.").format(V=status.upper(), col=_f(colin))
    ceilings.add(CeilingRecord(
        subsystem="La factorización PRODUCTO del keystone (ctrl×rel) como SESGO INDUCTIVO para APRENDER el valor (PIVOTE fuera de la vena saturada) — un prior de BAJA CAPACIDAD útil para ESTIMAR el valor bajo ESCASEZ (bias-variance: bate a un flexible que sobreajusta y a separables sin producto; el flexible alcanza con datos; minimalidad load-bearing; comparación justa en λ). CONDICIONAL a la alineación-con-el-producto: con residuo ORTOGONAL el prior hunde al estimador en todos los N (no free lunch). Anti-tautología débil (misespecificación ~0.95 colineal); decisión confundida por la suficiencia de w·c. Alcance: numpy, ridge, lineal",
        known_limit=kl,
        blockers=[{"text": "CONDICIONAL a la ALINEACIÓN (el caveat dominante, no free lunch): con misespecificación ORTOGONAL al producto (v=w·c+δ·w struct {wo_s} vs flex {wo_f}; o +δ·(w-c)²) STRUCT es el PEOR aprendiz en TODOS los N -- el prior de baja capacidad se vuelve un sesgo impagable. La ventaja bajo escasez es el resultado bias-variance ESTÁNDAR 'ayuda sólo si matchea la verdad', no algo especial del keystone. Lo NO-trivial/load-bearing: la MINIMALIDAD (2 params; un bilineal de 4 params CON el producto es 5x peor) + la comparación justa (FLEX con λ óptimo sigue ~3x peor)".format(wo_s=_f(bm['w_only']['mse']['struct']), wo_f=_f(bm['w_only']['mse']['flex'])), "kind": "diseno"},
        {"text": "ANTI-TAUTOLOGÍA DÉBIL + DECISIÓN CONFUNDIDA: (a) la misespecificación 'prod2' δ·(w·c)² que reivindiqué como 'fuera del span de STRUCT' está ~{col} CORRELACIONADA con la única feature de STRUCT (w·c) -> su sesgo irreducible es minúsculo POR DISEÑO (la elegí favorable; 'fuera del span' es cierto pero vacuo en magnitud). (b) el top-K perfecto de TODOS los aprendices (payoff ~1.0) NO es 'ranking robusto al MSE' como caractericé -- es la SUFICIENCIA de w·c para el ORDEN (v_true monótona en w·c -> el feature de STRUCT ordena perfecto por construcción; a N=100 STRUCT decide perfecto con MSE PEOR que flex). En pairwise STRUCT gana bajo escasez con prod2 pero COLAPSA con ortogonal".format(col=_f(colin)), "kind": "diseno"},
        {"text": "ALCANCE: numpy/toy, ridge sobre features polinomiales, v_true=w·c+δ·misespecificación, 2 features (w,c). NO cubre: un sesgo inductivo APRENDIDO desde la experiencia (no asumido a mano), features de alta dimensión, no-linealidad real, el lazo real, SCALE. El aporte neto -el keystone como prior útil-si-matchea- es el resultado bias-variance estándar, no específico del keystone", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP130.ref, S_ARCO.ref, S_VERIF.ref]))
    notes.append("1 techo 'real': la factorización producto es un sesgo inductivo de baja capacidad útil para estimar el valor bajo escasez (robusto), pero condicional a la alineación-con-el-producto (no free lunch); anti-tautología débil; decisión confundida por suficiencia de w·c.")

    dstmt = ("North-Star R-VALOR (PIVOTE: ¿la factorización del keystone ayuda a APRENDER el valor?): {V}. La factorización PRODUCTO "
             "ctrl×rel es un sesgo inductivo de BAJA CAPACIDAD útil para ESTIMAR el valor bajo ESCASEZ (robusto λ-justo/δ/noise/grado/"
             "seeds: STRUCT MSE {ms0} < flex {mf0} < add {ma0} a N={n0}; minimalidad load-bearing) PERO CONDICIONAL a la alineación-"
             "con-el-producto (con residuo ortogonal hunde al estimador, no free lunch); anti-tautología débil (colinealidad {col}); "
             "decisión confundida por suficiencia de w·c. Decisión: adoptar el keystone como prior útil-SI-MATCHEA (resultado "
             "bias-variance estándar), no como sesgo inductivo incondicional. META-DECISIÓN: 16mo ciclo con verificación adversarial "
             "(cazó un overclaim triple); PIVOTE confirmado fuera de la vena saturada. Próximo: un sesgo inductivo APRENDIDO; "
             "SCALE.").format(V=status.upper(), ms0=_f(ms0), mf0=_f(mf0), ma0=_f(ma0), n0=n0, col=_f(colin))
    drat = ("exp130 (tier5, propio, {n} seeds, numpy, post-verificación de 2 agentes): la factorización producto es un sesgo "
            "inductivo útil de baja capacidad para estimar el valor bajo escasez (bias-variance, minimalidad load-bearing, "
            "comparación justa) PERO condicional a la alineación-con-el-producto (con residuo ortogonal hunde al estimador); "
            "anti-tautología débil; decisión confundida por suficiencia de w·c. Convergente con el principio (tier2) y la "
            "verificación (tier4); pivota desde la vena saturada del arco (tier5). MIXTA: núcleo del estimador real + 3 acotaciones.").format(n=n_seeds)
    dec = Decision(id="D-V4-108", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP130), _to_plain(S_ARCO), _to_plain(S_VERIF)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-108 ACEPTADA por el ledger (tier5 exp130 + tier5 arco-127-145 + tier4 verificación adversarial).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-108:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle146_inductive_bias',
                                description='CYCLE 146 (RESET v4, H-V4-10r MIXTA: la factorización producto es un sesgo inductivo útil de baja capacidad para ESTIMAR el valor bajo escasez -robusto- PERO condicional a la alineación-con-el-producto -no free lunch-; anti-tautología débil; decisión confundida por suficiencia de w·c; 16mo ciclo con verificación adversarial).')
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
    print("RESUMEN — CYCLE 146 (RESET v4, PIVOTE): el keystone como sesgo inductivo para APRENDER el valor (útil-si-matchea) — H-V4-10r " + (status.upper() if status else "?"))
    print("=" * 78)
    print("veredicto H-V4-10r:", status.upper() if status else "?")
    print("  NÚCLEO (robusto λ-justo/δ/noise/grado/seeds): la factorización producto es un sesgo inductivo de BAJA CAPACIDAD útil para ESTIMAR el valor bajo ESCASEZ (bate a un flexible que sobreajusta y a separables sin producto; minimalidad load-bearing). RE-ACOTADO: CONDICIONAL a la alineación-con-el-producto (con residuo ortogonal hunde al estimador, no free lunch); anti-tautología débil (misespecificación ~colineal); decisión confundida por la suficiencia de w·c.")
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
