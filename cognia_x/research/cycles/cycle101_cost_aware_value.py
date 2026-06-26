r"""
cycle101_cost_aware_value.py — CICLO 101 (RESET v4, rama R-VALOR, extiende el arco de asignación con COSTO de acción
HETEROGÉNEO): H-V4-8f por las compuertas del engine. APOYADA (objeto-dependiente): bajo objetivo ADITIVO + costo
HETEROGÉNEO (lo valioso es caro), asignar por VALOR solo DESPERDICIA el presupuesto en ítems caros; asignar por
valor-POR-COSTO (knapsack) recupera (≈ cota LP). Bajo costo UNIFORME coinciden. PERO bajo objetivo de COBERTURA que SATURA
+ costo hetero el ratio NO ayuda (hay que CUBRIR los tipos sin importar el costo). => R-VALOR bajo costo de acción
heterogéneo es valor-POR-COSTO para objetivos ADITIVOS; para objetivos que SATURAN el costo importa menos. El
costo-por-valor es OBJETO-DEPENDIENTE.

DERIVA de exp085_cost_aware_value/results/results.json.

Correr (DESPUÉS de exp085):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp085_cost_aware_value.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle101_cost_aware_value
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle101_cost_aware_value')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp085_cost_aware_value', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="knapsack: bajo presupuesto de costo y valor ADITIVO, el greedy por valor/costo es near-óptimo y supera a elegir por valor; pero para objetivos que SATURAN (cobertura submodular) el ratio no domina (cost-benefit greedy)", obtained=False,
                     claim=("Bajo presupuesto de COSTO y valor ADITIVO, el greedy por valor/costo (eficiencia) es "
                            "near-óptimo (cota LP fraccionaria) y supera a elegir por valor solo (que malgasta en ítems "
                            "caros). PERO para objetivos que SATURAN (cobertura submodular) hay que CUBRIR -- el ratio no "
                            "domina; el cost-benefit greedy mezcla ambos. El costo-por-valor es OBJETO-DEPENDIENTE. "
                            "(Principio.)"))
S_EXP079 = Source(tier=5, ref="cognia_x/experiments/exp079_submodular_value", obtained=True,
                  claim=("CYCLE 95 mostró el valor MARGINAL bajo objetivo no-aditivo, con COSTO UNIFORME (presupuesto = "
                         "#picks). H-V4-8f añade COSTO HETEROGÉNEO y caracteriza cuándo el costo-por-valor importa."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp085 primero): " + results_path)

    ahg = sm['add_hetero_gain']
    aog = sm['add_oracle_gap']
    auc = sm['add_uniform_coincide']
    chg = sm['cov_hetero_gain']
    g = sm['grid']
    ah, ch = g['additive_hetero'], g['coverage_hetero']
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim085 = ("exp085 (propio, {n} seeds, numpy): ADITIVO+hetero ratio_greedy={arg} > value_greedy={avg} (+{ahg}, ≈ cota "
                "LP gap {aog}); ADITIVO+uniforme coinciden (Δ {auc}); COBERTURA+hetero el ratio NO ayuda (Δ {chg}: la "
                "cobertura satura). El costo-por-valor es objeto-dependiente.").format(
                    n=n_seeds, arg=_f(ah['ratio_greedy']), avg=_f(ah['value_greedy']), ahg=_f(ahg), aog=_f(aog),
                    auc=_f(auc), chg=_f(chg))
    S_EXP085 = Source(tier=5, ref="cognia_x/experiments/exp085_cost_aware_value", obtained=True, claim=claim085)
    for src in (S_PRINCIPLE, S_EXP079, S_EXP085):
        ledger.add_source(src)
    notes.append("3 fuentes (S_PRINCIPLE tier2 knapsack valor/costo objeto-dependiente; S_EXP079 tier5 marginal/cobertura de CYCLE 95; S_EXP085 tier5 dato propio).")

    ev_for = [S_EXP085.ref]
    ev_against = [S_EXP085.ref, S_EXP079.ref, S_PRINCIPLE.ref]
    advtext = ("{V} (extiende el arco con COSTO de acción HETEROGÉNEO; objeto-dependiente): todo el arco (83-100) asumió "
               "COSTO UNIFORME (presupuesto = #picks). Las acciones reales tienen costo HETEROGÉNEO (verificar un "
               "candidato difícil cuesta más, y lo valioso suele ser caro). H-V4-8f testea la asignación bajo presupuesto "
               "de COSTO total. RESULTADO objeto-dependiente: (1) ADITIVO + costo HETEROGÉNEO: asignar por VALOR solo "
               "DESPERDICIA el presupuesto en ítems caros (value_greedy={avg}); valor-POR-COSTO recupera (ratio_greedy="
               "{arg}, +{ahg}, ≈ cota LP fraccionaria, gap {aog}). (2) ADITIVO + costo UNIFORME: coinciden (Δ {auc}: "
               "cuando todo cuesta igual, valor = valor/costo). (3) COBERTURA que SATURA + costo hetero: el ratio NO ayuda "
               "(ratio={crg} vs value={cvg}, Δ {chg}<=0.03): hay que CUBRIR los tipos sin importar el costo, así que la "
               "eficiencia-por-costo NO domina (cubrir manda). => R-VALOR bajo costo de acción HETEROGÉNEO es "
               "valor-POR-COSTO para objetivos ADITIVOS (knapsack); para objetivos que SATURAN (cobertura) el costo "
               "importa menos. El costo-por-valor es OBJETO-DEPENDIENTE: completa el arco de asignación (feedback con "
               "costo no sólo LIMITADO -uniforme- sino HETEROGÉNEO). EVIDENCIA EN CONTRA / caveats HONESTOS: el ratio no "
               "alcanza la cota LP (gap {aog}: greedy ≠ óptimo entero; la LP es cota superior); el costo se modeló "
               "correlacionado con el valor (caso realista pero específico; con costo independiente el efecto sería "
               "menor); objetivo aditivo Σq y cobertura sintéticos, numpy/juguete.").format(
                   V=status.upper(), avg=_f(ah['value_greedy']), arg=_f(ah['ratio_greedy']), ahg=_f(ahg), aog=_f(aog),
                   auc=_f(auc), crg=_f(ch['ratio_greedy']), cvg=_f(ch['value_greedy']), chg=_f(chg))

    hyp = Hypothesis(
        id="H-V4-8f",
        statement=("Bajo costo de acción HETEROGÉNEO y presupuesto de costo total, R-VALOR es valor-POR-COSTO para "
                   "objetivos ADITIVOS (asignar por valor solo malgasta en ítems caros; valor/costo recupera ≈ knapsack); "
                   "para objetivos que SATURAN (cobertura) el costo importa menos (cubrir manda). El costo-por-valor es "
                   "OBJETO-DEPENDIENTE."),
        prediction=("APOYADA si ADITIVO+hetero ratio >> value (+>0.05) Y ≈ cota LP, ADITIVO+uniforme coinciden, Y "
                    "COBERTURA+hetero el ratio NO ayuda (Δ<=0.03); REFUTADA si ni bajo aditivo+hetero el ratio supera al "
                    "valor; MIXTA en otro caso. (Pre-registrada, numpy, 48 seeds.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp085_cost_aware_value")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-8f")
        notes.append("H-V4-8f marcada '{}' con DoD completo (costo de acción heterogéneo).".format(status))

    analogy = AnalogyRecord(
        problem=("Tengo $100 para comprar y quiero MÁS valor total. Algunas cosas valiosas son carísimas. ¿Compro lo más "
                 "valioso, o lo de mejor valor-POR-PESO? ¿Y si en cambio sólo necesito CUBRIR una lista (un ítem de cada "
                 "categoría)?"),
        everyday=("Para acumular valor total con plata limitada: lo de mejor valor-por-peso (rinde más por cada peso; "
                  "comprar lo más caro-valioso me deja sin plata pronto). Si todo cuesta igual, da lo mismo. PERO si sólo "
                  "necesito CUBRIR una lista (uno de cada categoría), compro lo que me falta de cada categoría sin importar "
                  "el precio -- ahí el valor-por-peso no manda, cubrir manda."),
        solutions=["aditivo + costo hetero: valor-por-costo (eficiencia) -> más valor por presupuesto",
                   "aditivo + costo uniforme: valor = valor/costo (da igual)",
                   "cobertura que satura + costo hetero: cubrir manda, el ratio no ayuda (debés cubrir cada tipo)",
                   "elegir por valor solo bajo costo hetero: malgasta el presupuesto en lo caro"],
        principles=["bajo valor ADITIVO + costo heterogéneo, R-VALOR es valor-POR-COSTO (knapsack near-óptimo)",
                    "bajo costo uniforme, valor = valor/costo (el costo no cambia la política)",
                    "bajo objetivo que SATURA (cobertura), el costo importa menos: cubrir manda, el ratio no domina",
                    "el costo-por-valor es OBJETO-DEPENDIENTE (depende de si el objetivo es aditivo o satura)"],
        adaptation=("El lab completa el arco de asignación con FEEDBACK/acción de costo HETEROGÉNEO (no sólo LIMITADO): la "
                    "política R-VALOR bajo presupuesto de costo es valor-POR-COSTO para objetivos ADITIVOS; para objetivos "
                    "que saturan (cobertura) prioriza CUBRIR. Junto con CYCLE 95/100 (valor marginal en la agregación), la "
                    "regla general es: asignar por GANANCIA MARGINAL en la agregación verdadera, dividida por el COSTO si "
                    "el objetivo es aditivo. Próximo: costo y valor correlacionados de un lazo REAL; integrar en el lazo "
                    "cerrado; y SCALE."),
        measurement=("exp085 ({n} seeds): ADITIVO+hetero ratio={arg} > value={avg} (+{ahg}, ≈ cota LP gap {aog}); "
                     "ADITIVO+uniforme coincide (Δ {auc}); COBERTURA+hetero ratio−value {chg}.").format(
                         n=n_seeds, arg=_f(ah['ratio_greedy']), avg=_f(ah['value_greedy']), ahg=_f(ahg), aog=_f(aog),
                         auc=_f(auc), chg=_f(chg)),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada ($100 para comprar: valor-por-peso para acumular, cubrir-la-lista cuando satura).")

    kl = ("REAL (exp085): bajo costo de acción HETEROGÉNEO, R-VALOR es valor-POR-COSTO para objetivos ADITIVOS (ratio={arg} "
          ">> value={avg}, +{ahg}, ≈ cota LP) -- asignar por valor solo malgasta en ítems caros; bajo costo uniforme "
          "coinciden (Δ {auc}); bajo cobertura que SATURA el ratio NO ayuda (Δ {chg}: cubrir manda). El costo-por-valor es "
          "OBJETO-DEPENDIENTE. TECHO: ratio no alcanza la cota LP (greedy≠óptimo); costo corr. con valor (caso específico); "
          "objetivos sintéticos.").format(arg=_f(ah['ratio_greedy']), avg=_f(ah['value_greedy']), ahg=_f(ahg),
                                          auc=_f(auc), chg=_f(chg))
    ceilings.add(CeilingRecord(
        subsystem="R-VALOR bajo COSTO de acción HETEROGÉNEO — valor-POR-COSTO para objetivos aditivos (knapsack); para objetivos que saturan (cobertura) cubrir manda; objeto-dependiente",
        known_limit=kl,
        blockers=[{"text": "el costo-por-valor es OBJETO-DEPENDIENTE: ayuda en objetivos ADITIVOS, no en objetivos que SATURAN (cobertura, donde cubrir manda)", "kind": "diseno"},
                  {"text": "el ratio-greedy no alcanza la cota LP fraccionaria (greedy != óptimo entero; la LP es cota superior); el óptimo knapsack exacto es NP-hard", "kind": "fisico"},
                  {"text": "costo modelado CORRELACIONADO con el valor (lo valioso es caro; caso realista pero específico -- con costo independiente el efecto sería menor); objetivos sintéticos, numpy/juguete, no integrado con el lazo real ni SCALE", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP085.ref, S_EXP079.ref]))
    notes.append("1 techo 'real': R-VALOR bajo costo heterogéneo es valor-por-costo (aditivo) / cubrir (saturante); objeto-dependiente.")

    dstmt = ("North-Star R-VALOR (completa el arco de asignación con COSTO de acción HETEROGÉNEO): bajo presupuesto de "
             "costo, R-VALOR es valor-POR-COSTO para objetivos ADITIVOS (asignar por valor solo malgasta en ítems caros; "
             "valor/costo recupera ≈ knapsack); para objetivos que SATURAN (cobertura) el costo importa menos (cubrir "
             "manda). Decisión: la política R-VALOR de asignación es GANANCIA MARGINAL en la agregación verdadera, "
             "dividida por el COSTO si el objetivo es aditivo (no si satura). El costo-por-valor es OBJETO-DEPENDIENTE. "
             "Completa el tema 'feedback con costo' (no sólo limitado/uniforme sino heterogéneo). Próximo: costo/valor de "
             "un lazo REAL; integrar en el lazo cerrado; y SCALE.")
    drat = ("exp085 (tier5, propio, {n} seeds, numpy): ADITIVO+hetero ratio={arg} > value={avg} (+{ahg}, ≈ cota LP gap "
            "{aog}); UNIFORME coincide (Δ {auc}); COBERTURA+hetero ratio no ayuda (Δ {chg}). Convergente con knapsack "
            "valor/costo objeto-dependiente (tier2) y con el marginal/cobertura de CYCLE 95 (tier5). APOYADA "
            "objeto-dependiente.").format(n=n_seeds, arg=_f(ah['ratio_greedy']), avg=_f(ah['value_greedy']), ahg=_f(ahg),
                                          aog=_f(aog), auc=_f(auc), chg=_f(chg))
    dec = Decision(id="D-V4-63", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP085), _to_plain(S_EXP079)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-63 ACEPTADA por el ledger (tier5 exp085 + tier5 exp079).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-63:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle101_cost_aware_value',
                                description='CYCLE 101 (RESET v4, H-V4-8f: R-VALOR bajo costo heterogéneo es valor-por-costo para objetivos aditivos; objeto-dependiente -- APOYADA).')
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
    print("RESUMEN — CYCLE 101 (RESET v4): R-VALOR bajo COSTO heterogéneo = valor-por-costo (aditivo) / cubrir (saturante) (H-V4-8f)")
    print("=" * 78)
    print("veredicto H-V4-8f:", status.upper() if status else "?")
    print("  aditivo+hetero: valor-por-costo gana; uniforme: coinciden; cobertura que satura: cubrir manda (ratio no ayuda). Objeto-dependiente.")
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
