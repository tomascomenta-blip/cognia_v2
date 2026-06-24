r"""
cycle42_robust_control_signal.py — CICLO 42 (RESET v4): H-V4-1g por las compuertas del engine.

H-V4-1g: ¿una señal de control VERIFIER-FREE (auto-consistencia / consenso emergente de rollouts) recupera la
ventaja de exp026 Y resiste el ruido del verificador que hundió a la señal verifier-dependiente (exp027)?
DERIVA de exp028_robust_control_signal/results/results.json.

RESULTADO REAL: MIXTA (4 seeds in-band, M=120, avg=5, n_probe=3). Curva vnoise->AZAR/PASIVA/CONSEC_V/CONSEC_FREE:
  0.0: 0.642/0.629/0.710/0.640   0.1: 0.529/0.525/0.560/0.531   0.2: 0.446/0.485/0.412/0.444
  - ROBUSTA SÍ: a vnoise=0.20 CONSEC_FREE (0.444) supera a CONSEC_V (0.412) por +0.031 (su asignación no usa
    el verificador -> no se corrompe). A ruido alto CONSEC_V es la PEOR; CONSEC_FREE aguanta como los baselines.
  - RECUPERA-EL-EDGE NO: a verificador bueno (vnoise<=0.1) CONSEC_V DOMINA (0.710/0.560); CONSEC_FREE sólo
    EMPATA a los baselines (≈ azar/pasiva), no recupera el edge del control.
  LECCIÓN (honesta): NO hay señal de asignación única dominante en todos los regímenes de calidad del
  verificador. El control verifier-dependiente paga cuando confiás en el verificador y colapsa cuando no; el
  verifier-free es robusto pero no es un free lunch (no recupera el edge). => el integrador necesita una
  política ADAPTATIVA (estimar la fiabilidad del verificador y mezclar), no un reemplazo verifier-free.

Correr (DESPUÉS de exp028):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp028_robust_control_signal.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle42_robust_control_signal
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
                             'cycle42_robust_control_signal')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp028_robust_control_signal', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _fmt(x):
    return "{:.3f}".format(x) if isinstance(x, (int, float)) else str(x)


S_SC = Source(tier=1, ref="arXiv:2203.11171", obtained=False,
              claim=("Self-consistency (Wang 2022): muestrear varias cadenas y tomar la respuesta plural mejora "
                     "el razonamiento sin verificador externo; la consistencia correlaciona con la correctitud. "
                     "(No re-obtenido esta sesión.)"))
S_EXP027 = Source(tier=5, ref="cognia_x/experiments/exp027_noisy_verifier_ttc", obtained=True,
                  claim=("exp027 (CYCLE 41): la señal de control verifier-dependiente hereda el ruido del "
                         "verificador y se invierte a vnoise=0.20; la pasiva-entropía es robusta pero peor."))


def _curve_str(curve, noises):
    return " | ".join("{}:{}/{}/{}/{}".format(
        vn, _fmt(curve[vn]['uniform']), _fmt(curve[vn]['passive']),
        _fmt(curve[vn]['consequence_v']), _fmt(curve[vn]['consequence_free'])) for vn in noises)


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    v = data.get('verdict')
    st = data.get('stats')
    if not v or not st:
        raise SystemExit("results.json sin verdict/stats (corre exp028 primero): " + results_path)
    status = v.lower()
    noises = [str(x) for x in data.get('noises', [])]
    curve = st['curve']
    lo, hi = str(st['lo']), str(st['hi'])
    fm_v_hi = st['free_minus_v_at_hi']
    fm_p_lo = st['free_minus_passive_at_lo']
    n_seeds = st['n_seeds_used']
    cv_lo = curve[lo]['consequence_v']
    free_lo = curve[lo]['consequence_free']
    free_hi = curve[hi]['consequence_free']
    cv_hi = curve[hi]['consequence_v']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    S_EXP028 = Source(tier=5, ref="cognia_x/experiments/exp028_robust_control_signal", obtained=True,
                      claim=("exp028 (propio, {n} seeds in-band, HybridLM + verificador ruidoso, señal de "
                             "control por CONSENSO EMERGENTE p_top sin usar el verificador): ROBUSTA a ruido "
                             "alto (a vnoise={hi} CONSEC_FREE {fh} > CONSEC_V {ch}, +{dv}) pero NO recupera el "
                             "edge a verificador bueno (a vnoise={lo} CONSEC_V {cl} DOMINA; CONSEC_FREE {fl} ≈ "
                             "baselines).").format(n=n_seeds, hi=st['hi'], fh=_fmt(free_hi), ch=_fmt(cv_hi),
                                                   dv=_fmt(fm_v_hi), lo=st['lo'], cl=_fmt(cv_lo), fl=_fmt(free_lo)))
    for src in (S_SC, S_EXP027, S_EXP028):
        ledger.add_source(src)
    notes.append("3 fuentes (S_SC tier1 self-consistency; S_EXP027 tier5 fragilidad verifier-dependiente; S_EXP028 tier5 dato propio).")

    ev_for = [S_EXP028.ref]                       # la señal verifier-free SÍ es más robusta al ruido
    ev_against = [S_EXP028.ref, S_EXP027.ref]     # pero NO recupera el edge -> no domina
    adv = ("MIXTA. A FAVOR (robustez): la señal de control VERIFIER-FREE (consenso emergente p_top, sin tocar "
           "el verificador) es MÁS ROBUSTA al ruido que la verifier-dependiente — a vnoise={hi} CONSEC_FREE "
           "{fh} supera a CONSEC_V {ch} (+{dv}), justo donde CONSEC_V colapsa a la PEOR. EN CONTRA (no recupera "
           "el edge): a verificador bueno (vnoise<={lo_p}) CONSEC_V DOMINA ({cl}); CONSEC_FREE sólo EMPATA a "
           "los baselines azar/pasiva ({fl}), no recupera la ventaja del control. LECCIÓN: NO existe una señal "
           "de asignación única dominante en todos los regímenes — el control verifier-dependiente paga cuando "
           "el verificador es confiable y colapsa cuando no; el verifier-free es robusto pero no un free lunch. "
           "Ataque considerado: '¿la señal está mal construida?' -> SÍ lo estuvo (p_top·(1−p_top) era simétrica: "
           "no distinguía caos 1/3 de consenso 2/3; el test de regresión lo cazó); corregida a consenso "
           "emergente monótono, el resultado se mantuvo MIXTA -> el null es del fenómeno, no del bug. "
           "IMPLICACIÓN: el integrador necesita una política ADAPTATIVA (estimar fiabilidad del verificador y "
           "mezclar control-verifier-dependiente / verifier-free / pasiva), no un reemplazo único.").format(
               hi=st['hi'], fh=_fmt(free_hi), ch=_fmt(cv_hi), dv=_fmt(fm_v_hi), lo_p=st['lo'],
               cl=_fmt(cv_lo), fl=_fmt(free_lo))

    hyp = Hypothesis(
        id="H-V4-1g",
        statement=("Una señal de control verifier-free (consenso emergente de rollouts) recupera la ventaja de "
                   "exp026 y es más robusta al ruido del verificador que la señal verifier-dependiente."),
        prediction=("APOYADA si CONSEC_FREE (a) a vnoise=0 >= pasiva y azar (recupera) Y (b) a vnoise alto > "
                    "CONSEC_V por >=0.02 (robusta); REFUTADA si <= pasiva a 0 o <= CONSEC_V a alto; MIXTA si una. "
                    "(Pre-registrada.)"),
        status='abierta', confidence='alta',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=adv, experiment_ref="exp028_robust_control_signal")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-1g")
        notes.append("H-V4-1g marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("Sin un corrector confiable, ¿en qué problema insistir? Mirás tus PROPIOS intentos. Pero esa "
                 "pista, ¿sirve tanto como preguntarle a un buen corrector?"),
        everyday=("Estudiás sin solucionario. Si tus 3 intentos coinciden, ya lo tenés (no insistas); si son 3 "
                  "respuestas distintas, no lo controlás (no insistas); si 2 coinciden y 1 no, estás en el filo: "
                  "insistir concentra la respuesta. Esa pista (auto-consistencia) AYUDA cuando no hay corrector, "
                  "pero un buen corrector que te dice 'esa está mal' te guía MEJOR — cuando es confiable."),
        solutions=["verificador confiable -> la señal verifier-DEPENDIENTE domina (mejor guía)",
                   "verificador muy ruidoso -> la verifier-dependiente colapsa; la verifier-FREE aguanta",
                   "la verifier-free (auto-consistencia) es ROBUSTA pero NO recupera el edge del control",
                   "ninguna señal domina en todos los regímenes -> conviene MEZCLAR según la confianza en el verificador"],
        principles=["una señal de valor que NO usa el verificador es inmune a su ruido (robusta) pero pierde su guía",
                    "la auto-consistencia (consenso emergente) es una pista de controlabilidad verifier-free, no un free lunch",
                    "no hay asignación única óptima: el régimen de calidad del verificador decide cuál señal gana",
                    "el integrador debe ESTIMAR la fiabilidad del verificador y MEZCLAR señales (política adaptativa)"],
        adaptation=("Próximo (H-V4-1h): una política ADAPTATIVA que estime la fiabilidad del verificador (p.ej. "
                    "tasa de acuerdo verificador-vs-consenso) y mezcle control-verifier-dependiente / verifier-free "
                    "/ pasiva según esa estimación. También: verificador real-chequeable (código→sandbox) y "
                    "razonamiento multi-paso (el ruido se compone)."),
        measurement=("exp028: curva vnoise->AZAR/PASIVA/CONSEC_V/CONSEC_FREE = {cv}. Robusta@vnoise={hi}: "
                     "FREE-CONSEC_V=+{dv}. Recupera@vnoise={lo}: FREE-PASIVA={dp}. {n} seeds in-band.").format(
                         cv=_curve_str(curve, noises), hi=st['hi'], dv=_fmt(fm_v_hi), lo=st['lo'],
                         dp="%+.3f" % fm_p_lo, n=n_seeds),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (estudiar sin solucionario: la auto-consistencia ayuda pero no reemplaza un buen corrector).")

    ceilings.add(CeilingRecord(
        subsystem="Señal de asignación TTS bajo verificador ruidoso — no hay señal única dominante",
        known_limit=("REAL (exp028): la señal de control verifier-FREE (consenso emergente) es más robusta al "
                     "ruido que la verifier-dependiente (+{dv} a vnoise={hi}) pero NO recupera su edge a "
                     "verificador bueno (sólo empata baselines). No existe asignación única óptima: el régimen "
                     "de calidad del verificador decide. Cota nueva: el lever de control sólo se explota bien "
                     "con una política ADAPTATIVA que estime la fiabilidad del verificador.").format(
                         dv=_fmt(fm_v_hi), hi=st['hi']),
        blockers=[{"text": "falta una política ADAPTATIVA que estime la fiabilidad del verificador y mezcle señales (H-V4-1h)", "kind": "diseno"},
                  {"text": "consenso emergente con n_probe=3 es de baja resolución (p_top∈{1/3,2/3,1}); más probe = más costo", "kind": "diseno"},
                  {"text": "verificador sintético simétrico; falta uno real-chequeable y razonamiento multi-paso (el ruido se compone)", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP028.ref, S_EXP027.ref]))
    notes.append("1 techo 'real': no hay señal de asignación única dominante; el lever de control necesita política adaptativa.")

    dstmt = ("No existe una señal de asignación de cómputo test-time única óptima bajo verificador imperfecto: "
             "la señal de control VERIFIER-DEPENDIENTE (exp026) domina cuando el verificador es confiable "
             "(error<=~0.1) y colapsa cuando no; la VERIFIER-FREE (consenso emergente, exp028) es robusta al "
             "ruido pero no recupera el edge (sólo empata baselines). Decisión: el integrador no usará un "
             "reemplazo verifier-free único, sino una política ADAPTATIVA (H-V4-1h) que estime la fiabilidad del "
             "verificador (p.ej. acuerdo verificador-vs-consenso) y MEZCLE control-verifier-dependiente / "
             "verifier-free / pasiva según ese estimado. Próximos: verificador real-chequeable (código→sandbox) "
             "y razonamiento multi-paso.")
    drat = ("exp028 (tier5, propio, {n} seeds in-band): robusta@vnoise={hi} (+{dv}) pero recupera@vnoise={lo} "
            "= {dp} (empata baselines). El bug de la señal simétrica lo cazó el test de regresión; corregido, "
            "el MIXTA se mantuvo -> el null es real. Convergente con self-consistency (Wang 2022) y con "
            "exp027.").format(n=n_seeds, hi=st['hi'], dv=_fmt(fm_v_hi), lo=st['lo'], dp="%+.3f" % fm_p_lo)
    dec = Decision(id="D-V4-7", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP028), _to_plain(S_EXP027)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-7 ACEPTADA por el ledger (tier5 exp028 + tier5 exp027).")
    except OpinionOnlyError as e:
        print("ERROR ledger D-V4-7:", e); raise

    return record, notes, status, st


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle42_robust_control_signal',
                                description='CYCLE 42 (RESET v4, H-V4-1g: señal de control verifier-free vs ruido).')
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
    print("RESUMEN — CYCLE 42 (RESET v4): señal de control verifier-free vs ruido del verificador (H-V4-1g)")
    print("=" * 78)
    print("veredicto H-V4-1g:", status.upper() if status else "?")
    print("  verifier-free = robusta al ruido pero NO recupera el edge; no hay señal única dominante -> adaptativa.")
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
