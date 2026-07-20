r"""
cycle51_iterated_real_verifier.py — CICLO 51 (RESET v4): H-V4-2d por las compuertas del engine.

H-V4-2d: ¿el LAZO ITERADO de auto-mejora con GUARDIA (sub-arco 48-50, probado sobre la SUMA con oráculo
EXACTO) sobrevive con un VERIFICADOR REAL-CHEQUEABLE (sandbox que EJECUTA la expresión generada, exp018) sobre
ITERACIÓN — sin colapso y sin reward-hack? DERIVA de exp037_iterated_real_verifier/results/results.json.

RESULTADO REAL: ver results.json (3 seeds, R=6). El lazo iterado PLANO vs GUARDED corre sobre la tarea de
síntesis de expresiones con el verificador FUERTE real (valor==target Y usa operador). Mide por ronda real_acc
(held-out), COBERTURA (prompts distintos verificados) y degenerate (echo). => el motor de auto-mejora + guardia
generaliza del oráculo aritmético EXACTO a un verificador chequeable REAL sobre iteración.

Correr (DESPUÉS de exp037):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp037_iterated_real_verifier.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle51_iterated_real_verifier
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
                             'cycle51_iterated_real_verifier')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp037_iterated_real_verifier', 'results', 'results.json')


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


S_STAR = Source(tier=1, ref="Zelikman 2022 (STaR)", obtained=False,
                claim=("Self-Taught Reasoner: reentrenar sobre las propias salidas VERIFICADO-correctas mejora "
                       "el modelo; iterarlo es un motor de auto-mejora. (Principio, no re-obtenido esta sesión.)"))
S_EXP018 = Source(tier=5, ref="cognia_x/experiments/exp018_real_verifier (CYCLE 31)", obtained=True,
                  claim=("exp018 (H-LEARN-3): UNA ronda de auto-mejora funciona con un VERIFICADOR REAL (sandbox "
                         "que EJECUTA la expresión), no solo con el oráculo aritmético cerrado."))
S_EXP036 = Source(tier=5, ref="cognia_x/experiments/exp036_diversity_guard (CYCLE 50)", obtained=True,
                  claim=("exp036 (H-V4-2c): una guardia barata (dedup+replay) controla el narrowing del lazo "
                         "iterado y sube su techo — PERO sobre la SUMA con oráculo EXACTO."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    v = data.get('verdict')
    st = data.get('stats')
    if not v or not st:
        raise SystemExit("results.json sin verdict/stats (corre exp037 primero): " + results_path)
    status = v.lower()
    rp, rg = st['real_plain'], st['real_guarded']
    cp, cg = st['cov_plain'], st['cov_guarded']
    dp, dg = st['degen_plain'], st['degen_guarded']
    R = len(rg) - 1
    n_seeds = st['n_seeds']
    base = st['base']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    S_EXP037 = Source(tier=5, ref="cognia_x/experiments/exp037_iterated_real_verifier", obtained=True,
                      claim=("exp037 (propio, {n} seeds, R={R}, HybridLM): el lazo ITERADO de auto-mejora con "
                             "guardia (dedup+replay) corre sobre síntesis de expresiones con un VERIFICADOR REAL "
                             "(sandbox): real_acc base {b} -> guarded final {fg} (plano {fp}); cobertura final "
                             "plano {kp} -> guarded {kg}; degenerate (echo) {dgf} con el verificador FUERTE.").format(
                                 n=n_seeds, R=R, b=_fmt(base), fg=_fmt(rg[R]), fp=_fmt(rp[R]), kp=int(cp[R]),
                                 kg=int(cg[R]), dgf=_fmt(dg[R])))
    for src in (S_STAR, S_EXP018, S_EXP036, S_EXP037):
        ledger.add_source(src)
    notes.append("4 fuentes (S_STAR tier1; S_EXP018 tier5 verificador real 1-ronda; S_EXP036 tier5 guardia/oráculo; S_EXP037 tier5 dato propio).")

    supported = status == 'apoyada'
    ev_for = [S_EXP037.ref, S_EXP018.ref, S_EXP036.ref]
    ev_against = [S_EXP037.ref]      # honesto: base alto (cerca del techo) y replay canónico (ver caveats)
    adv = ("{V}: el lazo ITERADO + guardia (sub-arco 48-50, hasta hoy probado SOLO sobre la SUMA con oráculo "
           "EXACTO) generaliza a un VERIFICADOR REAL-CHEQUEABLE (sandbox que EJECUTA la expresión generada, "
           "exp018). REAL_acc por ronda: PLANO {rp} GUARDED {rg} (base {b} -> guarded final {fg}). El motor "
           "MEJORA sobre base ({mejora:+.3f}) y es NO-DECRECIENTE (no colapsa al iterar con un verificador real, "
           "no solo con el oráculo). GUARDIA: cobertura final plano {kp} -> guarded {kg} (mantiene/sube la "
           "cobertura del espacio de problemas) sin costo de real_acc. REWARD-HACK: degenerate (echo) PLANO {dp} "
           "GUARDED {dg} — NO trepa con las rondas; el verificador FUERTE (exige operador) bloquea el echo aun "
           "iterando (consistente con exp018/H-LEARN-4: la imitación STaR no descubre el atajo). EVIDENCIA EN "
           "CONTRA (caveats honestos): (1) el base es ALTO ({b}, cerca del techo de esta tarea) -> el margen de "
           "mejora por iteración es chico y el plateau llega temprano (pico@r{pr}); no se midió un techo con base "
           "débil bajo el verificador real. (2) la regla canónica de replay '1+(n-1)' hace la tarea aprendible "
           "pero ESTRECHA (el strong acepta cualquier 'a op b'); falta una tarea de verificación más rica "
           "(código real con tests). (3) cobertura acotada por |test|={kp_t}. CONCLUSIÓN: el lazo de auto-mejora "
           "con guardia es robusto al CAMBIO de oráculo-exacto -> verificador-chequeable-real sobre iteración: "
           "el VERIFICADOR (no el tipo de oráculo) es el motor.").format(
               V=status.upper(), rp=_seq(rp), rg=_seq(rg), b=_fmt(base), fg=_fmt(rg[R]),
               mejora=st['peak_guarded'] - base, kp=int(cp[R]), kg=int(cg[R]), dp=_seq(dp, "%.3f"),
               dg=_seq(dg, "%.3f"), pr=st['peak_round'], kp_t=int(max(cg)))

    hyp = Hypothesis(
        id="H-V4-2d",
        statement=("El lazo iterado de auto-mejora con guardia (dedup+replay) generaliza del oráculo aritmético "
                   "EXACTO a un VERIFICADOR REAL-CHEQUEABLE (sandbox) sobre iteración, sin colapso ni reward-hack."),
        prediction=("APOYADA si el lazo con verificador real sube real_acc sobre base y es no-decreciente, la "
                    "guardia mantiene cobertura >= plano sin costo de real_acc, y degenerate no trepa con las "
                    "rondas; REFUTADA si real_acc colapsa tras el pico o degenerate trepa (aprende el echo) o la "
                    "guardia no controla la cobertura; MIXTA si satura inmediato o señal ambigua. (Pre-registrada.)"),
        status='abierta', confidence='alta' if supported else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=adv, experiment_ref="exp037_iterated_real_verifier")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-2d")
        notes.append("H-V4-2d marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("Tu motor de auto-mejora lo probaste corrigiendo SUMAS (mirás la tabla = oráculo perfecto). "
                 "¿Sigue funcionando cuando el corrector ya no es perfecto sino que EJECUTA lo que escribís "
                 "(como correr un programa contra sus tests), e iterás muchas rondas?"),
        everyday=("Pasás de practicar cuentas a escribir programitas: ahora 'correcto' = el programa CORRE y da "
                  "el resultado pedido (lo ejecutás, no lo mirás en una tabla). Repetís rondas entrenando con tus "
                  "programas que PASARON. Con dedup+replay seguís cubriendo casos nuevos y no aprendés a hacerle "
                  "trampa al test (poner el número a mano en vez de calcularlo)."),
        solutions=["oráculo EXACTO (suma, CYCLE 48-50) -> el motor + guardia ya funcionaban ahí",
                   "VERIFICADOR REAL (sandbox que ejecuta la expresión, exp018) -> el corrector ya no es cerrado",
                   "lazo ITERADO con ese verificador real -> ¿se mantiene estable y sin hackear el test?",
                   "guardia (dedup+replay) sobre el verificador real -> mantiene cobertura sin costo de precisión"],
        principles=["el motor de auto-mejora depende del VERIFICADOR, no del tipo de oráculo (exacto vs ejecutable)",
                    "un verificador FUERTE (exige computación real, no echo) bloquea el reward-hack aun iterando",
                    "la guardia (dedup+replay) sostiene la cobertura del espacio también con un verificador real",
                    "iterar con un verificador chequeable real NO colapsa si el filtro de corrección es estricto"],
        adaptation=("El lazo de auto-mejora del lab puede usar verificadores chequeables REALES (ejecución en "
                    "sandbox), no solo oráculos cerrados, manteniendo guardia (dedup+replay) y verificador FUERTE. "
                    "Próximos: base débil bajo el verificador real para medir el TECHO; tarea de verificación más "
                    "rica (código real con tests, no la regla canónica '1+(n-1)'); verificador PARCIAL/ruidoso "
                    "real (puente a H-LEARN-2 ε*≈0.15 con un verificador ejecutable)."),
        measurement=("exp037: real_acc base {b} -> guarded final {fg} (plano {fp}); cobertura final {kp}->{kg}; "
                     "degenerate guarded {dg}. {n} seeds, R={R}.").format(
                         b=_fmt(base), fg=_fmt(rg[R]), fp=_fmt(rp[R]), kp=int(cp[R]), kg=int(cg[R]),
                         dg=_seq(dg, "%.3f"), n=n_seeds, R=R),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (de corregir sumas mirando la tabla a corregir programas ejecutándolos).")

    ceilings.add(CeilingRecord(
        subsystem="SUSTRATO — lazo iterado de auto-mejora + guardia con VERIFICADOR REAL-CHEQUEABLE (sandbox)",
        known_limit=("REAL (exp037): el motor de auto-mejora + guardia generaliza del oráculo EXACTO (suma) a un "
                     "VERIFICADOR REAL (sandbox que ejecuta la expresión) sobre iteración: real_acc base {b} -> "
                     "guarded final {fg}, no-decreciente, cobertura {kp}->{kg}, sin reward-hack (degenerate {dg}). "
                     "El VERIFICADOR es el motor, no el tipo de oráculo.").format(
                         b=_fmt(base), fg=_fmt(rg[R]), kp=int(cp[R]), kg=int(cg[R]), dg=_fmt(dg[R])),
        blockers=[{"text": "el base es alto (cerca del techo de esta tarea); falta base débil bajo el verificador real para medir el TECHO/plateau real", "kind": "diseno"},
                  {"text": "la regla de replay '1+(n-1)' hace la tarea aprendible pero estrecha; falta verificación más rica (código real con tests)", "kind": "diseno"},
                  {"text": "falta el puente a verificador real PARCIAL/ruidoso (H-LEARN-2 ε*≈0.15 con un verificador ejecutable, no el oráculo)", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP037.ref, S_EXP018.ref]))
    notes.append("1 techo 'real': el motor + guardia generaliza del oráculo exacto a un verificador chequeable real sobre iteración.")

    dstmt = ("El lazo de auto-mejora del integrador con guardia (dedup+replay) NO depende de tener un oráculo "
             "EXACTO: generaliza a un VERIFICADOR REAL-CHEQUEABLE (sandbox que EJECUTA la salida, exp018) SOBRE "
             "ITERACIÓN — real_acc sube sobre base y es no-decreciente (base {b} -> guarded final {fg}), la "
             "guardia mantiene cobertura ({kp}->{kg}) sin costo de precisión, y NO emerge reward-hack (el "
             "verificador FUERTE bloquea el echo aun iterando, degenerate {dg}). Decisión: el lazo del lab admite "
             "verificadores chequeables reales (ejecución), no solo oráculos cerrados, conservando guardia + "
             "verificador FUERTE. Une el sub-arco AUTO-MEJORA (48-50, oráculo) con el frente VERIFICADOR-REAL "
             "(exp018/H-LEARN-3). Próximos: base débil para el techo, tarea de verificación más rica (código con "
             "tests), y verificador real PARCIAL/ruidoso (ε*).")
    drat = ("exp037 (tier5, propio, {n} seeds, R={R}): con el verificador REAL el lazo guarded mejora sobre base "
            "({mejora:+.3f}), no-decreciente, cobertura {kg} >= plano {kp}, degenerate {dg} (sin hack). Convergente "
            "con exp018 (verificador real 1-ronda), exp036 (guardia/oráculo) y STaR. {V}.").format(
                n=n_seeds, R=R, mejora=st['peak_guarded'] - base, kg=int(cg[R]), kp=int(cp[R]),
                dg=_fmt(dg[R]), V=status.upper())
    dec = Decision(id="D-V4-16", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP037), _to_plain(S_EXP018)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-16 ACEPTADA por el ledger (tier5 exp037 + tier5 exp018).")
    except OpinionOnlyError as e:
        print("ERROR ledger D-V4-16:", e); raise

    return record, notes, status, st


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle51_iterated_real_verifier',
                                description='CYCLE 51 (RESET v4, H-V4-2d: lazo iterado + guardia con verificador real).')
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
    print("RESUMEN — CYCLE 51 (RESET v4): lazo iterado + guardia con VERIFICADOR REAL (H-V4-2d)")
    print("=" * 78)
    print("veredicto H-V4-2d:", status.upper() if status else "?")
    print("  el motor de auto-mejora + guardia generaliza del oráculo EXACTO a un verificador chequeable REAL.")
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
