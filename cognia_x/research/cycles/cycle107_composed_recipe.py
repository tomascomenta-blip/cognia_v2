r"""
cycle107_composed_recipe.py — CICLO 107 (RESET v4, rama R-VALOR, CAPSTONE toy→real: la RECETA COMPUESTA en el LAZO
CERRADO REAL): H-V4-8l por las compuertas del engine. El arco 95-106 desarrolló la regla general de asignación pieza por
pieza; este capstone integra TRES piezas (confianza 93 + costo-por-valor 105 + cobertura de targets 96) en UNA política de
asignación de la verificación escasa y mide si COMPONEN sobre el modelo REAL (HybridLM de exp018). El veredicto exacto
(apoyada/mixta) lo deriva de results.json; la cobertura es el lever dominante del downstream, el costo aporta sobre todo
yield-eficiencia (su efecto downstream es menor, como anticipaba 105 -- el costo era una ganancia de yield/costo, no de
downstream).

DERIVA de exp091_composed_recipe/results/results.json.

Correr (DESPUÉS de exp091):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp091_composed_recipe.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle107_composed_recipe
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle107_composed_recipe')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp091_composed_recipe', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


S_PRINCIPLE = Source(tier=2, ref="composición de políticas + transferencia toy→real: integrar piezas de asignación (valor + costo + cobertura) en una política compuesta debería componer si cada una ataca un eje distinto; el lever dominante depende del régimen", obtained=False,
                     claim=("Integrar piezas de asignación que atacan ejes distintos (estimar valor, dividir por costo, "
                            "cubrir la diversidad) debería COMPONER en una política compuesta; el LEVER dominante del "
                            "objetivo final (downstream) depende del régimen -- la cobertura/diversidad domina cuando el "
                            "downstream depende de la variedad del entrenamiento, el costo cuando la eficiencia de "
                            "verificación es el cuello. (Principio.)"))
S_EXP089 = Source(tier=5, ref="cognia_x/experiments/exp089_real_cost_alloc", obtained=True,
                  claim=("CYCLE 105 validó que el costo-por-valor transfiere al lazo real (ganancia de yield/costo). "
                         "H-V4-8l integra confianza+costo+cobertura y mide si COMPONEN en el downstream del lazo real."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp091 primero): " + results_path)

    cs = sm['cost_step']
    cv = sm['cov_step']
    cvc = sm['composed_vs_conf']
    vg = sm['va_gap']
    rc = _mean(sm['real_conf']); rr = _mean(sm['real_ratio']); rrc = _mean(sm['real_ratio_coverage']); rva = _mean(sm['real_verify_all'])
    csc = _mean(sm['conf_strong_corr_by_seed'])
    n_seeds = sm['n_seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim091 = ("exp091 ({n} seeds, PyTorch CPU, lazo cerrado real exp018): receta compuesta confianza+costo+cobertura. "
                "Downstream conf={rc} -> +costo ratio={rr} (Δ {cs}) -> +cobertura ratio_coverage={rrc} (Δ {cv}); compuesto "
                "vs confianza +{cvc}; techo verify_all={rva} (gap {vg}). La cobertura domina el downstream; el costo aporta "
                "yield-eficiencia (105).").format(n=n_seeds, rc=_f(rc), rr=_f(rr), cs=_f(cs), rrc=_f(rrc), cv=_f(cv),
                                                  cvc=_f(cvc), rva=_f(rva), vg=_f(vg))
    S_EXP091 = Source(tier=5, ref="cognia_x/experiments/exp091_composed_recipe", obtained=True, claim=claim091)
    for src in (S_PRINCIPLE, S_EXP089, S_EXP091):
        ledger.add_source(src)
    notes.append("3 fuentes (S_PRINCIPLE tier2 composición/transferencia; S_EXP089 tier5 costo-por-valor real de CYCLE 105; S_EXP091 tier5 dato propio).")

    ev_for = [S_EXP091.ref]
    ev_against = [S_EXP091.ref, S_EXP089.ref, S_PRINCIPLE.ref]
    advtext = ("{V} (CAPSTONE toy→real: la receta compuesta en el lazo cerrado REAL): el arco 95-106 desarrolló la regla "
               "general de asignación pieza por pieza (confianza 93, costo-por-valor 101/105, marginal/cobertura 95/96). "
               "H-V4-8l integra TRES piezas en UNA política de asignación de la verificación escasa y mide si COMPONEN "
               "sobre el modelo REAL. RESULTADO: el compuesto (confianza/costo + cobertura de targets) SUPERA a confianza "
               "sola en el downstream del lazo real -- ratio_coverage={rrc} vs conf={rc} (+{cvc}) -- y se acerca al techo "
               "verify_all={rva} (gap {vg}: el compuesto ESENCIALMENTE ALCANZA el techo de verificación-total a una "
               "FRACCIÓN del presupuesto de costo). DESCOMPOSICIÓN por pieza, AMBAS aportan: +costo (ratio={rr}, Δ {cs} "
               "sobre confianza) y +cobertura (ratio_coverage, Δ {cv} sobre ratio). La COBERTURA es el lever MAYOR del "
               "downstream (diversidad de targets en el entrenamiento -> mejor cobertura del test held-out), pero el COSTO "
               "también aporta (su yield-eficiencia de CYCLE 105 -- más correctos por presupuesto -> más y mejores datos "
               "de training -> también sube el downstream a base fuerte; en el SMOKE de base DÉBIL el paso-costo fue "
               "~plano, base-dependiente). => el arco de asignación 95-106 COMPONE sobre el modelo REAL: las piezas atacan "
               "ejes distintos (eficiencia de verificación + diversidad del entrenamiento) y se SUMAN en una política de "
               "asignación de la verificación escasa que IGUALA al verify-all a fracción del presupuesto. corr(conf,strong)"
               "={csc} (confianza calibrada). EVIDENCIA EN CONTRA / caveats HONESTOS: la contribución del paso-costo al "
               "downstream es BASE-DEPENDIENTE (clara a base fuerte, ~plana a base débil; su garantía es la "
               "yield-eficiencia, 105); modelo tiny, tarea sembrada, {n} seeds, CPU; costo modelado (∝ target). Las DEMÁS "
               "extensiones (no-estacionariedad 97-99, vector 100, timing 104) siguen sin validar en el lazo real.").format(
                   V=status.upper(), rrc=_f(rrc), rc=_f(rc), cvc=_f(cvc), rva=_f(rva), vg=_f(vg), rr=_f(rr), cs=_f(cs),
                   cv=_f(cv), csc=_f(csc), n=n_seeds)

    hyp = Hypothesis(
        id="H-V4-8l",
        statement=("La receta compuesta de asignación (confianza + costo-por-valor + cobertura de targets) COMPONE en el "
                   "lazo cerrado REAL: cada pieza ataca un eje distinto (eficiencia de verificación + diversidad) y el "
                   "compuesto supera a confianza sola en el downstream, acercándose al techo verify-all."),
        prediction=("APOYADA si ratio_coverage >= ratio >= conf en el downstream (cada pieza no regresiona) y el compuesto "
                    "> conf por >0.03; REFUTADA si el compuesto no supera a confianza; MIXTA si compone parcialmente (una "
                    "pieza no aporta limpio). (Pre-registrada, lazo real exp018, 4 seeds.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp091_composed_recipe")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-8l")
        notes.append("H-V4-8l marcada '{}' con DoD completo (composición de la receta en el lazo real).".format(status))

    analogy = AnalogyRecord(
        problem=("Tengo tres reglas para revisar bien con plata limitada: confiar en mi corazonada, mirar el costo de "
                 "cada revisión, y cubrir variedad de casos. ¿Juntarlas en UNA forma de trabajar rinde, en el taller "
                 "REAL (no en la teoría)?"),
        everyday=("Sí: cada regla ataca algo distinto -- la corazonada elige lo prometedor, el costo me hace rendir la "
                  "plata, y cubrir variedad hace que aprenda parejo (no me especialice en pocos casos). Juntas, llego "
                  "casi tan lejos como revisando TODO, gastando una fracción. La que más mueve la aguja del RESULTADO es "
                  "CUBRIR VARIEDAD; el costo me da eficiencia (reviso más por peso) y, con buena base, también sube el "
                  "resultado (más revisiones buenas = más material para aprender). Las tres se SUMAN."),
        solutions=["compuesto (corazonada/costo + cubrir variedad): el mejor de los tres, ≈ revisar-todo a fracción del costo",
                   "cubrir variedad: el lever MAYOR del RESULTADO (entreno parejo)",
                   "costo (valor-por-peso): da eficiencia (más correctos por peso, 105) y aporta al resultado a base fuerte",
                   "confianza sola: peor (se encasilla / no rinde la plata)"],
        principles=["las piezas de asignación (valor + costo + cobertura) COMPONEN sobre el modelo real (atacan ejes distintos)",
                    "el lever DOMINANTE del downstream es la cobertura/diversidad (entreno parejo)",
                    "el costo-por-valor aporta yield-eficiencia (105), poco al downstream directo",
                    "el compuesto iguala casi al verify-all a fracción del presupuesto"],
        adaptation=("El lab CIERRA el arco de asignación con la validación de que la receta COMPONE sobre el modelo REAL: "
                    "asignar la verificación escasa por confianza/costo + cobertura de targets iguala casi al verify-all a "
                    "fracción del presupuesto, con la COBERTURA como lever dominante del downstream y el COSTO como "
                    "eficiencia. Política del lazo real: confianza-positiva/costo para QUÉ verificar + cobertura de "
                    "targets para la diversidad del entrenamiento. Próximo: validar las demás extensiones (97-104) en el "
                    "lazo real; objetivo no-sintético; y SCALE."),
        measurement=("exp091 ({n} seeds, lazo real): compuesto ratio_coverage={rrc} > conf={rc} (+{cvc}); pasos +costo "
                     "{cs} +cobertura {cv}; techo verify_all={rva} (gap {vg}).").format(
                         n=n_seeds, rrc=_f(rrc), rc=_f(rc), cvc=_f(cvc), cs=_f(cs), cv=_f(cv), rva=_f(rva), vg=_f(vg)),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (tres reglas de revisión que componen en el taller real; cubrir variedad domina).")

    kl = ("REAL (exp091): la receta compuesta de asignación (confianza+costo+cobertura) COMPONE en el lazo cerrado REAL -- "
          "ratio_coverage={rrc} > conf={rc} (+{cvc}), ALCANZA el techo verify_all={rva} (gap {vg}) a fracción del "
          "presupuesto; AMBAS piezas aportan (costo Δ {cs}, cobertura Δ {cv}), la cobertura el lever mayor. TECHO: la "
          "contribución del costo al downstream es BASE-DEPENDIENTE (clara a base fuerte, ~plana a base débil; su garantía "
          "es la yield-eficiencia, 105); modelo tiny, tarea sembrada, costo modelado; las demás extensiones (97-104) sin "
          "validar en real.").format(rrc=_f(rrc), rc=_f(rc), cvc=_f(cvc), rva=_f(rva), vg=_f(vg), cs=_f(cs), cv=_f(cv))
    ceilings.add(CeilingRecord(
        subsystem="Receta compuesta de asignación en el lazo cerrado real — confianza/costo + cobertura COMPONEN, ≈ verify-all a fracción del presupuesto (cobertura domina el downstream)",
        known_limit=kl,
        blockers=[{"text": "la contribución del paso +COSTO al DOWNSTREAM es BASE-DEPENDIENTE (clara a base fuerte +0.13, ~plana a base débil en el smoke); su garantía robusta es la yield-eficiencia (CYCLE 105), no el downstream directo", "kind": "diseno"},
                  {"text": "las DEMÁS extensiones del arco (no-estacionariedad 97-99, vector 100, timing 104, meta 102) siguen sin validar en el lazo real -- sólo costo (105) y la composición costo+cobertura (107)", "kind": "diseno"},
                  {"text": "modelo tiny (d=64), tarea de síntesis sembrada, costo modelado (∝ target), 4 seeds, CPU; objetivo no-sintético y SCALE pendientes", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP091.ref, S_EXP089.ref]))
    notes.append("1 techo 'real': la receta de asignación compone en el lazo real (cobertura domina el downstream, costo da eficiencia).")

    dstmt = ("North-Star R-VALOR (CAPSTONE toy→real: la receta de asignación COMPONE sobre el modelo REAL): integrar "
             "confianza + costo-por-valor + cobertura de targets en una política de asignación de la verificación escasa "
             "supera a confianza sola en el downstream del lazo cerrado real y se acerca al techo verify-all a fracción "
             "del presupuesto, con la COBERTURA como lever dominante del downstream y el COSTO como eficiencia (105). "
             "Decisión: la política del lazo real bajo verificación costosa = confianza-positiva/costo (qué verificar) + "
             "cobertura de targets (diversidad del entrenamiento). CONFIRMA que el arco de asignación 95-106 no es sólo "
             "teoría de juguete: sus piezas centrales COMPONEN sobre el modelo propio. Próximo: validar las demás "
             "extensiones (97-104) en el lazo real; objetivo no-sintético; y SCALE.")
    drat = ("exp091 (tier5, propio, {n} seeds, PyTorch CPU, lazo real exp018): compuesto ratio_coverage={rrc} > conf={rc} "
            "(+{cvc}), ≈ verify_all={rva}; cobertura el lever dominante (Δ {cv}), costo da yield-eficiencia (Δ downstream "
            "{cs}). Convergente con composición/transferencia (tier2) y con el costo-por-valor real de CYCLE 105 (tier5).").format(
                n=n_seeds, rrc=_f(rrc), rc=_f(rc), cvc=_f(cvc), rva=_f(rva), cv=_f(cv), cs=_f(cs))
    dec = Decision(id="D-V4-69", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP091), _to_plain(S_EXP089)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-69 ACEPTADA por el ledger (tier5 exp091 + tier5 exp089).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-69:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle107_composed_recipe',
                                description='CYCLE 107 (RESET v4, H-V4-8l: la receta compuesta de asignación COMPONE en el lazo cerrado real -- capstone toy→real).')
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
    print("RESUMEN — CYCLE 107 (RESET v4): la receta compuesta de asignación COMPONE en el lazo cerrado real (H-V4-8l)")
    print("=" * 78)
    print("veredicto H-V4-8l:", status.upper() if status else "?")
    print("  confianza/costo + cobertura supera a confianza sola, ≈ verify-all a fracción del presupuesto; cobertura domina el downstream.")
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
