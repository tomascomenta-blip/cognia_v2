r"""
cycle112_value_of_estimation.py — CICLO 112 (RESET v4, rama R-VALOR, R-VALOR RECURSIVO: el COSTO/ROI de ESTIMAR el valor):
H-V4-8q por las compuertas del engine. APOYADA: decidir SI estimar el valor es ella misma una decisión R-VALOR (ROI =
ganancia-por-heterogeneidad − costo-de-estimar). Hay un RÉGIMEN (baja heterogeneidad del valor, o alto costo de estimar)
donde conviene NO estimar y actuar sobre el PRIOR barato; el spread del cruce (donde estimar empieza a pagar) SUBE con el
costo de estimar. Cierra el lazo conceptual del arco: R-VALOR no sólo gobierna QUÉ elegir / CUÁNDO gastar, también SI vale
la pena estimar (la estimación es una acción con costo/retorno).

DERIVA de exp096_value_of_estimation/results/results.json.

Correr (DESPUÉS de exp096):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp096_value_of_estimation.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle112_value_of_estimation
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle112_value_of_estimation')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp096_value_of_estimation', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


S_PRINCIPLE = Source(tier=2, ref="valor de la información / valor del cómputo (metarazonamiento): pagar por estimar/computar sólo cuando la incertidumbre × las apuestas relevantes para la decisión exceden el costo del cómputo; si las opciones valen parecido o estimar es caro, actuar sobre el prior", obtained=False,
                     claim=("El valor de la información (o del cómputo) es positivo sólo cuando reduce incertidumbre que "
                            "CAMBIA una decisión con apuestas suficientes. Si las opciones valen parecido (baja "
                            "heterogeneidad) o estimar es caro, el ROI de estimar es negativo y conviene actuar sobre el "
                            "PRIOR. La decisión de estimar tiene su propio costo/retorno (metarazonamiento). (Principio.)"))
S_ARC = Source(tier=5, ref="cognia_x/experiments/exp090_calibration_decisions", obtained=True,
               claim=("Todo el arco de asignación supuso que YA tenés un estimador de valor. H-V4-8q sube un nivel: ¿vale "
                      "la pena ESTIMAR el valor (costo) vs actuar sobre el prior? R-VALOR recursivo."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp096 primero): " + results_path)

    xl = sm['crossover_spread_lo_cost']
    xh = sm['crossover_spread_hi_cost']
    n_seeds = data['args']['seeds']
    # extraer c_ests del grid keys
    import re as _re
    cset = sorted({float(_re.match(r"c([0-9.]+)_s", k).group(1)) for k in sm['grid'].keys()})
    ce_lo, ce_hi = cset[0], cset[-1]

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim096 = ("exp096 (propio, {n} seeds, numpy): decidir SI estimar el valor es una decisión R-VALOR. A bajo costo "
                "(c={cl}) el cruce estimate>prior está en spread {xl}; a alto costo (c={ch}) en spread {xh} (sube con el "
                "costo). Hay un régimen (baja heterogeneidad o alto costo) donde conviene NO estimar y usar el "
                "prior.").format(n=n_seeds, cl=ce_lo, xl=xl, ch=ce_hi, xh=xh)
    S_EXP096 = Source(tier=5, ref="cognia_x/experiments/exp096_value_of_estimation", obtained=True, claim=claim096)
    for src in (S_PRINCIPLE, S_ARC, S_EXP096):
        ledger.add_source(src)
    notes.append("3 fuentes (S_PRINCIPLE tier2 valor-de-la-información/metarazonamiento; S_ARC tier5 el arco supuso estimador dado; S_EXP096 tier5 dato propio).")

    ev_for = [S_EXP096.ref, S_PRINCIPLE.ref]
    ev_against = [S_EXP096.ref]
    advtext = ("{V} (R-VALOR RECURSIVO: el costo/ROI de ESTIMAR el valor): todo el arco de asignación (83-111) supuso que "
               "YA tenés un estimador de valor (confianza, verificador). Pero ESTIMAR no es gratis (computar confianza, "
               "probar, verificar para calibrar). H-V4-8q pregunta cuándo conviene PAGAR por estimar el valor (y asignar "
               "bien) vs ACTUAR sobre un PRIOR barato (al azar). RESULTADO: hay un CRUCE claro gobernado por la "
               "HETEROGENEIDAD del valor y el COSTO de estimar. A costo bajo (c={cl}) estimar empieza a pagar desde "
               "spread {xl}; a costo alto (c={ch}) recién desde spread {xh} -- el umbral de heterogeneidad para que valga "
               "estimar SUBE con el costo de estimar. A BAJA heterogeneidad (todos los ítems valen parecido) o ALTO costo, "
               "el PRIOR gana (no vale la pena estimar: pagás el costo y elegir bien casi no agrega valor). A ALTA "
               "heterogeneidad y costo bajo, estimar gana (elegir el mejor agrega mucho). => decidir SI estimar el valor "
               "es ella misma una decisión R-VALOR: el ROI de la estimación = ganancia-por-heterogeneidad − "
               "costo-de-estimar. Cierra el lazo conceptual: R-VALOR gobierna QUÉ elegir (83-103), CUÁNDO gastar (104) y "
               "SI vale la pena estimar (112). Es el 'valor de la información sobre el valor' (metarazonamiento). "
               "EVIDENCIA: el principio del valor-de-la-información (tier2) lo predice. EVIDENCIA EN CONTRA / caveats: "
               "modelo de valor escalar uniforme, costo de estimar CONSTANTE por decisión (no por-ítem), σ de estimación "
               "fija; numpy/juguete; el prior aquí es 'al azar' (un prior INFORMADO movería el cruce). La afirmación "
               "robusta es la EXISTENCIA del cruce y su monotonía con el costo, no los umbrales exactos.").format(
                   V=status.upper(), cl=ce_lo, xl=xl, ch=ce_hi, xh=xh)

    hyp = Hypothesis(
        id="H-V4-8q",
        statement=("Decidir SI estimar el valor es una decisión R-VALOR (ROI = ganancia-por-heterogeneidad − "
                   "costo-de-estimar): hay un régimen (baja heterogeneidad o alto costo de estimar) donde conviene NO "
                   "estimar y actuar sobre el prior; el umbral de heterogeneidad para que estimar pague sube con el costo."),
        prediction=("APOYADA si hay un CRUCE (prior gana a baja heterogeneidad, estimate a alta) y el spread del cruce "
                    "sube con c_est; REFUTADA si estimate domina/pierde siempre; MIXTA en otro caso. (Pre-registrada, "
                    "numpy, 64 seeds, barrido spread×c_est.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp096_value_of_estimation")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-8q")
        notes.append("H-V4-8q marcada '{}' con DoD completo (R-VALOR recursivo: ROI de estimar el valor).".format(status))

    analogy = AnalogyRecord(
        problem=("Antes de elegir entre varias opciones, ¿me pongo a INVESTIGAR cuál es mejor (cuesta tiempo/esfuerzo) o "
                 "elijo cualquiera y listo?"),
        everyday=("Depende de dos cosas: qué tan DISTINTAS son las opciones y qué tan caro es investigar. Si todas las "
                  "opciones son parecidas, investigar es plata tirada -- elijo cualquiera. Si una es mucho mejor que las "
                  "otras Y averiguar es barato, conviene investigar. Y cuanto MÁS caro es investigar, más distintas tienen "
                  "que ser las opciones para que valga la pena. Decidir SI investigar es, en sí, una decisión de "
                  "costo-beneficio."),
        solutions=["opciones parecidas (baja heterogeneidad) o investigar caro -> NO investigar, usar el prior",
                   "opciones muy distintas y barato investigar -> investigar y elegir la mejor",
                   "el umbral de 'cuán distintas' para que valga investigar sube con el costo de investigar",
                   "decidir SI estimar el valor es ella misma una decisión R-VALOR (valor de la información)"],
        principles=["el ROI de estimar el valor = ganancia-por-heterogeneidad − costo-de-estimar",
                    "hay un régimen (baja heterogeneidad o alto costo) donde conviene NO estimar y usar el prior",
                    "el umbral de heterogeneidad para que estimar pague sube con el costo de estimar",
                    "R-VALOR gobierna QUÉ elegir (83-103), CUÁNDO gastar (104) y SI vale estimar (112)"],
        adaptation=("El lab SUBE un nivel: la decisión de ESTIMAR el valor (computar confianza, verificar) tiene su propio "
                    "costo/retorno. Política: estimar el valor sólo cuando la heterogeneidad esperada de las opciones × "
                    "las apuestas supera el costo de estimar; si las opciones valen parecido o estimar es caro, actuar "
                    "sobre el prior. Cierra el lazo conceptual del arco R-VALOR (qué/cuándo/si-estimar). Próximo: prior "
                    "INFORMADO (no al azar); costo de estimar por-ítem; estimación PARCIAL/adaptativa (estimar más donde "
                    "más cambia la decisión); y SCALE."),
        measurement=("exp096 ({n} seeds): cruce estimate>prior a c={cl} en spread {xl}; a c={ch} en spread {xh} (sube con "
                     "el costo).").format(n=n_seeds, cl=ce_lo, xl=xl, ch=ce_hi, xh=xh),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (¿investigar cuál opción es mejor o elegir cualquiera? depende de cuán distintas y cuán caro).")

    kl = ("REAL (exp096): decidir SI estimar el valor es una decisión R-VALOR (ROI = ganancia-por-heterogeneidad − "
          "costo-de-estimar). Hay un régimen (baja heterogeneidad o alto costo) donde conviene NO estimar y actuar sobre "
          "el prior; el umbral de heterogeneidad para que estimar pague sube con el costo (cruce c={cl}@{xl} -> "
          "c={ch}@{xh}). TECHO: valor escalar uniforme, costo de estimar CONSTANTE por decisión, σ fija, prior 'al azar' "
          "(un prior informado movería el cruce); numpy/juguete; robusto es la existencia/monotonía del cruce, no los "
          "umbrales exactos.").format(cl=ce_lo, xl=xl, ch=ce_hi, xh=xh)
    ceilings.add(CeilingRecord(
        subsystem="R-VALOR recursivo — el COSTO/ROI de ESTIMAR el valor (estimar es una acción con costo/retorno; hay un régimen donde conviene NO estimar y usar el prior)",
        known_limit=kl,
        blockers=[{"text": "el prior aquí es 'al azar'; un prior INFORMADO (no uniforme) movería el cruce -- el ROI de estimar es relativo a qué tan bueno es el prior barato", "kind": "diseno"},
                  {"text": "costo de estimar CONSTANTE por decisión (no por-ítem ni adaptativo); la estimación PARCIAL/adaptativa (estimar más donde más cambia la decisión) no se modeló", "kind": "diseno"},
                  {"text": "valor escalar uniforme, σ de estimación fija, numpy/juguete; no integrado con el lazo cerrado real ni SCALE; robusta es la existencia/monotonía del cruce, no los umbrales exactos", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP096.ref, S_ARC.ref]))
    notes.append("1 techo 'real': el ROI de estimar el valor depende de heterogeneidad y costo; hay un régimen donde conviene NO estimar.")

    dstmt = ("North-Star R-VALOR (R-VALOR RECURSIVO, cierra el lazo conceptual del arco): decidir SI estimar el valor es "
             "ella misma una decisión R-VALOR -- ROI = ganancia-por-heterogeneidad − costo-de-estimar. Hay un régimen "
             "(baja heterogeneidad del valor, o alto costo de estimar) donde conviene NO estimar y actuar sobre el prior; "
             "el umbral de heterogeneidad para que estimar pague SUBE con el costo de estimar. Decisión: estimar el valor "
             "sólo cuando la heterogeneidad esperada × las apuestas supera el costo de estimar. R-VALOR gobierna QUÉ "
             "elegir (83-103), CUÁNDO gastar (104) y SI vale estimar (112) -- el 'valor de la información sobre el valor'. "
             "Próximo: prior informado; costo por-ítem; estimación adaptativa; y SCALE.")
    drat = ("exp096 (tier5, propio, {n} seeds, numpy): cruce estimate>prior a c={cl} en spread {xl}, a c={ch} en spread "
            "{xh} (sube con el costo). Convergente con el valor-de-la-información/metarazonamiento (tier2) y con que el "
            "arco supuso un estimador dado (tier5). APOYADA: estimar es una decisión R-VALOR con su régimen de "
            "no-estimar.").format(n=n_seeds, cl=ce_lo, xl=xl, ch=ce_hi, xh=xh)
    dec = Decision(id="D-V4-74", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP096), _to_plain(S_ARC)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-74 ACEPTADA por el ledger (tier5 exp096 + tier5 exp090).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-74:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle112_value_of_estimation',
                                description='CYCLE 112 (RESET v4, H-V4-8q: el ROI de estimar el valor -- decidir SI estimar es una decisión R-VALOR; hay un régimen donde conviene NO estimar -- APOYADA).')
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
    print("RESUMEN — CYCLE 112 (RESET v4): el COSTO/ROI de ESTIMAR el valor -- decidir SI estimar es una decisión R-VALOR (H-V4-8q)")
    print("=" * 78)
    print("veredicto H-V4-8q:", status.upper() if status else "?")
    print("  hay un régimen (baja heterogeneidad o alto costo) donde conviene NO estimar y usar el prior; el cruce sube con el costo.")
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
