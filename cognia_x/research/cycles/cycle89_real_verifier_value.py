r"""
cycle89_real_verifier_value.py — CICLO 89 (RESET v4, rama R-VALOR, EL SALTO GRANDE — gaps #1/#3): H-V4-7g por las
compuertas del engine. APOYADA: la política R-VALOR del arco gap #2 (aprender un combinador barato + asignar el feedback
ESCASO por él) SOBREVIVE el salto de un valor SINTÉTICO SUAVE (g=min/max) a un VERIFICADOR CHEQUEABLE REAL — el sandbox
de exp018 EJECUTA el candidato y decide v ∈ {0,1}. Bajo STRONG (verificador fuerte: operador Y valor==target) el valor
es conjuntivo, E[v|c,r]=c·r, el PRODUCTO es Bayes-óptimo y el aprendido lo IGUALA (no-regret Δ≈-0.011); bajo WEAK
(acepta el echo) E[v|c,r]=r, el producto mis-rankea los echoes (high-r/low-c) y el aprendido RECUPERA (+0.106,
relevancia-dominancia, paralelo REAL al régimen 'sustitutos' del gap #2). El feedback DISCRETO (Bernoulli) NO rompe el
aprendizaje (>> chance), y greedy NO se atrapa bajo feedback costoso/action-gated (confirma 87-88 con valor real).
CAVEAT HONESTO: la ESPERANZA del valor sigue siendo SUAVE y nesteable por el poly2 (el generador es sintético); se probó
que la VARIANZA Bernoulli del verificador real no rompe el mecanismo, NO un target cuya media condicional el poly2 no
pueda nestar -> genera la siguiente hija (H-V4-7h: media no-nesteable / generador de modelo real).

DERIVA de exp073_real_verifier_value/results/results.json.

Correr (DESPUÉS de exp073):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp073_real_verifier_value.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle89_real_verifier_value
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle89_real_verifier_value')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp073_real_verifier_value', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="un verificador chequeable es CONJUNTIVO en (estructura, valor); la regresión sobre la media condicional absorbe la varianza Bernoulli del veredicto discreto", obtained=False,
                     claim=("Un verificador que ejecuta y chequea valor==target es intrínsecamente CONJUNTIVO en "
                            "(bien-formado/operador, valor-correcto): exige AMBOS -> bajo el fuerte E[v|c,r]=c·r (el "
                            "producto es Bayes-óptimo, complementos); relajar la estructura (aceptar el echo, débil) lo "
                            "vuelve relevancia-dominante E[v|c,r]=r (el producto mis-rankea). Un regresor de mínimos "
                            "cuadrados sobre el veredicto discreto {0,1} estima la MEDIA condicional; la varianza "
                            "Bernoulli sólo añade ruido de muestreo que más feedback promedia. (Principio.)"))
S_EXP072 = Source(tier=5, ref="cognia_x/experiments/exp072_support_concentration", obtained=True,
                  claim=("CYCLE 83-88 validó la política R-VALOR (combinador aprendido nesta el producto; always-learn/"
                         "greedy robusta bajo feedback action-gated) PERO con un valor SINTÉTICO SUAVE (g=min/max) que el "
                         "poly2 nesta. Caveat: g sintético. H-V4-7g quita esa muleta usando el verificador REAL exp018."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp073 primero): " + results_path)

    nr = sm['noregret_strong']
    rc = sm['recover_weak']
    ts = sm['greedy_trap_strong']
    tw = sm['greedy_trap_weak']
    las = sm['learn_alive_strong']
    law = sm['learn_alive_weak']
    ogs = sm['oracle_gap_strong']
    ogw = sm['oracle_gap_weak']
    g = sm['grid']
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim073 = ("exp073 (propio, {n} seeds, numpy + sandbox exp018): la política R-VALOR SOBREVIVE el verificador REAL. "
                "STRONG (E[v]=c·r, producto Bayes-óptimo): greedy={lgs} ≈ product={ps} (no-regret Δ={nr}). WEAK "
                "(E[v]=r, producto mis-rankea echoes): greedy={lgw} > product={pw} (recupera +{rc}). Feedback DISCRETO "
                "no rompe el aprendizaje (>> chance: +{las}/+{law}); greedy sin trampa (S={ts}/W={tw}); gap al oracle "
                "S={ogs}/W={ogw}.").format(
                    n=n_seeds, lgs=_f(g['strong']['learned_greedy']), ps=_f(g['strong']['product']), nr=_f(nr),
                    lgw=_f(g['weak']['learned_greedy']), pw=_f(g['weak']['product']), rc=_f(rc),
                    las=_f(las), law=_f(law), ts=_f(ts), tw=_f(tw), ogs=_f(ogs), ogw=_f(ogw))
    S_EXP073 = Source(tier=5, ref="cognia_x/experiments/exp073_real_verifier_value", obtained=True, claim=claim073)
    for src in (S_PRINCIPLE, S_EXP072, S_EXP073):
        ledger.add_source(src)
    notes.append("3 fuentes (S_PRINCIPLE tier2 verificador-conjuntivo/media-condicional; S_EXP072 tier5 muleta del g suave; S_EXP073 tier5 dato propio).")

    ev_for = [S_EXP073.ref]
    ev_against = [S_EXP073.ref, S_EXP072.ref, S_PRINCIPLE.ref]
    advtext = ("{V} (EL SALTO GRANDE, gaps #1/#3): el arco gap #2 (83-88) construyó R-VALOR=control×relevancia con un "
               "valor SINTÉTICO SUAVE (g=min/max) que el poly2 nesta -- el caveat más repetido. H-V4-7g lo aterriza en un "
               "VERIFICADOR CHEQUEABLE REAL (el sandbox de exp018 EJECUTA el candidato; v ∈ {{0,1}}, valor DISCRETO no "
               "decidido por una fórmula). RESULTADO: la política SOBREVIVE. (1) STRONG (verificador fuerte: operador Y "
               "valor==target -> conjuntivo, E[v|c,r]=c·r): el PRODUCTO es Bayes-óptimo y el aprendido lo IGUALA "
               "(no-regret, greedy={lgs} vs product={ps}, Δ={nr}, |Δ|<=0.02). (2) WEAK (acepta el echo del target sin "
               "operador -> E[v|c,r]=r): el producto MIS-RANKEA los echoes (high-r/low-c) y el aprendido RECUPERA "
               "(greedy={lgw} > product={pw}, +{rc}>0.03) -- paralelo REAL al régimen 'sustitutos' del gap #2, pero por "
               "RELEVANCIA-DOMINANCIA vía la rama echo (reward-hack de exp018), no por un g=max de juguete. (3) El "
               "feedback DISCRETO (Bernoulli) NO rompe el aprendizaje del combinador (>> chance: +{las}/+{law}). (4) Bajo "
               "feedback COSTOSO/action-gated (presupuesto K=10 por ronda) greedy NO se atrapa (trap S={ts}/W={tw} <= "
               "0.03), confirmando 87-88 ahora con valor REAL. => el mecanismo del arco NO era un artefacto del g suave. "
               "EVIDENCIA EN CONTRA / CAVEAT HONESTO (lo que NO prueba): la ESPERANZA del valor E[v|c,r] sigue siendo "
               "SUAVE y NESTEABLE por el poly2 (c·r y r son sus features), porque el GENERADOR de candidatos es sintético "
               "(latentes c,r -> Bernoulli); se probó que la VARIANZA Bernoulli del verificador real no rompe el "
               "mecanismo, NO un target cuya MEDIA condicional el poly2 no pueda nestar. Además el gap al oracle en strong "
               "es grande ({ogs}: positivos escasos c·r, sin saturación trivial). => salto SMOOTH→DISCRETE cerrado; el "
               "salto a media NO-NESTEABLE / generador de MODELO real queda para la hija H-V4-7h.").format(
                   V=status.upper(), lgs=_f(g['strong']['learned_greedy']), ps=_f(g['strong']['product']), nr=_f(nr),
                   lgw=_f(g['weak']['learned_greedy']), pw=_f(g['weak']['product']), rc=_f(rc),
                   las=_f(las), law=_f(law), ts=_f(ts), tw=_f(tw), ogs=_f(ogs))

    hyp = Hypothesis(
        id="H-V4-7g",
        statement=("La política R-VALOR del gap #2 (combinador aprendido nesta el producto; asignación del feedback "
                   "escaso/costoso por el valor estimado) SOBREVIVE el salto de un valor sintético SUAVE a un VERIFICADOR "
                   "CHEQUEABLE REAL (sandbox exp018, valor discreto): no-regret donde el producto es Bayes-óptimo "
                   "(strong/conjuntivo) y recupera donde el producto mis-rankea (weak/relevancia-dom), sin que el feedback "
                   "discreto rompa el aprendizaje."),
        prediction=("APOYADA si strong no-regret (|Δ|<=0.02) Y weak recover (>+0.03) Y greedy sin trampa (<=random+0.03) "
                    "Y aprendizaje vivo (>> chance +0.05); REFUTADA si el valor discreto rompe el aprendizaje (learned ≈ "
                    "chance); MIXTA en otro caso. (Pre-registrada, sandbox real exp018, 48 seeds.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp073_real_verifier_value")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-7g")
        notes.append("H-V4-7g marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("Aprendí a apostar a qué vale la pena con un termómetro de juguete (un número suave que yo mismo "
                 "inventé). ¿Mi instinto sirve cuando el juez de verdad sólo dice SÍ o NO -- y revisar cuesta, así que "
                 "sólo puedo revisar unos pocos?"),
        everyday=("Sí: el juez real (probar la receta y ver si sale) sólo da un sí/no, pero si lo aplico a varias "
                  "tandas mi instinto promedia el ruido y aprende la regla igual. Donde 'rico' = 'bien hecho Y "
                  "sabroso' (ambos), multiplicar mis dos corazonadas ya es lo óptimo; donde basta con que ESTÉ rico "
                  "aunque no lo haya cocinado bien (el atajo), multiplicar me hace tirar buenas opciones -- ahí "
                  "aprender la regla de nuevo las recupera. Y elegir 'lo que creo mejor' para gastar mis pocas pruebas "
                  "no me atrapa."),
        solutions=["strong (rico = bien hecho Y sabroso): multiplicar las dos corazonadas = óptimo; aprender lo iguala",
                   "weak (basta con que esté sabroso, vale el atajo): multiplicar tira el atajo; aprender lo recupera (+0.106)",
                   "el juez sí/no (discreto) no rompe el instinto: promediar varias tandas absorbe el ruido",
                   "gastar las pocas pruebas en 'lo mejor' (greedy) no atrapa; explorar no hace falta"],
        principles=["un verificador real es CONJUNTIVO (estructura Y valor); el producto es Bayes-óptimo ahí",
                    "relajar la estructura (aceptar el atajo/echo) lo vuelve relevancia-dominante; el producto mis-rankea, el aprendido recupera",
                    "la regresión sobre el veredicto discreto estima la media condicional; la varianza Bernoulli se promedia con más feedback",
                    "la política R-VALOR (aprender + asignar greedy el feedback costoso) no era artefacto del valor suave"],
        adaptation=("El lab confirma que la política gap #2 (combinador aprendido que nesta el producto; always-learn/"
                    "greedy bajo feedback costoso) sobrevive el salto a un verificador chequeable REAL con valor discreto. "
                    "Cierra el caveat 'g sintético suave' del arco 83-88 para el eje SMOOTH→DISCRETE. Vigila el caveat "
                    "restante: la MEDIA del valor sigue nesteable por el poly2 (generador sintético). Próximo (la hija "
                    "H-V4-7h): un target cuya media condicional el poly2 NO nesta (umbral agudo / no-monotonía) y/o un "
                    "GENERADOR de modelo real (exp018) cuyo E[v|features-de-superficie] sea arbitrario; y SCALE (GPU)."),
        measurement=("exp073 ({n} seeds, sandbox exp018): strong no-regret Δ={nr}; weak recover +{rc}; trap S={ts}/W={tw}; "
                     "alive +{las}/+{law}; oracle gap S={ogs}/W={ogw}.").format(
                         n=n_seeds, nr=_f(nr), rc=_f(rc), ts=_f(ts), tw=_f(tw), las=_f(las), law=_f(law),
                         ogs=_f(ogs), ogw=_f(ogw)),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (el instinto de juguete sirve cuando el juez real sólo dice sí/no y revisar cuesta).")

    kl = ("REAL (exp073): la política R-VALOR del gap #2 sobrevive el salto a un VERIFICADOR CHEQUEABLE REAL (sandbox "
          "exp018, valor discreto v∈{{0,1}}). STRONG (conjuntivo, E[v]=c·r): producto Bayes-óptimo, aprendido lo iguala "
          "(no-regret Δ={nr}). WEAK (relevancia-dom por la rama echo, E[v]=r): producto mis-rankea, aprendido recupera "
          "(+{rc}). Feedback discreto no rompe el aprendizaje (>> chance); greedy no se atrapa bajo feedback costoso. "
          "TECHO: la media condicional E[v|features] sigue SUAVE y nesteable por el poly2 (generador sintético); falta un "
          "target NO-nesteable y un generador de modelo real.").format(nr=_f(nr), rc=_f(rc))
    ceilings.add(CeilingRecord(
        subsystem="R-VALOR sobre un verificador chequeable REAL (sandbox exp018) — la política gap #2 sobrevive el salto smooth→discrete (no-regret strong, recupera weak)",
        known_limit=kl,
        blockers=[{"text": "la ESPERANZA del valor E[v|c,r] sigue SUAVE y nesteable por el poly2 (c·r, r), porque el generador de candidatos es sintético (latentes c,r -> Bernoulli); se probó la varianza discreta, NO una media condicional no-nesteable (umbral agudo / no-monotonía)", "kind": "diseno"},
                  {"text": "el generador de candidatos es sintético; falta un GENERADOR de MODELO real (exp018 HybridLM) cuyo E[v|features-de-superficie] sea arbitrario y la dinámica sea un lazo cerrado de entrenamiento (verificado-correcto -> training -> el generador cambia)", "kind": "diseno"},
                  {"text": "objetivo escalar (perf_of), espacio 2D de features, presupuesto K fijo sin costo monetario; falta dinámica secuencial donde la elección afecte el estado futuro y SCALE (GPU)", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP073.ref, S_EXP072.ref]))
    notes.append("1 techo 'real': la política R-VALOR sobrevive el verificador real (smooth→discrete); el techo restante es la media no-nesteable + generador de modelo real.")

    dstmt = ("North-Star R-VALOR (EL SALTO GRANDE, gaps #1/#3 — primer aterrizaje en un verificador REAL): la política "
             "del arco gap #2 (combinador aprendido nesta el producto; always-learn/greedy bajo feedback costoso) "
             "SOBREVIVE el salto de un valor sintético SUAVE a un VERIFICADOR CHEQUEABLE REAL (sandbox exp018, valor "
             "discreto). Decisión: el lab CONFIRMA que el mecanismo del arco 83-88 no era artefacto del g suave -- vale "
             "con un juez real conjuntivo (producto Bayes-óptimo en strong) y con su relajación al echo (relevancia-dom "
             "en weak, donde el aprendido recupera). El feedback discreto no rompe el aprendizaje; greedy no se atrapa. "
             "Vigila el caveat: la media del valor sigue nesteable (generador sintético). Próximo: H-V4-7h (media "
             "NO-nesteable / generador de modelo real, lazo cerrado de entrenamiento) y SCALE (GPU).")
    drat = ("exp073 (tier5, propio, {n} seeds, numpy + sandbox exp018): strong no-regret Δ={nr} (|Δ|<=0.02); weak recover "
            "+{rc} (>0.03); greedy sin trampa (S={ts}/W={tw}); aprendizaje vivo (+{las}/+{law} vs chance). Convergente con "
            "el principio verificador-conjuntivo/media-condicional (tier2) y con la política gap #2 de CYCLE 86 (tier5). "
            "APOYADA la supervivencia smooth→discrete.").format(
                n=n_seeds, nr=_f(nr), rc=_f(rc), ts=_f(ts), tw=_f(tw), las=_f(las), law=_f(law))
    dec = Decision(id="D-V4-51", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP073), _to_plain(S_EXP072)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-51 ACEPTADA por el ledger (tier5 exp073 + tier5 exp072).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-51:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle89_real_verifier_value',
                                description='CYCLE 89 (RESET v4, H-V4-7g: la política R-VALOR sobrevive el salto a un verificador chequeable REAL -- APOYADA; EL SALTO GRANDE gaps #1/#3).')
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
    print("RESUMEN — CYCLE 89 (RESET v4): la política R-VALOR sobrevive el VERIFICADOR REAL (H-V4-7g) — EL SALTO GRANDE")
    print("=" * 78)
    print("veredicto H-V4-7g:", status.upper() if status else "?")
    print("  strong: producto Bayes-óptimo, aprendido lo iguala (no-regret); weak: aprendido recupera la relevancia-dom; discreto no rompe; greedy no atrapa.")
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
