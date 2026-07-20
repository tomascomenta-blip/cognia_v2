r"""
cycle58_nonstationary_forgetting.py — CICLO 58 (RESET v4): H-V4-1d por las compuertas del engine. North-Star
R-VALOR x memoria (escribir≡olvidar).

H-V4-1d: en un mundo NO-ESTACIONARIO (la causa se mueve tras un commitment profundo), el OLVIDO dirigido por
valor (descontar evidencia vieja) permite ADAPTARSE, donde el agente COMMITTED (acumula todo) queda ATASCADO.
DERIVA de exp044_nonstationary_forgetting/results/results.json.

Correr (DESPUÉS de exp044):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp044_nonstationary_forgetting.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle58_nonstationary_forgetting
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
                             'cycle58_nonstationary_forgetting')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp044_nonstationary_forgetting', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_FORGET = Source(tier=1, ref="non-stationary filtering / stability-plasticity (forgetting)", obtained=False,
                  claim=("En entornos no-estacionarios, descontar evidencia vieja (forgetting / discounted "
                         "Bayes) permite seguir un parámetro que cambia; sin olvido el estimador queda "
                         "committeado. Trade-off estabilidad-plasticidad. (Principio, no re-obtenido.)"))
S_EXP043 = Source(tier=5, ref="cognia_x/experiments/exp043_endogenous_signal (CYCLE 57)", obtained=True,
                  claim=("exp043 (H-V4-1c): hay valor endógeno (confianza calibrada) en mundo ESTACIONARIO; "
                         "límite: el North-Star pide NO-estacionario."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp044 primero): " + results_path)
    bd = sm['by_decay']
    committed = bd['1.0']
    best_d = sm['best_forgetter']
    best = bd[best_d]
    n_seeds = sm['n_seeds']
    gap = best['post_c_new_final'] - committed['post_c_new_final']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    S_EXP044 = Source(tier=5, ref="cognia_x/experiments/exp044_nonstationary_forgetting", obtained=True,
                      claim=("exp044 (propio, {n} seeds, bayesiano numpy, mundo no-estacionario K1=commit/K2=adapt): "
                             "el COMMITTED (decay=1) queda ATASCADO en la causa vieja (post_c_new {cm}, "
                             "post_c_old {co}); el OLVIDO (decay={bd}) ADAPTA parcialmente (post_c_new {bn}, gap "
                             "+{g}). Sweet spot estabilidad-plasticidad.").format(
                                 n=n_seeds, cm=_f(committed['post_c_new_final']),
                                 co=_f(committed['post_c_old_final']), bd=best_d,
                                 bn=_f(best['post_c_new_final']), g=_f(gap)))
    for src in (S_FORGET, S_EXP043, S_EXP044):
        ledger.add_source(src)
    notes.append("3 fuentes (S_FORGET tier1 forgetting/no-estacionario; S_EXP043 tier5 límite estacionario; S_EXP044 tier5 dato propio).")

    ev_for = [S_EXP044.ref, S_FORGET.ref]
    ev_against = [S_EXP044.ref]
    adv = ("{V}: introduce la NO-ESTACIONARIEDAD que pide el North-Star. Mundo donde la causa se mueve TRAS un "
           "commitment PROFUNDO (K1 largo) y con presupuesto de adaptación CORTO (K2). MISMA política (info-gain) "
           "para todos; lo único que cambia es el OLVIDO (decay del log-posterior). RESULTADO: el COMMITTED "
           "(decay=1, acumula toda la evidencia) queda TOTALMENTE ATASCADO en la causa vieja (post_c_new {cm}, "
           "post_c_old {co}) — su posterior está tan committeado que el presupuesto corto de adaptación no lo "
           "mueve. El OLVIDO (decay={bd}) descontó lo viejo y SE ADAPTA a la causa nueva (post_c_new {bn}, "
           "+{g} sobre committed), habiendo identificado la vieja en fase 1 (midpoint {bm}). HALLAZGO: OLVIDAR es "
           "una decisión de VALOR (la info vieja ya no vale) NECESARIA para adaptarse a la no-estacionariedad; "
           "conecta R-VALOR con MEMORIA (escribir≡olvidar, H-V4-5). Hay un SWEET SPOT estabilidad-plasticidad: "
           "decay 0.9 adapta sin perder fase 1; decay 0.7-0.8 olvida DEMASIADO (su midpoint cae -> ni identifica "
           "la vieja). EVIDENCIA EN CONTRA (caveats honestos): (1) la adaptación es PARCIAL (post_c_new {bn} < "
           "1.0): el presupuesto corto (K2) no alcanza para re-identificar del todo -> por eso el veredicto es "
           "{V} (no llega al umbral absoluto pre-registrado 0.60, aunque el GAP sobre committed es enorme). (2) "
           "BOUNDARY observado en calibración: con presupuesto de adaptación LARGO (K2~K1) el committed se adapta "
           "SOLO (la evidencia nueva DESCONFIRMA la causa vieja) -> el olvido sólo es necesario bajo commitment "
           "profundo + adaptación corta. (3) mundo de juguete. CONCLUSIÓN: el olvido dirigido por valor es un "
           "mecanismo NECESARIO de R-VALOR en mundos no-estacionarios con recursos finitos; el committed "
           "Bayesiano clásico falla justo donde el North-Star apunta.").format(
               V=status.upper(), cm=_f(committed['post_c_new_final']), co=_f(committed['post_c_old_final']),
               bd=best_d, bn=_f(best['post_c_new_final']), g=_f(gap), bm=_f(best['post_c_old_midpoint']))

    hyp = Hypothesis(
        id="H-V4-1d",
        statement=("En un mundo no-estacionario (la causa cambia tras un commitment profundo, presupuesto de "
                   "adaptación corto), el olvido dirigido por valor (decay) permite adaptarse donde el committed "
                   "queda atascado."),
        prediction=("APOYADA si el committed (decay=1) NO se adapta (post_c_new<=0.40) Y algún olvido (decay<1) "
                    "adapta (post_c_new>=0.60, +>0.20 sobre committed), con fase 1 identificada; REFUTADA si el "
                    "committed se adapta igual; MIXTA si el olvido ayuda con gran gap pero la adaptación absoluta "
                    "es parcial o desestabiliza. (Pre-registrada.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'mixta') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=adv, experiment_ref="exp044_nonstationary_forgetting")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-1d")
        notes.append("H-V4-1d marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("Dominaste un tema para un examen (mucho estudio = commitment profundo). El temario CAMBIA y te "
                 "queda poco tiempo. ¿Seguís sabiendo lo viejo y fallás lo nuevo, o soltás lo viejo y te adaptás?"),
        everyday=("Si repasás lo viejo con la misma fe (no olvidás), tu certeza sobre lo viejo es tan fuerte que "
                  "el poco tiempo nuevo no te mueve: fallás el tema nuevo. Si SOLTÁS lo viejo (olvido) y "
                  "re-estudiás, te adaptás — pero si olvidás DEMASIADO, perdés también lo que ya sabías. Hay un "
                  "punto justo de cuánto olvidar."),
        solutions=["COMMITTED (acumula todo, decay=1) -> atascado en lo viejo, no adapta con poco presupuesto",
                   "OLVIDO moderado (decay=0.9) -> adapta a lo nuevo manteniendo lo de la fase 1 (sweet spot)",
                   "OLVIDO excesivo (decay=0.7-0.8) -> olvida demasiado, ni identifica lo viejo",
                   "con MUCHO presupuesto de adaptación, el committed adapta solo (lo nuevo desconfirma lo viejo)"],
        principles=["en mundos no-estacionarios con recursos finitos, OLVIDAR es necesario para adaptarse",
                    "olvidar es una decisión de VALOR: la info vieja deja de valer cuando el mundo cambia (escribir≡olvidar)",
                    "hay un trade-off estabilidad-plasticidad: muy poco olvido = atasco; mucho = inestabilidad",
                    "el committed Bayesiano clásico falla justo donde el North-Star apunta (no-estacionariedad)"],
        adaptation=("El lab liga R-VALOR a MEMORIA: el valor de la información decae con la no-estacionariedad y el "
                    "olvido es el mecanismo (H-V4-5 escribir≡olvidar). Próximos: olvido ADAPTATIVO (ajustar decay "
                    "según la sorpresa/des-confirmación, en vez de fijo); detección de cambio endógena (sin saber "
                    "cuándo cambió la causa); ligar el olvido a la confianza calibrada (CYCLE 57)."),
        measurement=("exp044: committed post_c_new {cm} (atascado, post_c_old {co}); olvido(decay {bd}) post_c_new "
                     "{bn} (gap +{g}, midpoint {bm}). {n} seeds.").format(
                         cm=_f(committed['post_c_new_final']), co=_f(committed['post_c_old_final']), bd=best_d,
                         bn=_f(best['post_c_new_final']), g=_f(gap), bm=_f(best['post_c_old_midpoint']), n=n_seeds),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (el temario que cambia: soltar lo viejo para adaptarse, sin olvidar de más).")

    ceilings.add(CeilingRecord(
        subsystem="R-VALOR x MEMORIA — olvido dirigido por valor en mundo NO-estacionario (escribir≡olvidar)",
        known_limit=("REAL (exp044): bajo commitment profundo + adaptación corta, el COMMITTED queda atascado "
                     "(post_c_new {cm}) y el OLVIDO (decay {bd}) adapta parcialmente (post_c_new {bn}, gap +{g}); "
                     "sweet spot estabilidad-plasticidad en 0.9. Boundary: con adaptación larga el committed "
                     "adapta solo.").format(cm=_f(committed['post_c_new_final']), bd=best_d,
                                            bn=_f(best['post_c_new_final']), g=_f(gap)),
        blockers=[{"text": "la adaptación es PARCIAL (presupuesto K2 corto); no se midió un olvido ADAPTATIVO (decay según la sorpresa)", "kind": "diseno"},
                  {"text": "el cambio de causa es conocido por el experimento (en K1); falta DETECCIÓN de cambio endógena (sin saber cuándo cambió)", "kind": "diseno"},
                  {"text": "mundo de juguete (hipótesis lineal y=x_i); falta no-estacionariedad más rica", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP044.ref, S_FORGET.ref]))
    notes.append("1 techo 'real': el olvido dirigido por valor es necesario para adaptarse a la no-estacionariedad (R-VALOR x memoria).")

    dstmt = ("North-Star R-VALOR x MEMORIA: en un mundo NO-ESTACIONARIO (la causa cambia tras commitment profundo, "
             "adaptación corta), el OLVIDO dirigido por valor (descontar evidencia vieja) es NECESARIO para "
             "adaptarse: el COMMITTED Bayesiano clásico queda atascado (post_c_new {cm}) y el olvido (decay {bd}) "
             "adapta (post_c_new {bn}, gap +{g}), con sweet spot estabilidad-plasticidad. Decisión: el lab liga "
             "R-VALOR a memoria — el valor de la info decae con la no-estacionariedad y el olvido es su mecanismo "
             "(H-V4-5 escribir≡olvidar). Matiz honesto: adaptación PARCIAL en presupuesto corto (de ahí MIXTA si "
             "no llega al umbral absoluto, aunque el gap es enorme); con adaptación larga el committed adapta "
             "solo. Próximos: olvido adaptativo según la sorpresa; detección de cambio endógena; ligar olvido a "
             "la confianza calibrada (CYCLE 57).").format(
                 cm=_f(committed['post_c_new_final']), bd=best_d, bn=_f(best['post_c_new_final']), g=_f(gap))
    drat = ("exp044 (tier5, propio, {n} seeds): committed atascado (post_c_new {cm}), olvido(decay {bd}) adapta "
            "(post_c_new {bn}, gap +{g}, fase1 midpoint {bm}). Convergente con forgetting/no-estacionario (tier1) "
            "y extiende el North-Star a no-estacionariedad. {V}.").format(
                n=n_seeds, cm=_f(committed['post_c_new_final']), bd=best_d, bn=_f(best['post_c_new_final']),
                g=_f(gap), bm=_f(best['post_c_old_midpoint']), V=status.upper())
    dec = Decision(id="D-V4-23", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP044), _to_plain(S_FORGET)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-23 ACEPTADA por el ledger (tier5 exp044 + tier1 forgetting).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-23:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle58_nonstationary_forgetting',
                                description='CYCLE 58 (RESET v4, H-V4-1d: olvido dirigido por valor en mundo no-estacionario).')
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
    print("RESUMEN — CYCLE 58 (RESET v4): olvido dirigido por valor en mundo NO-estacionario (H-V4-1d) — North-Star")
    print("=" * 78)
    print("veredicto H-V4-1d:", status.upper() if status else "?")
    print("  olvidar (descontar lo viejo) es necesario para adaptarse a la no-estacionariedad; R-VALOR x memoria.")
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
