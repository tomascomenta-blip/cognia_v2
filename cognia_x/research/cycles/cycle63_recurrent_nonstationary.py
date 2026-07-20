r"""
cycle63_recurrent_nonstationary.py — CICLO 63 (RESET v4): H-V4-1f por las compuertas del engine. North-Star
R-VALOR x memoria — no-estacionariedad RECURRENTE.

H-V4-1f: el olvido maneja no-estacionariedad RECURRENTE (la causa cambia varias veces); el committed se atasca
PROGRESIVAMENTE y el adaptativo por sorpresa sigue la causa vigente. HALLAZGO: en mundo recurrente el olvido
CONSTANTE supera al surprise-gating (refina CYCLE 59). DERIVA de exp049_recurrent_nonstationary/results/results.json.

Correr (DESPUÉS de exp049):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp049_recurrent_nonstationary.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle63_recurrent_nonstationary
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
                             'cycle63_recurrent_nonstationary')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp049_recurrent_nonstationary', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_NONSTAT = Source(tier=1, ref="non-stationary tracking / constant-forgetting filters", obtained=False,
                   claim=("En entornos que cambian RECURRENTEMENTE, un olvido constante (filtro con descuento) "
                          "sigue mejor que acumular todo; gatear el olvido por sorpresa ayuda en cambios "
                          "aislados pero sobre-committea si el mundo nunca se estabiliza. (Principio.)"))
S_EXP045 = Source(tier=5, ref="cognia_x/experiments/exp045 (CYCLE 59)", obtained=True,
                  claim=("exp045 (H-V4-1e): el olvido ADAPTATIVO por sorpresa fue óptimo para UN cambio aislado "
                         "(estabilidad cuando estable + plasticidad al cambio). ¿Y para cambios recurrentes?"))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp049 primero): " + results_path)
    ba = sm['by_arm']
    com, fix, ada = ba['committed'], ba['fixed'], ba['adaptive']
    n_seeds = sm['n_seeds']
    n_changes = sm['n_phases'] - 1

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    S_EXP049 = Source(tier=5, ref="cognia_x/experiments/exp049_recurrent_nonstationary", obtained=True,
                      claim=("exp049 (propio, {n} seeds, bayesiano numpy, {c} cambios de causa): el committed se "
                             "atasca PROGRESIVAMENTE (post-vigente por fase {ct}, post-cambio {cm}); el adaptativo "
                             "sigue la causa vigente (post-cambio {am}); el olvido CONSTANTE es el mejor "
                             "({fm}).").format(n=n_seeds, c=n_changes, ct=str(com['post_per_phase']),
                                               cm=_f(com['post_change_mean']), am=_f(ada['post_change_mean']),
                                               fm=_f(fix['post_change_mean'])))
    for src in (S_NONSTAT, S_EXP045, S_EXP049):
        ledger.add_source(src)
    notes.append("3 fuentes (S_NONSTAT tier1 tracking no-estacionario; S_EXP045 tier5 CYCLE59; S_EXP049 tier5 dato propio).")

    ev_for = [S_EXP049.ref, S_EXP045.ref]
    ev_against = [S_EXP049.ref]
    adv = ("{V}: extiende R-VALOR x memoria a no-estacionariedad RECURRENTE (la causa cambia {c} veces), no un "
           "solo cambio (CYCLE 58/59). MISMA política (info-gain); sólo cambia el OLVIDO. RESULTADO: el COMMITTED "
           "(decay=1) se atasca PROGRESIVAMENTE — post-vigente por fase {ct}: acumular commitment lo deja cada "
           "vez MÁS trabado (post-cambio {cm}). El ADAPTATIVO por sorpresa SIGUE la causa vigente fase a fase "
           "(post-cambio {am}), detectando cada cambio por su propia sorpresa, sin que le digan cuándo cambia. "
           "HALLAZGO CLAVE (refina CYCLE 59): el olvido CONSTANTE (fixed decay=0.85, post-cambio {fm}) SUPERA al "
           "adaptativo ({am}) en el mundo recurrente -- cuando el mundo NUNCA se estabiliza, 'committear cuando "
           "confirma' (la virtud del surprise-gating para UN cambio) se vuelve un VICIO (sobre-committea en "
           "sub-fases y luego laggea); el olvido constante, bien matcheado a un mundo siempre-cambiante, va "
           "mejor. => el ÓPTIMO de olvido DEPENDE del régimen de no-estacionariedad: surprise-gated para cambios "
           "AISLADOS (CYCLE 59), constante para RECURRENTES. EVIDENCIA EN CONTRA (caveats honestos): (1) el "
           "veredicto APOYADA es por 'el olvido maneja recurrencia y el committed se atasca'; pero el adaptativo "
           "NO es el mejor olvido aquí (lo es el constante) -> matiz importante. (2) a budget por fase LARGO "
           "(K_phase~30) el committed re-adapta solo por desconfirmación (boundary del CYCLE 58); el efecto "
           "requiere fases cortas. (3) mundo de juguete. CONCLUSIÓN: el olvido es necesario en no-estacionariedad "
           "recurrente y el committed clásico falla progresivamente; el TIPO óptimo de olvido (constante vs "
           "adaptativo) depende del régimen -- un meta-parámetro que un VALOR endógeno debería elegir.").format(
               V=status.upper(), c=n_changes, ct=str(com['post_per_phase']), cm=_f(com['post_change_mean']),
               am=_f(ada['post_change_mean']), fm=_f(fix['post_change_mean']))

    hyp = Hypothesis(
        id="H-V4-1f",
        statement=("El olvido maneja no-estacionariedad RECURRENTE: el committed se atasca progresivamente y el "
                   "adaptativo por sorpresa sigue la causa vigente; el TIPO óptimo de olvido depende del régimen "
                   "(constante mejor para recurrente, surprise-gated para cambio aislado)."),
        prediction=("APOYADA si el adaptive sigue la causa vigente post-cambio (>=0.45, +>0.15 sobre committed) y "
                    "el committed se atasca progresivamente; REFUTADA si el adaptive no supera al committed; MIXTA "
                    "si supera pero no sostenido. (Pre-registrada.)"),
        status='abierta', confidence='alta' if status == 'apoyada' else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=adv, experiment_ref="exp049_recurrent_nonstationary")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-1f")
        notes.append("H-V4-1f marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("El temario del examen cambia VARIAS veces en el curso. ¿Cómo seguís el temario VIGENTE en cada "
                 "etapa sin que te avisen los cambios?"),
        everyday=("El que NUNCA olvida sabe sólo el PRIMER temario y cada vez le cuesta más cambiar (acumula). El "
                  "que suelta lo viejo cuando empieza a fallar (sorpresa) sigue el vigente. Pero si el temario "
                  "cambia TODO el tiempo, conviene olvidar un poco SIEMPRE (constante) en vez de esperar a "
                  "fallar: el ritmo fijo le gana al gatillo por sorpresa cuando nada se estabiliza."),
        solutions=["committed (nunca olvida) -> atascado en el primer temario, cada vez más trabado",
                   "adaptive (olvida al fallar) -> sigue los cambios, pero sobre-committea en sub-fases estables",
                   "fixed (olvido constante) -> el MEJOR en un mundo que siempre cambia (bien matcheado al régimen)",
                   "=> el ÓPTIMO de olvido depende del régimen de no-estacionariedad"],
        principles=["el committed se atasca PROGRESIVAMENTE en no-estacionariedad recurrente (acumula commitment)",
                    "el olvido (cualquiera) es necesario para seguir la causa vigente en cambios recurrentes",
                    "el TIPO óptimo de olvido depende del régimen: constante para recurrente, surprise-gated para aislado",
                    "elegir el meta-parámetro de olvido según el régimen es, en sí, una decisión de VALOR endógeno"],
        adaptation=("El lab reconoce que el olvido óptimo depende del régimen de no-estacionariedad; un VALOR "
                    "endógeno debería ELEGIR el tipo/ritmo de olvido (constante vs adaptativo) según el régimen "
                    "detectado. Próximos: un agente que estime la TASA de cambio del mundo y ajuste su olvido; "
                    "combinar surprise-gating con un piso de olvido constante."),
        measurement=("exp049 ({c} cambios): committed post-cambio {cm} (atascado, por fase {ct}); adaptive {am}; "
                     "fixed {fm} (mejor). {n} seeds.").format(c=n_changes, cm=_f(com['post_change_mean']),
                                                              ct=str(com['post_per_phase']),
                                                              am=_f(ada['post_change_mean']),
                                                              fm=_f(fix['post_change_mean']), n=n_seeds),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (temario que cambia varias veces: ritmo fijo de olvido le gana al gatillo por sorpresa).")

    ceilings.add(CeilingRecord(
        subsystem="R-VALOR x MEMORIA — olvido en no-estacionariedad RECURRENTE (el óptimo depende del régimen)",
        known_limit=("REAL (exp049): en {c} cambios de causa, el committed se atasca progresivamente (post-cambio "
                     "{cm}), el adaptativo sigue la causa vigente ({am}) y el olvido CONSTANTE es el mejor ({fm}). "
                     "El tipo óptimo de olvido DEPENDE del régimen: constante para recurrente, surprise-gated "
                     "para aislado (CYCLE 59).").format(c=n_changes, cm=_f(com['post_change_mean']),
                                                        am=_f(ada['post_change_mean']),
                                                        fm=_f(fix['post_change_mean'])),
        blockers=[{"text": "el adaptive (surprise-gated) NO es el mejor olvido en recurrente (lo es el constante); el óptimo depende del régimen", "kind": "diseno"},
                  {"text": "el efecto requiere fases CORTAS (K_phase~12); a budget largo el committed re-adapta solo (boundary CYCLE 58)", "kind": "diseno"},
                  {"text": "falta un agente que ESTIME la tasa de cambio y elija el tipo/ritmo de olvido (meta-decisión de valor)", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP049.ref, S_EXP045.ref]))
    notes.append("1 techo 'real': el olvido maneja recurrencia (committed se atasca progresivamente); el óptimo (constante vs adaptativo) depende del régimen.")

    dstmt = ("North-Star R-VALOR x MEMORIA (recurrente): en no-estacionariedad RECURRENTE ({c} cambios de causa), "
             "el committed Bayesiano se atasca PROGRESIVAMENTE (acumula commitment, post-cambio {cm}) y el olvido "
             "es necesario para seguir la causa vigente; el adaptativo por sorpresa la sigue ({am}). HALLAZGO que "
             "REFINA el CYCLE 59: el olvido CONSTANTE (fixed {fm}) SUPERA al surprise-gating en el mundo "
             "recurrente -- el óptimo de olvido DEPENDE del régimen (constante para recurrente, surprise-gated "
             "para cambio aislado). Decisión: elegir el tipo/ritmo de olvido según el régimen es una meta-decisión "
             "de VALOR endógeno (estimar la tasa de cambio del mundo). Próximos: agente que estime la tasa de "
             "cambio y ajuste su olvido; combinar surprise-gating con piso constante.").format(
                 c=n_changes, cm=_f(com['post_change_mean']), am=_f(ada['post_change_mean']),
                 fm=_f(fix['post_change_mean']))
    drat = ("exp049 (tier5, propio, {n} seeds): committed se atasca progresivamente (post-cambio {cm}), adaptive "
            "sigue ({am} > committed), fixed mejor ({fm}). Convergente con tracking no-estacionario (tier1); "
            "refina CYCLE 59. {V}.").format(n=n_seeds, cm=_f(com['post_change_mean']),
                                            am=_f(ada['post_change_mean']), fm=_f(fix['post_change_mean']),
                                            V=status.upper())
    dec = Decision(id="D-V4-27", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP049), _to_plain(S_EXP045)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-27 ACEPTADA por el ledger (tier5 exp049 + tier5 exp045).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-27:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle63_recurrent_nonstationary',
                                description='CYCLE 63 (RESET v4, H-V4-1f: olvido en no-estacionariedad recurrente).')
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
    print("RESUMEN — CYCLE 63 (RESET v4): olvido en no-estacionariedad RECURRENTE (H-V4-1f)")
    print("=" * 78)
    print("veredicto H-V4-1f:", status.upper() if status else "?")
    print("  el committed se atasca progresivamente; el olvido sigue la causa vigente; el óptimo depende del régimen.")
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
