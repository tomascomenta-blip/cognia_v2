r"""
cycle100_vector_value.py — CICLO 100 (RESET v4, rama R-VALOR, gap #4: objetivo VECTOR/multi-objetivo): H-V4-8e por las
compuertas del engine. APOYADA: bajo un objetivo VECTOR balance-requiriente (min(ΣV1,ΣV2), egalitario -- te juzga por tu
objetivo PEOR) Y ASIMÉTRICO (objetivos de escala distinta), seleccionar por UN objetivo o por la SUMA naive DESBALANCEA y
FALLA (carga el objetivo grande); la selección R-VALOR MARGINAL en la agregación real sube el objetivo REZAGADO y recupera
(≈ oracle). Bajo SIMETRÍA la suma ya balancea; bajo objetivo LINEAL todos coinciden. => R-VALOR bajo objetivo vector
balance-requiriente y asimétrico es la selección MARGINAL en la agregación real; generaliza CYCLE 95 (marginal escalar) a
vector y conecta con CYCLE 83 (complementos g=min) a nivel de CONJUNTO -- el 'balance' es la forma vectorial de la
cobertura/diversidad.

DERIVA de exp084_vector_value/results/results.json.

Correr (DESPUÉS de exp084):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp084_vector_value.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle100_vector_value
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle100_vector_value')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp084_vector_value', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="bienestar egalitario / max-min y Nash bargaining: bajo una agregación cóncava de varios objetivos (min, geométrica) la solución óptima BALANCEA los totales; un greedy por ganancia marginal en la agregación es la heurística estándar (la suma lineal no balancea bajo asimetría)", obtained=False,
                     claim=("En selección multi-objetivo bajo una agregación CÓNCAVA/egalitaria (min(ΣV1,ΣV2), media "
                            "geométrica/Nash), el óptimo BALANCEA los totales de los objetivos; el greedy por ganancia "
                            "MARGINAL en la agregación es la heurística estándar. Una scalarización LINEAL (suma) sólo "
                            "coincide con el óptimo bajo simetría; bajo escalas asimétricas carga el objetivo grande y "
                            "deja el peor objetivo bajo. (Principio.)"))
S_EXP079 = Source(tier=5, ref="cognia_x/experiments/exp079_submodular_value", obtained=True,
                  claim=("CYCLE 95 mostró que bajo objetivo NO-aditivo ESCALAR (submodular) el valor es MARGINAL. H-V4-8e "
                         "lo extiende a un objetivo VECTOR (multi-objetivo) con agregación egalitaria min, donde el "
                         "balance entre objetivos es la estructura."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp084 primero): " + results_path)

    avs = sm['asym_marg_vs_sum']
    avo = sm['asym_marg_vs_obj1']
    aog = sm['asym_oracle_gap']
    sso = sm['sym_sum_ok']
    lc = sm['lin_coincide']
    g = sm['grid']
    asym, sym = g['min_asym'], g['min_sym']
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim084 = ("exp084 (propio, {n} seeds, numpy): bajo objetivo VECTOR egalitario min(ΣV1,ΣV2) ASIMÉTRICO, la suma naive "
                "falla (sum={asg}) y la selección MARGINAL recupera (marginal={amg}, +{avs} vs sum, +{avo} vs obj1, ≈ "
                "oracle gap {aog}); bajo SIMÉTRICO la suma basta (Δ {sso}); bajo LINEAL coinciden (Δ {lc}).").format(
                    n=n_seeds, asg=_f(asym['sum_greedy']), amg=_f(asym['marginal_greedy']), avs=_f(avs), avo=_f(avo),
                    aog=_f(aog), sso=_f(sso), lc=_f(lc))
    S_EXP084 = Source(tier=5, ref="cognia_x/experiments/exp084_vector_value", obtained=True, claim=claim084)
    for src in (S_PRINCIPLE, S_EXP079, S_EXP084):
        ledger.add_source(src)
    notes.append("3 fuentes (S_PRINCIPLE tier2 bienestar egalitario/max-min; S_EXP079 tier5 marginal escalar de CYCLE 95; S_EXP084 tier5 dato propio).")

    ev_for = [S_EXP084.ref]
    ev_against = [S_EXP084.ref, S_EXP079.ref, S_PRINCIPLE.ref]
    advtext = ("{V} (gap #4: objetivo VECTOR/multi-objetivo): todo el arco asumió un objetivo ESCALAR. El valor real suele "
               "ser un VECTOR (varios objetivos) bajo una agregación que exige BALANCE (egalitaria: te juzga por tu "
               "objetivo PEOR, min(ΣV1,ΣV2)). H-V4-8e barre la ASIMETRÍA de escala entre objetivos. RESULTADO: bajo "
               "objetivo vector egalitario Y ASIMÉTRICO (objetivo 2 de escala menor), la SUMA naive DESBALANCEA -- carga "
               "el objetivo GRANDE (ΣV1≫ΣV2) y deja el peor objetivo bajo: sum_greedy={asg} -- mientras la selección "
               "R-VALOR MARGINAL en la agregación real sube el objetivo REZAGADO y BALANCEA: marginal_greedy={amg} (vs sum "
               "+{avs}, vs un-solo-objetivo +{avo}, ≈ oracle gap {aog}). Bajo objetivo SIMÉTRICO la suma YA balancea "
               "(marginal ≈ sum, Δ {sso}: por simetría max-suma ≈ balanceado -- por eso la suma naive 'parecía' bastar). "
               "Bajo objetivo LINEAL ('sum') todos coinciden (Δ {lc}: es la aditividad). => R-VALOR bajo un objetivo "
               "VECTOR balance-requiriente Y ASIMÉTRICO es la selección MARGINAL en la agregación real; la suma naive "
               "sólo basta bajo simetría/linealidad; optimizar UN objetivo falla siempre. GENERALIZA CYCLE 95 (marginal "
               "escalar bajo submodular) a VECTOR, y conecta con CYCLE 83 (complementos g=min per-ítem) a nivel de "
               "CONJUNTO: el 'balance' entre objetivos es la forma VECTORIAL de la cobertura/diversidad (CYCLE 95/96). "
               "EVIDENCIA EN CONTRA / caveats HONESTOS: bajo SIMETRÍA la suma naive basta (la marginal no aporta) -> el "
               "resultado es CONDICIONAL a la asimetría; objetivos anti-correlacionados sintéticos (k=2), agregación min "
               "(egalitaria pura; Nash/ponderada podrían diferir), greedy-marginal como oracle (el óptimo exacto es "
               "NP-hard), numpy/juguete.").format(
                   V=status.upper(), asg=_f(asym['sum_greedy']), amg=_f(asym['marginal_greedy']), avs=_f(avs), avo=_f(avo),
                   aog=_f(aog), sso=_f(sso), lc=_f(lc))

    hyp = Hypothesis(
        id="H-V4-8e",
        statement=("Bajo un objetivo VECTOR balance-requiriente (egalitario min(ΣV1,ΣV2)) Y ASIMÉTRICO, seleccionar por "
                   "un objetivo o por la suma naive desbalancea y falla; la selección R-VALOR MARGINAL en la agregación "
                   "real balancea el objetivo rezagado y recupera. Bajo simetría/linealidad la suma basta. -> R-VALOR "
                   "bajo objetivo vector es marginal en la agregación (generaliza CYCLE 95 a vector)."),
        prediction=("APOYADA si bajo 'min' ASIMÉTRICO marginal >> sum (+>0.05) Y ≈ oracle, bajo 'min' SIMÉTRICO sum ≈ "
                    "marginal, y bajo 'sum' lineal coinciden; REFUTADA si ni bajo asimetría la suma falla; MIXTA en otro "
                    "caso. (Pre-registrada, numpy, 48 seeds, barrido de asimetría.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp084_vector_value")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-8e")
        notes.append("H-V4-8e marcada '{}' con DoD completo (gap #4: objetivo vector/multi-objetivo).".format(status))

    analogy = AnalogyRecord(
        problem=("Armo una dieta eligiendo alimentos, y me juzgan por el NUTRIENTE en el que peor quedo (proteína, hierro, "
                 "vitamina). Algunos nutrientes son fáciles de conseguir y otros escasos. ¿Elijo por calorías totales, o "
                 "cuido el que me falta?"),
        everyday=("Cuido el que me falta. Si elijo por 'lo más nutritivo en total' (suma), cargo de lo abundante y me "
                  "quedo corto en el nutriente ESCASO -> mi peor nutriente me hunde. Mejor: en cada elección miro qué "
                  "nutriente tengo más flojo y sumo a ÉSE (marginal). Si todos los nutrientes fueran igual de fáciles "
                  "(simétrico), elegir por total ya quedaría balanceado y daría igual. El cuidado del rezagado importa "
                  "cuando los objetivos son ASIMÉTRICOS."),
        solutions=["selección marginal en la agregación egalitaria: sube el objetivo rezagado -> balancea (recupera)",
                   "suma naive: carga el objetivo abundante, deja el escaso bajo -> falla bajo asimetría",
                   "un solo objetivo: desbalancea siempre (falla)",
                   "bajo simetría la suma ya balancea (max-suma ≈ balanceado); el balance importa con asimetría"],
        principles=["bajo agregación egalitaria/cóncava (min) el óptimo BALANCEA los totales de los objetivos",
                    "la selección marginal en la agregación real sube el objetivo rezagado -> balancea (generaliza CYCLE 95)",
                    "la suma lineal sólo coincide bajo simetría; bajo asimetría carga el objetivo grande",
                    "el 'balance' entre objetivos es la forma VECTORIAL de la cobertura/diversidad (CYCLE 95/96)"],
        adaptation=("El lab extiende R-VALOR a objetivos VECTOR/multi-objetivo: bajo agregación balance-requiriente y "
                    "asimétrica, asignar por la ganancia MARGINAL en la agregación real (sube el objetivo rezagado), no "
                    "por un objetivo ni por la suma naive. Unifica gap #4 (no-aditivo escalar CYCLE 95 + vector CYCLE 100) "
                    "bajo el mismo principio: el valor es MARGINAL en la agregación verdadera. Próximo: agregaciones Nash/"
                    "ponderadas con pesos inciertos; >2 objetivos; integrar con el lazo cerrado real; y SCALE."),
        measurement=("exp084 ({n} seeds): min ASIM marginal={amg} vs sum={asg} (+{avs}) ≈ oracle (gap {aog}); min SIM sum "
                     "basta (Δ {sso}); LINEAL coincide (Δ {lc}).").format(
                         n=n_seeds, amg=_f(asym['marginal_greedy']), asg=_f(asym['sum_greedy']), avs=_f(avs), aog=_f(aog),
                         sso=_f(sso), lc=_f(lc)),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (armar la dieta cuidando el nutriente en que peor quedás, no las calorías totales).")

    kl = ("REAL (exp084): bajo objetivo VECTOR egalitario (min(ΣV1,ΣV2)) Y ASIMÉTRICO, la suma naive desbalancea y falla "
          "(sum={asg}), la selección MARGINAL en la agregación real balancea el objetivo rezagado y recupera "
          "(marginal={amg}, +{avs}, ≈ oracle); bajo simetría la suma basta (Δ {sso}); bajo lineal coinciden (Δ {lc}). "
          "R-VALOR bajo objetivo vector es marginal en la agregación. TECHO: condicional a asimetría; objetivos "
          "anti-corr sintéticos k=2, agregación min pura, greedy-marginal como oracle (óptimo exacto NP-hard).").format(
              asg=_f(asym['sum_greedy']), amg=_f(asym['marginal_greedy']), avs=_f(avs), sso=_f(sso), lc=_f(lc))
    ceilings.add(CeilingRecord(
        subsystem="R-VALOR bajo objetivo VECTOR/multi-objetivo (gap #4) — el valor es MARGINAL en la agregación egalitaria; la suma naive sólo basta bajo simetría/linealidad",
        known_limit=kl,
        blockers=[{"text": "el resultado es CONDICIONAL a la ASIMETRÍA de escala entre objetivos; bajo simetría la suma naive ya balancea (la marginal no aporta)", "kind": "diseno"},
                  {"text": "objetivos anti-correlacionados SINTÉTICOS (k=2), agregación min (egalitaria pura); Nash/ponderada con pesos inciertos podrían diferir; >2 objetivos sin testear", "kind": "diseno"},
                  {"text": "greedy-marginal usado como oracle (el óptimo exacto multi-objetivo es NP-hard); numpy/juguete; no integrado con el lazo cerrado real ni SCALE", "kind": "fisico"}],
        real_or_assumed="real", evidence=[S_EXP084.ref, S_EXP079.ref]))
    notes.append("1 techo 'real': R-VALOR bajo objetivo vector es marginal en la agregación; condicional a asimetría.")

    dstmt = ("North-Star R-VALOR (gap #4 EXTENDIDO a objetivo VECTOR): bajo un objetivo VECTOR balance-requiriente "
             "(egalitario min(ΣV1,ΣV2)) Y ASIMÉTRICO, optimizar un objetivo o la suma naive desbalancea y falla; la "
             "selección R-VALOR MARGINAL en la agregación real sube el objetivo rezagado y recupera. Decisión: bajo "
             "objetivos VECTOR con agregación balance-requiriente, la política R-VALOR usa la ganancia MARGINAL en la "
             "agregación verdadera (no un objetivo, no la suma naive), salvo bajo simetría/linealidad donde la suma basta. "
             "Unifica gap #4: el valor es MARGINAL en la agregación verdadera, sea escalar-submodular (CYCLE 95) o "
             "vector-egalitaria (CYCLE 100); el 'balance' es la forma vectorial de la cobertura/diversidad. Próximo: "
             "agregaciones Nash/ponderadas con pesos inciertos; >2 objetivos; lazo cerrado real; y SCALE.")
    drat = ("exp084 (tier5, propio, {n} seeds, numpy): min ASIM marginal={amg} >> sum={asg} (+{avs}) ≈ oracle (gap {aog}); "
            "min SIM sum basta (Δ {sso}); LINEAL coincide (Δ {lc}). Convergente con bienestar egalitario/max-min (tier2) y "
            "con el marginal escalar de CYCLE 95 (tier5). APOYADA: R-VALOR vector es marginal en la agregación.").format(
                n=n_seeds, amg=_f(asym['marginal_greedy']), asg=_f(asym['sum_greedy']), avs=_f(avs), aog=_f(aog),
                sso=_f(sso), lc=_f(lc))
    dec = Decision(id="D-V4-62", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP084), _to_plain(S_EXP079)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-62 ACEPTADA por el ledger (tier5 exp084 + tier5 exp079).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-62:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle100_vector_value',
                                description='CYCLE 100 (RESET v4, H-V4-8e: R-VALOR bajo objetivo VECTOR es marginal en la agregación -- APOYADA; gap #4 extendido a vector).')
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
    print("RESUMEN — CYCLE 100 (RESET v4): R-VALOR bajo objetivo VECTOR es MARGINAL en la agregación (H-V4-8e) — gap #4 extendido")
    print("=" * 78)
    print("veredicto H-V4-8e:", status.upper() if status else "?")
    print("  min asimétrico: la suma naive desbalancea, la marginal sube el objetivo rezagado y recupera; bajo simetría/lineal la suma basta.")
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
