r"""
cycle40_ttc_allocation.py — CICLO 40 (RESET v4): H-V4-1e (INTEGRADOR) por las compuertas del engine.

H-V4-1e: el salto al sustrato de LENGUAJE. El valor de CONTROLABILIDAD/CONSECUENCIA (empowerment, CYCLE
38-39) asigna CÓMPUTO de test-time (act-and-verify) sobre el MODELO PROPIO DEL LAB (HybridLM byte-level,
desde cero) + verificador chequeable (oráculo de suma), y convierte cómputo barato en respuestas correctas
mejor que el AZAR (uniforme) y que la PREDICCIÓN-PASIVA (incertidumbre), a IGUAL presupuesto. Unifica el
arco v4: R-INTERVENCIÓN (muestrear=actuar+verificar) + R-VALOR (controlabilidad como criterio de gasto).
DERIVA de exp026_ttc_allocation/results/results.json.

RESULTADO REAL: APOYADA (régimen ESCASO discriminante avg=3, 4 seeds in-band, M=120):
  CONSEC 0.562 vs AZAR 0.506 (+0.056) vs PASIVA 0.490 (+0.073); ambos > 2σ(0.045) y > margen(0.03).
  PASIVA es consistentemente la PEOR (la incertidumbre pasiva es anti-útil) — control DECISIVO del arco v4.
  CAVEAT honesto (curva completa): la ventaja existe SÓLO bajo ESCASEZ; a presupuesto generoso (avg>=6) +
  verificador perfecto el AZAR alcanza/supera (efecto techo) — misma forma que exp025 (ventaja sólo bajo
  recursos limitados). => R-VALOR aplicado AL LENGUAJE: el valor de control hace el cómputo barato cuando es
  escaso. Primer ladrillo de "algo que razona barato": TTS verifier-based guiado por controlabilidad.

Correr (DESPUÉS de exp026):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp026_ttc_allocation.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle40_ttc_allocation
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
                             'cycle40_ttc_allocation')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp026_ttc_allocation', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _fmt(x):
    return "{:.3f}".format(x) if isinstance(x, (int, float)) else str(x)


S_TTS = Source(tier=1, ref="arXiv:2408.03314", obtained=False,
               claim=("Test-time compute verifier-based: escalar el cómputo de inferencia con un "
                      "verificador supera a escalar parámetros en tareas de razonamiento. (No re-obtenido.)"))
S_EXP025 = Source(tier=5, ref="cognia_x/experiments/exp025_empowerment_downstream", obtained=True,
                  claim=("exp025 (CYCLE 39): el empowerment como valor MEJORA un agente de capacidad limitada "
                         "en tarea TABULAR. Faltaba el salto a LENGUAJE -> exp026."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    v = data.get('verdict')
    st = data.get('stats')
    if not v or not st:
        raise SystemExit("results.json sin verdict/stats (corre exp026 primero): " + results_path)
    status = v.lower()
    scarce_avg = st['scarce_avg']
    sc = st['scarce']
    cons, uni, pas = sc['consequence'], sc['uniform'], sc['passive']
    dvu, dvp, sig = sc['d_vs_uniform'], sc['d_vs_passive'], sc['two_sigma']
    curve = st['curve']
    n_seeds = st['n_seeds_used']
    # punto de techo: el avg más grande donde el azar ya alcanza/supera a la consecuencia
    avgs = sorted(int(a) for a in curve.keys())
    ceil_pt = next((a for a in avgs if a > scarce_avg and curve[str(a)]['consequence'] <= curve[str(a)]['uniform']), None)

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    S_EXP026 = Source(tier=5, ref="cognia_x/experiments/exp026_ttc_allocation", obtained=True,
                      claim=("exp026 (propio, CPU, {n} seeds in-band, modelo HybridLM byte-level desde cero + "
                             "oráculo de suma como verificador): a presupuesto ESCASO (avg={a}), asignar el "
                             "cómputo test-time por CONTROLABILIDAD/CONSECUENCIA logra acc {c} vs AZAR {u} "
                             "(+{du}) vs PASIVA-incertidumbre {p} (+{dp}); ambos > 2σ={s2}. La PASIVA es la "
                             "PEOR. Caveat: a avg>=6 el azar alcanza (techo, verificador perfecto).").format(
                                 n=n_seeds, a=scarce_avg, c=_fmt(cons), u=_fmt(uni), du=_fmt(dvu),
                                 p=_fmt(pas), dp=_fmt(dvp), s2=_fmt(sig)))
    for src in (S_TTS, S_EXP025, S_EXP026):
        ledger.add_source(src)
    notes.append("3 fuentes (S_TTS tier1 verifier-based TTS; S_EXP025 tier5 tabular previo; S_EXP026 tier5 dato propio en LENGUAJE).")

    ev_for = [S_EXP026.ref, S_EXP025.ref]
    ev_against = [S_EXP026.ref]   # honesto: la ventaja desaparece a presupuesto generoso (efecto techo)
    adv = ("APOYADA en el régimen DISCRIMINANTE. Sobre el MODELO PROPIO del lab (no un GGUF externo), en una "
           "tarea de lenguaje VERIFICABLE, asignar el cómputo de test-time (act-and-verify) por "
           "CONTROLABILIDAD/CONSECUENCIA (empowerment) supera al AZAR (+{du}) y a la PREDICCIÓN-PASIVA (+{dp}) "
           "a IGUAL presupuesto, ambos sobre 2σ ({s2}). La PASIVA-incertidumbre es la PEOR de las tres: "
           "malgasta cómputo en lo incierto-pero-no-controlable (ya resuelto / irresoluble), confirmando el "
           "arco v4 (controlabilidad≠predictibilidad) AHORA en lenguaje. Ataques considerados: (1) '¿es sólo "
           "best-of-k?' -> NO: los 3 brazos gastan el MISMO presupuesto B; sólo cambia la DISTRIBUCIÓN; el azar "
           "es best-of-k uniforme y pierde. (2) '¿el avg escaso fue elegido a posteriori?' -> NO: a avg<=n_probe "
           "el extra=0 y las políticas son idénticas POR CONSTRUCCIÓN; el discriminante es el menor avg>n_probe "
           "(pre-definido). EVIDENCIA EN CONTRA (honesta): a presupuesto generoso (avg>={cp}) + verificador "
           "perfecto el azar ALCANZA/supera (efecto techo) — la ventaja del valor existe SÓLO bajo ESCASEZ, "
           "misma forma que exp025 (capacidad limitada). Límite: verificador perfecto (oráculo); el verificador "
           "ruidoso/parcial (exp017/018) es el siguiente realismo.").format(
               du=_fmt(dvu), dp=_fmt(dvp), s2=_fmt(sig), cp=(ceil_pt if ceil_pt else "6"))

    hyp = Hypothesis(
        id="H-V4-1e",
        statement=("Sobre el modelo propio del lab (lenguaje byte-level) + verificador chequeable, asignar el "
                   "cómputo de test-time por CONTROLABILIDAD/CONSECUENCIA (empowerment) convierte cómputo barato "
                   "en respuestas correctas mejor que el azar y que la predicción-pasiva, a igual presupuesto."),
        prediction=("APOYADA si en el régimen escaso (menor avg>n_probe) consecuencia supera a azar Y a pasiva "
                    "por >=0.03 absoluto y >2σ; REFUTADA si consecuencia<=azar o consecuencia<=pasiva. "
                    "(Pre-registrada.)"),
        status='abierta', confidence='alta',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=adv, experiment_ref="exp026_ttc_allocation")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-1e")
        notes.append("H-V4-1e marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("Tenés POCO tiempo en un examen con muchos problemas. ¿Cómo repartís tu tiempo (cómputo "
                 "limitado) para sacar la mejor nota total?"),
        everyday=("Examen con reloj corriendo: NO repartís el tiempo igual (azar) ni 'por cuánto me pone "
                  "nervioso cada uno' (incertidumbre pasiva). Lo gastás donde PENSAR MÁS CAMBIA TU NOTA: ni en "
                  "los que ya clavaste (consecuencia 0) ni en los imposibles (no los controlás), sino en los "
                  "que están a tu alcance y aún no resolviste. Eso es empowerment sobre el resultado."),
        solutions=["asignar el cómputo por CONSECUENCIA/CONTROLABILIDAD -> mejor nota (exp026: +0.056 vs azar a avg=3)",
                   "asignar por INCERTIDUMBRE pasiva -> la PEOR: malgasta en lo incierto-pero-no-controlable",
                   "repartir UNIFORME (azar) -> baseline; alcanza al de consecuencia sólo con tiempo de sobra",
                   "tiempo INFINITO (verificador perfecto + presupuesto grande) -> da igual la estrategia (techo)"],
        principles=["bajo cómputo ESCASO, el valor para asignar test-time es la controlabilidad, no la incertidumbre",
                    "act-and-verify: muestrear=actuar (intervención) + verificar=quedarse con lo correcto (R-INTERVENCIÓN)",
                    "la predicción-pasiva (incertidumbre) es ANTI-útil para asignar cómputo (peor que uniforme)",
                    "la ventaja del valor aparece bajo presupuesto finito = el régimen real del lab (CPU)",
                    "el VERIFICADOR + la asignación-por-control, no los parámetros, hacen el razonamiento barato (TTS)"],
        adaptation=("Primer ladrillo del INTEGRADOR sobre el sustrato de lenguaje: un razonador act-and-verify "
                    "que reparte su cómputo limitado por controlabilidad/consecuencia. Próximo realismo: "
                    "verificador RUIDOSO/PARCIAL (exp017/018) en vez del oráculo perfecto, y estimar la "
                    "consecuencia sin un probe caro (señal más barata)."),
        measurement=("exp026: régimen escaso avg={a} -> CONSEC {c} / AZAR {u} / PASIVA {p}; "
                     "Δazar=+{du} Δpasiva=+{dp} (2σ={s2}); curva: a avg>=6 el azar alcanza (techo). "
                     "{n} seeds in-band, CPU.").format(a=scarce_avg, c=_fmt(cons), u=_fmt(uni), p=_fmt(pas),
                                                        du=_fmt(dvu), dp=_fmt(dvp), s2=_fmt(sig), n=n_seeds),
        iterations=1)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (examen con reloj: gastar el tiempo en lo controlable, no en lo incierto).")

    ceilings.add(CeilingRecord(
        subsystem="R-VALOR aplicado al LENGUAJE — controlabilidad asigna cómputo test-time (act-and-verify)",
        known_limit=("REAL (exp026, modelo propio): bajo presupuesto ESCASO, asignar test-time por "
                     "controlabilidad/consecuencia supera al azar (+{du}) y a la incertidumbre pasiva (+{dp}); "
                     "la pasiva es la PEOR. Cota: la ventaja existe SÓLO bajo escasez — a presupuesto generoso "
                     "+ verificador perfecto el azar alcanza (efecto techo).").format(du=_fmt(dvu), dp=_fmt(dvp)),
        blockers=[{"text": "verificador PERFECTO (oráculo de suma); falta el realismo de verificador ruidoso/parcial (exp017/018) sobre lenguaje", "kind": "diseno"},
                  {"text": "la señal de consecuencia usa un PROBE (n_probe samples) que consume presupuesto; falta una señal de control más barata", "kind": "diseno"},
                  {"text": "tarea aritmética de 1 paso; falta razonamiento multi-paso real (donde act-and-verify intermedio importa más)", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP026.ref, S_EXP025.ref]))
    notes.append("1 techo 'real': R-VALOR aplicado al lenguaje (controlabilidad asigna test-time bajo escasez).")

    dstmt = ("El arco v4 cruza al sustrato de LENGUAJE: sobre el modelo propio del lab (HybridLM byte-level "
             "desde cero) + verificador chequeable, asignar el cómputo de test-time (act-and-verify) por "
             "CONTROLABILIDAD/CONSECUENCIA (empowerment) supera al azar y a la predicción-pasiva bajo "
             "presupuesto escaso — unificando R-INTERVENCIÓN (muestrear+verificar) y R-VALOR (controlabilidad) "
             "AHORA en lenguaje, convergente con TTS verifier-based. Decisión: el integrador del lab será un "
             "razonador act-and-verify que reparte cómputo por control; los próximos realismos son verificador "
             "ruidoso/parcial (exp017/018), señal de consecuencia barata (sin probe caro) y razonamiento "
             "multi-paso. Restricción confirmada: la ventaja del valor vive bajo ESCASEZ de cómputo (régimen CPU).")
    drat = ("exp026 (tier5, propio): régimen escaso avg={a}: CONSEC {c} vs AZAR {u} (+{du}) vs PASIVA {p} "
            "(+{dp}), ambos >2σ={s2}; 4 seeds in-band. La pasiva es la peor. Convergente con verifier-based "
            "TTS (arXiv:2408.03314) y con el arco tabular (exp024/025). Barato: ~50s/seed CPU.").format(
                a=scarce_avg, c=_fmt(cons), u=_fmt(uni), du=_fmt(dvu), p=_fmt(pas), dp=_fmt(dvp), s2=_fmt(sig))
    dec = Decision(id="D-V4-5", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP026), _to_plain(S_EXP025)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-5 ACEPTADA por el ledger (tier5 exp026 + tier5 exp025).")
    except OpinionOnlyError as e:
        print("ERROR ledger D-V4-5:", e); raise

    return record, notes, status, st


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle40_ttc_allocation',
                                description='CYCLE 40 (RESET v4, H-V4-1e: integrador act-and-verify TTS en lenguaje).')
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
    print("RESUMEN — CYCLE 40 (RESET v4): integrador act-and-verify TTS en LENGUAJE (H-V4-1e)")
    print("=" * 78)
    print("veredicto H-V4-1e:", status.upper() if status else "?")
    print("  el valor de controlabilidad asigna el cómputo test-time mejor que azar/pasiva bajo escasez.")
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
