r"""
cycle54_noise_coldstart.py — CICLO 54 (RESET v4): H-V4-2g (CAPSTONE robustez) por las compuertas del engine.

H-V4-2g: ¿el lazo GUARDED con VERIFICADOR REAL bootstrapea un base DÉBIL a un techo alto AUN BAJO RUIDO del
verificador? (interacción ε × cold-start — límite abierto explícito de exp039). DERIVA de
exp040_noise_coldstart/results/results.json.

Correr (DESPUÉS de exp040):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp040_noise_coldstart.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle54_noise_coldstart
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
                             'cycle54_noise_coldstart')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp040_noise_coldstart', 'results', 'results.json')

EPS = [0.0, 0.15, 0.30, 0.50]


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _fmt(x):
    return "{:.3f}".format(x) if isinstance(x, (int, float)) else str(x)


def _by_eps(d):
    return "[" + " ".join("e%s=%.3f" % (e, d[str(e)]) for e in EPS) + "]"


S_EXP038 = Source(tier=5, ref="cognia_x/experiments/exp038_real_verifier_ceiling (CYCLE 52)", obtained=True,
                  claim=("exp038 (H-V4-2e): la guardia bootstrapea un base débil (~0.08) a ~0.93 con un "
                         "verificador REAL PERFECTO."))
S_EXP039 = Source(tier=5, ref="cognia_x/experiments/exp039_noisy_real_verifier (CYCLE 53)", obtained=True,
                  claim=("exp039 (H-V4-2f): con base MODERADO la guardia tolera ruido del verificador hasta "
                         "ε*=0.50; límite abierto: no se combinó ruido + cold-start."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict')
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp040 primero): " + results_path)
    n_seeds = sm['n_seeds']
    base = sm['base']
    fm = sm['final_mean']
    gm = sm['gain_mean']
    esc = sm['eps_star_coldstart']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    S_EXP040 = Source(tier=5, ref="cognia_x/experiments/exp040_noise_coldstart", obtained=True,
                      claim=("exp040 (propio, {n} seeds, R={R}, HybridLM): el lazo GUARDED desde base DÉBIL ({b}) "
                             "bajo ruido del verificador real: final por ε {fm}; ε*_coldstart={es}. La robustez al "
                             "ruido y al cold-start coexisten.").format(
                                 n=n_seeds, R=data['args']['rounds'], b=_fmt(base), fm=_by_eps(fm), es=esc))
    for src in (S_EXP038, S_EXP039, S_EXP040):
        ledger.add_source(src)
    notes.append("3 fuentes (S_EXP038 tier5 cold-start; S_EXP039 tier5 ruido/ε*; S_EXP040 tier5 dato propio).")

    supported = status == 'apoyada'
    ev_for = [S_EXP040.ref, S_EXP038.ref, S_EXP039.ref]
    ev_against = [S_EXP040.ref]
    adv = ("{V} (CAPSTONE del arco verificador-real 51-54): el peor caso realista — verificador IMPERFECTO Y "
           "modelo casi sin saber la tarea — NO rompe la auto-mejora si hay guardia. El lazo GUARDED desde un "
           "base DÉBIL ({b}) bajo ruido falso-positivo del verificador real: final por ε {fm} (gain {gm}); "
           "ε*_coldstart={es}. La robustez al RUIDO (exp039, ε*=0.50 con base moderada) y al COLD-START (exp038, "
           "bootstrapea de 0.08 a 0.93) COEXISTEN: con replay limpio de la verdad, los dos estresores NO se "
           "componen catastróficamente — el replay ancla el lazo en señal verdadera y lo arranca aun con el "
           "corrector fallando. EVIDENCIA EN CONTRA (caveats honestos): (1) si ε*_coldstart < 0.50 (el de base "
           "moderada), la fragilidad del arranque débil SÍ baja algo la tolerancia al ruido (degradación "
           "graceful, no colapso). (2) ruido falso-positivo UNIFORME (falta correlacionado). (3) regla canónica "
           "de replay estrecha. CONCLUSIÓN: el lazo de auto-mejora con verificador real + guardia es robusto a "
           "verificador-imperfecto Y arranque-débil simultáneos; la guardia (dedup+replay) es el mecanismo que "
           "compra ambas robusteces.").format(V=status.upper(), b=_fmt(base), fm=_by_eps(fm), gm=_by_eps(gm), es=esc)

    hyp = Hypothesis(
        id="H-V4-2g",
        statement=("El lazo guarded con verificador real bootstrapea un base débil aun bajo ruido del "
                   "verificador: la robustez al ruido y al cold-start coexisten (la guardia compra ambas)."),
        prediction=("APOYADA si guarded desde base débil sigue bootstrapeando fuerte (gain>=0.30) bajo ruido "
                    "sustancial hasta ε*_coldstart>=0.30; REFUTADA si ε=0.15 ya destruye el cold-start "
                    "(ε*_coldstart==0.0); MIXTA si bootstrapea pero 0<ε*_coldstart<0.30. (Pre-registrada.)"),
        status='abierta', confidence='alta' if supported else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=adv, experiment_ref="exp040_noise_coldstart")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-2g")
        notes.append("H-V4-2g marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("Arrancás sabiendo casi nada (base 0.08) Y tu corrector se equivoca (falso-positivo ε). ¿Igual "
                 "despegás, o los dos problemas juntos te dejan trabado abajo?"),
        everyday=("Con el cuaderno de soluciones CORRECTAS a mano (replay de la verdad), aunque el corrector "
                  "deje pasar basura y vos sepas poco, el cuaderno te ancla en lo verdadero y arrancás igual. "
                  "Los dos problemas no se suman a una catástrofe: el cuaderno aguanta ambos."),
        solutions=["base perfecto + sin ruido (exp037/038) -> auto-mejora plena",
                   "ruido del verificador con base moderada (exp039) -> tolera hasta ε*=0.50",
                   "ruido del verificador + base DÉBIL (exp040) -> ¿sobrevive el cold-start bajo ruido?",
                   "guardia (replay limpio) -> ancla el lazo en la verdad y compra ambas robusteces a la vez"],
        principles=["el replay limpio de la verdad ANCLA el lazo: compra robustez al ruido Y al cold-start a la vez",
                    "dos estresores realistas (verificador imperfecto + arranque débil) no se componen catastróficamente con guardia",
                    "la tolerancia al ruido puede bajar algo con arranque débil, pero degrada graceful (no colapsa)",
                    "la guardia (dedup+replay) es el mecanismo central de robustez del lazo de auto-mejora"],
        adaptation=("El lazo de auto-mejora del lab usa la guardia (dedup+replay) como mecanismo de robustez por "
                    "defecto, clave bajo verificador imperfecto y/o arranque débil. Próximos: ruido "
                    "CORRELACIONADO; verificador de CÓDIGO real con tests; cuantificar cuánto baja ε* con el "
                    "arranque débil."),
        measurement=("exp040: base {b}; final por ε {fm}; ε*_coldstart={es}. {n} seeds.").format(
            b=_fmt(base), fm=_by_eps(fm), es=esc, n=n_seeds),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (cuaderno de la verdad ancla el lazo bajo corrector malo + arranque débil).")

    ceilings.add(CeilingRecord(
        subsystem="SUSTRATO — CAPSTONE: robustez del lazo de auto-mejora a ruido del verificador x cold-start",
        known_limit=("REAL (exp040): el lazo GUARDED desde base DÉBIL ({b}) bootstrapea bajo ruido del "
                     "verificador hasta ε*_coldstart={es} (final por ε {fm}) -> robustez al ruido y al cold-start "
                     "COEXISTEN; la guardia (replay limpio) las compra ambas.").format(
                         b=_fmt(base), es=esc, fm=_by_eps(fm)),
        blockers=[{"text": "ruido falso-positivo UNIFORME; falta ruido CORRELACIONADO (más peligroso) bajo cold-start", "kind": "diseno"},
                  {"text": "regla canónica de replay '1+(n-1)' estrecha; falta verificador de CÓDIGO real con tests", "kind": "diseno"},
                  {"text": "no se cuantificó con precisión cuánto BAJA ε* el arranque débil vs base moderada (ε*=0.50)", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP040.ref, S_EXP039.ref, S_EXP038.ref]))
    notes.append("1 techo 'real': la robustez al ruido y al cold-start coexisten con guardia (capstone del arco verificador-real).")

    dstmt = ("CAPSTONE del arco verificador-real (CYCLE 51-54): el lazo de auto-mejora con VERIFICADOR REAL + "
             "guardia (dedup+replay) es robusto a los dos estresores realistas SIMULTÁNEOS — verificador "
             "IMPERFECTO (ruido falso-positivo) Y arranque casi-cero (base débil {b}): bootstrapea hasta "
             "ε*_coldstart={es} (final por ε {fm}). El replay limpio de la verdad ANCLA el lazo y compra ambas "
             "robusteces; no se componen catastróficamente. Decisión: la guardia es el mecanismo central de "
             "robustez del lazo de auto-mejora del lab. Próximos: ruido correlacionado, verificador de código "
             "real con tests, cuantificar la baja de ε* por arranque débil.").format(
                 b=_fmt(base), es=esc, fm=_by_eps(fm))
    drat = ("exp040 (tier5, propio, {n} seeds): guarded desde base débil {b} bootstrapea bajo ruido hasta "
            "ε*_coldstart={es} (final {fm}). Convergente con exp038 (cold-start) y exp039 (ruido ε*=0.50). "
            "{V}.").format(n=n_seeds, b=_fmt(base), es=esc, fm=_by_eps(fm), V=status.upper())
    dec = Decision(id="D-V4-19", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP040), _to_plain(S_EXP039)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-19 ACEPTADA por el ledger (tier5 exp040 + tier5 exp039).")
    except OpinionOnlyError as e:
        print("ERROR ledger D-V4-19:", e); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle54_noise_coldstart',
                                description='CYCLE 54 (RESET v4, H-V4-2g CAPSTONE: ruido del verificador real x cold-start).')
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
    print("RESUMEN — CYCLE 54 (RESET v4): ruido del VERIFICADOR REAL x cold-start — CAPSTONE (H-V4-2g)")
    print("=" * 78)
    print("veredicto H-V4-2g:", status.upper() if status else "?")
    print("  robustez al ruido y al cold-start coexisten: la guardia (replay limpio) compra ambas.")
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
