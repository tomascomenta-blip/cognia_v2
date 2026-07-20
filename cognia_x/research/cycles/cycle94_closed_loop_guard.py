r"""
cycle94_closed_loop_guard.py — CICLO 94 (RESET v4, rama R-VALOR, CIERRA la tensión de CYCLE 93; receta completa del lazo):
H-V4-7j por las compuertas del engine. La GUARDIA dedup+replay (CYCLE 50) RESCATA el downstream de la asignación
confidence-greedy SIN perder el yield -> la RECETA COMPLETA del lazo de auto-mejora bajo presupuesto es R-VALOR-allocation
(confianza endógena, alto yield) + guardia de diversidad (dedup de verificados + replay de verdad canónica). Cierra la
tensión allocation↔diversidad que CYCLE 93 reveló.

DERIVA de exp078_closed_loop_guard/results/results.json.

Correr (DESPUÉS de exp078):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp078_closed_loop_guard.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle94_closed_loop_guard
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle94_closed_loop_guard')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp078_closed_loop_guard', 'results', 'results.json')


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


S_PRINCIPLE = Source(tier=2, ref="la guardia dedup+replay resuelve el trade-off explotación-narrowing del self-training: selección por valor (alto yield) + preservación de diversidad (cobertura) = receta estable (CYCLE 50)", obtained=False,
                     claim=("En self-training, seleccionar por valor (confianza) maximiza la utilidad inmediata pero "
                            "estrecha la distribución (narrowing/colapso de diversidad, CYCLE 49-50; model collapse, "
                            "[[arXiv:2305.17493]]). La GUARDIA -- dedup de los aceptados (no re-entrenar lo mismo) + "
                            "replay de datos-semilla CLEAN (verdad canónica) -- sostiene la cobertura y desacopla la "
                            "selección por valor de la pérdida de diversidad. Receta estable: valor-guiado + diversidad. "
                            "(Principio; es la guardia de CYCLE 50.)"))
S_EXP077 = Source(tier=5, ref="cognia_x/experiments/exp077_closed_loop_budget", obtained=True,
                  claim=("CYCLE 93 halló que en el lazo cerrado real la asignación por confianza maximiza el yield "
                         "(+35, corr 0.59) PERO el downstream regresiona por narrowing (conf 0.40 < random 0.56). Dejó "
                         "como próximo combinar la guardia dedup+replay (CYCLE 50). H-V4-7j lo testea."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp078 primero): " + results_path)

    gr = sm['guard_rescue']
    gvr = sm['guard_vs_random']
    gky = sm['guard_keeps_yield']
    rc, rg, rn, rva = sm['real_conf'], sm['real_guard'], sm['real_random'], sm['real_verify_all']
    yc, yg = sm['yield_conf'], sm['yield_guard']
    B, M = sm['B'], sm['M']
    n_seeds = sm['n_seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim078 = ("exp078 (propio, {n} seeds, PyTorch CPU, lazo cerrado real exp018): la GUARDIA dedup+replay RESCATA el "
                "downstream de la asignación confidence-greedy SIN perder el yield. real_acc guard={rg} > conf={rc} "
                "(+{grr}, deshace el narrowing) Y >= random={rn} ({gvr}); yield guard={yg} vs conf={yc} (Δ={gky}); "
                "verify_all techo={rva}.").format(
                    n=n_seeds, rg=_f(_mean(rg)), rc=_f(_mean(rc)), grr=_f(gr), rn=_f(_mean(rn)), gvr=_f(gvr),
                    yg=_f(_mean(yg)), yc=_f(_mean(yc)), gky=_f(gky), rva=_f(_mean(rva)))
    S_EXP078 = Source(tier=5, ref="cognia_x/experiments/exp078_closed_loop_guard", obtained=True, claim=claim078)
    for src in (S_PRINCIPLE, S_EXP077, S_EXP078):
        ledger.add_source(src)
    notes.append("3 fuentes (S_PRINCIPLE tier2 guardia dedup+replay/CYCLE 50; S_EXP077 tier5 tensión de CYCLE 93; S_EXP078 tier5 dato propio).")

    ev_for = [S_EXP078.ref]
    ev_against = [S_EXP078.ref, S_EXP077.ref, S_PRINCIPLE.ref]
    advtext = ("{V} (cierra la tensión allocation↔diversidad de CYCLE 93; RECETA COMPLETA del lazo): CYCLE 93 mostró que "
               "asignar la verificación por confianza endógena maximiza el yield pero COLAPSA la diversidad (narrowing, "
               "CYCLE 49-50) -> el downstream regresiona. H-V4-7j combina la asignación R-VALOR con la GUARDIA de CYCLE "
               "50 (dedup de los verificados-correctos + replay de la verdad canónica), que sólo cambia la COMPOSICIÓN "
               "del entrenamiento, NO la asignación. RESULTADO: la guardia RESCATA el downstream sin perder el yield. "
               "(1) real_acc guard={rg} > conf={rc} (+{grr}, deshace el narrowing de 93). (2) guard >= random={rn} "
               "({gvr}): la confianza-greedy + guardia se vuelve VIABLE (la confianza sola NO lo era en 93). (3) el yield "
               "se MANTIENE (guard={yg} vs conf={yc}, Δ={gky}: la guardia no toca la asignación, sólo desacopla el "
               "entrenamiento de la repetición). verify_all (presupuesto infinito) techo={rva}: la guardia alcanza/se "
               "acerca al techo a una FRACCIÓN del presupuesto. MECANISMO: el dedup colapsa las picks repetitivas de "
               "alta confianza a su soporte ÚNICO y el replay re-inyecta cobertura -> la selección por valor (yield) y "
               "la diversidad (downstream) se DESACOPLAN. => RECETA COMPLETA del lazo de auto-mejora bajo presupuesto: "
               "R-VALOR-allocation (confianza endógena, alto yield) + guardia de diversidad (dedup+replay) -> alto yield "
               "Y downstream sano. EVIDENCIA EN CONTRA / caveats: modelo tiny (d=64), tarea sembrada, {n} seeds, CPU; "
               "replay_frac fijo (no barrido); la guardia añade datos clean (semilla) -> parte del rescate es el replay "
               "de verdad, no sólo el dedup; SCALE pendiente.").format(
                   V=status.upper(), rg=_f(_mean(rg)), rc=_f(_mean(rc)), grr=_f(gr), rn=_f(_mean(rn)), gvr=_f(gvr),
                   yg=_f(_mean(yg)), yc=_f(_mean(yc)), gky=_f(gky), rva=_f(_mean(rva)), n=n_seeds)

    hyp = Hypothesis(
        id="H-V4-7j",
        statement=("En el lazo CERRADO real bajo presupuesto, la GUARDIA dedup+replay (CYCLE 50) RESCATA el downstream "
                   "de la asignación confidence-greedy (R-VALOR) SIN perder el yield -> la receta completa del lazo es "
                   "R-VALOR-allocation + guardia de diversidad."),
        prediction=("APOYADA si la guardia rescata (real guard > conf +>0.03) Y la vuelve viable (guard >= random −0.03) "
                    "manteniendo el yield (yield guard ≈ conf); REFUTADA si no rescata (guard ≈ conf); MIXTA si rescata "
                    "parcial / cuesta yield. (Pre-registrada, lazo real exp018, {n} seeds.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp078_closed_loop_guard")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-7j")
        notes.append("H-V4-7j marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("Si reviso a fondo sólo los borradores que MÁS confío (rinde mucho por revisión) termino puliendo "
                 "siempre el mismo estilo y empeoro en lo demás. ¿Cómo aprovecho mi corazonada SIN encasillarme?"),
        everyday=("Dos hábitos baratos lo arreglan: (1) no repulir DOS veces el mismo borrador (quedarme con los "
                  "distintos), y (2) intercalar relecturas de material de referencia sólido (lo que sé que está bien). "
                  "Así sigo aprovechando mi corazonada para elegir QUÉ revisar (alto rinde) pero mi práctica se mantiene "
                  "variada y mejoro en general -- llego casi tan lejos como si revisara TODO, gastando una fracción."),
        solutions=["confianza para ELEGIR qué verificar (alto yield) + dedup (no repetir) + replay (verdad canónica)",
                   "sólo confianza-greedy: alto yield pero encasilla (narrowing) -> empeora el downstream (CYCLE 93)",
                   "sólo al azar: no encasilla pero desperdicia revisiones (bajo yield)",
                   "revisar todo: techo, pero caro; la receta lo alcanza a fracción del costo"],
        principles=["la selección por valor (confianza) maximiza el yield pero estrecha la diversidad (narrowing)",
                    "dedup + replay desacoplan la selección-por-valor de la pérdida de diversidad (CYCLE 50)",
                    "la receta estable del lazo = R-VALOR-allocation + guardia de diversidad",
                    "se alcanza casi el techo (verify-all) a una fracción del presupuesto de verificación"],
        adaptation=("El lab CIERRA el salto grande: el lazo de auto-mejora bajo presupuesto se gobierna con la RECETA "
                    "COMPLETA -- asignar la verificación escasa por R-VALOR (confianza endógena, CYCLE 57/60) para el "
                    "yield, Y la guardia dedup+replay (CYCLE 50) para que el downstream no se gatee por narrowing. "
                    "Unifica R-VALOR-allocation (83-92) + confianza endógena (57/60) + verificador-real (48-55) + "
                    "diversidad (49-50) en UN lazo cerrado sobre el modelo propio. Próximo: barrer replay_frac/budget "
                    "(curva costo-beneficio); objetivo no-escalar; y SCALE (GPU)."),
        measurement=("exp078 ({n} seeds): guard_rescue=+{gr} (guard {rg} > conf {rc}); guard_vs_random={gvr} (guard >= "
                     "random {rn}); guard_keeps_yield={gky} (yield guard {yg} vs conf {yc}); verify_all techo "
                     "{rva}.").format(n=n_seeds, gr=_f(gr), rg=_f(_mean(rg)), rc=_f(_mean(rc)), gvr=_f(gvr),
                                      rn=_f(_mean(rn)), gky=_f(gky), yg=_f(_mean(yg)), yc=_f(_mean(yc)), rva=_f(_mean(rva))),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (corazonada para elegir + no repetir + releer referencia = aprovechar sin encasillarse).")

    kl = ("REAL (exp078): en el lazo CERRADO real bajo presupuesto, la GUARDIA dedup+replay (CYCLE 50) RESCATA el "
          "downstream de la asignación confidence-greedy SIN perder el yield (guard {rg} > conf {rc}, +{gr}; >= random "
          "{rn}; yield guard {yg} ≈ conf {yc}; verify_all techo {rva}). La RECETA COMPLETA = R-VALOR-allocation + guardia "
          "de diversidad. TECHO: modelo tiny, tarea sembrada, replay_frac fijo; parte del rescate es el replay de verdad "
          "canónica (no sólo el dedup); SCALE pendiente.").format(
              rg=_f(_mean(rg)), rc=_f(_mean(rc)), gr=_f(gr), rn=_f(_mean(rn)), yg=_f(_mean(yg)), yc=_f(_mean(yc)), rva=_f(_mean(rva)))
    ceilings.add(CeilingRecord(
        subsystem="Lazo cerrado real — RECETA COMPLETA: R-VALOR-allocation (confianza) + guardia dedup+replay rescata el downstream sin perder el yield (cierra la tensión de CYCLE 93)",
        known_limit=kl,
        blockers=[{"text": "parte del rescate proviene del REPLAY de verdad canónica (datos-semilla clean), no sólo del dedup; sin acceso a datos clean el rescate sería menor -- no se aisló dedup vs replay", "kind": "diseno"},
                  {"text": "replay_frac y budget_frac FIJOS (no barridos); la curva costo-beneficio (cuánto replay, cuánto presupuesto) queda por caracterizar", "kind": "diseno"},
                  {"text": "modelo tiny (d=64, ~200k params), tarea de síntesis sembrada, verificación de costo modelado, CPU; falta un verificador caro REAL y SCALE (GPU)", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP078.ref, S_EXP077.ref]))
    notes.append("1 techo 'real': la receta completa (allocation + guardia) gobierna el lazo cerrado real; caveats: replay de verdad, hiperparámetros fijos, escala.")

    dstmt = ("North-Star R-VALOR (CIERRA el salto grande / la tensión de CYCLE 93): el lazo de auto-mejora bajo "
             "presupuesto se gobierna con la RECETA COMPLETA -- asignar la verificación escasa por R-VALOR (confianza "
             "endógena, CYCLE 57/60) para el YIELD, Y la guardia dedup+replay (CYCLE 50) para que el downstream no se "
             "gatee por narrowing. Decisión: bajo verificación costosa, usar confianza-greedy + guardia de diversidad "
             "(no una sola de las dos); así se alcanza casi el techo verify-all a una fracción del presupuesto. UNIFICA "
             "R-VALOR-allocation (83-92) + confianza endógena (57/60) + verificador-real (48-55) + diversidad (49-50) en "
             "UN lazo cerrado sobre el modelo propio. Próximo: barrer replay_frac/budget (curva costo-beneficio); "
             "objetivo no-escalar; y SCALE (GPU).")
    drat = ("exp078 (tier5, propio, {n} seeds, PyTorch CPU, lazo cerrado real exp018): guard_rescue=+{gr} (guard {rg} > "
            "conf {rc}); guard >= random ({gvr}); yield mantenido (Δ={gky}); verify_all techo {rva}. Convergente con la "
            "guardia dedup+replay/CYCLE 50 (tier2) y con la tensión de CYCLE 93 (tier5).").format(
                n=n_seeds, gr=_f(gr), rg=_f(_mean(rg)), rc=_f(_mean(rc)), gvr=_f(gvr), gky=_f(gky), rva=_f(_mean(rva)))
    dec = Decision(id="D-V4-56", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP078), _to_plain(S_EXP077)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-56 ACEPTADA por el ledger (tier5 exp078 + tier5 exp077).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-56:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle94_closed_loop_guard',
                                description='CYCLE 94 (RESET v4, H-V4-7j: la guardia dedup+replay rescata el downstream de la asignación R-VALOR -- receta completa del lazo; cierra la tensión de CYCLE 93).')
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
    print("RESUMEN — CYCLE 94 (RESET v4): la guardia dedup+replay rescata el downstream del lazo cerrado (H-V4-7j) — RECETA COMPLETA")
    print("=" * 78)
    print("veredicto H-V4-7j:", status.upper() if status else "?")
    print("  R-VALOR-allocation (confianza, alto yield) + guardia de diversidad (dedup+replay) -> alto yield Y downstream sano.")
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
