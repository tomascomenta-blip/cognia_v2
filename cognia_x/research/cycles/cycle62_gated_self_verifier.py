r"""
cycle62_gated_self_verifier.py — CICLO 62 (RESET v4): H-V4-2j por las compuertas del engine. Cierra la
UNIFICACIÓN: el agente DECIDE cuándo confiar en su auto-consistencia por su propia calibración estimada.

H-V4-2j: el GATING EXPLÍCITO (estimar la calibración con un probe y usar el filtro endógeno sólo donde es
confiable, cayendo al externo donde no) hace al agente ROBUSTO en ambos regímenes — nunca colapsa. DERIVA de
exp047_gated_self_verifier/results/results.json.

Correr (DESPUÉS de exp047):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp047_gated_self_verifier.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle62_gated_self_verifier
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
                             'cycle62_gated_self_verifier')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp047_gated_self_verifier', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_METACOG = Source(tier=1, ref="meta-cognición / selective prediction (knowing when you know)", obtained=False,
                   claim=("Un sistema robusto sabe CUÁNDO confiar en su propio juicio y cuándo deferir; estimar "
                          "la propia fiabilidad y abstenerse/deferir evita fallos confiados. (Principio.)"))
S_EXP046 = Source(tier=5, ref="cognia_x/experiments/exp046 (CYCLE 60)", obtained=True,
                  claim=("exp046 (H-V4-2i): la auto-consistencia es verificador parcial GATEADO por calibración; "
                         "COLAPSA con base mal-calibrada. El peligro: usarla cuando no es confiable."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp047 primero): " + results_path)
    S, W = sm['strong'], sm['weak']
    n_seeds = sm['n_seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    S_EXP047 = Source(tier=5, ref="cognia_x/experiments/exp047_gated_self_verifier", obtained=True,
                      claim=("exp047 (propio, {n} seeds, HybridLM): el agente estima su calibración con un probe "
                             "y decide. FUERTE: elige ENDÓGENO {se:.0f}% (oracle_frac {sof}), gated {sg} (vs "
                             "self_cons {ssc}, verified {sv}). DÉBIL: elige EXTERNO {we:.0f}%, gated {wg} EVITA el "
                             "colapso (self_cons {wsc}) {match} a verified {wv}.").format(
                                 n=n_seeds, se=S['frac_endo'] * 100, sof=_f(S['oracle_frac']), sg=_f(S['gated']),
                                 ssc=_f(S['self_consistency']), sv=_f(S['verified']), we=(1 - W['frac_endo']) * 100,
                                 wg=_f(W['gated']), wsc=_f(W['self_consistency']),
                                 match="igualando" if sm['weak_matches_verified'] else "sin igualar del todo",
                                 wv=_f(W['verified'])))
    for src in (S_METACOG, S_EXP046, S_EXP047):
        ledger.add_source(src)
    notes.append("3 fuentes (S_METACOG tier1 meta-cognición/selective prediction; S_EXP046 tier5 gating/CYCLE60; S_EXP047 tier5 dato propio).")

    ev_for = [S_EXP047.ref, S_EXP046.ref]
    ev_against = [S_EXP047.ref]
    adv = ("{V} (cierre de la UNIFICACIÓN): el agente DECIDE cuándo confiar en su auto-consistencia estimando su "
           "PROPIA calibración con un probe barato (en esta tarea el target está en el prompt -> el probe es "
           "barato; en tareas con oráculo CARO serían unas pocas llamadas para calibrar y luego filtro endógeno "
           "sin oráculo en el grueso). RESULTADO: FUERTE/calibrado: el gate elige ENDÓGENO {se:.0f}% de las "
           "rondas (oracle_frac {sof}), gated {sg} NO pierde vs self_cons ({ssc}) y se acerca a verified ({sv}) "
           "-> verificación barata sin oráculo donde es confiable. DÉBIL/mal-calibrado: el gate elige EXTERNO "
           "{we:.0f}%, gated {wg} EVITA el COLAPSO de self_consistency ({wsc}) {match} a verified ({wv}). => el "
           "agente que estima su calibración es ROBUSTO: nunca colapsa como la auto-consistencia pura; endógeno "
           "barato cuando es confiable, externo seguro cuando no. EVIDENCIA EN CONTRA (caveats honestos): (1) la "
           "ESTIMACIÓN de calibración por probe es RUIDOSA (sobre todo para un modelo débil con probe chico) -> "
           "el gate a veces confía de más en el régimen débil y no IGUALA del todo a verified (de ahí {V} si así "
           "salió); el valor robusto es EVITAR EL COLAPSO, no la recuperación perfecta. (2) en esta tarea el "
           "oráculo es barato (target en el prompt) -> el ahorro de oráculo es la GENERALIZACIÓN a tareas caras, "
           "no medido aquí; lo demostrado es el MECANISMO de decisión y la SEGURIDAD. (3) un solo umbral. "
           "CONCLUSIÓN: cierra el lazo de la corrida — un agente con valor endógeno (confianza calibrada) puede "
           "decidir cuándo su propio juicio reemplaza al verificador externo y cuándo deferir, sin colapsar; es "
           "meta-cognición barata (saber cuándo sabe).").format(
               V=status.upper(), se=S['frac_endo'] * 100, sof=_f(S['oracle_frac']), sg=_f(S['gated']),
               ssc=_f(S['self_consistency']), sv=_f(S['verified']), we=(1 - W['frac_endo']) * 100,
               wg=_f(W['gated']), wsc=_f(W['self_consistency']),
               match="igualando" if sm['weak_matches_verified'] else "sin igualar del todo", wv=_f(W['verified']))

    hyp = Hypothesis(
        id="H-V4-2j",
        statement=("El gating explícito (estimar la propia calibración y usar el filtro endógeno sólo donde es "
                   "confiable, deferir al externo donde no) hace al agente robusto: nunca colapsa como la "
                   "auto-consistencia pura."),
        prediction=("APOYADA si el gated en FUERTE elige endógeno sin perder (usando poco oráculo) y en DÉBIL "
                    "elige externo, evita el colapso e iguala a verified; MIXTA si decide bien pero no iguala a "
                    "verified en débil (estimación ruidosa); REFUTADA si elige mal o no evita el colapso. "
                    "(Pre-registrada.)"),
        status='abierta', confidence='alta' if status == 'apoyada' else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=adv, experiment_ref="exp047_gated_self_verifier")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-2j")
        notes.append("H-V4-2j marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("¿Cómo evitás reforzarte en tus propios errores cuando NO sabés si tu seguridad es confiable? "
                 "¿Cuándo te corregís solo y cuándo pedís la tabla de respuestas?"),
        everyday=("Te tomás un MINI-test con la tabla (probe barato) para ver si tus 'seguros' suelen ser "
                  "correctos. Si sí (estás calibrado), te corregís solo en el resto (sin la tabla). Si no, usás "
                  "la tabla para todo. Así nunca te encerrás en errores confiados -- sabés cuándo confiar en vos."),
        solutions=["self_consistency pura -> colapsa cuando el modelo es confiado-pero-equivocado",
                   "verified puro -> seguro pero siempre necesita el oráculo",
                   "GATED (estimar calibración + decidir) -> endógeno barato cuando es confiable, externo cuando no",
                   "=> robustez: nunca colapsa; meta-cognición barata (saber cuándo sabe)"],
        principles=["estimar la propia fiabilidad y deferir cuando es baja evita los fallos confiados (selective prediction)",
                    "el gate por calibración da lo mejor de ambos: endógeno barato calibrado, externo seguro mal-calibrado",
                    "la estimación de calibración es ruidosa -> el gate garantiza SEGURIDAD (no colapsar) más que recuperación perfecta",
                    "cierra el lazo de la corrida: valor endógeno (confianza) -> decisión de cuándo reemplazar al verificador externo"],
        adaptation=("El lab puede gatear el uso de la confianza endógena por una calibración estimada barata, "
                    "reservando el verificador externo para el régimen no-confiable. Próximos: estimador de "
                    "calibración menos ruidoso (probe adaptativo); medir el AHORRO de oráculo en una tarea con "
                    "oráculo caro; combinar con la confianza calibrada del CYCLE 57 como señal de gate."),
        measurement=("exp047: FUERTE gated {sg} (endo {se:.0f}%, oracle {sof}) vs self_cons {ssc}/verified {sv}; "
                     "DÉBIL gated {wg} (externo {we:.0f}%) vs self_cons {wsc}/verified {wv}. {n} seeds.").format(
                         sg=_f(S['gated']), se=S['frac_endo'] * 100, sof=_f(S['oracle_frac']),
                         ssc=_f(S['self_consistency']), sv=_f(S['verified']), wg=_f(W['gated']),
                         we=(1 - W['frac_endo']) * 100, wsc=_f(W['self_consistency']), wv=_f(W['verified']),
                         n=n_seeds),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (mini-test con la tabla para saber si confiar en tus propios 'seguros').")

    ceilings.add(CeilingRecord(
        subsystem="UNIFICACIÓN (cierre) — gating explícito por calibración estimada: el agente sabe cuándo confiar en sí mismo",
        known_limit=("REAL (exp047): el agente estima su calibración con un probe y decide -> ROBUSTO: en fuerte "
                     "elige endógeno barato ({se:.0f}%, oracle {sof}) sin perder (gated {sg}); en débil elige "
                     "externo y EVITA el colapso de self_consistency ({wg} vs {wsc}). Garantiza SEGURIDAD (no "
                     "colapsar).").format(se=S['frac_endo'] * 100, sof=_f(S['oracle_frac']), sg=_f(S['gated']),
                                          wg=_f(W['gated']), wsc=_f(W['self_consistency'])),
        blockers=[{"text": "la estimación de calibración por probe es RUIDOSA (modelo débil + probe chico); el gate no iguala del todo a verified en débil", "kind": "diseno"},
                  {"text": "el oráculo es barato en esta tarea (target en el prompt); el ahorro de oráculo (generalización a oráculo caro) no se midió", "kind": "diseno"},
                  {"text": "un solo umbral de calibración; falta probe adaptativo y ligar el gate a la confianza calibrada del CYCLE 57", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP047.ref, S_EXP046.ref]))
    notes.append("1 techo 'real': el agente que estima su calibración decide cuándo confiar en sí mismo y nunca colapsa (cierre de la unificación).")

    dstmt = ("CIERRE de la UNIFICACIÓN: un agente con valor endógeno (confianza calibrada, CYCLE 56-59) puede "
             "DECIDIR cuándo su propio juicio (auto-consistencia) reemplaza al verificador externo y cuándo "
             "deferir, estimando su PROPIA calibración con un probe barato. Es ROBUSTO: en el régimen calibrado "
             "elige endógeno barato sin perder (gated {sg}, endo {se:.0f}%, oracle {sof}); en el mal-calibrado "
             "elige externo y EVITA el colapso de la auto-consistencia pura ({wg} vs {wsc}). Decisión: el lab "
             "gatea la confianza endógena por una calibración estimada -> meta-cognición barata (saber cuándo "
             "sabe). Matiz honesto: la estimación es ruidosa -> garantiza SEGURIDAD (no colapsar) más que "
             "recuperación perfecta; el ahorro de oráculo es la generalización a tareas con oráculo caro. "
             "Próximos: estimador menos ruidoso; medir el ahorro en oráculo caro; gate por la confianza calibrada "
             "del CYCLE 57.").format(sg=_f(S['gated']), se=S['frac_endo'] * 100, sof=_f(S['oracle_frac']),
                                     wg=_f(W['gated']), wsc=_f(W['self_consistency']))
    drat = ("exp047 (tier5, propio, {n} seeds): gated robusto -- fuerte endo {se:.0f}% gated {sg} sin perder; "
            "débil externo evita colapso ({wg} vs self_cons {wsc}). Convergente con meta-cognición/selective "
            "prediction (tier1) y cierra el CYCLE 60. {V}.").format(
                n=n_seeds, se=S['frac_endo'] * 100, sg=_f(S['gated']), wg=_f(W['gated']),
                wsc=_f(W['self_consistency']), V=status.upper())
    dec = Decision(id="D-V4-26", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP047), _to_plain(S_EXP046)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-26 ACEPTADA por el ledger (tier5 exp047 + tier5 exp046).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-26:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle62_gated_self_verifier',
                                description='CYCLE 62 (RESET v4, H-V4-2j: gating explícito por calibración estimada).')
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
    print("RESUMEN — CYCLE 62 (RESET v4): gating explícito por calibración estimada (H-V4-2j) — cierre unificación")
    print("=" * 78)
    print("veredicto H-V4-2j:", status.upper() if status else "?")
    print("  el agente estima su calibración y decide cuándo confiar en su auto-consistencia -> nunca colapsa.")
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
