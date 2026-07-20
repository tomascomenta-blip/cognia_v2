r"""
cycle41_noisy_verifier_ttc.py — CICLO 41 (RESET v4): H-V4-1f por las compuertas del engine.

H-V4-1f: realismo del VERIFICADOR. ¿La ventaja de asignar cómputo test-time por CONTROLABILIDAD/CONSECUENCIA
(exp026/CYCLE 40) SOBREVIVE a un verificador RUIDOSO/PARCIAL — y hasta qué nivel? Era el techo que dejó
exp026 (oráculo perfecto, irreal). DERIVA de exp027_noisy_verifier_ttc/results/results.json.

RESULTADO REAL: MIXTA (matizada y muy informativa, 4 seeds in-band, M=120, presupuesto escaso avg=3):
  Curva vnoise -> CONSEC/AZAR/PASIVA/greedy:
    0.00: 0.544/0.490/0.483/0.317   (reproduce exp026: CONSEC +0.054, ventaja clara)
    0.05: 0.502/0.452/0.483/0.317   (ventaja vs azar +0.050 sobrevive; vs pasiva se achica)
    0.10: 0.444/0.440/0.435/0.317   (ventaja diluida en el ruido: +0.004/+0.008)
    0.20: 0.358/0.385/0.398/0.317   (ventaja INVERTIDA: la consecuencia pasa a ser la PEOR)
  TRES hallazgos honestos: (1) a vnoise=0 reproduce exp026 limpio (validación cruzada). (2) ROBUSTEZ: el
  act-and-verify NUNCA cae bajo el greedy en ningún ruido (0.358>0.317 aun a 0.20) -> samplear+verificar
  degrada con GRACIA, no hace daño. (3) FRAGILIDAD del LEVER: la ventaja del CONTROL requiere verificador
  preciso (error <=~5%); a partir de ~0.10 se diluye y a 0.20 se invierte, porque la señal de consecuencia
  depende del verificador (solved_observed) mientras la pasiva-entropía no -> el ruido corrompe MÁS la señal
  de control. => para el integrador: invertir en CALIDAD del verificador es prerequisito del lever de control.

Correr (DESPUÉS de exp027):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp027_noisy_verifier_ttc.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle41_noisy_verifier_ttc
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
                             'cycle41_noisy_verifier_ttc')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp027_noisy_verifier_ttc', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _fmt(x):
    return "{:.3f}".format(x) if isinstance(x, (int, float)) else str(x)


S_017 = Source(tier=5, ref="cognia_x/experiments/exp017_noisy_verifier", obtained=True,
               claim=("exp017 (CYCLE 30): el aprendizaje verificado tolera ruido del verificador hasta un "
                      "umbral; pasado ese umbral el bootstrapping se degrada. (Antecedente de verificador imperfecto.)"))
S_EXP026 = Source(tier=5, ref="cognia_x/experiments/exp026_ttc_allocation", obtained=True,
                  claim=("exp026 (CYCLE 40): con verificador PERFECTO, asignar test-time por controlabilidad "
                         "supera a azar/pasiva bajo escasez. Techo: oráculo perfecto irreal -> exp027."))


def _curve_str(curve, noises):
    return " | ".join("{}:{}/{}/{}/{}".format(
        vn, _fmt(curve[vn]['consequence']), _fmt(curve[vn]['uniform']),
        _fmt(curve[vn]['passive']), _fmt(curve[vn]['greedy'])) for vn in noises)


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    v = data.get('verdict')
    st = data.get('stats')
    if not v or not st:
        raise SystemExit("results.json sin verdict/stats (corre exp027 primero): " + results_path)
    status = v.lower()
    noises = [str(x) for x in data.get('noises', [])]
    curve = st['curve']                          # claves string tras json
    mod = st['mod_noise']
    am = st['at_mod']
    cons, uni, pas, grd = am['consequence'], am['uniform'], am['passive'], am['greedy']
    dvu, dvp, sig = am['d_vs_uniform'], am['d_vs_passive'], am['two_sigma']
    n_seeds = st['n_seeds_used']
    # nivel de ruido donde la ventaja vs azar deja de ser >0 (umbral de tolerancia)
    avns = sorted(float(k) for k in curve.keys())
    thr = next((vn for vn in avns if curve[str(vn) if str(vn) in curve else ("%g" % vn)]['consequence']
                <= curve[str(vn) if str(vn) in curve else ("%g" % vn)]['uniform']), None)
    c0key = next((k for k in curve.keys() if float(k) == 0.0), None)
    repro = curve.get(c0key) if c0key else None

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    S_EXP027 = Source(tier=5, ref="cognia_x/experiments/exp027_noisy_verifier_ttc", obtained=True,
                      claim=("exp027 (propio, {n} seeds in-band, HybridLM byte-level + verificador RUIDOSO "
                             "simétrico vnoise=FP=FN): a ruido moderado vnoise={m} CONSEC {c} / AZAR {u} / "
                             "PASIVA {p} / greedy {g}. A vnoise=0 reproduce exp026 (CONSEC mejor). El "
                             "act-and-verify NUNCA cae bajo greedy (robusto), pero la ventaja del CONTROL se "
                             "diluye a ~0.10 y se invierte a 0.20 (la señal de consecuencia depende del "
                             "verificador).").format(n=n_seeds, m=mod, c=_fmt(cons), u=_fmt(uni), p=_fmt(pas), g=_fmt(grd)))
    for src in (S_017, S_EXP026, S_EXP027):
        ledger.add_source(src)
    notes.append("3 fuentes (S_017 tier5 verificador ruidoso previo; S_EXP026 tier5 oráculo perfecto; S_EXP027 tier5 dato propio).")

    ev_for = [S_EXP027.ref, S_EXP026.ref]       # robustez del lazo + reproducción a vnoise=0
    ev_against = [S_EXP027.ref]                  # la VENTAJA del lever no sobrevive ruido alto
    adv = ("MIXTA, matizada. EVIDENCIA A FAVOR: (1) a vnoise=0 exp027 REPRODUCE exp026 (CONSEC {r0c} vs AZAR "
           "{r0u} vs PASIVA {r0p}) -> validación cruzada del lever. (2) ROBUSTEZ del lazo: el act-and-verify "
           "NUNCA cae por debajo del greedy ({g}) en NINGÚN nivel de ruido probado (hasta 0.20) -> samplear+"
           "verificar degrada con GRACIA, no hace daño. EVIDENCIA EN CONTRA (la razón del MIXTA): la VENTAJA "
           "del lever de CONTROL es FRÁGIL al ruido del verificador — significativa a vnoise<=0.05 (Δazar "
           "+0.05), diluida a vnoise={m} (Δazar {du}, dentro de 2σ={s2}) e INVERTIDA a 0.20 (la consecuencia "
           "pasa a ser la PEOR). MECANISMO: la señal de consecuencia usa solved_observed (depende del "
           "verificador), mientras la pasiva-entropía NO -> el ruido corrompe MÁS la señal de control. "
           "Ataque considerado: '¿es artefacto del commit-first-accepted?' -> no: a vnoise=0 commit-first = "
           "best-of-k y reproduce exp026; el efecto es del ruido, no de la regla de commit. CONCLUSIÓN para "
           "el integrador: la CALIDAD del verificador es prerequisito del lever de control (no un detalle); "
           "el siguiente paso es una señal de control MENOS dependiente del verificador o un verificador "
           "auto-calibrado.").format(
               r0c=_fmt(repro['consequence']) if repro else "?", r0u=_fmt(repro['uniform']) if repro else "?",
               r0p=_fmt(repro['passive']) if repro else "?", g=_fmt(grd), m=mod, du="%+.3f" % dvu, s2=_fmt(sig))

    hyp = Hypothesis(
        id="H-V4-1f",
        statement=("La ventaja de asignar cómputo test-time por controlabilidad (exp026) sobrevive a un "
                   "verificador ruidoso/parcial moderado y el lazo act-and-verify degrada con gracia."),
        prediction=("APOYADA si a vnoise=0.10 CONSEC>=AZAR y >=PASIVA (>2σ) sin colapso bajo greedy; REFUTADA "
                    "si CONSEC<=AZAR a 0.10 o la accuracy colapsa bajo greedy; MIXTA si parcial. (Pre-registrada.)"),
        status='abierta', confidence='alta',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=adv, experiment_ref="exp027_noisy_verifier_ttc")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-1f")
        notes.append("H-V4-1f marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("Repartís tu tiempo de examen donde 'pensar más' controla la nota (exp026), pero ahora el "
                 "CORRECTOR se equivoca a veces. ¿Sigue conviniendo la estrategia de control?"),
        everyday=("Corriges con un compañero DISTRAÍDO: a veces da por buena una respuesta mala (falso "
                  "positivo) y a veces tacha una buena (falso negativo). Si el compañero acierta casi siempre, "
                  "tu estrategia de gastar tiempo en lo controlable sigue ganando; si el compañero es un "
                  "desastre, te conviene NO confiar en su veredicto para decidir dónde insistir."),
        solutions=["verificador casi perfecto (error<=5%) -> el control sigue ganando (exp027: +0.05 a vnoise=0.05)",
                   "verificador moderado (~10%) -> la ventaja se diluye al nivel del azar",
                   "verificador malo (20%) -> el control se INVIERTE (peor que azar): la señal está corrompida",
                   "en TODOS los casos, samplear+verificar no hace daño (nunca peor que no samplear)"],
        principles=["el lazo act-and-verify degrada con GRACIA: nunca peor que el greedy (robustez del método)",
                    "pero el LEVER de control depende de la calidad del verificador -> es condicional, no incondicional",
                    "una señal de valor que depende del verificador hereda su ruido; la pasiva-entropía es más robusta pero peor",
                    "la calidad del verificador es prerequisito del lever de control, no un detalle de ingeniería"],
        adaptation=("Refina el integrador: antes de explotar el lever de controlabilidad hay que asegurar un "
                    "verificador preciso (o auto-calibrado), o usar una señal de consecuencia MENOS dependiente "
                    "del veredicto del verificador (p.ej. consecuencia estimada por divergencia de rollouts sin "
                    "etiquetar correctas). Próximo: verificador real-chequeable (código->sandbox) y señal barata."),
        measurement=("exp027: curva vnoise->CONSEC/AZAR/PASIVA/greedy = {cv}. A vnoise={m}: Δazar {du}, "
                     "Δpasiva {dp} (2σ={s2}); robustez: CONSEC>greedy en todo el rango. {n} seeds in-band.").format(
                         cv=_curve_str(curve, noises), m=mod, du="%+.3f" % dvu, dp="%+.3f" % dvp, s2=_fmt(sig), n=n_seeds),
        iterations=1)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (corrector distraído: el lever de control depende de su calidad).")

    ceilings.add(CeilingRecord(
        subsystem="R-VALOR aplicado al lenguaje bajo verificador RUIDOSO — robustez del lazo vs fragilidad del lever",
        known_limit=("REAL (exp027): el lazo act-and-verify es ROBUSTO (nunca peor que greedy hasta vnoise=0.20), "
                     "PERO la ventaja del lever de control es CONDICIONAL a la calidad del verificador: "
                     "significativa a error<=~5%, diluida a ~10%, invertida a 20%. La señal de consecuencia "
                     "hereda el ruido del verificador (depende de solved_observed); la pasiva-entropía no."),
        blockers=[{"text": "la señal de consecuencia depende del veredicto del verificador -> hereda su ruido; falta una señal de control robusta-al-ruido (p.ej. divergencia de rollouts sin etiquetas)", "kind": "diseno"},
                  {"text": "verificador sintético (flip simétrico); falta un verificador REAL-chequeable ruidoso de verdad (código->sandbox, exp018) sobre lenguaje", "kind": "diseno"},
                  {"text": "umbral de tolerancia (~5-10%) medido en tarea de 1 paso; en multi-paso el ruido se compone y el umbral puede ser más estricto", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP027.ref, S_EXP026.ref]))
    notes.append("1 techo 'real': lazo robusto pero lever de control CONDICIONAL a la calidad del verificador.")

    dstmt = ("El lever de asignar cómputo por controlabilidad (exp026) es CONDICIONAL a la calidad del "
             "verificador: el lazo act-and-verify es robusto (nunca peor que greedy) pero la VENTAJA del "
             "control sólo paga con verificador preciso (error<=~5%), se diluye a ~10% y se invierte a 20%, "
             "porque la señal de consecuencia depende del veredicto del verificador. Decisión: el integrador "
             "debe (a) priorizar un verificador preciso/auto-calibrado o (b) usar una señal de consecuencia "
             "MENOS dependiente del verificador (divergencia de rollouts sin etiquetar correctas). Próximos: "
             "verificador real-chequeable ruidoso (exp018 sobre lenguaje), señal de control robusta-al-ruido, "
             "y razonamiento multi-paso (donde el ruido se compone).")
    drat = ("exp027 (tier5, propio, 4 seeds in-band): a vnoise=0 reproduce exp026; robustez del lazo (CONSEC>"
            "greedy en todo el rango); pero Δazar pasa de +0.05 (vnoise=0.05) a {du} (0.10) a NEGATIVO (0.20). "
            "Convergente con exp017 (umbral de tolerancia al ruido del verificador). MIXTA pre-registrada.").format(du="%+.3f" % dvu)
    dec = Decision(id="D-V4-6", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP027), _to_plain(S_EXP026)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-6 ACEPTADA por el ledger (tier5 exp027 + tier5 exp026).")
    except OpinionOnlyError as e:
        print("ERROR ledger D-V4-6:", e); raise

    return record, notes, status, st


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle41_noisy_verifier_ttc',
                                description='CYCLE 41 (RESET v4, H-V4-1f: realismo del verificador en act-and-verify TTS).')
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
    print("RESUMEN — CYCLE 41 (RESET v4): realismo del verificador en act-and-verify TTS (H-V4-1f)")
    print("=" * 78)
    print("veredicto H-V4-1f:", status.upper() if status else "?")
    print("  lazo ROBUSTO (nunca peor que greedy) pero el lever de control es CONDICIONAL a la calidad del verificador.")
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
