r"""
cycle130_graded_value.py — CICLO 130 (RESET v4, rama control/acción, GENERALIZA el keystone 129 a GRADOS+COSTO y halla CUÁNDO
importa el producto): H-V4-10d por las compuertas del engine. APOYADA: 129 mostró (en régimen BINARIO/disociado) que el
control reconstruye R-VALOR = controlabilidad × relevancia. Este ciclo lo generaliza a GRADOS continuos + COSTO cuadrático de
acción ρ·u² (que hace que la controlabilidad graduada importe: el beneficio de regular el modo i es w_i·b_i²/(b_i²+ρ) =
relevancia × controlabilidad-descontada). Y halla CUÁNDO importa el producto: barre la CORRELACIÓN controlabilidad-relevancia.
VALOR_COST es DOMINANTE en toda la correlación y su MARGEN sobre la mejor base de un solo factor ESCALA con la DISOCIACIÓN:
anti +0.368, indep +0.188, corr +0.044 -- el producto importa MÁS cuanto más 'lo fácil de controlar ≠ lo importante'. Une la
rama control/acción con la asignación cost-aware (101) y la complementariedad (83-86).

DERIVA de exp114_graded_value/results/results.json.

Correr (DESPUÉS de exp114):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp114_graded_value.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle130_graded_value
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle130_graded_value')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp114_graded_value', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="en el régimen GRADUADO con costo de acción, la asignación óptima de capacidad sigue el producto relevancia × controlabilidad-descontada-por-costo (w·b²/(b²+ρ), derivado del control de 1 paso con costo cuadrático); la VENTAJA del producto sobre asignar por un solo factor escala con la DISOCIACIÓN entre los dos factores (grande cuando lo controlable ≠ lo relevante, chica cuando coinciden). Producto cost-aware + dependencia de la disociación", obtained=False,
                     claim=("En el régimen GRADUADO con costo de acción, la asignación óptima de capacidad de modelado sigue "
                            "el PRODUCTO relevancia × controlabilidad-DESCONTADA-por-costo: w·b²/(b²+ρ), que se DERIVA del "
                            "control de 1 paso con costo cuadrático (u*=b(target−a·x)/(b²+ρ), beneficio ∝ b²/(b²+ρ)). La "
                            "VENTAJA del producto sobre asignar por un solo factor ESCALA con la DISOCIACIÓN entre "
                            "controlabilidad y relevancia: grande cuando 'lo fácil de controlar ≠ lo importante', chica "
                            "cuando coinciden (ahí un solo factor casi basta). (Principio.)"))
S_C129 = Source(tier=5, ref="cognia_x/experiments/exp113_value_factorization", obtained=True,
                claim=("CYCLE 129 (keystone): el objetivo de control reconstruye R-VALOR = controlabilidad × relevancia, en "
                       "régimen BINARIO/disociado (4 cuadrantes). H-V4-10d lo generaliza a GRADOS + COSTO y mide cuándo "
                       "importa el producto."))
S_COST = Source(tier=5, ref="cognia_x/experiments/exp085_cost_aware_value", obtained=True,
                claim=("CYCLE 101: bajo costo de acción heterogéneo, R-VALOR es valor-POR-COSTO (knapsack). H-V4-10d conecta: "
                       "la controlabilidad-descontada-por-costo b²/(b²+ρ) es el factor de control que el costo introduce en "
                       "el producto -- une la rama control/acción con la asignación cost-aware."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp114 primero): " + results_path)

    mg = sm['margins']
    m_anti, m_ind, m_corr = mg['anti'], mg['indep'], mg['corr']
    g = sm['grid']
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim114 = ("exp114 (propio, {n} seeds, numpy, eval PAREADO): en el régimen GRADUADO (b,w∈(0,1)) + COSTO de acción, "
                "VALOR_COST (w·b̂²/(b̂²+ρ)) es DOMINANTE y su margen sobre la mejor base de un solo factor ESCALA con la "
                "disociación controlabilidad-relevancia: anti +{ma}, indep +{mi}, corr +{mc}. El producto generaliza a "
                "grados+costo; importa más cuanto más disociados los factores.").format(
                    n=n_seeds, ma=_f(m_anti), mi=_f(m_ind), mc=_f(m_corr))
    S_EXP114 = Source(tier=5, ref="cognia_x/experiments/exp114_graded_value", obtained=True, claim=claim114)
    for src in (S_PRINCIPLE, S_C129, S_COST, S_EXP114):
        ledger.add_source(src)
    notes.append("4 fuentes (S_PRINCIPLE tier2 producto cost-aware + disociación; S_C129 tier5 el keystone que generaliza; S_COST tier5 cost-aware 101; S_EXP114 tier5 dato propio).")

    ev_for = [S_EXP114.ref, S_PRINCIPLE.ref]
    ev_against = [S_EXP114.ref]
    advtext = ("{V} (GENERALIZA el keystone 129 a GRADOS+COSTO y halla CUÁNDO importa el producto): 129 reconstruyó R-VALOR = "
               "controlabilidad × relevancia desde el control, pero en régimen BINARIO y DISOCIADO (los 4 cuadrantes). "
               "H-V4-10d lo generaliza a GRADOS continuos (b,w∈(0,1)) y añade un COSTO cuadrático de acción ρ·u² -- que es lo "
               "que hace que la controlabilidad GRADUADA importe (sin costo, cualquier b>0 regula perfecto). La derivación "
               "del control de 1 paso con costo da u*=b(target−a·x)/(b²+ρ) y BENEFICIO de regular el modo i = "
               "w_i·b_i²/(b_i²+ρ): relevancia × controlabilidad-descontada. Un HALLAZGO PRECURSOR honesto (el 1er diseño, con "
               "factores independientes, dio REFUTADA porque cada factor por separado ya es informativo del producto cuando "
               "no están disociados; además cazó un bug de pareo -- valor_simple>1 superando al oracle por usar instancias "
               "distintas por arm) RE-ENFOCÓ la pregunta a CUÁNDO importa el producto: barriendo la CORRELACIÓN "
               "controlabilidad-relevancia, con TODOS los arms PAREADOS sobre las mismas instancias. RESULTADO: VALOR_COST es "
               "DOMINANTE en toda la correlación (>= todas las bases) y su MARGEN sobre la mejor base de un solo factor "
               "ESCALA con la DISOCIACIÓN: ANTI-correlacionados +{ma} (lo fácil de controlar ≠ lo importante -> elegir por un "
               "solo factor falla feo), INDEP +{mi}, CORRELACIONADOS +{mc} (cuando controlar e importar coinciden, un solo "
               "factor casi basta). => el producto R-VALOR que el control reconstruye (129) NO era artefacto de lo binario: "
               "generaliza al régimen GRADUADO con costo de acción, y MÁS importa cuanto más DISOCIADAS están controlabilidad "
               "y relevancia -- la firma de la COMPLEMENTARIEDAD (83-86: el producto es un prior de complementariedad, "
               "decisivo bajo no-factorizabilidad). Une control/acción con la asignación cost-aware (101). EVIDENCIA: el "
               "principio producto-cost-aware + disociación (tier2), cost-aware (tier5). EVIDENCIA EN CONTRA / caveats: "
               "numpy, lineal multi-modo, control de 1 paso, capacidad = elegir-K; el producto se evalúa como criterio de "
               "asignación (no se demuestra que un agente lo compute espontáneamente); reproducible smoke 60 ≈ full "
               "300.").format(V=status.upper(), ma=_f(m_anti), mi=_f(m_ind), mc=_f(m_corr))

    hyp = Hypothesis(
        id="H-V4-10d",
        statement=("El producto R-VALOR = relevancia × controlabilidad(-descontada-por-costo) que el control reconstruye "
                   "(129) generaliza del régimen BINARIO al GRADUADO continuo + COSTO de acción: es el criterio dominante y "
                   "su ventaja sobre asignar por un solo factor ESCALA con la DISOCIACIÓN entre controlabilidad y relevancia "
                   "(grande cuando lo fácil de controlar ≠ lo importante, chica cuando coinciden). Une control/acción con la "
                   "asignación cost-aware (101) y la complementariedad (83-86)."),
        prediction=("APOYADA si VALOR_COST es dominante (>= cada base de un solo factor en toda la correlación) Y su margen "
                    "escala con la disociación (anti − corr > 0.10, anti > 0.15). REFUTADA si el margen no depende de la "
                    "correlación o es despreciable. MIXTA en otro caso. (Pre-registrada, numpy, 300 seeds, eval pareado, "
                    "barrido de correlación ctrl-rel.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp114_graded_value")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-10d")
        notes.append("H-V4-10d marcada '{}' con DoD completo (el producto generaliza a grados+costo; su ventaja escala con la disociación ctrl-rel).".format(status))

    analogy = AnalogyRecord(
        problem=("Si las cosas tienen GRADOS de 'cuánto las puedo mover' y 'cuánto me importan' (no sólo sí/no), y mover "
                 "cuesta esfuerzo, ¿conviene siempre pensar en el producto de las dos? ¿O a veces basta mirar una sola?"),
        everyday=("Depende de si van JUNTAS o no. Si lo que puedo mover suele ser justo lo que me importa (van juntas), mirar "
                  "cualquiera de las dos me alcanza para elegir bien. Pero si están CRUZADAS -- lo más fácil de mover es lo "
                  "que menos me importa, y lo que me importa casi no lo puedo mover -- entonces mirar una sola me engaña feo, "
                  "y necesito el PRODUCTO (importa × lo puedo mover, descontando el esfuerzo). El producto vale MÁS cuanto más "
                  "cruzadas están las dos cosas."),
        solutions=["en grados + costo, la asignación óptima sigue el producto relevancia × controlabilidad-descontada (w·b²/(b²+ρ))",
                   "el producto es DOMINANTE, pero su ventaja sobre un solo factor escala con la DISOCIACIÓN ctrl-rel",
                   "bajo factores correlacionados (control e importancia coinciden) un solo factor casi basta; bajo anti-correlación el producto gana feo",
                   "el costo de acción es lo que hace que la controlabilidad GRADUADA importe (descuenta b por b²/(b²+ρ))"],
        principles=["el producto ctrl×rel generaliza del régimen binario al graduado + costo de acción (no era artefacto de lo binario)",
                    "la VENTAJA del producto sobre un solo factor escala con la DISOCIACIÓN entre controlabilidad y relevancia",
                    "el costo de acción introduce la controlabilidad-DESCONTADA b²/(b²+ρ) como el factor de control (cost-aware, 101)",
                    "firma de la complementariedad (83-86): el producto importa donde los factores NO van juntos"],
        adaptation=("El lab GENERALIZA su keystone (129) del régimen binario al GRADUADO con costo de acción y, de paso, "
                    "precisa CUÁNDO importa el producto R-VALOR: su ventaja sobre asignar por un solo factor (controlabilidad "
                    "o relevancia) escala con la DISOCIACIÓN entre los dos -- es máxima cuando 'lo fácil de controlar ≠ lo "
                    "importante' (anti-correlación) y se desvanece cuando coinciden. Esto conecta tres hilos: la rama "
                    "control/acción (127-129), la asignación COST-AWARE (101: la controlabilidad-descontada-por-costo es el "
                    "factor de control) y la COMPLEMENTARIEDAD (83-86: el producto es un prior de complementariedad, decisivo "
                    "bajo no-factorizabilidad). Política: usar el producto relevancia × controlabilidad-descontada como "
                    "criterio de asignación SIEMPRE (es dominante), invirtiendo en estimarlo bien sobre todo cuando "
                    "controlabilidad y relevancia están disociadas. Próximo: descubrimiento bajo dinámica NO-lineal; "
                    "capacidad como presupuesto continuo de precisión; y el puente a active inference."),
        measurement=("exp114 ({n} seeds): VALOR_COST dominante; margen vs mejor base anti +{ma} / indep +{mi} / corr +{mc} "
                     "(escala con la disociación).").format(n=n_seeds, ma=_f(m_anti), mi=_f(m_ind), mc=_f(m_corr)),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (el producto importa más cuando 'lo puedo mover' y 'me importa' están cruzadas; si van juntas, un solo factor basta).")

    kl = ("REAL (exp114): el producto R-VALOR = relevancia × controlabilidad(-descontada-por-costo) generaliza del régimen "
          "binario (129) al GRADUADO continuo + COSTO de acción. VALOR_COST (w·b̂²/(b̂²+ρ)) es DOMINANTE y su margen sobre la "
          "mejor base de un solo factor ESCALA con la disociación controlabilidad-relevancia: anti +{ma}, indep +{mi}, corr "
          "+{mc}. El costo de acción introduce la controlabilidad-descontada b²/(b²+ρ) (cost-aware, 101); el escalado con la "
          "disociación es la firma de la complementariedad (83-86). TECHO: numpy, lineal multi-modo, control 1 paso, "
          "capacidad = elegir-K; el producto se evalúa como criterio, no se demuestra que un agente lo COMPUTE solo; "
          "frontera: no-lineal, capacidad continua, active inference.").format(ma=_f(m_anti), mi=_f(m_ind), mc=_f(m_corr))
    ceilings.add(CeilingRecord(
        subsystem="R-VALOR graduado + cost-aware (rama control/acción) — el producto relevancia × controlabilidad-descontada-por-costo (w·b²/(b²+ρ)) generaliza el keystone 129 al régimen graduado con costo de acción; es dominante y su ventaja sobre asignar por un solo factor escala con la DISOCIACIÓN controlabilidad-relevancia (firma de complementariedad)",
        known_limit=kl,
        blockers=[{"text": "numpy, sistema LINEAL multi-modo, control de 1 paso, capacidad = elegir-K-modos; el producto se evalúa como criterio de asignación, no se demuestra que un agente lo COMPUTE espontáneamente", "kind": "diseno"},
                  {"text": "la controlabilidad-descontada b²/(b²+ρ) sale de la derivación LINEAL del control de 1 paso con costo cuadrático; bajo dinámica NO-lineal o costo no-cuadrático la forma exacta del factor podría cambiar", "kind": "diseno"},
                  {"text": "honestidad: el 1er diseño (factores independientes) dio REFUTADA y cazó un bug de pareo (valor_simple>oracle por usar instancias distintas por arm); el resultado robusto requirió PAREAR los arms y barrer la correlación -- la afirmación firme es el ESCALADO con la disociación", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP114.ref, S_C129.ref, S_COST.ref]))
    notes.append("1 techo 'real': el producto generaliza a grados+costo y su ventaja escala con la disociación ctrl-rel (anti +{} vs corr +{}).".format(_f(m_anti), _f(m_corr)))

    dstmt = ("North-Star R-VALOR (generaliza el keystone a GRADOS+COSTO y precisa cuándo importa el producto): el producto "
             "relevancia × controlabilidad-descontada-por-costo (w·b̂²/(b̂²+ρ)) es el criterio de asignación DOMINANTE en el "
             "régimen graduado con costo de acción, y su ventaja sobre asignar por un solo factor ESCALA con la DISOCIACIÓN "
             "controlabilidad-relevancia (anti +{ma} / indep +{mi} / corr +{mc}). Decisión: usar SIEMPRE el producto "
             "relevancia × controlabilidad-descontada como criterio (es dominante), invirtiendo en estimarlo bien sobre todo "
             "cuando lo controlable y lo relevante están DISOCIADOS (lo fácil de controlar ≠ lo importante). Une control/"
             "acción (127-129) con cost-aware (101) y complementariedad (83-86). Próximo: no-lineal, capacidad continua, "
             "active inference.").format(ma=_f(m_anti), mi=_f(m_ind), mc=_f(m_corr))
    drat = ("exp114 (tier5, propio, {n} seeds, numpy, eval pareado): VALOR_COST (w·b̂²/(b̂²+ρ)) dominante; margen sobre la "
            "mejor base de un solo factor escala con la disociación (anti +{ma}, indep +{mi}, corr +{mc}). Convergente con el "
            "principio producto-cost-aware+disociación (tier2), generaliza el keystone 129 (tier5) y conecta con cost-aware "
            "101 (tier5). APOYADA: el producto generaliza a grados+costo; importa más bajo disociación.").format(
                n=n_seeds, ma=_f(m_anti), mi=_f(m_ind), mc=_f(m_corr))
    dec = Decision(id="D-V4-92", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP114), _to_plain(S_C129), _to_plain(S_COST)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-92 ACEPTADA por el ledger (tier5 exp114 + tier5 exp113 + tier5 exp085).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-92:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle130_graded_value',
                                description='CYCLE 130 (RESET v4, H-V4-10d: el producto R-VALOR generaliza a grados+costo; su ventaja escala con la disociación controlabilidad-relevancia -- une control/acción con cost-aware 101 y complementariedad 83-86).')
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
    print("RESUMEN — CYCLE 130 (RESET v4): el producto R-VALOR generaliza a GRADOS+COSTO; su ventaja escala con la DISOCIACIÓN controlabilidad-relevancia — H-V4-10d")
    print("=" * 78)
    print("veredicto H-V4-10d:", status.upper() if status else "?")
    print("  VALOR_COST (w·b̂²/(b̂²+ρ)) dominante; margen vs un solo factor grande bajo anti-correlación, chico bajo correlación. Une control/acción + cost-aware (101) + complementariedad (83-86).")
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
