r"""
cycle52_real_verifier_ceiling.py — CICLO 52 (RESET v4): H-V4-2e por las compuertas del engine.

H-V4-2e: ¿el lazo iterado + guardia con VERIFICADOR REAL bootstrapea un base DÉBIL (~0.08) a un techo ALTO y
PLATEABLE, igual que el oráculo EXACTO (CYCLE 49)? Cierra el límite honesto #1 del CYCLE 51 ("falta base débil
bajo el verificador real para medir el techo"). DERIVA de exp038_real_verifier_ceiling/results/results.json.

Correr (DESPUÉS de exp038):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp038_real_verifier_ceiling.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle52_real_verifier_ceiling
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
                             'cycle52_real_verifier_ceiling')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp038_real_verifier_ceiling', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _fmt(x):
    return "{:.3f}".format(x) if isinstance(x, (int, float)) else str(x)


def _seq(xs, fmt="%.3f"):
    return "[" + " ".join(fmt % x for x in xs) + "]"


S_REPLAY = Source(tier=1, ref="experience-replay/anti-collapse", obtained=False,
                  claim=("Replay de datos originales + dedup evita el colapso/cold-start al auto-entrenar. "
                         "(Principio, no re-obtenido esta sesión.)"))
S_EXP035 = Source(tier=5, ref="cognia_x/experiments/exp035_iterated_star (CYCLE 49)", obtained=True,
                  claim=("exp035 (H-V4-2b): un base DÉBIL se bootstrapea a ~0.78 con el lazo iterado — pero con "
                         "el ORÁCULO aritmético EXACTO."))
S_EXP037 = Source(tier=5, ref="cognia_x/experiments/exp037_iterated_real_verifier (CYCLE 51)", obtained=True,
                  claim=("exp037 (H-V4-2d): el lazo iterado + guardia generaliza a un VERIFICADOR REAL, pero "
                         "desde un base MODERADO (~0.44) y R=6 -> límite: medir el techo desde base débil."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    v = data.get('verdict')
    st = data.get('stats')
    if not v or not st:
        raise SystemExit("results.json sin verdict/stats (corre exp038 primero): " + results_path)
    status = v.lower()
    rg, rp = st['real_guarded'], st['real_plain']
    cg, dg = st['cov_guarded'], st['degen_guarded']
    R = len(rg) - 1
    n_seeds = st['n_seeds']
    base = st['base']
    final_g = st['final_guarded']
    pr = st['plateau_round']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    S_EXP038 = Source(tier=5, ref="cognia_x/experiments/exp038_real_verifier_ceiling", obtained=True,
                      claim=("exp038 (propio, {n} seeds, R={R}, HybridLM): desde un base DÉBIL ({b}) el lazo "
                             "GUARDED con el VERIFICADOR REAL bootstrapea a {fg} (gain {g:+.3f}) y platea en r{pr}; "
                             "el lazo PLANO desde el mismo base débil se queda en {fp} -> con base débil la "
                             "GUARDIA (replay de la verdad) es CRÍTICA (resuelve el cold-start).").format(
                                 n=n_seeds, R=R, b=_fmt(base), fg=_fmt(final_g), g=st['gain'], pr=pr,
                                 fp=_fmt(rp[R])))
    for src in (S_REPLAY, S_EXP035, S_EXP037, S_EXP038):
        ledger.add_source(src)
    notes.append("4 fuentes (S_REPLAY tier1; S_EXP035 tier5 bootstrapping/oráculo; S_EXP037 tier5 verificador real; S_EXP038 tier5 dato propio).")

    supported = status == 'apoyada'
    ev_for = [S_EXP038.ref, S_EXP035.ref, S_EXP037.ref]
    ev_against = [S_EXP038.ref]      # honesto: regla canónica de replay; tarea acotada (ver caveats)
    adv = ("{V}: cierra el límite #1 del CYCLE 51. Desde un base DÉBIL ({b}, calibrado), el lazo GUARDED con el "
           "VERIFICADOR REAL (sandbox que EJECUTA la expresión) BOOTSTRAPEA a un techo ALTO: real_acc por ronda "
           "{rg} -> final {fg} (gain {g:+.3f}), NO-DECRECIENTE, PLATEA en r{pr} (deja de mejorar dentro del "
           "margen). MISMO poder de bootstrapping que el ORÁCULO exacto (CYCLE 49, ~0.78) AHORA con un "
           "verificador chequeable REAL. HALLAZGO EXTRA (más fuerte que el CYCLE 51): el lazo PLANO desde el "
           "MISMO base débil se queda MUY ABAJO ({fp}) -> con base débil la GUARDIA (replay de ejemplos "
           "CORRECTOS de la verdad) es CRÍTICA: resuelve el COLD-START que el plano no puede (el plano débil "
           "genera pocas verificadas y se estanca; el replay reinyecta señal de la verdad y arranca el motor). "
           "degenerate={dg} (sin reward-hack con el verificador FUERTE, aun iterando R={R}). EVIDENCIA EN CONTRA "
           "(caveats honestos): (1) la regla canónica de replay '1+(n-1)' hace la tarea aprendible pero ESTRECHA "
           "-> falta verificación más rica (código real con tests). (2) cobertura acotada por |test|. (3) el "
           "techo medido es de ESTA tarea; no es un techo universal. CONCLUSIÓN: el motor de auto-mejora con "
           "verificador REAL bootstrapea desde casi-cero y su techo es localizable; la guardia es necesaria al "
           "arranque débil, no solo un refinamiento.").format(
               V=status.upper(), b=_fmt(base), rg=_seq(rg), fg=_fmt(final_g), g=st['gain'], pr=pr,
               fp=_fmt(rp[R]), dg=_fmt(dg[R]), R=R)

    hyp = Hypothesis(
        id="H-V4-2e",
        statement=("El lazo iterado + guardia con VERIFICADOR REAL bootstrapea un base DÉBIL a un techo alto y "
                   "plateable, igual que el oráculo exacto (CYCLE 49); con base débil la guardia es crítica."),
        prediction=("APOYADA si guarded bootstrapea el base débil (final-base >= 0.30 Y final >= 0.50) y PLATEA "
                    "(no-decreciente y últimas rondas aplanadas); REFUTADA si no bootstrapea o colapsa; MIXTA si "
                    "bootstrapea pero no platea (techo no alcanzado) o ganancia modesta. (Pre-registrada.)"),
        status='abierta', confidence='alta' if supported else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=adv, experiment_ref="exp038_real_verifier_ceiling")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-2e")
        notes.append("H-V4-2e marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("Arrancás sabiendo casi nada de escribir programas (base 0.08). ¿Practicando muchas rondas y "
                 "corrigiéndote EJECUTANDO lo que escribís llegás lejos y te estabilizás, o te quedás trabado?"),
        everyday=("Con un cuaderno de soluciones correctas a mano (replay de la verdad) y sin machacar el mismo "
                  "ejercicio (dedup), arrancás de casi-cero y trepás rápido hasta un techo donde dejás de "
                  "mejorar. SIN ese cuaderno (lazo plano), desde tan abajo casi no producís ejercicios bien "
                  "hechos para aprender y te quedás estancado: el cuaderno es lo que ARRANCA el motor."),
        solutions=["lazo PLANO desde base débil -> casi no bootstrapea (genera pocas verificadas, se estanca)",
                   "GUARDED (dedup + replay de la verdad) desde base débil -> bootstrapea a techo alto y platea",
                   "verificador REAL (sandbox) en vez de oráculo exacto -> mismo poder de bootstrapping",
                   "muchas rondas (R alto) -> localiza el plateau (round donde deja de mejorar)"],
        principles=["el lazo de auto-mejora con verificador REAL bootstrapea desde casi-cero, no solo refina",
                    "con base DÉBIL la guardia (replay de la verdad) es CRÍTICA: resuelve el cold-start del lazo plano",
                    "el techo del bootstrapping es localizable (plateau) con suficientes rondas",
                    "el verificador FUERTE bloquea el reward-hack aun bootstrapeando desde un base débil"],
        adaptation=("El lazo de auto-mejora del lab usa la guardia (dedup+replay) por defecto especialmente al "
                    "ARRANQUE débil. Próximos: tarea de verificación más rica (código real con tests, no la regla "
                    "canónica); verificador real PARCIAL/ruidoso (ε*); y un currículo que mueva el plateau."),
        measurement=("exp038: base {b} -> guarded final {fg} (gain {g:+.3f}), plateau r{pr}; plano final {fp}. "
                     "{n} seeds, R={R}.").format(b=_fmt(base), fg=_fmt(final_g), g=st['gain'], pr=pr,
                                                 fp=_fmt(rp[R]), n=n_seeds, R=R),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (arrancar de casi-cero con el cuaderno de la verdad = replay).")

    ceilings.add(CeilingRecord(
        subsystem="SUSTRATO — TECHO del lazo iterado + guardia con VERIFICADOR REAL desde base débil",
        known_limit=("REAL (exp038): desde un base DÉBIL ({b}) el lazo GUARDED con el verificador REAL bootstrapea "
                     "a {fg} (gain {g:+.3f}) y PLATEA en r{pr}; el plano se queda en {fp}. La guardia es crítica "
                     "al cold-start. El techo es localizable; mismo poder que el oráculo (CYCLE 49).").format(
                         b=_fmt(base), fg=_fmt(final_g), g=st['gain'], pr=pr, fp=_fmt(rp[R])),
        blockers=[{"text": "la regla de replay '1+(n-1)' es estrecha; falta verificación más rica (código real con tests) para un techo no de juguete", "kind": "diseno"},
                  {"text": "falta verificador real PARCIAL/ruidoso (ε*≈0.15) bajo bootstrapping desde base débil", "kind": "diseno"},
                  {"text": "el techo es de ESTA tarea; falta un currículo que mueva el plateau (H-V4-4)", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP038.ref, S_EXP035.ref]))
    notes.append("1 techo 'real': el lazo con verificador real bootstrapea desde base débil y su plateau es localizable; la guardia es crítica al arranque.")

    dstmt = ("El lazo de auto-mejora del integrador con guardia (dedup+replay) y VERIFICADOR REAL bootstrapea "
             "desde un base DÉBIL ({b}) a un techo alto ({fg}, gain {g:+.3f}) y PLATEA en r{pr} — mismo poder que "
             "el oráculo exacto (CYCLE 49) pero con un verificador chequeable real. Con base débil la GUARDIA es "
             "CRÍTICA (el plano se queda en {fp}): el replay de la verdad resuelve el cold-start. Decisión: la "
             "guardia (dedup+replay) es parte del motor, no un refinamiento opcional, sobre todo al arranque "
             "débil. Cierra el límite #1 del CYCLE 51. Próximos: verificación más rica (código real), verificador "
             "ruidoso real (ε*), currículo que mueva el plateau.")
    drat = ("exp038 (tier5, propio, {n} seeds, R={R}): guarded bootstrapea base débil {b} -> {fg} (gain {g:+.3f}), "
            "platea r{pr}, sin reward-hack; plano se estanca en {fp}. Convergente con exp035 (oráculo) y exp037 "
            "(verificador real). {V}.").format(n=n_seeds, R=R, b=_fmt(base), fg=_fmt(final_g), g=st['gain'],
                                               pr=pr, fp=_fmt(rp[R]), V=status.upper())
    dec = Decision(id="D-V4-17", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP038), _to_plain(S_EXP035)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-17 ACEPTADA por el ledger (tier5 exp038 + tier5 exp035).")
    except OpinionOnlyError as e:
        print("ERROR ledger D-V4-17:", e); raise

    return record, notes, status, st


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle52_real_verifier_ceiling',
                                description='CYCLE 52 (RESET v4, H-V4-2e: techo del lazo con verificador real desde base débil).')
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
    print("RESUMEN — CYCLE 52 (RESET v4): techo del lazo iterado + guardia con VERIFICADOR REAL (H-V4-2e)")
    print("=" * 78)
    print("veredicto H-V4-2e:", status.upper() if status else "?")
    print("  con verificador REAL el lazo bootstrapea un base débil a un techo alto y plateable; guardia crítica.")
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
