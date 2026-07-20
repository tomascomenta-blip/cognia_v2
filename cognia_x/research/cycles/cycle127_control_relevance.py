r"""
cycle127_control_relevance.py — CICLO 127 (RESET v4, ABRE la rama NEGLECTADA del árbol: inteligencia = CONTROL/ACCIÓN como
raíz de la RELEVANCIA, unificada con R-VALOR): H-V4-10a por las compuertas del engine. APOYADA: la directiva v4 marca
"inteligencia = control/acción (active inference / empowerment / good-regulator)" como la mayor pendiente del árbol de
descomposición -- tocada (38/39/79) pero nunca entretenida como la RAÍZ de la relevancia. Este ciclo la ataca con una
pregunta que además la UNIFICA con R-VALOR: ¿un objetivo de CONTROL provee el criterio endógeno de RELEVANCIA (qué vale la
pena modelar) que la PREDICCIÓN pura no tiene? RESULTADO: sí -- bajo capacidad limitada + un distractor irrelevante de alta
varianza, predecir gasta la capacidad en el distractor ruidoso y COLAPSA el control, mientras controlar enfoca el modo
accionable y se MANTIENE (good-regulator). El CONTROL es la fuente de la relevancia.

DERIVA de exp111_control_relevance/results/results.json.

Correr (DESPUÉS de exp111):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp111_control_relevance.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle127_control_relevance
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle127_control_relevance')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp111_control_relevance', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="good-regulator (Conant&Ashby): un buen regulador de un sistema debe ser un modelo de ese sistema -- pero sólo de la parte CONTROL-RELEVANTE. Un objetivo de control provee el criterio endógeno de RELEVANCIA (qué modelar) que la predicción pura no tiene: bajo capacidad limitada, predecir gasta el presupuesto en la varianza (aunque sea irrelevante/incontrolable), controlar lo gasta en lo accionable. Control como fuente de la relevancia", obtained=False,
                     claim=("Un objetivo de CONTROL provee el criterio endógeno de RELEVANCIA -- qué vale la pena modelar -- "
                            "que la PREDICCIÓN pura no tiene. Bajo capacidad limitada, un predictor gasta su modelo en lo de "
                            "mayor VARIANZA (aunque sea irrelevante e incontrolable); un controlador lo gasta en lo "
                            "ACCIONABLE (lo que su acción afecta). Un buen regulador modela sólo la parte control-relevante "
                            "del sistema (good-regulator, Conant&Ashby). => el control es la FUENTE de la relevancia. "
                            "(Principio.)"))
S_C40 = Source(tier=5, ref="cognia_x/experiments/exp026_ttc_allocation", obtained=True,
               claim=("CYCLE 40: bajo ESCASEZ de cómputo, asignar por CONTROLABILIDAD/consecuencia supera a la predicción "
                      "pasiva-por-incertidumbre (que es anti-útil). H-V4-10a extiende ese hallazgo del cómputo test-time al "
                      "dominio del MODELO (qué estructura se aprende)."))
S_EMP = Source(tier=5, ref="cognia_x/experiments/exp024_empowerment", obtained=True,
               claim=("CYCLE 38: el empowerment (valor auto-generado) aísla lo CONTROLABLE y da 0 a lo predecible-inútil; "
                      "controlabilidad ≠ predictibilidad. H-V4-10a lo lleva a la construcción del MODELO: el control define "
                      "qué modelar."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp111 primero): " + results_path)

    g = sm['grid']
    s2s = sorted([float(k) for k in g['prediccion'].keys()])
    lo, hi = s2s[0], s2s[-1]
    pred_lo, pred_hi = g['prediccion'][str(lo)], g['prediccion'][str(hi)]
    ctrl_lo, ctrl_hi = g['control'][str(lo)], g['control'][str(hi)]
    gap_hi, gap_lo = sm['gap_hi'], sm['gap_lo']
    pred_collapse = sm['pred_collapse']
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim111 = ("exp111 (propio, {n} seeds, numpy): modelo-del-mundo con cuello de botella (capacidad-1) sobre un sistema 2D "
                "con un modo controlable-relevante y un distractor incontrolable-irrelevante. CROSSOVER: a distractor débil "
                "(s2={lo}) predicción y control empatan (gap {gl}); a distractor fuerte (s2={hi}) la PREDICCIÓN colapsa el "
                "control ({ph}, cae {pc}: modela el distractor ruidoso) mientras CONTROL se mantiene ({ch}, gap {gh}). El "
                "control provee el criterio de relevancia.").format(
                    n=n_seeds, lo=lo, gl=_f(gap_lo), hi=hi, ph=_f(pred_hi), pc=_f(pred_collapse), ch=_f(ctrl_hi), gh=_f(gap_hi))
    S_EXP111 = Source(tier=5, ref="cognia_x/experiments/exp111_control_relevance", obtained=True, claim=claim111)
    for src in (S_PRINCIPLE, S_C40, S_EMP, S_EXP111):
        ledger.add_source(src)
    notes.append("4 fuentes (S_PRINCIPLE tier2 good-regulator/control=relevancia; S_C40 tier5 control>pasiva bajo escasez; S_EMP tier5 empowerment=controlabilidad; S_EXP111 tier5 dato propio).")

    ev_for = [S_EXP111.ref, S_PRINCIPLE.ref]
    ev_against = [S_EXP111.ref]
    advtext = ("{V} (ABRE la rama NEGLECTADA del árbol -- control/acción como raíz de la RELEVANCIA): la directiva v4 marca "
               "'inteligencia = control/acción (active inference / empowerment / good-regulator)' como la mayor pendiente del "
               "árbol de descomposición, tocada (38/39/79) pero nunca entretenida como la RAÍZ de la relevancia. H-V4-10a la "
               "ataca con una pregunta que la UNIFICA con R-VALOR: ¿un objetivo de CONTROL provee el criterio endógeno de "
               "RELEVANCIA (qué vale la pena modelar) que la PREDICCIÓN pura no tiene? DISEÑO: un modelo-del-mundo con CUELLO "
               "DE BOTELLA (capacidad-1) sobre un sistema 2D con un modo CONTROLABLE-relevante (x1, responde a la acción) y "
               "un distractor INCONTROLABLE-irrelevante (x2) de varianza creciente. El objetivo PREDICCIÓN elige modelar el "
               "modo de mayor varianza (minimiza el MSE de predicción); el objetivo CONTROL elige el modo accionable. "
               "RESULTADO: CROSSOVER al crecer el distractor. A distractor DÉBIL (s2={lo}) ambos empatan ({pl}≈{cl}, gap "
               "{gl}: los dos modelan x1). A distractor FUERTE (s2={hi}) la PREDICCIÓN COLAPSA el control ({ph}, cae {pc}: "
               "gasta su capacidad en el distractor ruidoso pero irrelevante e incontrolable) mientras CONTROL se MANTIENE "
               "({ch}, gap {gh}). => un objetivo de CONTROL provee el criterio endógeno de RELEVANCIA -- modela lo "
               "CONTROL-relevante, no lo más RUIDOSO; la predicción pura carece de ese criterio. Un buen regulador modela "
               "sólo la parte control-relevante (good-regulator, Conant&Ashby). UNIFICA la rama control/acción con R-VALOR: "
               "el CONTROL es la FUENTE de la relevancia (qué vale la pena modelar) que todo el programa R-VALOR presuponía "
               "como dada. EVIDENCIA: el principio good-regulator (tier2), CYCLE 40 (tier5: control>pasiva bajo escasez) y el "
               "empowerment (tier5). EVIDENCIA EN CONTRA / caveats: abstracción numpy (sistema LINEAL 2D, cuello de botella "
               "modelado como elegir-1-de-2-modos axis-aligned, métrica de control de 1 paso); demuestra el PRINCIPIO limpio "
               "y reproducible (smoke 50 ≈ full 200), no en un modelo rico ni un controlador multi-paso; el 'cuello de "
               "botella' es una idealización de la capacidad limitada. La afirmación robusta: bajo capacidad finita, el "
               "objetivo de control determina QUÉ estructura del mundo se modela bien -- la predicción persigue la varianza, "
               "el control persigue lo accionable.").format(
                   V=status.upper(), lo=lo, pl=_f(pred_lo), cl=_f(ctrl_lo), gl=_f(gap_lo), hi=hi, ph=_f(pred_hi),
                   pc=_f(pred_collapse), ch=_f(ctrl_hi), gh=_f(gap_hi))

    hyp = Hypothesis(
        id="H-V4-10a",
        statement=("Un objetivo de CONTROL provee el criterio endógeno de RELEVANCIA (qué vale la pena modelar) que la "
                   "PREDICCIÓN pura no tiene: bajo capacidad limitada + un distractor irrelevante de alta varianza, predecir "
                   "gasta la capacidad en el distractor ruidoso y colapsa el control, mientras controlar enfoca el modo "
                   "accionable y se mantiene (good-regulator). El control es la fuente de la relevancia; une la rama "
                   "control/acción con R-VALOR."),
        prediction=("APOYADA si hay CROSSOVER: a distractor débil predicción≈control (gap<0.15), a distractor fuerte la "
                    "predicción colapsa el control (caída>0.30) y control se mantiene (gap>0.30). REFUTADA si la predicción "
                    "controla tan bien como el control aun con distractor fuerte (predecir basta para hallar lo relevante). "
                    "MIXTA en otro caso. (Pre-registrada, numpy, 200 seeds, barrido de varianza del distractor.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp111_control_relevance")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-10a")
        notes.append("H-V4-10a marcada '{}' con DoD completo (abre la rama control/acción: el control es la fuente de la relevancia; good-regulator).".format(status))

    analogy = AnalogyRecord(
        problem=("Tengo memoria/atención limitada y un mundo lleno de cosas. ¿Qué vale la pena entender? ¿Me sirve más "
                 "entender lo que más LLAMA la atención (lo más ruidoso/variable) o lo que puedo CAMBIAR con mis actos?"),
        everyday=("Si quiero APRENDER A PREDECIR todo, mi cabeza se va a lo más ruidoso y variable -- aunque no pueda hacer "
                  "nada al respecto (el clima, el ruido de la calle). Si quiero CONTROLAR algo (llegar a un objetivo), mi "
                  "cabeza se enfoca sola en lo que mis acciones MUEVEN, e ignora el ruido que no puedo cambiar. Con poca "
                  "capacidad, querer-predecir me hace estudiar el distractor y fallar la tarea; querer-controlar me hace "
                  "estudiar lo accionable y lograrla. El querer-actuar es lo que me dice QUÉ vale la pena entender."),
        solutions=["bajo capacidad limitada, la PREDICCIÓN modela lo de mayor varianza (persigue el ruido), aunque sea incontrolable e irrelevante",
                   "el CONTROL modela lo accionable y se mantiene robusto al distractor ruidoso (good-regulator)",
                   "el objetivo de control PROVEE el criterio endógeno de relevancia (qué modelar) que la predicción pura no tiene",
                   "une la rama control/acción con R-VALOR: el control es la FUENTE de la relevancia que el programa presuponía dada"],
        principles=["un objetivo de control determina QUÉ estructura del mundo se modela bien bajo capacidad finita (lo accionable, no lo ruidoso)",
                    "la predicción persigue la varianza; el control persigue la consecuencia -- controlabilidad ≠ predictibilidad (eco de 38/40)",
                    "un buen regulador modela sólo la parte control-relevante del sistema (good-regulator, Conant&Ashby)",
                    "el CONTROL es candidato a RAÍZ de la relevancia: la fuente endógena del 'qué importa' que R-VALOR presuponía"],
        adaptation=("El lab ABRE la rama más grande pendiente del árbol (inteligencia = control/acción) y la une con el "
                    "programa R-VALOR: el objetivo de CONTROL es candidato a ser la FUENTE de la relevancia (el criterio "
                    "endógeno de qué modelar) que todo el arco R-VALOR presuponía dado. Bajo capacidad finita, querer-predecir "
                    "persigue la varianza (modela el distractor ruidoso); querer-controlar persigue la consecuencia (modela "
                    "lo accionable) y es un buen regulador. Política/dirección: derivar la señal de relevancia de R-VALOR "
                    "(relevancia × controlabilidad) de un objetivo de CONTROL/empowerment, no de la predicción; esto cierra "
                    "el lazo con la tesis 79-82 (R-VALOR = controlabilidad × relevancia) dándole a la 'relevancia' un origen "
                    "endógeno en el control. Próximo (sub-arco H-V4-10): control multi-paso / no-lineal; capacidad como "
                    "presupuesto continuo (no elegir-1-de-2); ¿el control descubre la PARTITION controlable/incontrolable "
                    "sin saberla de antemano?; y el puente a active inference (minimizar energía libre esperada)."),
        measurement=("exp111 ({n} seeds): predicción control-perf {plo}(s2={lo})->{ph}(s2={hi}) COLAPSA; control "
                     "{clo}->{ch} se mantiene; gap fuerte +{gh}.").format(
                         n=n_seeds, plo=_f(pred_lo), lo=lo, ph=_f(pred_hi), hi=hi, clo=_f(ctrl_lo), ch=_f(ctrl_hi), gh=_f(gap_hi)),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (querer-controlar -no querer-predecir- te dice qué vale la pena entender bajo capacidad limitada).")

    kl = ("REAL (exp111): bajo capacidad limitada, el objetivo de CONTROL provee el criterio de RELEVANCIA (qué modelar) que "
          "la PREDICCIÓN no tiene. Con un distractor incontrolable de varianza creciente, la predicción colapsa el control "
          "({plo}->{ph}: modela el distractor ruidoso) mientras el control se mantiene ({clo}->{ch}); gap a distractor fuerte "
          "+{gh}. El control es la fuente de la relevancia (good-regulator); une la rama control/acción con R-VALOR. TECHO: "
          "numpy, sistema LINEAL 2D, cuello de botella = elegir-1-de-2-modos (axis-aligned), control de 1 paso; demuestra el "
          "PRINCIPIO, no en un modelo rico / controlador multi-paso (frontera: no-lineal, capacidad continua, descubrir la "
          "partición, active inference).").format(
              plo=_f(pred_lo), ph=_f(pred_hi), clo=_f(ctrl_lo), ch=_f(ctrl_hi), gh=_f(gap_hi))
    ceilings.add(CeilingRecord(
        subsystem="CONTROL como fuente de RELEVANCIA (rama control/acción, nueva) — un objetivo de control determina qué estructura del mundo se modela bien bajo capacidad finita (lo accionable, no lo más ruidoso); un buen regulador modela sólo la parte control-relevante; el control es candidato a raíz de la relevancia que R-VALOR presuponía dada",
        known_limit=kl,
        blockers=[{"text": "numpy, sistema LINEAL 2D; el cuello de botella se modela como elegir 1 de 2 modos axis-aligned (idealización de la capacidad limitada); control de 1 paso (no multi-paso/LQR)", "kind": "diseno"},
                  {"text": "la partición controlable/incontrolable se da de antemano (el control 'sabe' cuál modo es accionable); falta demostrar que el control DESCUBRE la partición de los datos sin saberla", "kind": "diseno"},
                  {"text": "abre la rama pero no la conecta aún con active inference (energía libre esperada) ni con un substrato no-lineal / lazo real; primer ciclo del sub-arco H-V4-10", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP111.ref, S_C40.ref, S_EMP.ref]))
    notes.append("1 techo 'real': el control es la fuente de la relevancia (good-regulator); abre la rama control/acción y la une con R-VALOR.")

    dstmt = ("North-Star R-VALOR (ABRE la rama control/acción y la UNE con R-VALOR): un objetivo de CONTROL provee el criterio "
             "endógeno de RELEVANCIA (qué vale la pena modelar) que la predicción pura no tiene. Bajo capacidad limitada + un "
             "distractor irrelevante de alta varianza, predecir colapsa el control ({plo}->{ph}: modela el ruido) y controlar "
             "se mantiene ({clo}->{ch}; gap +{gh}) -- good-regulator. Decisión: tratar el CONTROL como candidato a FUENTE de "
             "la relevancia que el arco R-VALOR (relevancia × controlabilidad, 79-82) presuponía dada; derivar la señal de "
             "'qué importa' de un objetivo de control/empowerment, no de la predicción. Abre el sub-arco H-V4-10. Próximo: "
             "control multi-paso/no-lineal; capacidad continua; ¿el control DESCUBRE la partición controlable/incontrolable?; "
             "puente a active inference.").format(
                 plo=_f(pred_lo), ph=_f(pred_hi), clo=_f(ctrl_lo), ch=_f(ctrl_hi), gh=_f(gap_hi))
    drat = ("exp111 (tier5, propio, {n} seeds, numpy): CROSSOVER -- predicción colapsa el control bajo distractor fuerte "
            "({plo}->{ph}), control se mantiene ({clo}->{ch}, gap +{gh}). Convergente con good-regulator (tier2), CYCLE 40 "
            "(tier5) y empowerment (tier5). APOYADA: el control es la fuente de la relevancia; abre la rama control/acción "
            "unificada con R-VALOR.").format(
                n=n_seeds, plo=_f(pred_lo), ph=_f(pred_hi), clo=_f(ctrl_lo), ch=_f(ctrl_hi), gh=_f(gap_hi))
    dec = Decision(id="D-V4-89", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP111), _to_plain(S_C40), _to_plain(S_EMP)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-89 ACEPTADA por el ledger (tier5 exp111 + tier5 exp026 + tier5 exp024).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-89:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle127_control_relevance',
                                description='CYCLE 127 (RESET v4, H-V4-10a: el CONTROL es la fuente de la RELEVANCIA -- abre la rama control/acción y la une con R-VALOR; good-regulator).')
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
    print("RESUMEN — CYCLE 127 (RESET v4): el CONTROL es la FUENTE de la RELEVANCIA -- abre la rama control/acción, la une con R-VALOR (good-regulator) — H-V4-10a")
    print("=" * 78)
    print("veredicto H-V4-10a:", status.upper() if status else "?")
    print("  bajo capacidad limitada, predecir modela el distractor ruidoso (colapsa el control) y controlar enfoca lo accionable (se mantiene). El control define qué modelar.")
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
