r"""
cycle44_multistep_reasoning.py — CICLO 44 (RESET v4): H-V4-1i por las compuertas del engine. Primer ciclo
MULTI-PASO (gran salto tras cerrar el integrador de 1 paso, 40-43).

H-V4-1i: ¿la verificación INTERMEDIA (step-wise act-and-verify) supera a la SÓLO-FINAL (end-to-end best-of-k)
a IGUAL cómputo, y la ventaja crece con la longitud de cadena porque los errores se COMPONEN? DERIVA de
exp030_multistep_reasoning/results/results.json.

RESULTADO REAL: MIXTA (4 seeds, cadena de sumas mod 20, k=4, cómputo k·K). Curva K->END_TO_END/STEP_WISE/gap:
  K1:0.667/0.692/+0.025  K2:0.317/0.448/+0.131  K4:0.046/0.219/+0.173  K6:0.004/0.092/+0.088
  - El gap ABSOLUTO crece hasta K=4 (+0.173) y CAE a K=6 (+0.088): MIXTA contra la predicción (gap>0.20
    monótono). PERO la razón es honesta: AMBAS estrategias colapsan a 0 con K (con presupuesto por-paso FIJO
    k=4 ningún paso queda 100% garantizado), sólo que step-wise colapsa MUCHO más lento.
  - La ventaja RELATIVA (step_wise/end_to_end) SÍ crece monótona y es enorme: 1.04× (K1) -> 1.4× (K2) ->
    4.8× (K4) -> 23× (K6). La verificación intermedia FRENA drásticamente el compounding pero no lo elimina
    a presupuesto por-paso fijo.
  => el lever multi-paso es la verificación INTERMEDIA, pero para cadenas largas hace falta ESCALAR el
     presupuesto por-paso (o casi-perfeccionar el paso) -> conecta con el control adaptativo per-step (43).

Correr (DESPUÉS de exp030):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp030_multistep_reasoning.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle44_multistep_reasoning
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store',
                             'cycle44_multistep_reasoning')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp030_multistep_reasoning', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _fmt(x):
    return "{:.3f}".format(x) if isinstance(x, (int, float)) else str(x)


def _ratio(sw, e2e):
    return sw / e2e if e2e > 1e-9 else float('inf')


S_PRM = Source(tier=1, ref="process-vs-outcome-supervision", obtained=False,
               claim=("Supervisión de PROCESO (verificar pasos intermedios) supera a la de RESULTADO (sólo el "
                      "final) en razonamiento multi-paso (Lightman 2023, 'Let's Verify Step by Step'). "
                      "(Principio, no re-obtenido esta sesión.)"))
S_EXP029 = Source(tier=5, ref="cognia_x/experiments/exp029_adaptive_allocation", obtained=True,
                  claim=("exp029 (CYCLE 43): el integrador act-and-verify de UN paso quedó cerrado (control + "
                         "política adaptativa). El razonamiento real es multi-paso -> exp030."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    v = data.get('verdict')
    st = data.get('stats')
    if not v or not st:
        raise SystemExit("results.json sin verdict/stats (corre exp030 primero): " + results_path)
    status = v.lower()
    Ks = [str(x) for x in data.get('Ks', [])]
    curve = st['curve']
    Kmax = str(st['Kmax'])
    n_seeds = st['n_seeds']
    ratios = {K: _ratio(curve[K]['step_wise'], curve[K]['end_to_end']) for K in Ks}
    ratio_max = ratios[Kmax]
    ratios_grow = all(ratios[Ks[i + 1]] >= ratios[Ks[i]] - 1e-6 for i in range(len(Ks) - 1))
    gap_max = st['gap_at_Kmax']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    S_EXP030 = Source(tier=5, ref="cognia_x/experiments/exp030_multistep_reasoning", obtained=True,
                      claim=("exp030 (propio, {n} seeds, modelo HybridLM, cadena de sumas mod 20): la "
                             "verificación INTERMEDIA (step-wise) vs SÓLO-FINAL (end-to-end) a igual cómputo "
                             "k·K. El gap ABSOLUTO no es monótono (crece a K=4 y cae a K=6 porque AMBAS "
                             "colapsan a 0), pero la ventaja RELATIVA crece monótona: {r1}× -> ... -> {rm}× a "
                             "K={km}. La verificación intermedia frena el compounding, no lo elimina a "
                             "presupuesto por-paso fijo.").format(n=n_seeds, r1=_fmt(ratios[Ks[0]]),
                                                                  rm=_fmt(ratio_max), km=st['Kmax']))
    for src in (S_PRM, S_EXP029, S_EXP030):
        ledger.add_source(src)
    notes.append("3 fuentes (S_PRM tier1 proceso>resultado; S_EXP029 tier5 integrador 1-paso; S_EXP030 tier5 dato propio multi-paso).")

    ev_for = [S_EXP030.ref, S_EXP029.ref]
    ev_against = [S_EXP030.ref]      # honesto: el gap absoluto NO crece monótono (ambas -> 0); step-wise también colapsa
    adv = ("MIXTA, informativa. La predicción pre-registrada pedía gap ABSOLUTO > 0.20 y monótono en K: NO se "
           "cumple — el gap crece hasta K=4 (+0.173) y CAE a K=6 (+{gm}) porque AMBAS estrategias colapsan a 0 "
           "(con presupuesto por-paso FIJO k=4 ningún paso queda 100% garantizado; step-wise también decae). "
           "PERO la dirección del fenómeno es clarísima y A FAVOR: la verificación INTERMEDIA frena el "
           "compounding muchísimo — la ventaja RELATIVA (step_wise/end_to_end) crece MONÓTONA y es enorme: "
           "{r1}× (K1) -> {rm}× (K={km}); end_to_end se desploma a {e2e} mientras step_wise aguanta {sw}. "
           "Ataques considerados: (1) '¿es el piso de suerte?' -> NO: la 1ra versión con mod-20 y verif "
           "sólo-del-último-número daba un piso de azar ~0.19 que inflaba end-to-end; corregido a verif de la "
           "TRAZA COMPLETA (sin piso), el efecto real emergió. (2) '¿igual cómputo?' -> SÍ: ambas gastan k·K "
           "llamadas. LECCIÓN: el lever multi-paso es la verificación intermedia (supervisión de PROCESO, "
           "convergente con Lightman 2023), pero para cadenas LARGAS hay que ESCALAR el presupuesto por-paso "
           "o casi-perfeccionar el paso -> conecta con el control adaptativo per-step (43).").format(
               gm=_fmt(gap_max), r1=_fmt(ratios[Ks[0]]), rm=_fmt(ratio_max), km=st['Kmax'],
               e2e=_fmt(curve[Kmax]['end_to_end']), sw=_fmt(curve[Kmax]['step_wise']))

    hyp = Hypothesis(
        id="H-V4-1i",
        statement=("En razonamiento multi-paso, la verificación intermedia (step-wise act-and-verify) supera a "
                   "la sólo-final (end-to-end) a igual cómputo, y la ventaja crece con la longitud de cadena "
                   "porque los errores se componen."),
        prediction=("APOYADA si el gap (step_wise−end_to_end) crece monótono con K y es >0.20 en Kmax, con "
                    "end_to_end decayendo; MIXTA si crece modesto/no-monótono; REFUTADA si no crece o "
                    "step_wise<=end_to_end en Kmax. (Pre-registrada.)"),
        status='abierta', confidence='alta',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=adv, experiment_ref="exp030_multistep_reasoning")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-1i")
        notes.append("H-V4-1i marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("Resolvés un problema de VARIOS pasos con tiempo limitado. ¿Revisás cada paso a medida que "
                 "avanzás, o sólo el resultado final?"),
        everyday=("Cuenta larga a mano: si revisás SÓLO el total y está mal, no sabés dónde fallaste y la "
                  "chance de que TODA la cuenta salga bien de un tirón decae rapidísimo con los pasos. Si "
                  "revisás CADA paso y corregís ahí, un paso malo no contamina los siguientes: aguantás cadenas "
                  "mucho más largas. Pero si en un paso te trabás y no lo sacás, igual se descarrila."),
        solutions=["verificar CADA paso (step-wise) -> frena el compounding; ventaja RELATIVA crece hasta 23× a K=6",
                   "verificar SÓLO el final (end-to-end best-of-k) -> se desploma con K (≈p^K)",
                   "AMBAS colapsan a 0 si la cadena es muy larga y el presupuesto por-paso es fijo",
                   "para cadenas largas: ESCALAR el presupuesto por-paso o casi-perfeccionar cada paso"],
        principles=["en multi-paso, la supervisión de PROCESO (pasos) supera a la de RESULTADO (final) a igual cómputo",
                    "el compounding hace que la verificación intermedia gane cada vez más (ventaja relativa creciente)",
                    "verificación intermedia frena el compounding pero NO lo elimina a presupuesto por-paso fijo",
                    "cadenas largas exigen escalar el presupuesto por-paso -> usar el control adaptativo per-step (43)"],
        adaptation=("Define el siguiente paso del integrador: act-and-verify POR PASO con presupuesto por-paso "
                    "ESCALADO/ADAPTATIVO (el control de 43 asignando MÁS cómputo a los pasos difíciles). "
                    "Próximo (H-V4-1j): control adaptativo per-step en cadenas largas + verificador real-chequeable."),
        measurement=("exp030: curva K->END_TO_END/STEP_WISE/gap = {cv}; ventaja relativa {r1}× -> {rm}× a "
                     "K={km}. {n} seeds.").format(
                         cv=" | ".join("K{}:{}/{}/{}".format(K, _fmt(curve[K]['end_to_end']),
                                                             _fmt(curve[K]['step_wise']), _fmt(curve[K]['gap'])) for K in Ks),
                         r1=_fmt(ratios[Ks[0]]), rm=_fmt(ratio_max), km=st['Kmax'], n=n_seeds),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (cuenta larga: revisar cada paso frena el compounding).")

    ceilings.add(CeilingRecord(
        subsystem="Razonamiento MULTI-PASO — verificación intermedia (proceso) vs sólo-final (resultado)",
        known_limit=("REAL (exp030): la verificación INTERMEDIA frena el compounding — ventaja relativa "
                     "step_wise/end_to_end crece monótona hasta {rm}× a K={km}. PERO a presupuesto por-paso "
                     "FIJO (k=4) AMBAS colapsan a 0 con K (step_wise {sw}, end_to_end {e2e} a K={km}); la "
                     "verificación intermedia ralentiza el compounding, no lo elimina.").format(
                         rm=_fmt(ratio_max), km=st['Kmax'], sw=_fmt(curve[Kmax]['step_wise']),
                         e2e=_fmt(curve[Kmax]['end_to_end'])),
        blockers=[{"text": "presupuesto por-paso FIJO -> cadenas largas colapsan; falta ESCALAR/ADAPTAR el presupuesto por-paso (control de 43 per-step)", "kind": "diseno"},
                  {"text": "verificador PERFECTO por paso; falta verificador ruidoso/real-chequeable per-step (el ruido per-step se compone)", "kind": "diseno"},
                  {"text": "cuando un paso no tiene NINGÚN sample correcto, step-wise commitea uno malo y descarrila; falta backtracking/abstención", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP030.ref, S_EXP029.ref]))
    notes.append("1 techo 'real': verificación intermedia frena (no elimina) el compounding; cadenas largas exigen presupuesto per-step escalado.")

    dstmt = ("El razonamiento MULTI-PASO confirma la dirección del integrador: la verificación INTERMEDIA "
             "(supervisión de proceso, act-and-verify por paso) frena drásticamente el compounding de errores "
             "frente a la verificación sólo-final (ventaja relativa creciente, hasta 23× a K=6), convergente "
             "con 'Let's Verify Step by Step' (Lightman 2023). PERO a presupuesto por-paso FIJO ambas colapsan "
             "en cadenas largas. Decisión: el integrador multi-paso usará act-and-verify POR PASO con "
             "presupuesto por-paso ESCALADO/ADAPTATIVO (el control de 43 asignando más cómputo a los pasos "
             "difíciles) y, a futuro, backtracking/abstención cuando un paso no verifique. Próximos: control "
             "adaptativo per-step en cadenas largas (H-V4-1j) + verificador ruidoso/real-chequeable per-step.")
    drat = ("exp030 (tier5, propio, {n} seeds): ventaja relativa step_wise/end_to_end crece monótona {r1}× -> "
            "{rm}× a K={km}; gap absoluto no-monótono porque ambas -> 0 (MIXTA pre-registrada). El piso de "
            "suerte (mod-20) se detectó y corrigió a verif de traza completa. Convergente con proceso>resultado "
            "(Lightman 2023).").format(n=n_seeds, r1=_fmt(ratios[Ks[0]]), rm=_fmt(ratio_max), km=st['Kmax'])
    dec = Decision(id="D-V4-9", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP030), _to_plain(S_EXP029)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-9 ACEPTADA por el ledger (tier5 exp030 + tier5 exp029).")
    except OpinionOnlyError as e:
        print("ERROR ledger D-V4-9:", e); raise

    return record, notes, status, st


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle44_multistep_reasoning',
                                description='CYCLE 44 (RESET v4, H-V4-1i: razonamiento multi-paso).')
    p.add_argument('--store', default=DEFAULT_STORE)
    p.add_argument('--results', default=DEFAULT_RESULTS)
    p.add_argument('--reset', dest='reset', action='store_true', default=True)
    p.add_argument('--no-reset', dest='reset', action='store_false')
    args = p.parse_args(argv)
    store = os.path.abspath(args.store)
    if args.reset and os.path.isdir(store):
        shutil.rmtree(store)
    os.makedirs(store, exist_ok=True)
    record, notes, status, st = run(store, os.path.abspath(args.results))
    res = record.verify_no_loss()
    print("=" * 78)
    print("RESUMEN — CYCLE 44 (RESET v4): razonamiento MULTI-PASO, verif intermedia vs sólo-final (H-V4-1i)")
    print("=" * 78)
    print("veredicto H-V4-1i:", status.upper() if status else "?")
    print("  la verificación intermedia frena el compounding (ventaja relativa creciente); ambas colapsan a K largo.")
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
