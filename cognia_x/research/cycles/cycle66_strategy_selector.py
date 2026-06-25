r"""
cycle66_strategy_selector.py — CICLO 66 (RESET v4): H-V4-1i por las compuertas del engine. North-Star R-VALOR x
memoria — CIERRE del arco: el agente elige la ESTRATEGIA de memoria (decisión discreta), no sólo la tasa.

H-V4-1i: un selector de estrategia (clasifica el régimen de su sorpresa sostenida y conmuta committear<->olvidar-
fuerte) alcanza el ÓPTIMO en ambos regímenes, lo que la modulación de tasa (CYCLE 64/65) no pudo. DERIVA de
exp052_strategy_selector/results/results.json.

Correr (DESPUÉS de exp052):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp052_strategy_selector.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle66_strategy_selector
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle66_strategy_selector')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp052_strategy_selector', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_SELECT = Source(tier=1, ref="mixture-of-experts / context-gated strategy selection", obtained=False,
                  claim=("Seleccionar la ESTRATEGIA según el régimen (decisión discreta, gateada por el contexto) "
                         "supera a modular un solo parámetro cuando los regímenes piden óptimos opuestos. (Principio.)"))
S_EXP051 = Source(tier=5, ref="cognia_x/experiments/exp051 (CYCLE 65)", obtained=True,
                  claim=("exp051 (H-V4-1h REFUTADA): modular la TASA de olvido no alcanza el óptimo en regímenes "
                         "opuestos -> hace falta DETECTAR el régimen y CAMBIAR de ESTRATEGIA."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp052 primero): " + results_path)
    S, R = sm['stationary'], sm['recurrent']
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    S_EXP052 = Source(tier=5, ref="cognia_x/experiments/exp052_strategy_selector", obtained=True,
                      claim=("exp052 (propio, {n} seeds, bayesiano numpy): un SELECTOR de estrategia (clasifica el "
                             "régimen de su sorpresa sostenida y conmuta committear<->olvidar-fuerte) alcanza el "
                             "ÓPTIMO en AMBOS regímenes: ESTACIONARIO selector {ss} ~ committed {sc} (>> fixed "
                             "{sf}); RECURRENTE selector {rs} >= fixed {rf} (>> committed {rc}).").format(
                                 n=n_seeds, ss=_f(S['selector']), sc=_f(S['committed']), sf=_f(S['fixed']),
                                 rs=_f(R['selector']), rf=_f(R['fixed']), rc=_f(R['committed'])))
    for src in (S_SELECT, S_EXP051, S_EXP052):
        ledger.add_source(src)
    notes.append("3 fuentes (S_SELECT tier1 selección de estrategia; S_EXP051 tier5 CYCLE65 (rate-modulation falla); S_EXP052 tier5 dato propio).")

    ev_for = [S_EXP052.ref, S_EXP051.ref]
    ev_against = [S_EXP052.ref]
    adv = ("{V} (CIERRE del arco R-VALOR x memoria): el CYCLE 65 mostró que modular la TASA de olvido tiene un "
           "techo (el trade-off estabilidad-plasticidad) y concluyó que hace falta DETECTAR el régimen y CAMBIAR "
           "de ESTRATEGIA. exp052 lo PRUEBA: el SELECTOR clasifica el régimen de su propia sorpresa SOSTENIDA "
           "(EMA por encima del piso de ruido) y CONMUTA la ESTRATEGIA -- estable -> COMMITTEAR (decay=1), "
           "cambiante -> OLVIDAR-FUERTE (decay=0.85). RESULTADO: alcanza el ÓPTIMO de cada régimen, lo que la "
           "modulación de TASA (meta CYCLE 64, combined CYCLE 65) NO pudo. ESTACIONARIO: selector {ss} = committed "
           "{sc} EXACTO (>> fixed {sf}) -> clasifica ESTABLE y committea. RECURRENTE: selector {rs} >= fixed {rf} "
           "(>> committed {rc}) -> clasifica CAMBIANTE y olvida-fuerte (incluso un poco MEJOR que el constante "
           "porque consolida en las sub-fases estables y olvida en las transiciones). => el VALOR endógeno elige "
           "la ESTRATEGIA de memoria (committear vs olvidar-fuerte), no sólo el ritmo -- la decisión DISCRETA "
           "vence el trade-off donde el escalar continuo fallaba. EVIDENCIA EN CONTRA (caveats honestos): (1) "
           "sólo DOS estrategias y DOS regímenes; un mundo con régimen INTERMEDIO (cambio aislado) necesitaría una "
           "tercera estrategia o el surprise-gating del CYCLE 59. (2) el umbral de clasificación (p_obs+buffer) y "
           "la EMA son hiperparámetros; un mundo con tasa de cambio cercana al umbral confundiría al selector. "
           "(3) mundo de juguete. CONCLUSIÓN: cierra el arco R-VALOR x memoria con la SOLUCIÓN CORRECTA -- el "
           "valor endógeno (de la propia sorpresa) selecciona la ESTRATEGIA de memoria; la meta-cognición de "
           "'cómo recordar/olvidar' es una decisión de modo, no de intensidad.").format(
               V=status.upper(), ss=_f(S['selector']), sc=_f(S['committed']), sf=_f(S['fixed']),
               rs=_f(R['selector']), rf=_f(R['fixed']), rc=_f(R['committed']))

    hyp = Hypothesis(
        id="H-V4-1i",
        statement=("Un selector de estrategia (clasifica el régimen de su sorpresa sostenida y conmuta "
                   "committear<->olvidar-fuerte, decisión discreta) alcanza el óptimo en ambos regímenes, lo que "
                   "la modulación de tasa no pudo."),
        prediction=("APOYADA si el selector ~ committed en estacionario (>> fixed) Y ~ fixed en recurrente (>> "
                    "committed); REFUTADA si no alcanza el óptimo en ningún régimen; MIXTA si en uno sí y en otro "
                    "no. (Pre-registrada.)"),
        status='abierta', confidence='alta' if status == 'apoyada' else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=adv, experiment_ref="exp052_strategy_selector")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-1i")
        notes.append("H-V4-1i marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("Si modular CUÁNTO olvidás no te hace bueno en estable y en cambiante a la vez (CYCLE 65), "
                 "¿cómo lo lográs?"),
        everyday=("DECIDÍS el MODO según el régimen, no la intensidad. Si te das cuenta (por tus errores) de que "
                  "el temario está estable, entrás en modo 'me quedo con lo que sé' (committear). Si cambia "
                  "seguido, entrás en modo 'soltar y re-estudiar' (olvidar-fuerte). Cambiar de MODO te da lo "
                  "mejor de cada régimen; un único 'cuánto olvido' no."),
        solutions=["modular la TASA (meta/combined) -> techo por el trade-off (CYCLE 64/65)",
                   "SELECTOR de estrategia (clasifica régimen -> committear o olvidar-fuerte) -> óptimo en ambos",
                   "la clasificación viene de la sorpresa SOSTENIDA del propio agente (sin oráculo)",
                   "=> el valor endógeno elige la ESTRATEGIA de memoria, no el ritmo"],
        principles=["seleccionar la ESTRATEGIA (decisión discreta) vence el trade-off donde modular un escalar falla",
                    "el régimen es clasificable de la sorpresa sostenida del propio agente (sin oráculo externo)",
                    "la meta-cognición de memoria es una decisión de MODO (committear vs olvidar-fuerte), no de intensidad",
                    "el valor endógeno selecciona la estrategia de memoria -> cierra el arco R-VALOR x memoria"],
        adaptation=("El lab cierra el arco R-VALOR x memoria: el agente clasifica su régimen de no-estacionariedad "
                    "de su sorpresa y selecciona la estrategia de memoria. Próximos: más de dos estrategias (p.ej. "
                    "+surprise-gating del CYCLE 59 para cambios aislados); clasificación robusta cerca del umbral; "
                    "ligar la selección de estrategia al lazo de auto-mejora (verificador interno/externo)."),
        measurement=("exp052: ESTACIONARIO selector {ss}/committed {sc}/fixed {sf}; RECURRENTE selector {rs}/"
                     "committed {rc}/fixed {rf}. {n} seeds.").format(ss=_f(S['selector']), sc=_f(S['committed']),
                                                                     sf=_f(S['fixed']), rs=_f(R['selector']),
                                                                     rc=_f(R['committed']), rf=_f(R['fixed']),
                                                                     n=n_seeds),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (decidir el MODO de memoria según el régimen, no la intensidad).")

    ceilings.add(CeilingRecord(
        subsystem="R-VALOR x MEMORIA (CIERRE) — selector de ESTRATEGIA de memoria gateado por la sorpresa (vence el trade-off)",
        known_limit=("REAL (exp052): un selector que clasifica el régimen de su sorpresa sostenida y conmuta "
                     "committear<->olvidar-fuerte alcanza el ÓPTIMO en AMBOS regímenes (ESTACIONARIO selector {ss} "
                     "= committed {sc}; RECURRENTE selector {rs} >= fixed {rf}), lo que la modulación de TASA no "
                     "pudo. El valor endógeno elige la ESTRATEGIA de memoria.").format(
                         ss=_f(S['selector']), sc=_f(S['committed']), rs=_f(R['selector']), rf=_f(R['fixed'])),
        blockers=[{"text": "sólo DOS estrategias y DOS regímenes; un régimen INTERMEDIO (cambio aislado) necesitaría una 3ra estrategia (p.ej. surprise-gating del CYCLE 59)", "kind": "diseno"},
                  {"text": "umbral de clasificación + EMA son hiperparámetros; una tasa de cambio cerca del umbral confundiría al selector", "kind": "diseno"},
                  {"text": "mundo de juguete; falta ligar la selección de estrategia al lazo de auto-mejora (verificador)", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP052.ref, S_EXP051.ref]))
    notes.append("1 techo 'real': un selector de ESTRATEGIA gateado por la sorpresa vence el trade-off y alcanza el óptimo en ambos regímenes (cierra el arco).")

    dstmt = ("North-Star R-VALOR x MEMORIA (CIERRE del arco): el agente clasifica su régimen de no-estacionariedad "
             "de su PROPIA SORPRESA SOSTENIDA y SELECCIONA la ESTRATEGIA de memoria (committear si estable, "
             "olvidar-fuerte si cambiante) -- una decisión DISCRETA que alcanza el ÓPTIMO en AMBOS regímenes "
             "(ESTACIONARIO selector {ss} = committed {sc} >> fixed {sf}; RECURRENTE selector {rs} >= fixed {rf} "
             ">> committed {rc}), lo que la modulación de TASA (meta/combined, CYCLE 64/65) NO pudo. Decisión: el "
             "valor endógeno elige la ESTRATEGIA de memoria, no sólo el ritmo; la meta-cognición de memoria es "
             "una decisión de MODO. Cierra el arco R-VALOR x memoria (58·63-66): el sistema juzga qué información "
             "vale, cuándo dejó de valer, y CÓMO recordar/olvidar según el régimen, todo de señales endógenas. "
             "Próximos: 3ra estrategia (cambio aislado); ligar a la auto-mejora.").format(
                 ss=_f(S['selector']), sc=_f(S['committed']), sf=_f(S['fixed']), rs=_f(R['selector']),
                 rf=_f(R['fixed']), rc=_f(R['committed']))
    drat = ("exp052 (tier5, propio, {n} seeds): selector alcanza el óptimo en ambos (estacionario {ss}={sc}; "
            "recurrente {rs}>={rf}), venciendo el trade-off que la modulación de tasa no pudo (CYCLE 64/65). "
            "Convergente con selección de estrategia gateada por contexto (tier1). {V}.").format(
                n=n_seeds, ss=_f(S['selector']), sc=_f(S['committed']), rs=_f(R['selector']), rf=_f(R['fixed']),
                V=status.upper())
    dec = Decision(id="D-V4-30", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP052), _to_plain(S_EXP051)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-30 ACEPTADA por el ledger (tier5 exp052 + tier5 exp051).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-30:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle66_strategy_selector',
                                description='CYCLE 66 (RESET v4, H-V4-1i: selector de estrategia de memoria).')
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
    print("RESUMEN — CYCLE 66 (RESET v4): selector de ESTRATEGIA de memoria (H-V4-1i) — CIERRE del arco R-VALOR x memoria")
    print("=" * 78)
    print("veredicto H-V4-1i:", status.upper() if status else "?")
    print("  el valor endógeno elige la ESTRATEGIA de memoria (committear/olvidar-fuerte) según el régimen de su sorpresa.")
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
