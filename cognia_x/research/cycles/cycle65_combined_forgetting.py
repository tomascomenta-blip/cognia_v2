r"""
cycle65_combined_forgetting.py — CICLO 65 (RESET v4): H-V4-1h por las compuertas del engine. North-Star R-VALOR
x memoria — ¿un piso de olvido constante + sorpresa cierra el caveat del CYCLE 64? (resultado NEGATIVO informativo).

H-V4-1h: el olvido COMBINADO (piso constante + boost por sorpresa) cierra el caveat del CYCLE 64 (meta débil en
recurrente). DERIVA de exp051_combined_forgetting/results/results.json.

Correr (DESPUÉS de exp051):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp051_combined_forgetting.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle65_combined_forgetting
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
                             'cycle65_combined_forgetting')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp051_combined_forgetting', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_TRADEOFF = Source(tier=1, ref="stability-plasticity trade-off (Grossberg)", obtained=False,
                    claim=("Estabilidad (retener) y plasticidad (adaptar) están en TENSIÓN; modular un solo "
                           "escalar (la tasa de olvido) no logra el óptimo de regímenes opuestos a la vez. "
                           "(Principio.)"))
S_EXP050 = Source(tier=5, ref="cognia_x/experiments/exp050 (CYCLE 64)", obtained=True,
                  claim=("exp050 (H-V4-1g): el meta-olvido (sólo sorpresa) es robusto pero débil en recurrente "
                         "(decay vuelve a subir entre cambios). Caveat a cerrar."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp051 primero): " + results_path)
    S, R = sm['stationary'], sm['recurrent']
    ceiling = sm['ceiling']
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    S_EXP051 = Source(tier=5, ref="cognia_x/experiments/exp051_combined_forgetting", obtained=True,
                      claim=("exp051 (propio, {n} seeds, bayesiano numpy): el olvido COMBINADO (piso {ce} + "
                             "sorpresa) NO cierra el caveat del meta: RECURRENTE combined {rc} ~ meta {rm} (no "
                             "mejora; el fixed {rf} sigue siendo el mejor) y ESTACIONARIO combined {sc} < meta "
                             "{sm} (el piso lo hunde). El trade-off estabilidad-plasticidad es FUNDAMENTAL.").format(
                                 n=n_seeds, ce=ceiling, rc=_f(R['combined']), rm=_f(R['meta']), rf=_f(R['fixed']),
                                 sc=_f(S['combined']), sm=_f(S['meta'])))
    for src in (S_TRADEOFF, S_EXP050, S_EXP051):
        ledger.add_source(src)
    notes.append("3 fuentes (S_TRADEOFF tier1 estabilidad-plasticidad; S_EXP050 tier5 CYCLE64; S_EXP051 tier5 dato propio).")

    ev_for = [S_EXP051.ref]          # el experimento es la evidencia que informa el veredicto (aunque refute la hipótesis)
    ev_against = [S_EXP051.ref, S_EXP050.ref]
    adv = ("{V} (resultado NEGATIVO informativo): el fix propuesto al caveat del CYCLE 64 — un PISO CONSTANTE de "
           "olvido ({ce}) MÁS el boost por sorpresa — NO funciona. RECURRENTE: combined {rc} ~ meta {rm} (NO "
           "mejora; el piso suave no alcanza al fixed {rf} que olvida más). ESTACIONARIO: combined {sc} < meta "
           "{sm} (el piso constante HUNDE el estacionario, donde lo mejor es committear). => un piso suave es "
           "CONTRAPRODUCENTE (peor estacionario, sin ganar recurrente). Y un piso AGRESIVO (≈0.85) simplemente "
           "SE CONVIERTE en el olvido-constante (fixed), perdiendo el estacionario del todo. INTERPRETACIÓN: el "
           "trade-off estabilidad-plasticidad es FUNDAMENTAL para un meta-controlador que sólo modula la TASA de "
           "olvido: no hay un escalar de olvido que sea óptimo en ESTACIONARIO (committear) y RECURRENTE (olvidar "
           "mucho) a la vez. Para lograr ambos haría falta DETECTAR el régimen y CAMBIAR de ESTRATEGIA (decisión "
           "DISCRETA committear-vs-olvidar-fuerte), no sólo modular un escalar. EVIDENCIA: ni el meta (CYCLE 64) "
           "ni el combined igualan el óptimo de ambos; ambos son robustos-pero-subóptimos. CONCLUSIÓN: afina el "
           "CYCLE 64 -- la meta-decisión de olvido por modulación de tasa tiene un TECHO (el trade-off); el valor "
           "endógeno tendría que elegir la ESTRATEGIA de memoria, no sólo el ritmo. (Honestidad anti-Goodhart: se "
           "reporta el negativo tal cual.)").format(
               V=status.upper(), ce=ceiling, rc=_f(R['combined']), rm=_f(R['meta']), rf=_f(R['fixed']),
               sc=_f(S['combined']), sm=_f(S['meta']))

    hyp = Hypothesis(
        id="H-V4-1h",
        statement=("Un piso de olvido constante + boost por sorpresa cierra el caveat del meta (CYCLE 64), "
                   "dando robustez óptima en ambos regímenes."),
        prediction=("APOYADA si el combined mejora al meta en recurrente sin romper estacionario; REFUTADA si no "
                    "mejora recurrente o el piso hunde estacionario; MIXTA si mejora un eje no el otro. "
                    "(Pre-registrada.)"),
        status='abierta', confidence='alta',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=adv, experiment_ref="exp051_combined_forgetting")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-1h")
        notes.append("H-V4-1h marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("¿Un 'siempre olvidá un poquito' fijo + 'olvidá más si te sorprendés' te hace bueno tanto cuando "
                 "el temario es estable como cuando cambia seguido?"),
        everyday=("No. Si el 'poquito' es suave, no te alcanza cuando cambia seguido (necesitás olvidar fuerte) y "
                  "encima te hace olvidar de más cuando es estable (donde convenía quedarte con lo que sabés). Y "
                  "si el 'poquito' es fuerte, ya sos el que olvida constante y perdés lo estable. No hay UN ritmo "
                  "de olvido bueno para ambos: hay que DECIDIR la estrategia según el régimen."),
        solutions=["piso SUAVE + sorpresa -> contraproducente (peor estable, no gana recurrente)",
                   "piso AGRESIVO + sorpresa -> se convierte en el olvido-constante (pierde estable)",
                   "meta (sólo sorpresa) -> robusto pero subóptimo (CYCLE 64)",
                   "=> el trade-off es fundamental: modular la TASA no basta; hay que cambiar de ESTRATEGIA"],
        principles=["estabilidad y plasticidad están en TENSIÓN; un solo escalar de olvido no optimiza regímenes opuestos",
                    "un piso de olvido constante no cierra el caveat: o es suave (inútil) o agresivo (= constante)",
                    "lograr el óptimo de ambos régimenes exige DETECTAR el régimen y CAMBIAR de estrategia (decisión discreta)",
                    "la meta-decisión de olvido por modulación de TASA tiene un techo: el valor endógeno tendría que elegir la ESTRATEGIA"],
        adaptation=("El lab reconoce que la modulación de la TASA de olvido tiene un techo (el trade-off); para el "
                    "óptimo en regímenes opuestos hace falta un selector de ESTRATEGIA de memoria (committear vs "
                    "olvidar-fuerte) gateado por la detección de régimen. Próximos: un agente que CLASIFIQUE el "
                    "régimen (estacionario/aislado/recurrente) de su sorpresa y elija la estrategia, no la tasa."),
        measurement=("exp051 (piso {ce}): ESTACIONARIO meta {sm}/combined {sc}; RECURRENTE meta {rm}/combined {rc}/"
                     "fixed {rf}. {n} seeds.").format(ce=ceiling, sm=_f(S['meta']), sc=_f(S['combined']),
                                                      rm=_f(R['meta']), rc=_f(R['combined']), rf=_f(R['fixed']),
                                                      n=n_seeds),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (no hay UN ritmo de olvido bueno para estable y cambiante a la vez).")

    ceilings.add(CeilingRecord(
        subsystem="R-VALOR x MEMORIA — TECHO de la modulación de tasa de olvido (trade-off estabilidad-plasticidad)",
        known_limit=("REAL (exp051): un piso de olvido constante + sorpresa NO cierra el caveat del meta "
                     "(recurrente combined {rc} ~ meta {rm}; estacionario combined {sc} < meta {sm}). El trade-off "
                     "estabilidad-plasticidad es FUNDAMENTAL para un controlador que sólo modula la TASA: no hay "
                     "un escalar óptimo en regímenes opuestos -> hace falta cambiar de ESTRATEGIA.").format(
                         rc=_f(R['combined']), rm=_f(R['meta']), sc=_f(S['combined']), sm=_f(S['meta'])),
        blockers=[{"text": "modular la TASA de olvido (meta, combined) no alcanza el óptimo de regímenes opuestos: el trade-off es fundamental", "kind": "fisico"},
                  {"text": "falta un SELECTOR de estrategia de memoria (committear vs olvidar-fuerte) gateado por la detección de régimen", "kind": "diseno"},
                  {"text": "mundo de juguete; falta clasificar el régimen (estacionario/aislado/recurrente) de la sorpresa", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP051.ref, S_EXP050.ref]))
    notes.append("1 techo 'real': la modulación de la TASA de olvido tiene un techo (trade-off estabilidad-plasticidad); hace falta elegir la ESTRATEGIA.")

    dstmt = ("North-Star R-VALOR x MEMORIA (resultado NEGATIVO informativo): un piso de olvido constante + boost "
             "por sorpresa NO cierra el caveat del CYCLE 64 (recurrente combined {rc} ~ meta {rm}; estacionario "
             "combined {sc} < meta {sm}). El trade-off estabilidad-plasticidad es FUNDAMENTAL para un "
             "meta-controlador que sólo modula la TASA de olvido: no existe un escalar de olvido óptimo en "
             "ESTACIONARIO (committear) y RECURRENTE (olvidar mucho) a la vez. Decisión: para el óptimo en "
             "regímenes opuestos hace falta DETECTAR el régimen y CAMBIAR de ESTRATEGIA (decisión discreta), no "
             "modular un escalar -- el valor endógeno tendría que elegir la ESTRATEGIA de memoria, no sólo el "
             "ritmo. Afina el CYCLE 64. Próximos: un selector de estrategia gateado por la clasificación del "
             "régimen.").format(rc=_f(R['combined']), rm=_f(R['meta']), sc=_f(S['combined']), sm=_f(S['meta']))
    drat = ("exp051 (tier5, propio, {n} seeds): combined (piso {ce}+sorpresa) no mejora al meta en recurrente "
            "({rc}~{rm}) y hunde el estacionario ({sc}<{sm}). Convergente con stability-plasticity (tier1). "
            "{V}.").format(n=n_seeds, ce=ceiling, rc=_f(R['combined']), rm=_f(R['meta']), sc=_f(S['combined']),
                           sm=_f(S['meta']), V=status.upper())
    dec = Decision(id="D-V4-29", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP051), _to_plain(S_EXP050)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-29 ACEPTADA por el ledger (tier5 exp051 + tier5 exp050).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-29:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle65_combined_forgetting',
                                description='CYCLE 65 (RESET v4, H-V4-1h: olvido combinado piso+sorpresa).')
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
    print("RESUMEN — CYCLE 65 (RESET v4): olvido COMBINADO piso+sorpresa (H-V4-1h) — negativo informativo")
    print("=" * 78)
    print("veredicto H-V4-1h:", status.upper() if status else "?")
    print("  el trade-off estabilidad-plasticidad es fundamental: modular la tasa de olvido tiene un techo.")
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
