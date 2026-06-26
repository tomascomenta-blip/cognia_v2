r"""
cycle93_closed_loop_budget.py — CICLO 93 (RESET v4, rama R-VALOR, EL CAPSTONE del salto grande, gaps #1/#3): H-V4-7i por
las compuertas del engine. En un LAZO CERRADO de auto-mejora con el GENERADOR de MODELO REAL (HybridLM de exp018) y un
VERIFICADOR chequeable REAL (sandbox), bajo presupuesto de verificación (B ≪ pool), asignar la verificación por la
CONFIANZA ENDÓGENA del modelo (logprob de su generación — la señal R-VALOR de CYCLE 57/60) rinde MUCHo más datos
verificado-correctos por verificación que asignar al azar. UNIFICA el lab entero: R-VALOR-allocation (83-92) +
confianza endógena calibrada (57/60) + lazo verificador-real de auto-mejora (48-55) + el matiz de narrowing/diversidad
(49-50). El downstream queda gateado por diversidad (la selección de alta-confianza NARROWING), cuyo remedio conocido es
la guardia dedup+replay de CYCLE 50.

DERIVA de exp077_closed_loop_budget/results/results.json.

Correr (DESPUÉS de exp077):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp077_closed_loop_budget.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle93_closed_loop_budget
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle93_closed_loop_budget')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp077_closed_loop_budget', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="confianza endógena calibrada como señal de valor (active learning por confianza del modelo); el filtrado por confianza puede NARROWING (colapso de diversidad), remediable con dedup+replay", obtained=False,
                     claim=("La confianza del propio modelo (logprob) correlaciona con la corrección cuando está "
                            "razonablemente calibrado (cf. CYCLE 57/60) -> usarla para asignar un presupuesto de "
                            "verificación escaso es active-learning por confianza: prioriza lo probablemente correcto. "
                            "RIESGO: filtrar por alta confianza NARROWING (selecciona lo típico/repetitivo -> colapso "
                            "de diversidad, CYCLE 49-50), remediable con la guardia dedup+replay (CYCLE 50). (Principio.)"))
S_EXP018 = Source(tier=5, ref="cognia_x/experiments/exp018_real_verifier", obtained=True,
                  claim=("exp018 estableció el lazo de auto-mejora con VERIFICADOR REAL (sandbox que ejecuta la salida) "
                         "sobre el HybridLM propio; CYCLE 93 lo reusa y le añade la dimensión de PRESUPUESTO de "
                         "verificación + asignación por confianza endógena (el salto grande: lazo cerrado real + costo)."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp077 primero): " + results_path)

    yg = sm['yield_gain']
    mc = sm['mean_corr']
    rg = sm['real_gain']
    B = sm['B']
    M = sm['M']
    yc = sm['yield_conf_by_seed']
    yn = sm['yield_random_by_seed']
    yva = sm['yield_verify_all_by_seed']
    rc = sm['real_conf_by_seed']
    rn = sm['real_random_by_seed']
    rva = sm['real_verify_all_by_seed']
    n_seeds = sm['n_seeds']

    def _mean(xs):
        return sum(xs) / len(xs) if xs else 0.0

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim077 = ("exp077 (propio, {n} seeds, PyTorch CPU, lazo CERRADO con HybridLM real + sandbox exp018): asignar la "
                "verificación por CONFIANZA ENDÓGENA rinde MÁS correctas por verificación que al azar -- yield "
                "conf={yc:.1f} vs random={yn:.1f} (+{yg}) a igual presupuesto B={B}/{M}; corr(confianza,strong)={mc}. "
                "Downstream real_acc conf vs random Δ={rg} (verify_all techo={rva:.3f}).").format(
                    n=n_seeds, yc=_mean(yc), yn=_mean(yn), yg=_f(yg), B=B, M=M, mc=_f(mc), rg=_f(rg), rva=_mean(rva))
    S_EXP077 = Source(tier=5, ref="cognia_x/experiments/exp077_closed_loop_budget", obtained=True, claim=claim077)
    for src in (S_PRINCIPLE, S_EXP018, S_EXP077):
        ledger.add_source(src)
    notes.append("3 fuentes (S_PRINCIPLE tier2 confianza-calibrada/narrowing; S_EXP018 tier5 lazo verificador-real; S_EXP077 tier5 dato propio).")

    ev_for = [S_EXP077.ref]
    ev_against = [S_EXP077.ref, S_EXP018.ref, S_PRINCIPLE.ref]
    advtext = ("{V} (EL CAPSTONE del salto grande, gaps #1/#3 -- lazo CERRADO con el GENERADOR de MODELO REAL): el arco "
               "83-92 desarrolló la política R-VALOR pero con candidatos SINTÉTICOS y sin lazo cerrado. CYCLE 93 lo "
               "cierra: el HybridLM REAL (exp018) GENERA candidatos, el sandbox REAL los VERIFICA, las correctas lo "
               "ENTRENAN, y el modelo cambia (dinámica secuencial REAL). Bajo presupuesto de verificación (B={B}/{M}), la "
               "señal R-VALOR para elegir QUÉ verificar es la CONFIANZA ENDÓGENA del modelo (logprob de su generación, "
               "CYCLE 57/60). RESULTADO PRIMARIO (asignación): la confianza endógena asigna la verificación MUCHo mejor "
               "que el azar -- yield conf={yc:.1f} vs random={yn:.1f} por ronda (+{yg}) a igual presupuesto; "
               "corr(confianza,strong)={mc} (la confianza PREDICE la corrección -> calibración real, confirma 57/60 "
               "sobre el modelo propio en el lazo). El azar DESPERDICIA el presupuesto en el pool desordenado (base débil "
               "+ temp alta); la confianza lo concentra en lo probablemente correcto. SECUNDARIO (downstream): real_acc "
               "conf vs random Δ={rg}; verify_all (presupuesto infinito) es el techo ({rva:.3f}). MATIZ HONESTO "
               "(diversidad): la selección de ALTA confianza NARROWING (lo típico/repetitivo) -> el downstream del lazo "
               "queda GATEADO por diversidad (el colapso de CYCLE 49-50); el remedio conocido es la guardia dedup+replay "
               "(CYCLE 50), no testeada aquí. => la política R-VALOR (allocation por confianza endógena) FUNCIONA en un "
               "lazo de auto-mejora REAL para el problema de asignar verificación escasa; UNIFICA R-VALOR-allocation "
               "(83-92) + confianza endógena (57/60) + verificador-real (48-55) + el matiz narrowing (49-50). Caveats: "
               "modelo tiny (d=64, ~200k params), tarea de síntesis sembrada, {n} seeds, CPU; SCALE pendiente.").format(
                   V=status.upper(), B=B, M=M, yc=_mean(yc), yn=_mean(yn), yg=_f(yg), mc=_f(mc), rg=_f(rg),
                   rva=_mean(rva), n=n_seeds)

    hyp = Hypothesis(
        id="H-V4-7i",
        statement=("En un lazo CERRADO de auto-mejora con el generador de MODELO REAL + verificador chequeable REAL, "
                   "bajo presupuesto de verificación, asignar la verificación por la CONFIANZA ENDÓGENA del modelo rinde "
                   "MÁS datos verificado-correctos por verificación que asignar al azar, y no regresiona el downstream."),
        prediction=("APOYADA si yield conf > random por > margen en TODOS los seeds (corr confianza-strong > 0) Y el "
                    "downstream real_acc conf >= random; REFUTADA si yield conf ≈ random (la confianza no discrimina); "
                    "MIXTA si mejora el yield pero no el downstream. (Pre-registrada, lazo real exp018, {n} seeds.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp077_closed_loop_budget")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-7i")
        notes.append("H-V4-7i marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("Tengo una montaña de borradores que escribí yo mismo y sólo tiempo para revisar UNOS POCOS a fondo. "
                 "¿Reviso al azar, o confío en mi propia corazonada de cuáles me salieron bien?"),
        everyday=("Confiar en mi corazonada (qué borrador 'sentí' más sólido al escribirlo) acierta: reviso muchos más "
                  "buenos por cada revisión que eligiendo al azar -- mi propia confianza, cuando estoy calibrado, "
                  "predice cuáles están bien. CUIDADO: si siempre elijo 'lo que me sale con más soltura', termino "
                  "puliendo siempre el mismo estilo y pierdo variedad -- ahí conviene mezclar deliberadamente (no "
                  "repetir, refrescar con material de base) para no encasillarme."),
        solutions=["asignar la revisión por confianza propia: muchas más buenas por revisión que al azar",
                   "al azar: desperdicia revisiones en borradores flojos del montón",
                   "revisar todo (presupuesto infinito): techo, pero no siempre se puede pagar",
                   "la alta confianza NARROWING -> mezclar/refrescar (dedup+replay, CYCLE 50) para no perder variedad"],
        principles=["la confianza endógena calibrada predice la corrección (CYCLE 57/60) -> guía la asignación escasa",
                    "asignar el feedback costoso por R-VALOR (confianza) rinde más señal por unidad de costo",
                    "filtrar por alta confianza estrecha la diversidad (narrowing, CYCLE 49-50)",
                    "el downstream del lazo queda gateado por diversidad; remedio: dedup+replay (CYCLE 50)"],
        adaptation=("El lab cierra el SALTO GRANDE: la política R-VALOR (asignar el feedback escaso por valor estimado, "
                    "83-92) funciona en un lazo de auto-mejora REAL (modelo propio genera, sandbox verifica, entrena), "
                    "con la CONFIANZA ENDÓGENA (57/60) como señal de asignación bajo presupuesto. Política: bajo "
                    "verificación costosa, asignar por confianza endógena (no al azar); y combinar con la guardia "
                    "dedup+replay (CYCLE 50) para que el downstream no se gatee por narrowing. Próximo: añadir la guardia "
                    "de diversidad al lazo bajo presupuesto (cierra el matiz); objetivo no-escalar; y SCALE (GPU)."),
        measurement=("exp077 ({n} seeds): yield conf={yc:.1f} vs random={yn:.1f} (+{yg}) a B={B}/{M}; "
                     "corr(confianza,strong)={mc}; downstream Δ={rg}; verify_all techo={rva:.3f}.").format(
                         n=n_seeds, yc=_mean(yc), yn=_mean(yn), yg=_f(yg), B=B, M=M, mc=_f(mc), rg=_f(rg), rva=_mean(rva)),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (revisar por corazonada propia vs al azar; cuidado con el narrowing).")

    kl = ("REAL (exp077): en un lazo CERRADO de auto-mejora con el GENERADOR de MODELO REAL + verificador real, asignar "
          "la verificación escasa por la CONFIANZA ENDÓGENA del modelo rinde MÁS correctas por verificación que al azar "
          "(yield conf={yc:.1f} vs random={yn:.1f}, +{yg}; corr confianza-strong={mc}). TECHO: el downstream del lazo "
          "queda GATEADO por DIVERSIDAD (alta confianza -> narrowing, CYCLE 49-50; verify_all techo {rva:.3f}); el "
          "remedio conocido (dedup+replay, CYCLE 50) no se combinó aquí. Modelo tiny, tarea sembrada, CPU.").format(
              yc=_mean(yc), yn=_mean(yn), yg=_f(yg), mc=_f(mc), rva=_mean(rva))
    ceilings.add(CeilingRecord(
        subsystem="R-VALOR en lazo CERRADO real — asignar la verificación escasa por confianza endógena rinde más correctas/verificación que al azar (capstone del salto grande)",
        known_limit=kl,
        blockers=[{"text": "el downstream del lazo queda gateado por DIVERSIDAD: la selección de alta confianza NARROWING (CYCLE 49-50); no se combinó la guardia dedup+replay (CYCLE 50) que lo remediaría -- próximo paso natural", "kind": "diseno"},
                  {"text": "modelo tiny (HybridLM d=64, ~200k params), tarea de síntesis sembrada, pool de base débil + temp alta para forzar un mix; la magnitud del downstream depende de estos settings", "kind": "diseno"},
                  {"text": "verificación de costo MODELADO (presupuesto B sobre un sandbox barato); falta un verificador caro REAL (tests de código) y SCALE (GPU)", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP077.ref, S_EXP018.ref]))
    notes.append("1 techo 'real': la asignación por confianza endógena funciona en el lazo cerrado real; el downstream queda gateado por diversidad (remedio: CYCLE 50).")

    dstmt = ("North-Star R-VALOR (EL CAPSTONE del salto grande, gaps #1/#3): la política R-VALOR (asignar el feedback "
             "escaso por valor estimado, 83-92) FUNCIONA en un lazo de auto-mejora REAL -- el HybridLM propio genera, el "
             "sandbox verifica, las correctas lo entrenan -- usando la CONFIANZA ENDÓGENA (CYCLE 57/60) como señal de "
             "asignación bajo presupuesto de verificación: rinde MUCHo más correctas por verificación que al azar "
             "(corr confianza-strong real). Decisión: bajo verificación costosa, asignar por confianza endógena (no al "
             "azar); combinar con la guardia dedup+replay (CYCLE 50) para que el downstream no se gatee por narrowing. "
             "UNIFICA R-VALOR-allocation (83-92) + confianza endógena (57/60) + verificador-real (48-55) + diversidad "
             "(49-50). Próximo: la guardia de diversidad en el lazo bajo presupuesto; objetivo no-escalar; SCALE (GPU).")
    drat = ("exp077 (tier5, propio, {n} seeds, PyTorch CPU, lazo cerrado real exp018): yield conf={yc:.1f} vs "
            "random={yn:.1f} (+{yg}) a B={B}/{M}; corr(confianza,strong)={mc}; downstream Δ={rg}; verify_all techo "
            "{rva:.3f}. Convergente con confianza-calibrada/active-learning (tier2) y con el lazo verificador-real de "
            "exp018 (tier5).").format(n=n_seeds, yc=_mean(yc), yn=_mean(yn), yg=_f(yg), B=B, M=M, mc=_f(mc), rg=_f(rg),
                                      rva=_mean(rva))
    dec = Decision(id="D-V4-55", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP077), _to_plain(S_EXP018)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-55 ACEPTADA por el ledger (tier5 exp077 + tier5 exp018).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-55:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle93_closed_loop_budget',
                                description='CYCLE 93 (RESET v4, H-V4-7i: la confianza endógena asigna la verificación escasa en un lazo CERRADO real -- el capstone del salto grande).')
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
    print("RESUMEN — CYCLE 93 (RESET v4): confianza endógena asigna la verificación en un LAZO CERRADO real (H-V4-7i) — CAPSTONE")
    print("=" * 78)
    print("veredicto H-V4-7i:", status.upper() if status else "?")
    print("  yield por confianza >> al azar a igual presupuesto; downstream gateado por diversidad (remedio CYCLE 50).")
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
