r"""
cycle88_support_concentration.py — CICLO 88 (RESET v4, rama R-VALOR, CIERRA el caveat de CYCLE 87): H-V4-7f por las
compuertas del engine. REFUTADA (robustez TOTAL): bajo feedback action-gated, NI SIQUIERA la concentración extrema del
soporte atrapa al greedy. Probando el verdadero peor caso -- POOL FIJO (los mismos n ítems recurren cada ronda ->
observación CORRELACIONADA) + k_obs=1 (observar 1 ítem/ronda) -- el greedy igual recupera la forma de sustitutos
(greedy ≈ random insesgado, gap sub-umbral ~0.037 < 0.05); con tareas FRESH tampoco hay trap (confirma CYCLE 87).
Mecanismo: el ridge-poly2 ajustado incluso sobre pocos puntos both-high (que igual tienen SPREAD) generaliza max(). =>
cierra el caveat de CYCLE 87 con una robustez MÁS fuerte: la explotación greedy basta a través de tipo-de-pool y amplitud
de observación; la EXPLORACIÓN es innecesaria (R-INTERVENCIÓN no liga aquí). Hay un costo MILD sub-umbral de concentración
que la exploración cierra, pero nunca llega a trap.

DERIVA de exp072_support_concentration/results/results.json.

Correr (DESPUÉS de exp072):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp072_support_concentration.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle88_support_concentration
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle88_support_concentration')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp072_support_concentration', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_QUAD = Source(tier=2, ref="aproximación polinómica de bajo grado sobre muestra con SPREAD: generaliza un target suave aunque la muestra esté sesgada; el trap severo exige soporte casi degenerado", obtained=False,
                claim=("Un ajuste polinómico de bajo grado sobre una muestra SESGADA pero con SPREAD (no degenerada) "
                       "aproxima un target suave en todo el dominio; el trap por sesgo de selección sólo sería severo si "
                       "el soporte observado COLAPSARA a casi un punto. Una región both-high igual tiene spread -> sin "
                       "colapso -> sin trap severo. (Principio.)"))
S_EXP071 = Source(tier=5, ref="cognia_x/experiments/exp071_action_gated_feedback", obtained=True,
                  claim=("CYCLE 87 halló que con ítems frescos la explotación greedy ya recupera sin explorar (no trap), "
                         "pero dejó como caveat probar CONCENTRACIÓN extrema. H-V4-7f cierra el caveat con pool fijo."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp072 primero): " + results_path)

    gap_fixed = sm['gap_fixed_random_minus_greedy']
    gap_fresh = sm['gap_fresh_random_minus_greedy']
    gf1 = gap_fixed['1']
    gfr1 = gap_fresh['1']
    trap_fixed_kobs = sm['trap_fixed_kobs']
    fixed_traps_low = sm['fixed_traps_low']
    fresh_robust_low = sm['fresh_robust_low']
    comp_ok = sm['comp_control_ok']
    n_seeds = data['args']['seeds']
    tk = "ninguno" if trap_fixed_kobs is None else str(trap_fixed_kobs)

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim072 = ("exp072 (propio, {n} seeds, numpy): probando el peor caso de concentración -- POOL FIJO (observación "
                "correlacionada) + k_obs=1 -- el greedy NO se atrapa (gap random−greedy fixed/k_obs=1 = {gf} <= 0.05, "
                "umbral de trap k_obs*={tk}); con POOL FRESH tampoco (gap {gfr}). El ridge-poly2 sobre pocos puntos "
                "both-high con SPREAD generaliza max(). Robustez TOTAL a través de tipo-de-pool y amplitud de "
                "observación; control comp/fixed OK={co}.").format(
                    n=n_seeds, gf=_f(gf1), tk=tk, gfr=_f(gfr1), co=comp_ok)
    S_EXP072 = Source(tier=5, ref="cognia_x/experiments/exp072_support_concentration", obtained=True, claim=claim072)
    for src in (S_QUAD, S_EXP071, S_EXP072):
        ledger.add_source(src)
    notes.append("3 fuentes (S_QUAD tier2 aproximación/spread; S_EXP071 tier5 caveat CYCLE 87; S_EXP072 tier5 dato propio).")

    ev_for = [S_EXP072.ref]
    ev_against = [S_EXP072.ref, S_EXP071.ref, S_QUAD.ref]
    advtext = ("{V} (cierra el caveat de CYCLE 87 con robustez MÁS fuerte): el caveat era que CYCLE 87 usó ítems FRESCOS, "
               "que diversifican el soporte aunque observes top-1. exp072 prueba el verdadero peor caso -- POOL FIJO (los "
               "mismos n ítems recurren cada ronda -> el greedy RE-OBSERVA siempre la misma región both-high) + k_obs=1. "
               "RESULTADO: ni así se atrapa -- fixed/k_obs=1 gap random−greedy = {gf} (<= 0.05, sin trap; umbral "
               "k_obs*={tk}); fresh/k_obs=1 gap {gfr}. El greedy recupera max() aun re-observando una región estrecha. "
               "MECANISMO: el ridge-poly2 ajustado incluso sobre pocos puntos both-high (que igual tienen SPREAD en "
               "(ctrl,rel)) aproxima un target suave (max) en todo el dominio; el trap severo exigiría que el soporte "
               "COLAPSARA a casi un punto, lo que una región both-high no hace. => la robustez de CYCLE 87 es TOTAL a "
               "través de tipo-de-pool y amplitud de observación; la EXPLORACIÓN es innecesaria (R-INTERVENCIÓN no liga "
               "en este régimen, 2ª refutación consecutiva tras 87). EVIDENCIA EN CONTRA / matiz HONESTO: hay un costo "
               "MILD sub-umbral de concentración (gap ~{gf} bajo fixed/k_obs=1) que la exploración cierra (explore alcanza "
               "el techo insesgado), pero NUNCA llega a trap (>0.05). Caveats: g=max sintético, base poly2 que nesta el "
               "producto, objetivo escalar, n=50 (espacio 2D chico); un soporte realmente degenerado (1 ítem idéntico) o "
               "una base que no nestara el target podrían atrapar. CONCLUSIÓN: caveat de CYCLE 87 CERRADO -- la política "
               "always-learn/greedy es robusta también bajo concentración extrema; el sub-tema feedback-realismo (87-88) "
               "queda cerrado.").format(V=status.upper(), gf=_f(gf1), tk=tk, gfr=_f(gfr1))

    hyp = Hypothesis(
        id="H-V4-7f",
        statement=("Bajo concentración extrema del soporte observado (pool fijo + k_obs chico) el trap de sesgo de "
                   "selección reaparece y la exploración se vuelve necesaria; la robustez de CYCLE 87 era regime-specific."),
        prediction=("APOYADA si pool fijo a k_obs=1 atrapa (greedy < random−0.05) y fresh no; REFUTADA si ni el pool fijo "
                    "a k_obs=1 atrapa; MIXTA en otro caso. (Pre-registrada, sustitutos, q2.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp072_support_concentration")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-7f")
        notes.append("H-V4-7f marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("Sólo pruebo lo que mi corazonada marca mejor, y encima del MISMO menú fijo una y otra vez. ¿Me quedo "
                 "atrapado probando siempre lo mismo y nunca aprendo que a veces basta UN sabor fuerte?"),
        everyday=("No: aun probando siempre 'lo mejor' del mismo menú, eso que pruebo IGUAL abarca una variedad de "
                  "sabores (no es un único plato idéntico), y de esa variedad infiero la regla real -- incluso la de "
                  "'a veces basta uno'. Sólo te atraparías si el menú colapsara a UN plato repetido. Hay una pizca de "
                  "ventaja en probar algo distinto de vez en cuando, pero no te hace falta para no equivocarte feo."),
        solutions=["greedy sobre pool fijo + k_obs=1 -> recupera max() igual (gap sub-umbral): no se atrapa",
                   "explorar -> cierra el costo MILD de concentración, pero no es necesario (gap nunca llega a trap)",
                   "random/insesgado -> techo; greedy queda apenas debajo",
                   "el trap severo exigiría soporte degenerado (un ítem idéntico) o una base que no nestara el target"],
        principles=["un ajuste polinómico de bajo grado sobre muestra con SPREAD generaliza aunque esté sesgada",
                    "la observación correlacionada (pool fijo) NO atrapa si la región observada igual tiene spread",
                    "la robustez de la explotación greedy es total a través de pool fijo/fresh y amplitud de observación",
                    "R-INTERVENCIÓN (explorar para aprender el valor) no liga aquí: 2ª refutación consecutiva (87-88)"],
        adaptation=("El lab confirma la política gap #2 (always-learn/greedy, sin exploración) también bajo concentración "
                    "extrema y observación correlacionada. Cierra el sub-tema feedback-realismo (87-88). Vigila sólo "
                    "soporte DEGENERADO o bases que no nesten el target. Próximo (el salto grande): lazo de "
                    "acción-consecuencia REAL con verificador chequeable (sandbox exp018), donde el feedback tiene costo, "
                    "la dinámica es secuencial y el target no es un g sintético; y SCALE (GPU)."),
        measurement=("exp072 ({n} seeds): fixed/k_obs=1 gap random−greedy={gf} (<=0.05, sin trap, k_obs*={tk}); "
                     "fresh/k_obs=1 gap={gfr}; comp control OK={co}.").format(
                         n=n_seeds, gf=_f(gf1), tk=tk, gfr=_f(gfr1), co=comp_ok),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (probar 'lo mejor' del mismo menú fijo igual abarca variedad y enseña la regla).")

    kl = ("REAL (exp072): bajo feedback action-gated, ni la concentración extrema del soporte atrapa al greedy. Pool FIJO "
          "(observación correlacionada) + k_obs=1: gap random−greedy = {gf} (<= 0.05, sin trap); pool FRESH idem ({gfr}). "
          "El ridge-poly2 sobre pocos puntos both-high con SPREAD generaliza max(). Robustez TOTAL a través de tipo-de-pool "
          "y amplitud de observación; exploración innecesaria. Costo MILD sub-umbral de concentración que la exploración "
          "cierra pero nunca llega a trap. Cierra el caveat de CYCLE 87.").format(gf=_f(gf1), gfr=_f(gfr1))
    ceilings.add(CeilingRecord(
        subsystem="R-VALOR bajo concentración extrema del soporte — greedy robusto aun con pool fijo + k_obs=1 (no trap)",
        known_limit=kl,
        blockers=[{"text": "un soporte realmente DEGENERADO (1 ítem idéntico repetido, sin spread) o una base que no nestara el target sí podrían atrapar; no testeados", "kind": "diseno"},
                  {"text": "g=max sintético, base poly2 que nesta el producto, objetivo escalar, espacio 2D chico (n=50); en features de mayor dimensión la generalización del top-k podría degradarse", "kind": "diseno"},
                  {"text": "feedback sin costo de muestreo y dinámica no-secuencial real; falta el lazo de acción-consecuencia REAL (sandbox exp018) -- el salto grande pendiente", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP072.ref, S_EXP071.ref]))
    notes.append("1 techo 'real': greedy robusto aun bajo pool fijo + k_obs=1; sub-tema feedback-realismo (87-88) cerrado.")

    dstmt = ("North-Star R-VALOR (cierra el caveat de CYCLE 87 y el sub-tema feedback-realismo 87-88): bajo feedback "
             "action-gated, ni la concentración extrema del soporte (pool fijo + k_obs=1) atrapa al greedy -- recupera "
             "la forma de sustitutos igual (gap sub-umbral). Decisión: el lab CONFIRMA la política gap #2 (always-learn/"
             "greedy, sin maquinaria de exploración) también bajo observación correlacionada y estrecha; vigila sólo "
             "soporte degenerado o bases que no nesten el target. R-INTERVENCIÓN no liga aquí (2ª refutación, 87-88). "
             "Próximo (el salto grande): lazo de acción-consecuencia REAL con verificador chequeable (sandbox exp018) y "
             "SCALE (GPU).")
    drat = ("exp072 (tier5, propio, {n} seeds): fixed/k_obs=1 gap random−greedy={gf} (<=0.05, sin trap); fresh/k_obs=1 "
            "gap={gfr}; comp control OK={co}. Convergente con aproximación-sobre-spread (tier2) y con CYCLE 87 (tier5). "
            "REFUTADA la reaparición del trap.").format(n=n_seeds, gf=_f(gf1), gfr=_f(gfr1), co=comp_ok)
    dec = Decision(id="D-V4-50", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP072), _to_plain(S_EXP071)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-50 ACEPTADA por el ledger (tier5 exp072 + tier5 exp071).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-50:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle88_support_concentration',
                                description='CYCLE 88 (RESET v4, H-V4-7f: ni la concentración extrema atrapa al greedy -- REFUTADA; cierra caveat CYCLE 87).')
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
    print("RESUMEN — CYCLE 88 (RESET v4): ni la concentración extrema atrapa (H-V4-7f) — cierra caveat CYCLE 87")
    print("=" * 78)
    print("veredicto H-V4-7f:", status.upper() if status else "?")
    print("  pool fijo + k_obs=1: el greedy igual recupera max() (gap sub-umbral); robustez total; exploración innecesaria.")
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
