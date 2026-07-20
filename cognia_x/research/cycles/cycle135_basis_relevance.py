r"""
cycle135_basis_relevance.py — CICLO 135 (RESET v4, rama control/acción, ataca el caveat EJE2 de 134 -la relevancia NO se descubre
bajo meta no-lineal con credit-assignment lineal-): H-V4-10i por las compuertas del engine. ¿Una BASE de credit-assignment más
RICA recupera la relevancia bajo una meta NO-LINEAL? ¿El prior PAGA? ¿Es R-PRIOR?

VEREDICTO: MIXTA (post-verificación adversarial de 4 agentes — 5to ciclo de la institución; leakage-free verificado). El NÚCLEO
RECUPERA pero el ciclo BUNDLEABA dos claims secundarios FRÁGILES/FALSOS (directiva v4: bundle de claims = MIXTA).

CONTEXTO. CYCLE 134 (exp118) cerró el supuesto 'relevancia DADA' del arco 127-133, pero dejó un CAVEAT (EJE2/forma-de-meta): el
credit-assignment LINEAL (regresar la señal de meta G ~ x) recupera la relevancia sólo si la meta es ~lineal-descomponible; bajo
meta PAR (G=Σw·x²) recupera corr(ŵ,w)≈0 y la decisión cae a azar. Este ciclo ataca el caveat cambiando la BASE del credit-
assignment (las features sobre las que se regresa G).

SOBREVIVE (núcleo verificado, sin leakage): una base RICA [x,x²,relu] -o de paridad-mixta- recupera el factor RELEVANCIA del
R-VALOR bajo meta NO-LINEAL, cerrando el caveat. La base LINEAL de 134 queda fuertemente DEGRADADA bajo meta PAR (ambos≈0.64 vs
ctrl_solo≈0.49, corr_w≈0.18; ~29% del gap) por ORTOGONALIDAD-DE-PARIDAD (una función impar no representa una par); la MATCHED y la
RICA genérica (que NO sabe la forma) la RESUCITAN (ambos=1.000, t~17.6), robustas a TODA forma y a sustratos más duros (pesos
graduados, disociación genuina ctrl-rel ctrl_solo→0.20, D=16 K=4); con dato limpio la generalidad es GRATIS.

NO SE SOSTIENEN (claims retractados por la verificación adversarial):
  (1) 'el PRIOR PAGA / costo de DATOS escala con la riqueza' -- el eje DATOS es NULO (T≥30; sólo paga a T≤15, base rica rank-
      deficiente) y el eje RUIDO (σ_g=20) es ~80% ARTEFACTO de sub-regularizar la base rica: subir el ridge a 0.3 (cross-validable,
      gratis en el régimen fácil) cierra el gap de +0.29 a +0.07 y el propio build_summary vira a MIXTA.
  (2) 'NO hay base FIJA universal' es FALSO: un feature fijo relu (paridad-mixta) recupera todas las formas probadas (peor caso
      ~0.99); sólo fallan las bases de PARIDAD-PURA ORTOGONALES (linear↔even). El fenómeno real es ORTOGONALIDAD-DE-PARIDAD.
  (3) 'une R-VALOR con R-PRIOR' es un PUENTE SUGERIDO, no testeado: el experimento hace ingeniería de features, no APRENDE/
      SELECCIONA la base ni varía un prior.

=> H-V4-10i acota a: el factor relevancia ES discoverable bajo no-linealidad con una base suficientemente expresiva, barato con
dato limpio. PRÓXIMO: testear R-PRIOR explícito (aprender/seleccionar la base; si la robustez-al-ruido del prior sobrevive a la
cross-validación).

DERIVA de exp119_basis_relevance/results/results.json.

Correr (DESPUÉS de exp119):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp119_basis_relevance.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle135_basis_relevance
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle135_basis_relevance')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp119_basis_relevance', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="el factor RELEVANCIA del R-VALOR (qué importa) es discoverable bajo una meta NO-LINEAL si la BASE de features del credit-assignment es suficientemente expresiva (span-ea la no-linealidad de la meta); una base ortogonal-en-paridad a la meta falla. Esto SUGIERE -no prueba- que elegir/aprender la base es un problema tipo-prior (R-PRIOR); pero una base rica/paridad-mixta lo resuelve sin conocer la forma y, con regularización cross-validada, la ventaja de conocer la forma (el prior) se cierra casi por completo.", obtained=False,
                     claim=("El factor RELEVANCIA del R-VALOR es descubrible bajo no-linealidad de la meta con una BASE de credit-"
                            "assignment expresiva (que span-ee la no-linealidad). El credit-assignment LINEAL (134) falla bajo meta "
                            "par por ORTOGONALIDAD-DE-PARIDAD. Una base rica/paridad-mixta lo recupera SIN conocer la forma; la "
                            "ventaja de una base MATCHED a la forma (el 'prior') es real sólo a regularización fija y mild, y se "
                            "cierra casi por completo con cross-validación del ridge -> 'descubrir la relevancia bajo no-linealidad "
                            "es R-PRIOR' queda como HIPÓTESIS a testear (aprender/seleccionar la base), no como hecho. (Principio.)"))
S_C134 = Source(tier=5, ref="cognia_x/experiments/exp118_discovered_relevance", obtained=True,
                claim=("CYCLE 134 (EJE2): el credit-assignment LINEAL recupera la relevancia sólo si la meta es ~lineal-"
                       "descomponible; bajo meta PAR (G=Σw·x²) recupera corr(ŵ,w)≈0 y la decisión cae a azar. H-V4-10i ataca el "
                       "caveat cambiando la BASE del credit-assignment: una base expresiva lo cierra (la lineal fallaba por "
                       "ortogonalidad-de-paridad, no por una barrera profunda)."))
S_VERIF = Source(tier=4, ref="verificación adversarial de 4 agentes (lentes leakage/efecto/overclaim/identificabilidad; probes reales sobre exp119)", obtained=True,
                 claim=("La verificación adversarial (5to ciclo) confirmó el NÚCLEO leakage-free (4 controles nulos: decoy-w -> "
                        "colapso a ctrl_solo; G ruido -> sin ventaja; uniform-s -> idéntico; identificabilidad even coef=w·std(x²) "
                        "ratio 0.99) y CAZÓ 3 overclaims: (1) 'el prior paga' es ~80% artefacto de sub-regularizar la base rica "
                        "(gap σ_g=20 cae +0.29->+0.07 a ridge 0.3; build_summary vira a MIXTA); (2) 'no hay base fija universal' es "
                        "FALSO (relu fijo recupera todas las formas, peor caso ~0.99); (3) 'une R-VALOR con R-PRIOR' es un puente no "
                        "testeado. El núcleo sobrevive a sustratos más duros (graded, disociado, D=16)."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp119 primero): " + results_path)

    al = sm['even_ambos_linear']; ae = sm['even_ambos_even']; ar = sm['even_ambos_rich']; cs = sm['even_ctrl_solo']
    cwl = sm['even_corrw_linear']
    rl = sm['rich_linear']; re = sm['rich_even']; rr = sm['rich_relu']; rm = sm['rich_mixed']
    offle = sm['offform_linear_on_even']; offel = sm['offform_even_on_linear']
    rw = sm['relu_worst']
    dc = sm['data_cost']
    gnl = dc['gap_noise_loridge']; gnh = dc['gap_noise_hiridge']; rlo = dc['ridge_lo']; rhi = dc['ridge_hi']
    hsg_m = dc['hi_sg_matched']; hsg_r = dc['hi_sg_rich']
    gap = ar - al
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim119 = ("exp119 (propio, {n} seeds, numpy, post-verificación adversarial de 4 agentes): MIXTA. SOBREVIVE: una base RICA "
                "[x,x²,relu] -o paridad-mixta- recupera el factor RELEVANCIA bajo meta NO-LINEAL (cierra el caveat EJE2 de 134). "
                "Bajo meta PAR la base LINEAL queda degradada (ambos={al} vs ctrl_solo {cs}, corr_w {cwl}, ~29% del gap) por "
                "ORTOGONALIDAD-DE-PARIDAD; matched/rica la RESUCITAN (ambos {ae}/{ar}, +{gap} sobre lineal, t~17.6), robustas a "
                "TODA forma (lin {rl}/even {re}/relu {rr}/mixed {rm}). NO SE SOSTIENEN: (1) 'prior paga' -- eje datos NULO (T≥30) y "
                "eje ruido (σ_g=20: matched {hm} vs rica {hr}, +{gnl} a ridge {rlo}) ~80% artefacto de sub-regularización (a ridge "
                "{rhi} cae a +{gnh}); (2) 'no hay base fija universal' FALSO (relu fijo peor-caso {rw}); sólo falla la paridad-PURA "
                "ortogonal (lin-en-even {ole}, even-en-lin {oel}); (3) R-PRIOR = puente sugerido, no testeado.").format(
                    n=n_seeds, al=_f(al), cs=_f(cs), cwl=_f(cwl), ae=_f(ae), ar=_f(ar), gap=_f(gap), rl=_f(rl), re=_f(re),
                    rr=_f(rr), rm=_f(rm), hm=_f(hsg_m), hr=_f(hsg_r), gnl=_f(gnl), rlo=rlo, rhi=rhi, gnh=_f(gnh),
                    rw=_f(rw), ole=_f(offle), oel=_f(offel))
    S_EXP119 = Source(tier=5, ref="cognia_x/experiments/exp119_basis_relevance", obtained=True, claim=claim119)
    for src in (S_PRINCIPLE, S_C134, S_VERIF, S_EXP119):
        ledger.add_source(src)
    notes.append("4 fuentes (S_PRINCIPLE tier2 relevancia-bajo-no-linealidad=base-expresiva, R-PRIOR como HIPÓTESIS; S_C134 tier5 el caveat EJE2 atacado; S_VERIF tier4 verificación adversarial de 4 agentes -núcleo leakage-free + 3 overclaims cazados-; S_EXP119 tier5 dato propio MIXTA).")

    ev_for = [S_EXP119.ref, S_PRINCIPLE.ref]
    ev_against = [S_EXP119.ref, S_VERIF.ref]
    advtext = ("{V} (post-verificación adversarial de 4 agentes -- 5to ciclo de la institución; leakage-free verificado): el "
               "NÚCLEO RECUPERA pero el ciclo BUNDLEABA dos claims secundarios frágiles/falsos. SOBREVIVE (verificado): una base "
               "de credit-assignment RICA [x,x²,relu] -o de paridad-mixta- recupera el factor RELEVANCIA del R-VALOR bajo meta "
               "NO-LINEAL, cerrando el caveat EJE2 de 134. La base LINEAL de 134 queda fuertemente DEGRADADA bajo meta PAR (decisión "
               "ambos={al} vs ctrl_solo {cs}, corr(ŵ,w)={cwl}; recupera ~29% del gap de relevancia) por ORTOGONALIDAD-DE-PARIDAD "
               "(una función impar no representa una par); la MATCHED (ambos={ae}) y la RICA genérica -que NO conoce la forma- "
               "(ambos={ar}, +{gap} sobre la lineal, t~17.6, frac(rich≥lin)=1.0) la RESUCITAN, robustas a TODA forma (linear {rl}/"
               "even {re}/relu {rr}/mixed {rm}); con dato amplio/limpio la generalidad es GRATIS, y el núcleo SOBREVIVE a sustratos "
               "más duros (pesos graduados, disociación genuina ctrl-rel ctrl_solo→0.20, D=16 K=4). El descubrimiento es genuino: "
               "4 controles nulos pasan (decoy-w -> colapso a ctrl_solo; G ruido -> sin ventaja; uniform-s -> idéntico) e "
               "identificabilidad verificada (coef even = w·std(x²), ratio 0.99; centrado exacto, sesgo 4e-16). NO SE SOSTIENEN "
               "(EVIDENCIA EN CONTRA, claims retractados): (1) 'el PRIOR PAGA / costo de DATOS escala con la riqueza' -- el eje "
               "DATOS es NULO (T≥30; sólo a T≤15 la base rica es rank-deficiente) y el eje RUIDO (σ_g=20: matched {hm} vs rica {hr}, "
               "+{gnl} a ridge {rlo}) es ~80% ARTEFACTO de sub-regularizar la base rica: subiendo el ridge a {rhi} (cross-validable, "
               "GRATIS en el régimen fácil) el gap cae a +{gnh} y el propio build_summary vira a MIXTA. El mecanismo es VARIANZA "
               "por colinealidad x²/relu, no un costo intrínseco de la generalidad. (2) 'NO hay base FIJA universal' es FALSO: la "
               "base FIJA relu (1 columna, paridad-mixta) es casi-universal sobre las formas probadas (peor caso {rw}); sólo fallan "
               "las bases de PARIDAD-PURA ORTOGONALES (lin-en-even {ole}, even-en-lin {oel}). (3) 'une R-VALOR con R-PRIOR' es un "
               "PUENTE SUGERIDO, no testeado (ingeniería de features, no aprende/selecciona la base ni varía un prior). DIAGNÓSTICO "
               "secundario: corr_w bajo (~0.6) con decisión perfecta es el sesgo positivo de la norma-del-bloque (no usar como "
               "criterio). => MIXTA EXITOSA (directiva v4 §4): el núcleo apoyado afila el PRÓXIMO ciclo -- testear R-PRIOR explícito "
               "(aprender/seleccionar la base; si la robustez-al-ruido del prior sobrevive a la cross-validación).").format(
                   V=status.upper(), al=_f(al), cs=_f(cs), cwl=_f(cwl), ae=_f(ae), ar=_f(ar), gap=_f(gap), rl=_f(rl),
                   re=_f(re), rr=_f(rr), rm=_f(rm), hm=_f(hsg_m), hr=_f(hsg_r), gnl=_f(gnl), rlo=rlo, rhi=rhi,
                   gnh=_f(gnh), rw=_f(rw), ole=_f(offle), oel=_f(offel))

    hyp = Hypothesis(
        id="H-V4-10i",
        statement=("Una BASE de credit-assignment más RICA recupera la relevancia bajo una meta NO-LINEAL (cierra el caveat EJE2 "
                   "de 134). NÚCLEO (sobrevive, verificado leakage-free): la base lineal de 134 falla bajo meta par por "
                   "ORTOGONALIDAD-DE-PARIDAD; una base rica/paridad-mixta la recupera SIN conocer la forma, robusta a las 4 formas "
                   "y a sustratos más duros; con dato limpio la generalidad es GRATIS. SECUNDARIOS RETRACTADOS (bundle, directiva "
                   "v4): 'el prior paga' es ~80% artefacto de sub-regularización (se cierra con cross-validación del ridge); 'no "
                   "hay base fija universal' es FALSO (un feature relu fijo es casi-universal); 'une R-VALOR con R-PRIOR' es un "
                   "puente SUGERIDO, no testeado. R-PRIOR (elegir/aprender la base) queda como hipótesis para el próximo ciclo."),
        prediction=("APOYADA si la base rica recupera Y el prior paga ROBUSTAMENTE (sobrevive al ridge cross-validado) Y no hay "
                    "base universal; MIXTA si el núcleo recupera pero los claims secundarios no se sostienen; REFUTADA si ni la "
                    "matched recupera. (Pre-registrada: numpy, barrido forma×base + T + σ_g + probe robustez-a-ridge, 200 seeds; "
                    "métrica primaria = la DECISIÓN top-K.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp119_basis_relevance")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-10i")
        notes.append("H-V4-10i marcada '{}' con DoD completo (núcleo recupera la relevancia bajo no-linealidad con base expresiva -leakage-free-; 3 claims secundarios retractados por la verificación adversarial: prior-paga-artefacto, relu-casi-universal, R-PRIOR-puente-no-testeado).".format(status))

    analogy = AnalogyRecord(
        problem=("Querés saber QUÉ COSAS IMPORTAN para un puntaje, mirando cómo cambia el puntaje cuando cambian las cosas. Pero "
                 "el puntaje depende de las cosas de forma TORCIDA (p.ej. del cuadrado), no derecha. ¿Podés descubrir qué importa? "
                 "¿Te cuesta MÁS no saber de antemano la forma de la torcedura?"),
        everyday=("Sí, si mirás con una lente que pueda VER curvas (no sólo rectas). Si la relación es 'al cuadrado' y sólo mirás "
                  "rectas, no ves nada (la lineal falla porque recta y cuadrado son 'perpendiculares'). Una lente que casa con la "
                  "forma la ve clarísima; pero NO hace falta saber la forma: una lente versátil (que ve rectas Y curvas, como un "
                  "'codo'/relu) ve casi todas las formas igual de bien. ¿Y cuesta más no saber la forma? Resulta que CASI NO: la "
                  "lente versátil parece costar más sólo cuando mirás con poco cuidado (poca regularización); si ajustás bien el "
                  "foco (cross-validás), la ventaja de saber la forma de antemano casi desaparece. Moraleja PROVISORIA: importa "
                  "tener una lente expresiva; saber la forma exacta de antemano ayuda menos de lo que parecía."),
        solutions=["descubrir qué importa bajo una relación torcida = usar una BASE de features que pueda representar la torcedura",
                   "una base lineal falla bajo meta par por ORTOGONALIDAD-DE-PARIDAD (impar no representa par), no por una barrera profunda",
                   "una base rica/paridad-mixta (relu) recupera SIN conocer la forma, robusta a las formas probadas y a sustratos duros",
                   "la ventaja de una base MATCHED (el 'prior de la forma') es real sólo a regularización fija/mild y se cierra casi del todo con cross-validación -> que esto sea un cuello de R-PRIOR queda por testear (aprender/seleccionar la base)"],
        principles=["el factor RELEVANCIA del R-VALOR es discoverable bajo no-linealidad con una base de credit-assignment EXPRESIVA (que span-ee la no-linealidad)",
                    "la base lineal falla por ORTOGONALIDAD-DE-PARIDAD; una base rica/paridad-mixta recupera sin conocer la forma; no hay 'no existe base universal'",
                    "la ventaja del prior (base matched) es ~80% artefacto de sub-regularización: se cierra con cross-validación del ridge -> 'el prior paga' NO se sostiene como costo intrínseco",
                    "META: 5to ciclo con verificación adversarial -- confirmó el núcleo leakage-free y retractó 3 overclaims (prior-paga, base-universal, puente-R-PRIOR) antes del ledger"],
        adaptation=("El lab ataca el caveat EJE2 de 134 (la relevancia no se descubría bajo meta no-lineal) y obtiene una MIXTA "
                    "EXITOSA. NÚCLEO (apoyado, verificado leakage-free): el factor RELEVANCIA del R-VALOR ES discoverable bajo "
                    "no-linealidad con una base de credit-assignment expresiva (rica/paridad-mixta); la base lineal falla por "
                    "ortogonalidad-de-paridad, no por una barrera profunda; con dato limpio la generalidad es gratis. CLAIMS "
                    "RETRACTADOS por la verificación adversarial: (1) 'el prior paga' es ~80% artefacto de sub-regularizar la base "
                    "rica (se cierra con cross-validación del ridge); (2) 'no hay base fija universal' es FALSO (un feature relu "
                    "fijo es casi-universal sobre las formas probadas); (3) 'une R-VALOR con R-PRIOR' es un puente SUGERIDO, no "
                    "testeado. POLÍTICA: usar una base expresiva (rica/relu) por DEFECTO; el costo de no conocer la forma es chico "
                    "si se regulariza bien. META-LECCIÓN: 5to ciclo seguido en que la verificación adversarial corrige overclaims "
                    "antes del ledger; institucionalizada la compuerta. PRÓXIMO (afilado por esta MIXTA): testear R-PRIOR EXPLÍCITO "
                    "-- aprender/seleccionar la base de un menú (model selection / cross-validación / prior jerárquico sobre las "
                    "features) y medir si un aprendiz que NO conoce la forma IGUALA a la base matched (lo que esta MIXTA predice). "
                    "Si lo iguala, 'la relevancia bajo no-linealidad es un cuello de R-PRIOR' queda REFUTADO; si no, se acota el "
                    "régimen donde el prior sí es cuello. También: relevancia bajo sustrato ACOPLADO (133), lazo real, active inference."),
        measurement=("exp119 ({n} seeds): bajo meta even la base lineal ambos={al} (corr_w {cwl}, ~29% del gap) vs matched/rica "
                     "{ae}/{ar}; rica robusta a forma (lin {rl}/even {re}/relu {rr}/mixed {rm}); relu fijo peor-caso {rw} (casi-"
                     "universal); 'prior paga' a σ_g=20 +{gnl} a ridge {rlo} -> +{gnh} a ridge {rhi} (se cierra); base ortogonal "
                     "falla (lin-en-even {ole}, even-en-lin {oel}).").format(
                         n=n_seeds, al=_f(al), cwl=_f(cwl), ae=_f(ae), ar=_f(ar), rl=_f(rl), re=_f(re), rr=_f(rr), rm=_f(rm),
                         rw=_f(rw), gnl=_f(gnl), rlo=rlo, gnh=_f(gnh), rhi=rhi, ole=_f(offle), oel=_f(offel)),
        iterations=1)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (la lente expresiva ve la torcedura sin saber la forma; saber la forma ayuda menos de lo que parecía -se cierra con foco/cross-validación-).")

    kl = ("REAL (exp119, MIXTA post-verificación adversarial): el factor RELEVANCIA del R-VALOR ES discoverable bajo meta NO-LINEAL "
          "con una base de credit-assignment EXPRESIVA (rica/paridad-mixta). La base lineal de 134 falla bajo meta even (ambos={al}, "
          "corr_w {cwl}) por ortogonalidad-de-paridad; matched/rica la recuperan (ambos={ae}/{ar}), robustas a toda forma y a "
          "sustratos más duros. RETRACTADO: 'el prior paga' es artefacto de sub-regularización (gap σ_g=20 +{gnl}@ridge{rlo} -> "
          "+{gnh}@ridge{rhi}); 'no hay base universal' es falso (relu fijo peor-caso {rw}). TECHO: numpy; la base se elige de un "
          "MENÚ FIJO (no se aprende) -> R-PRIOR explícito sin testear; eval con control oracle. Frontera: APRENDER/SELECCIONAR la "
          "base (R-PRIOR), relevancia bajo sustrato acoplado (133), lazo real, active inference.").format(
              al=_f(al), cwl=_f(cwl), ae=_f(ae), ar=_f(ar), gnl=_f(gnl), rlo=rlo, gnh=_f(gnh), rhi=rhi, rw=_f(rw))
    ceilings.add(CeilingRecord(
        subsystem="Descubrimiento del factor RELEVANCIA del R-VALOR bajo meta NO-LINEAL — discoverable con una BASE de credit-assignment EXPRESIVA (rica/paridad-mixta), sin conocer la forma; la base lineal de 134 falla por ORTOGONALIDAD-DE-PARIDAD (no por una barrera profunda), robusta a las 4 formas y a sustratos más duros. MIXTA: el ciclo bundleaba claims secundarios falsos -'el prior paga' (artefacto de sub-regularización) y 'no hay base fija universal' (un relu fijo es casi-universal)-; 'une R-VALOR con R-PRIOR' es un puente no testeado. Cierra el caveat EJE2 de 134",
        known_limit=kl,
        blockers=[{"text": "numpy; la base se elige de un MENÚ FIJO {linear,even,relu,rich}, NO se aprende/selecciona -> el R-PRIOR EXPLÍCITO (aprender la base, model selection, cross-validación, prior jerárquico) queda como frontera y como el PRÓXIMO ciclo; eval con control ridge ORACLE (aísla la asignación)", "kind": "diseno"},
                  {"text": "RETRACTADO 'el prior paga': el eje DATOS es nulo (gap matched-rica ~0 a T>=30; sólo a T<=15 la base rica de 24 cols es rank-deficiente) y el eje RUIDO (σ_g=20) es ~80% artefacto de sub-regularizar la base rica -- a ridge 0.3 (cross-validable, gratis en el régimen fácil) el gap cae de +0.29 a +0.07 y el propio build_summary vira a MIXTA. El mecanismo es VARIANZA por colinealidad x²/relu, no un costo intrínseco de la generalidad", "kind": "diseno"},
                  {"text": "RETRACTADO 'no hay base fija universal': un feature FIJO relu (paridad-mixta) recupera todas las formas probadas (peor caso ~0.99); sólo fallan las bases de PARIDAD-PURA ORTOGONALES (linear<->even, E[x·x²]=0). El fenómeno real es ORTOGONALIDAD-DE-PARIDAD; no hay universalidad sobre TODA forma posible, sólo sobre el set probado", "kind": "diseno"},
                  {"text": "METODO/honestidad: 5to ciclo seguido en que la verificación adversarial (4 agentes) corrige overclaims antes del ledger. Confirmó el núcleo leakage-free (4 controles nulos + identificabilidad) y retractó 3 claims (prior-paga, base-universal, puente-R-PRIOR). corr_w es diagnóstico secundario (sesgo positivo de la norma-del-bloque): ~0.6 aun con decisión perfecta", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP119.ref, S_C134.ref, S_VERIF.ref]))
    notes.append("1 techo 'real': la relevancia bajo no-linealidad es discoverable con base expresiva (núcleo); 3 claims secundarios retractados (prior-paga-artefacto, relu-casi-universal, R-PRIOR-puente); la base se elige de menú fijo (aprenderla = frontera).")

    dstmt = ("North-Star R-VALOR (cierra el caveat EJE2 de 134; MIXTA post-verificación adversarial): el factor RELEVANCIA del "
             "R-VALOR es DISCOVERABLE bajo una meta NO-LINEAL con una BASE de credit-assignment EXPRESIVA (rica/paridad-mixta), sin "
             "conocer la forma. La base LINEAL de 134 falla bajo meta PAR (ambos={al} vs ctrl_solo {cs}, corr_w {cwl}) por "
             "ORTOGONALIDAD-DE-PARIDAD; la MATCHED y la RICA la RESUCITAN (ambos {ae}/{ar}), robustas a TODA forma (lin {rl}/even "
             "{re}/relu {rr}/mixed {rm}) y a sustratos más duros; con dato limpio la generalidad es GRATIS. RETRACTADO (bundle, "
             "directiva v4): (1) 'el prior paga' es ~80% artefacto de sub-regularización -- gap σ_g=20 +{gnl}@ridge{rlo} -> "
             "+{gnh}@ridge{rhi} (cross-validable); (2) 'no hay base fija universal' FALSO (relu fijo peor-caso {rw}); sólo falla la "
             "paridad-PURA ortogonal; (3) 'une R-VALOR con R-PRIOR' = puente SUGERIDO, no testeado. Decisión: usar una base "
             "EXPRESIVA por defecto; el costo de no conocer la forma es chico si se regulariza bien. META-DECISIÓN: 5to ciclo con "
             "verificación adversarial (núcleo leakage-free + 3 overclaims cazados). PRÓXIMO: testear R-PRIOR EXPLÍCITO (aprender/"
             "seleccionar la base; ¿iguala un aprendiz sin-forma a la base matched?).").format(
                 al=_f(al), cs=_f(cs), cwl=_f(cwl), ae=_f(ae), ar=_f(ar), rl=_f(rl), re=_f(re), rr=_f(rr), rm=_f(rm),
                 gnl=_f(gnl), rlo=rlo, gnh=_f(gnh), rhi=rhi, rw=_f(rw))
    drat = ("exp119 (tier5, propio, {n} seeds, numpy, post-verificación de 4 agentes): bajo meta even la base lineal cae (ambos="
            "{al}, corr_w {cwl}) por ortogonalidad-de-paridad y la matched/rica recuperan ({ae}/{ar}), robustas a toda forma. "
            "Convergente con el principio (tier2); ataca y cierra el caveat de 134 (tier5). MIXTA: el núcleo recupera (leakage-free, "
            "S_VERIF tier4) pero 3 claims secundarios fueron retractados (prior-paga-artefacto, relu-casi-universal, R-PRIOR-"
            "puente). Directiva v4: bundle de claims donde sólo el núcleo se aísla = MIXTA.").format(
                n=n_seeds, al=_f(al), cwl=_f(cwl), ae=_f(ae), ar=_f(ar))
    dec = Decision(id="D-V4-97", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP119), _to_plain(S_C134), _to_plain(S_VERIF)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-97 ACEPTADA por el ledger (tier5 exp119 + tier5 exp118 + tier4 verificación adversarial).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-97:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle135_basis_relevance',
                                description='CYCLE 135 (RESET v4, H-V4-10i MIXTA: una base de credit-assignment expresiva recupera la relevancia bajo meta no-lineal -núcleo, cierra el caveat EJE2 de 134-; 3 claims secundarios retractados por verificación adversarial de 4 agentes -prior-paga-artefacto, relu-casi-universal, R-PRIOR-puente; 5to ciclo).')
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
    print("RESUMEN — CYCLE 135 (RESET v4): la base de credit-assignment cierra el caveat EJE2 de 134 (núcleo); el 'prior paga' y 'no hay base universal' RETRACTADOS — H-V4-10i MIXTA")
    print("=" * 78)
    print("veredicto H-V4-10i:", status.upper() if status else "?")
    print("  NÚCLEO (apoyado, leakage-free): la relevancia ES discoverable bajo no-linealidad con una base EXPRESIVA (la lineal falla por ortogonalidad-de-paridad). RETRACTADOS por verificación adversarial: 'el prior paga' (artefacto de sub-regularización), 'no hay base fija universal' (un relu fijo es casi-universal), 'une R-VALOR con R-PRIOR' (puente no testeado). PRÓXIMO: testear R-PRIOR explícito.")
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
