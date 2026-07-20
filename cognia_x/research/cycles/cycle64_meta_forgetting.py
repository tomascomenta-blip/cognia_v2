r"""
cycle64_meta_forgetting.py — CICLO 64 (RESET v4): H-V4-1g por las compuertas del engine. North-Star R-VALOR x
memoria — cierre del loop 58-63: el olvido META-ADAPTATIVO (el agente estima la tasa de cambio y elige su olvido).

H-V4-1g: el agente estima la tasa de cambio del mundo (su propia sorpresa por encima del piso de ruido) y elige
su ritmo de olvido (committea si estable, olvida si cambia) SIN que le digan el régimen. DERIVA de
exp050_meta_forgetting/results/results.json.

Correr (DESPUÉS de exp050):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp050_meta_forgetting.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle64_meta_forgetting
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
                             'cycle64_meta_forgetting')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp050_meta_forgetting', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_METALEARN = Source(tier=1, ref="meta-learning del olvido / adaptive forgetting-rate", obtained=False,
                     claim=("Estimar la tasa de cambio del entorno y ajustar la tasa de olvido a ella es una "
                            "meta-decisión que un agente puede tomar de señales internas (su sorpresa). El "
                            "óptimo del olvido depende del régimen. (Principio.)"))
S_EXP049 = Source(tier=5, ref="cognia_x/experiments/exp049 (CYCLE 63)", obtained=True,
                  claim=("exp049 (H-V4-1f): el óptimo de olvido DEPENDE del régimen (constante para recurrente, "
                         "surprise-gated para aislado). ¿Puede el agente estimar el régimen y elegir su olvido?"))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp050 primero): " + results_path)
    S, R = sm['stationary'], sm['recurrent']
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    S_EXP050 = Source(tier=5, ref="cognia_x/experiments/exp050_meta_forgetting", obtained=True,
                      claim=("exp050 (propio, {n} seeds, bayesiano numpy): el olvido META-ADAPTATIVO (estima la "
                             "tasa de cambio por su sorpresa y elige el decay) adapta en DIRECCIÓN correcta — "
                             "ESTACIONARIO meta {sm} (committea más que constante {sf}, óptimo committed {sc}); "
                             "RECURRENTE meta {rm} (olvida más que committed {rc}, óptimo fixed {rf}) — robusto "
                             "pero sin igualar el óptimo de cada régimen.").format(
                                 n=n_seeds, sm=_f(S['meta']), sf=_f(S['fixed']), sc=_f(S['committed']),
                                 rm=_f(R['meta']), rc=_f(R['committed']), rf=_f(R['fixed'])))
    for src in (S_METALEARN, S_EXP049, S_EXP050):
        ledger.add_source(src)
    notes.append("3 fuentes (S_METALEARN tier1 adaptive forgetting-rate; S_EXP049 tier5 CYCLE63; S_EXP050 tier5 dato propio).")

    ev_for = [S_EXP050.ref, S_EXP049.ref]
    ev_against = [S_EXP050.ref]
    adv = ("{V} (cierre del loop 58-63): CYCLE 63 dejó que el ÓPTIMO de olvido depende del régimen, pero un "
           "agente real no sabe en qué régimen está. exp050 le da una señal ENDÓGENA: su propia SORPRESA por "
           "encima del piso de ruido (= tasa de cambio estimada), y con ella elige su decay. RESULTADO: el META "
           "adapta su olvido en DIRECCIÓN correcta en AMBOS regímenes SIN que le digan cuál — ESTACIONARIO (lo "
           "mejor es committear): meta {sm} COMMITTEA mucho más que el olvido-constante ({sf}) (aunque no llega "
           "al committed perfecto {sc}); RECURRENTE (lo mejor es olvidar): meta {rm} OLVIDA más que el committed "
           "({rc}) (aunque no llega al fixed {rf}). Es ROBUSTO: NUNCA es el peor brazo, a diferencia del "
           "committed (catastrófico en recurrente {rc}) o del olvido-constante (subóptimo en estacionario {sf}). "
           "=> la meta-decisión de olvido es un VALOR endógeno computable de la propia sorpresa. EVIDENCIA EN "
           "CONTRA (caveats honestos): (1) el META no IGUALA el óptimo de cada régimen (compromiso); es ASIMÉTRICO "
           "-- detecta ESTABILIDAD y committea MUY bien (meta {sm} vs constante {sf}), pero su olvido bajo "
           "RECURRENCIA es DÉBIL (meta {rm}, lejos del constante {rf}) porque entre cambios su decay vuelve a "
           "subir. (2) el mapeo sorpresa->decay tiene hiperparámetros (ref, ema, floor) no barridos. (3) mundo de "
           "juguete. CONCLUSIÓN: un agente puede estimar la no-estacionariedad de su propia sorpresa y mover su "
           "olvido en la dirección correcta (robustez), pero igualar el óptimo del régimen requiere un meta-"
           "controlador mejor; el VALOR (cuánto olvidar) es endógenamente estimable, parcialmente.").format(
               V=status.upper(), sm=_f(S['meta']), sf=_f(S['fixed']), sc=_f(S['committed']), rm=_f(R['meta']),
               rc=_f(R['committed']), rf=_f(R['fixed']))

    hyp = Hypothesis(
        id="H-V4-1g",
        statement=("El agente estima la tasa de cambio del mundo (su sorpresa por encima del ruido) y elige su "
                   "ritmo de olvido (committea si estable, olvida si cambia) sin que le digan el régimen."),
        prediction=("APOYADA si el meta IGUALA al mejor brazo de cada régimen (committed en estacionario, fixed "
                    "en recurrente); MIXTA si adapta en DIRECCIÓN correcta en ambos (robusto) pero no iguala el "
                    "óptimo; REFUTADA si no adapta (se comporta como un brazo fijo). (Pre-registrada.)"),
        status='abierta', confidence='media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=adv, experiment_ref="exp050_meta_forgetting")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-1g")
        notes.append("H-V4-1g marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("No sabés si el temario del examen es ESTABLE o cambia SEGUIDO. ¿Cómo elegís cuánto olvidar sin "
                 "que te avisen el régimen?"),
        everyday=("Te fijás en cuánto te SORPRENDÉS (más allá de los errores normales). Si casi nunca te "
                  "sorprendés, el temario es estable -> te quedás con lo que sabés (committear). Si te sorprendés "
                  "seguido, cambia -> soltás lo viejo constantemente. Movés tu ritmo de olvido a tu sorpresa. "
                  "Funciona en dirección (nunca elegís lo peor) pero no clavás el ritmo ideal de cada régimen."),
        solutions=["committed (nunca olvida) -> óptimo si estable, catastrófico si cambia",
                   "fixed (olvido constante) -> óptimo si cambia, subóptimo si estable",
                   "META (olvido por sorpresa estimada) -> robusto: nunca el peor; commitea bien si estable",
                   "pero el META no IGUALA el óptimo de cada régimen (compromiso; olvido recurrente débil)"],
        principles=["la tasa de cambio del mundo es estimable de la propia sorpresa por encima del piso de ruido",
                    "elegir cuánto olvidar según esa estimación es una meta-decisión de VALOR endógeno",
                    "el meta-olvido es ROBUSTO (nunca el peor) pero asimétrico: detecta estabilidad mejor que sostener olvido bajo recurrencia",
                    "igualar el óptimo del régimen requiere un meta-controlador mejor (hiperparámetros del mapeo sorpresa->olvido)"],
        adaptation=("El lab puede dar al agente un meta-controlador de olvido basado en su sorpresa, ganando "
                    "ROBUSTEZ entre regímenes sin saber cuál. Próximos: mejor mapeo sorpresa->decay (barrer "
                    "ref/ema/floor); un piso de olvido constante + surprise-gating combinados; estimar también la "
                    "MAGNITUD del cambio."),
        measurement=("exp050: ESTACIONARIO meta {sm}/committed {sc}/fixed {sf}; RECURRENTE meta {rm}/committed "
                     "{rc}/fixed {rf}. {n} seeds.").format(sm=_f(S['meta']), sc=_f(S['committed']),
                                                           sf=_f(S['fixed']), rm=_f(R['meta']),
                                                           rc=_f(R['committed']), rf=_f(R['fixed']), n=n_seeds),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (elegir cuánto olvidar según cuánto te sorprendés).")

    ceilings.add(CeilingRecord(
        subsystem="R-VALOR x MEMORIA — meta-olvido: el agente estima la tasa de cambio y elige su olvido (robusto, no óptimo)",
        known_limit=("REAL (exp050): el meta-olvido (decay por sorpresa estimada) adapta en dirección correcta en "
                     "ambos regímenes (ESTACIONARIO meta {sm}>constante {sf}; RECURRENTE meta {rm}>committed {rc}) "
                     "y es ROBUSTO (nunca el peor), pero no iguala el óptimo de cada régimen (asimétrico: commitea "
                     "bien si estable, olvido recurrente débil).").format(
                         sm=_f(S['meta']), sf=_f(S['fixed']), rm=_f(R['meta']), rc=_f(R['committed'])),
        blockers=[{"text": "el meta NO iguala el óptimo de cada régimen (compromiso); olvido bajo recurrencia DÉBIL (decay vuelve a subir entre cambios)", "kind": "diseno"},
                  {"text": "el mapeo sorpresa->decay tiene hiperparámetros (ref, ema, floor) no barridos; un meta-controlador mejor podría acercarse al óptimo", "kind": "diseno"},
                  {"text": "mundo de juguete; falta estimar también la MAGNITUD del cambio y combinar piso constante + surprise-gating", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP050.ref, S_EXP049.ref]))
    notes.append("1 techo 'real': el meta-olvido es robusto (estima la tasa de cambio de su sorpresa y elige el olvido) pero no iguala el óptimo del régimen.")

    dstmt = ("North-Star R-VALOR x MEMORIA (cierre del loop 58-63): un agente puede ESTIMAR la tasa de cambio del "
             "mundo de su PROPIA SORPRESA (por encima del piso de ruido) y ELEGIR su ritmo de olvido sin que le "
             "digan el régimen. El META-olvido adapta en DIRECCIÓN correcta en ambos regímenes (ESTACIONARIO meta "
             "{sm} committea mucho más que el constante {sf}; RECURRENTE meta {rm} olvida más que committed {rc}) "
             "y es ROBUSTO (nunca el peor). Decisión: la meta-decisión de olvido (cuánto olvidar) es un VALOR "
             "endógeno computable de la sorpresa. Matiz honesto: el meta NO iguala el óptimo de cada régimen "
             "(compromiso, asimétrico: detecta estabilidad mejor que sostener olvido recurrente). Próximos: mejor "
             "mapeo sorpresa->olvido; combinar piso constante + surprise-gating.").format(
                 sm=_f(S['meta']), sf=_f(S['fixed']), rm=_f(R['meta']), rc=_f(R['committed']))
    drat = ("exp050 (tier5, propio, {n} seeds): meta adapta direccional (estacionario {sm}>{sf}; recurrente "
            "{rm}>{rc}), robusto, sin igualar el óptimo. Convergente con adaptive forgetting-rate (tier1); cierra "
            "el loop del CYCLE 63. {V}.").format(n=n_seeds, sm=_f(S['meta']), sf=_f(S['fixed']), rm=_f(R['meta']),
                                                 rc=_f(R['committed']), V=status.upper())
    dec = Decision(id="D-V4-28", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP050), _to_plain(S_EXP049)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-28 ACEPTADA por el ledger (tier5 exp050 + tier5 exp049).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-28:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle64_meta_forgetting',
                                description='CYCLE 64 (RESET v4, H-V4-1g: meta-olvido por sorpresa estimada).')
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
    print("RESUMEN — CYCLE 64 (RESET v4): meta-olvido (estima la tasa de cambio y elige el olvido) (H-V4-1g)")
    print("=" * 78)
    print("veredicto H-V4-1g:", status.upper() if status else "?")
    print("  el agente estima la tasa de cambio de su sorpresa y mueve su olvido en la dirección correcta (robusto).")
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
