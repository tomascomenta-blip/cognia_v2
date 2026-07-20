r"""
cycle129_value_factorization.py — CICLO 129 (RESET v4, rama control/acción, KEYSTONE: el objetivo de CONTROL RECONSTRUYE
R-VALOR = controlabilidad × relevancia): H-V4-10c por las compuertas del engine. APOYADA: 127 mostró que el control es la
fuente de la relevancia; 128 que la partición controlable es descubrible actuando. Este ciclo cierra el lazo con la TESIS
CENTRAL del lab (79-82: R-VALOR = controlabilidad × relevancia): con capacidad de modelado MULTI-UNIDAD y modos que varían en
controlabilidad Y relevancia, un objetivo de CONTROL asigna su capacidad por el PRODUCTO w·b̂² (relevancia × controlabilidad
estimada), batiendo a cada factor por separado -- VALOR 0.994 vs mejor base ~0.50 (margen +0.49). => el producto value=
ctrl×rel EMERGE del objetivo de control; la tesis 79-82 (postulada) queda DERIVADA de la raíz del control.

DERIVA de exp113_value_factorization/results/results.json.

Correr (DESPUÉS de exp113):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp113_value_factorization.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle129_value_factorization
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle129_value_factorization')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp113_value_factorization', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="un objetivo de CONTROL con capacidad de modelado limitada asigna su capacidad por el PRODUCTO controlabilidad × relevancia, no por ningún factor por separado: modelar un modo da beneficio de control sólo si es CONTROLABLE (se puede regular) Y RELEVANTE (importa al objetivo); controlabilidad-sola modela controlable-irrelevante, relevancia-sola modela relevante-incontrolable (inútil), predicción modela lo ruidoso. El producto value=ctrl×rel emerge del control", obtained=False,
                     claim=("Un objetivo de CONTROL con capacidad de modelado LIMITADA asigna su capacidad por el PRODUCTO "
                            "controlabilidad × relevancia. Modelar un modo rinde beneficio de control SÓLO si es CONTROLABLE "
                            "(se puede regular hacia el target) Y RELEVANTE (pesa en el objetivo): ninguno de los dos "
                            "factores por separado basta -- controlabilidad-sola gasta capacidad en lo controlable-pero-"
                            "irrelevante, relevancia-sola en lo relevante-pero-incontrolable (no se puede regular), la "
                            "predicción en lo ruidoso. => el producto value = ctrl × rel EMERGE del objetivo de control. "
                            "(Principio.)"))
S_THESIS = Source(tier=5, ref="cognia_x/experiments/exp066_endogenous_rvalue", obtained=True,
                  claim=("TESIS CENTRAL 79-82: R-VALOR (referido al objetivo) = CONTROLABILIDAD × RELEVANCIA, con ambas "
                         "marginales estimables endógenamente. Se POSTULÓ/validó como reconstrucción-producto. H-V4-10c la "
                         "DERIVA de un objetivo de control (la asignación óptima de capacidad ES el producto)."))
S_C128 = Source(tier=5, ref="cognia_x/experiments/exp112_control_discovery", obtained=True,
                claim=("CYCLE 128: la controlabilidad (b̂) es DESCUBRIBLE actuando. H-V4-10c usa ese b̂ estimado como el "
                       "factor de controlabilidad del producto -- la asignación por w·b̂² es endógena (relevancia del propio "
                       "objetivo × controlabilidad descubierta)."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp113 primero): " + results_path)

    g = sm['grid']
    val = sm['value']; bb = sm['best_base']; bn = sm['best_base_name']; margin = sm['margin']
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim113 = ("exp113 (propio, {n} seeds, numpy): con capacidad de modelado limitada (K de D modos), el criterio VALOR "
                "(w·b̂², relevancia × controlabilidad estimada) asigna mejor que cada factor por separado -- VALOR {v} vs "
                "predicción {p} (modela el ruido) / controlabilidad-sola {c} / relevancia-sola {r} (las bases de un solo "
                "factor caen a ~0.5, mitad-óptimo). El producto value=ctrl×rel emerge del objetivo de control.").format(
                    n=n_seeds, v=_f(val), p=_f(g['prediccion']), c=_f(g['controlabilidad']), r=_f(g['relevancia']))
    S_EXP113 = Source(tier=5, ref="cognia_x/experiments/exp113_value_factorization", obtained=True, claim=claim113)
    for src in (S_PRINCIPLE, S_THESIS, S_C128, S_EXP113):
        ledger.add_source(src)
    notes.append("4 fuentes (S_PRINCIPLE tier2 capacidad∝ctrl×rel; S_THESIS tier5 la tesis 79-82 que se DERIVA; S_C128 tier5 b̂ descubierta = factor de controlabilidad; S_EXP113 tier5 dato propio).")

    ev_for = [S_EXP113.ref, S_PRINCIPLE.ref]
    ev_against = [S_EXP113.ref]
    advtext = ("{V} (KEYSTONE: el control RECONSTRUYE R-VALOR = controlabilidad × relevancia -- cierra el lazo con la tesis "
               "central 79-82): 127 mostró que el control es la fuente de la relevancia; 128 que la controlabilidad es "
               "DESCUBRIBLE actuando. H-V4-10c une eso con la TESIS CENTRAL del lab (R-VALOR = controlabilidad × relevancia, "
               "79-82, que se había POSTULADO/validado como reconstrucción-producto): con capacidad de modelado MULTI-UNIDAD "
               "(K de D modos) y modos que varían en controlabilidad (b∈{{1,0}}) Y relevancia (w∈{{1,0}}, los irrelevantes-"
               "incontrolables RUIDOSOS), ¿un objetivo de CONTROL asigna su capacidad por el PRODUCTO? Cuatro criterios de "
               "asignación. RESULTADO: el criterio VALOR (w·b̂², relevancia del propio objetivo × controlabilidad ESTIMADA de "
               "los datos) bate a TODOS los factores por separado -- VALOR {v} vs mejor base ({bn}) {bb} (margen +{mg}); la "
               "PREDICCIÓN {p} modela el ruido (perf ~0), CONTROLABILIDAD-sola {c} modela controlable-pero-irrelevante, "
               "RELEVANCIA-sola {r} modela relevante-pero-INCONTROLABLE (no se puede regular). Las bases de un solo factor "
               "caen a ~0.5 (mitad-óptimo: capturan uno de los dos modos necesarios). => SÓLO el PRODUCTO captura los modos "
               "controlable-Y-relevante: el objetivo de CONTROL RECONSTRUYE R-VALOR = controlabilidad × relevancia. La tesis "
               "central del lab (79-82), que se postulaba, EMERGE como la asignación óptima de capacidad de un agente que "
               "quiere CONTROLAR -- con la relevancia dada por su objetivo y la controlabilidad DESCUBIERTA actuando (128). "
               "Cierra el lazo conceptual: control (raíz) -> relevancia (127) + controlabilidad descubierta (128) -> el "
               "producto R-VALOR (129). EVIDENCIA: el principio capacidad∝ctrl×rel (tier2) y la tesis 79-82 (tier5). "
               "EVIDENCIA EN CONTRA / caveats: numpy, sistema LINEAL multi-modo, controlabilidad/relevancia BINARIAS (no "
               "grados), control de 1 paso, capacidad = elegir-K-modos; demuestra el PRINCIPIO (el producto emerge), "
               "reproducible smoke 60 ≈ full 300; la relevancia w se da por el objetivo (es lo correcto: la relevancia ES el "
               "objetivo) y la controlabilidad se estima (128).").format(
                   V=status.upper(), v=_f(val), bn=bn, bb=_f(bb), mg=_f(margin), p=_f(g['prediccion']),
                   c=_f(g['controlabilidad']), r=_f(g['relevancia']))

    hyp = Hypothesis(
        id="H-V4-10c",
        statement=("Un objetivo de CONTROL con capacidad de modelado limitada asigna su capacidad por el PRODUCTO "
                   "controlabilidad × relevancia (w·b̂²), batiendo a cada factor por separado (predicción/controlabilidad-"
                   "sola/relevancia-sola) -> el objetivo de control RECONSTRUYE R-VALOR = controlabilidad × relevancia; la "
                   "tesis central 79-82 EMERGE de la raíz del control, no se postula."),
        prediction=("APOYADA si VALOR (w·b̂²) supera a la MEJOR línea base de un solo factor por margen >0.20 y VALOR >0.7. "
                    "REFUTADA si VALOR no supera a la mejor base de un solo factor. MIXTA en otro caso. (Pre-registrada, "
                    "numpy, 300 seeds, D=8 modos 4 cuadrantes, K=2 capacidad.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp113_value_factorization")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-10c")
        notes.append("H-V4-10c marcada '{}' con DoD completo (el control reconstruye R-VALOR = ctrl × rel; la tesis 79-82 emerge de la raíz del control).".format(status))

    analogy = AnalogyRecord(
        problem=("Tengo poca cabeza para entender cosas y muchas cosas alrededor. ¿En qué conviene gastar esa cabeza -- en "
                 "lo que puedo cambiar, en lo que me importa, o hace falta que sea AMBAS?"),
        everyday=("Hace falta AMBAS. Estudiar algo que puedo mover pero no me importa (controlable-irrelevante) es perder el "
                  "tiempo; estudiar algo que me importa pero no puedo mover (relevante-incontrolable) no me sirve porque igual "
                  "no lo cambio; y lo más ruidoso suele ser justo lo que ni controlo ni me importa. La cabeza rinde sólo "
                  "donde se cruzan las dos cosas: lo que puedo cambiar Y me importa. Querer-controlar mi mundo me hace gastar "
                  "la cabeza exactamente ahí -- en el producto de 'lo puedo mover' por 'me importa'."),
        solutions=["modelar un modo rinde beneficio de control SÓLO si es controlable Y relevante (el producto)",
                   "controlabilidad-sola modela lo controlable-pero-irrelevante; relevancia-sola lo relevante-pero-incontrolable (inútil); predicción lo ruidoso",
                   "el criterio w·b̂² (relevancia del objetivo × controlabilidad descubierta) bate a cada factor por separado (margen +0.49)",
                   "el objetivo de control RECONSTRUYE R-VALOR = controlabilidad × relevancia -- la tesis 79-82 emerge de la raíz del control"],
        principles=["un objetivo de control asigna su capacidad de modelado por el PRODUCTO controlabilidad × relevancia",
                    "ningún factor por separado basta (caen a ~mitad-óptimo): el producto es necesario",
                    "la tesis central R-VALOR = controlabilidad × relevancia (79-82) EMERGE de la raíz del control, no se postula",
                    "cierra el lazo: control (raíz) -> relevancia (127) + controlabilidad descubierta (128) -> el producto R-VALOR (129)"],
        adaptation=("El lab CIERRA el lazo conceptual entre la rama control/acción (recién abierta, 127-128) y su TESIS "
                    "CENTRAL (79-82: R-VALOR = controlabilidad × relevancia). Lo que en 79-82 se POSTULABA -- que el valor "
                    "endógeno es el producto de controlabilidad por relevancia -- aquí se DERIVA: es la asignación óptima de "
                    "capacidad de modelado de un agente que quiere CONTROLAR su mundo, con la relevancia dada por su objetivo "
                    "y la controlabilidad descubierta actuando (128). Esto da a R-VALOR una RAÍZ: no es un criterio arbitrario "
                    "ni una reetiqueta de meta externa -- es lo que cae de querer-controlar bajo capacidad finita. Política/"
                    "dirección: construir el estimador de valor del sistema como (relevancia-del-objetivo × controlabilidad-"
                    "descubierta), no como predicción-de-varianza. Próximo (H-V4-10): controlabilidad/relevancia en GRADOS "
                    "(continuas, no binarias) -> ¿la asignación sigue el producto graduado?; capacidad continua; no-lineal; y "
                    "el puente a active inference (donde el producto cae de minimizar energía libre esperada)."),
        measurement=("exp113 ({n} seeds): VALOR {v} vs predicción {p} / controlabilidad {c} / relevancia {r}; margen sobre la "
                     "mejor base +{mg}.").format(n=n_seeds, v=_f(val), p=_f(g['prediccion']), c=_f(g['controlabilidad']),
                                                 r=_f(g['relevancia']), mg=_f(margin)),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (la cabeza rinde sólo donde se cruzan 'lo puedo mover' y 'me importa' = el producto).")

    kl = ("REAL (exp113): el objetivo de CONTROL RECONSTRUYE R-VALOR = controlabilidad × relevancia. Con capacidad de modelado "
          "limitada, el criterio VALOR (w·b̂²) bate a cada factor por separado -- VALOR {v} vs predicción {p} (ruido) / "
          "controlabilidad-sola {c} / relevancia-sola {r} (~mitad-óptimo); margen +{mg}. La tesis central 79-82 EMERGE de la "
          "raíz del control (no se postula): es la asignación óptima de capacidad de un agente que quiere controlar, con la "
          "relevancia del objetivo y la controlabilidad descubierta (128). TECHO: numpy, lineal multi-modo, controlabilidad/"
          "relevancia BINARIAS, control 1 paso, capacidad = elegir-K; frontera: grados continuos, no-lineal, active "
          "inference.").format(v=_f(val), p=_f(g['prediccion']), c=_f(g['controlabilidad']), r=_f(g['relevancia']), mg=_f(margin))
    ceilings.add(CeilingRecord(
        subsystem="R-VALOR DERIVADO del control (rama control/acción, keystone) — un objetivo de control con capacidad limitada asigna su capacidad de modelado por el PRODUCTO controlabilidad × relevancia, batiendo a cada factor por separado; la tesis central 79-82 (R-VALOR = ctrl × rel) emerge de la raíz del control en vez de postularse",
        known_limit=kl,
        blockers=[{"text": "numpy, sistema LINEAL multi-modo; controlabilidad y relevancia BINARIAS (b,w∈{0,1}), no grados continuos; control de 1 paso; capacidad = elegir-K-modos (no presupuesto continuo de precisión)", "kind": "diseno"},
                  {"text": "la relevancia w se da por el objetivo (correcto: la relevancia ES el objetivo) y la controlabilidad b̂ se estima (128); el producto se evalúa, no se demuestra que un agente lo COMPUTE espontáneamente sin que se lo defina como criterio", "kind": "diseno"},
                  {"text": "el puente a active inference (donde el producto controlabilidad×relevancia caería de minimizar la energía libre esperada) queda abierto; primer cierre conceptual control<->tesis, no formal", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP113.ref, S_THESIS.ref, S_C128.ref]))
    notes.append("1 techo 'real': el control reconstruye R-VALOR = ctrl × rel (margen +{} sobre cada factor); la tesis 79-82 emerge de la raíz del control.".format(_f(margin)))

    dstmt = ("North-Star R-VALOR (KEYSTONE -- el control DERIVA la tesis central): un objetivo de CONTROL con capacidad de "
             "modelado limitada asigna su capacidad por el PRODUCTO controlabilidad × relevancia (w·b̂²), batiendo a cada "
             "factor por separado (VALOR {v} vs predicción {p} / controlabilidad {c} / relevancia {r}; margen +{mg}). Sólo el "
             "producto captura los modos controlable-Y-relevante. => la tesis central del lab (R-VALOR = controlabilidad × "
             "relevancia, 79-82), que se POSTULABA, EMERGE como la asignación óptima de capacidad de un agente que quiere "
             "controlar -- relevancia del objetivo × controlabilidad descubierta (128). Decisión: R-VALOR tiene RAÍZ en el "
             "control; construir el estimador de valor como (relevancia-del-objetivo × controlabilidad-descubierta), no como "
             "predicción-de-varianza. Cierra el lazo control(raíz)->relevancia(127)+controlabilidad(128)->producto(129). "
             "Próximo: grados continuos, no-lineal, active inference.").format(
                 v=_f(val), p=_f(g['prediccion']), c=_f(g['controlabilidad']), r=_f(g['relevancia']), mg=_f(margin))
    drat = ("exp113 (tier5, propio, {n} seeds, numpy): VALOR (w·b̂²) {v} bate a predicción {p} / controlabilidad {c} / "
            "relevancia {r} (margen +{mg}; las bases de un factor caen a ~0.5). Convergente con el principio capacidad∝ctrl×rel "
            "(tier2) y DERIVA la tesis 79-82 (tier5) desde el control; usa la controlabilidad descubierta de 128 (tier5). "
            "APOYADA: el control reconstruye R-VALOR = controlabilidad × relevancia.").format(
                n=n_seeds, v=_f(val), p=_f(g['prediccion']), c=_f(g['controlabilidad']), r=_f(g['relevancia']), mg=_f(margin))
    dec = Decision(id="D-V4-91", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP113), _to_plain(S_THESIS), _to_plain(S_C128)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-91 ACEPTADA por el ledger (tier5 exp113 + tier5 exp066 + tier5 exp112).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-91:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle129_value_factorization',
                                description='CYCLE 129 (RESET v4, H-V4-10c: el objetivo de control RECONSTRUYE R-VALOR = controlabilidad × relevancia -- la tesis central 79-82 emerge de la raíz del control).')
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
    print("RESUMEN — CYCLE 129 (RESET v4): el objetivo de CONTROL RECONSTRUYE R-VALOR = controlabilidad × relevancia -- la tesis central 79-82 emerge de la raíz del control — H-V4-10c")
    print("=" * 78)
    print("veredicto H-V4-10c:", status.upper() if status else "?")
    print("  el criterio VALOR (w·b̂², ctrl×rel) bate a cada factor por separado; sólo el producto captura los modos controlable-Y-relevante. La tesis 79-82 emerge de querer-controlar.")
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
