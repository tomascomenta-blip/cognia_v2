r"""
cycle123_decisional_scarcity.py — CICLO 123 (RESET v4, rama R-VALOR, CAPSTONE POSITIVO del arco): H-V4-9c por las
compuertas del engine. APOYADA: demuestra POSITIVAMENTE -- en una abstracción numpy CONTROLADA -- lo que el toy torch de
122 no pudo aislar: la CALIBRACIÓN del selector PAGA en una decisión de asignación de recurso escaso EXACTAMENTE bajo
ESCASEZ de buenas opciones, y SATURA (la calibración no importa) bajo abundancia. Cierra el arco: 121 re-localizó R-VALOR
como DECISIONAL; 122 no pudo demostrarlo en el toy (saturaba) y diagnosticó que necesita escasez; 123 lo demuestra
positivamente bajo escasez controlada.

DERIVA de exp107_decisional_scarcity/results/results.json.

Correr (DESPUÉS de exp107):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp107_decisional_scarcity.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle123_decisional_scarcity
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle123_decisional_scarcity')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp107_decisional_scarcity', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="el valor de un selector calibrado en una decisión escala con la ESCASEZ de buenas opciones relativa al presupuesto: bajo escasez la calibración determina el payoff; bajo abundancia cualquier selector acierta (la decisión satura). Valor-de-la-información/selección bajo escasez", obtained=False,
                     claim=("El payoff de un selector calibrado en una decisión de asignación ESCALA con la ESCASEZ de "
                            "buenas opciones relativa al presupuesto: bajo escasez, la calibración determina cuántas "
                            "buenas se eligen (de azar a casi-óptimo); bajo abundancia, someter cualquier subconjunto "
                            "captura casi todas las buenas (satura). (Principio.)"))
S_C121 = Source(tier=5, ref="cognia_x/experiments/exp105_full_recipe_payoff", obtained=True,
                claim=("CYCLE 121 re-localizó el valor de R-VALOR como DECISIONAL (no acelera el self-training downstream). "
                       "H-V4-9c lo demuestra POSITIVAMENTE bajo escasez controlada."))
S_C122 = Source(tier=5, ref="cognia_x/experiments/exp106_decisional_payoff", obtained=True,
                claim=("CYCLE 122 no pudo aislar el payoff decisional en el toy (saturaba por correctos abundantes / temp "
                       "alta desestabilizaba) y diagnosticó que necesita ESCASEZ. H-V4-9c provee la escasez controlada."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp107 primero): " + results_path)

    sg = sm['scarce_gain']
    ag = sm['abund_gain']
    g = sm['grid']
    rhos = sorted([float(k) for k in g['escaso'].keys()])
    lo, hi = rhos[0], rhos[-1]
    sc = g['escaso']; ab = g['abundante']
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim107 = ("exp107 (propio, {n} seeds, numpy): bajo ESCASEZ (q=0.08) el payoff de la decisión sube de {sl} (ρ=0) a "
                "{sh} (ρ={hi}) -- la calibración PAGA +{sg}; bajo ABUNDANCIA (q=0.9) {al}->{ah} (+{ag}) -- SATURA, la "
                "calibración no importa. El payoff decisional de la calibración se manifiesta bajo escasez.").format(
                    n=n_seeds, sl=_f(sc[str(lo)]), sh=_f(sc[str(hi)]), hi=hi, sg=_f(sg), al=_f(ab[str(lo)]), ah=_f(ab[str(hi)]), ag=_f(ag))
    S_EXP107 = Source(tier=5, ref="cognia_x/experiments/exp107_decisional_scarcity", obtained=True, claim=claim107)
    for src in (S_PRINCIPLE, S_C121, S_C122, S_EXP107):
        ledger.add_source(src)
    notes.append("4 fuentes (S_PRINCIPLE tier2 payoff-selector∝escasez; S_C121 tier5 re-localización decisional; S_C122 tier5 diagnóstico de escasez; S_EXP107 tier5 dato propio).")

    ev_for = [S_EXP107.ref, S_PRINCIPLE.ref]
    ev_against = [S_EXP107.ref]
    advtext = ("{V} (CAPSTONE POSITIVO del arco: demuestra lo que el toy de 122 no pudo): 121 re-localizó el valor de "
               "R-VALOR como DECISIONAL; 122 no pudo demostrarlo positivamente en el toy torch (el submission SATURABA por "
               "correctos abundantes, o la temp alta desestabilizaba) y diagnosticó que el payoff decisional necesita "
               "ESCASEZ. H-V4-9c lo demuestra POSITIVAMENTE en una abstracción numpy CONTROLADA que aísla los dos ejes -- "
               "calibración ρ del selector × escasez q de buenas opciones. RESULTADO: bajo ESCASEZ (q=0.08, sólo 8% buenas) "
               "el payoff de la decisión (buenas elegidas / oracle al someter las top-m por el estimador) sube de {sl} "
               "(ρ=0, azar) a {sh} (ρ={hi}, calibrado) -- la calibración PAGA +{sg}, de casi-azar a casi-óptimo. Bajo "
               "ABUNDANCIA (q=0.9) el payoff {al}->{ah} (+{ag}) -- SATURA cerca de 1, la calibración es IRRELEVANTE "
               "(someter cualquier subconjunto captura casi todas las buenas). => DEMUESTRA POSITIVAMENTE la "
               "re-localización de 121: el valor de R-VALOR (la señal de valor calibrada) es DECISIONAL -- PAGA en la "
               "DECISIÓN de asignar un recurso ESCASO, exactamente donde la teoría de asignación (83-114) dice que el "
               "valor importa (bajo escasez/presupuesto). Y CONFIRMA el diagnóstico de 122: el toy no podía aislarlo "
               "porque el modelo DOMINA la tarea (correctos abundantes -> régimen saturado). CIERRA el arco R-VALOR de "
               "forma coherente: el valor endógeno es una BRÚJULA para ASIGNAR bajo escasez, y la cura de durabilidad (119) "
               "la mantiene confiable. EVIDENCIA: el principio payoff∝escasez (tier2) lo predice. EVIDENCIA EN CONTRA / "
               "caveats: abstracción numpy (estimador con corr-ρ sintética, bondad binaria) -- demuestra el PRINCIPIO "
               "limpio, no lo re-mide en el lazo real (el lazo real es el de 122, que satura); el ρ es exógeno (en el lazo "
               "real la cura 119 lo provee). La afirmación robusta: el payoff decisional de la calibración escala con la "
               "escasez.").format(V=status.upper(), sl=_f(sc[str(lo)]), sh=_f(sc[str(hi)]), hi=hi, sg=_f(sg),
                                  al=_f(ab[str(lo)]), ah=_f(ab[str(hi)]), ag=_f(ag))

    hyp = Hypothesis(
        id="H-V4-9c",
        statement=("El payoff DECISIONAL de la calibración del selector se manifiesta exactamente bajo ESCASEZ de buenas "
                   "opciones (paga fuerte con ρ bajo escasez; satura bajo abundancia) -> demuestra positivamente que "
                   "R-VALOR es DECISIONAL (121) y confirma que el toy de 122 no podía aislarlo por falta de escasez."),
        prediction=("APOYADA si bajo escasez payoff(ρ alto) − payoff(ρ=0) > 0.10 Y bajo abundancia satura (Δ <= 0.10, base "
                    ">= 0.9); REFUTADA si la calibración no paga bajo escasez; MIXTA en otro caso. (Pre-registrada, numpy, "
                    "200 seeds, barrido ρ×q.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp107_decisional_scarcity")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-9c")
        notes.append("H-V4-9c marcada '{}' con DoD completo (capstone positivo: la calibración paga en la decisión bajo escasez).".format(status))

    analogy = AnalogyRecord(
        problem=("¿Cuándo vale la pena tener buen criterio para elegir? Si tengo que elegir unas pocas cosas para "
                 "presentar, ¿importa mi criterio igual cuando casi todo es bueno que cuando lo bueno es raro?"),
        everyday=("Mi criterio vale MUCHO cuando lo bueno es RARO: si de 100 cosas sólo 8 son buenas y tengo que elegir 5, "
                  "un buen criterio me hace agarrar casi todas las buenas, y elegir al azar me hace agarrar casi ninguna. "
                  "Pero cuando casi todo es bueno (90 de 100), elija como elija agarro buenas -- mi criterio no se nota. "
                  "El buen criterio (calibración) PAGA exactamente cuando lo bueno ESCASEA; bajo abundancia da igual."),
        solutions=["bajo escasez de buenas opciones: la calibración del selector paga ENORME (de azar a casi-óptimo)",
                   "bajo abundancia: el payoff satura, cualquier selector acierta -> la calibración es irrelevante",
                   "el payoff decisional de la calibración escala con la escasez relativa al presupuesto",
                   "demuestra positivamente que R-VALOR es DECISIONAL y vale donde hay que asignar bajo escasez"],
        principles=["el payoff de un selector calibrado en una decisión escala con la ESCASEZ de buenas opciones",
                    "bajo abundancia la decisión satura -> la calibración no importa (por eso el toy de 122 no la aislaba)",
                    "R-VALOR (la señal de valor calibrada) es una BRÚJULA DECISIONAL: paga al asignar bajo escasez/presupuesto",
                    "cierra el arco: valor endógeno para ASIGNAR bajo escasez + cura de durabilidad (119) que lo mantiene confiable"],
        adaptation=("El lab CIERRA el arco R-VALOR con la demostración positiva: la señal de valor calibrada PAGA en una "
                    "decisión de asignación de recurso escaso, exactamente bajo ESCASEZ (donde la teoría de asignación "
                    "83-114 dice que el valor importa), y satura bajo abundancia. Esto confirma que R-VALOR es una BRÚJULA "
                    "DECISIONAL (no un motor de aprendizaje, 121) y explica por qué el toy de 122 (que el modelo domina) no "
                    "podía aislarlo (régimen saturado). Política: medir/usar la señal calibrada para asignar bajo escasez "
                    "(presupuesto de verificación, atención, cómputo); la cura de durabilidad (119) la mantiene confiable. "
                    "Próximo: el lazo real EN un régimen de escasez genuina (tarea dura) o SCALE, para re-medir el payoff "
                    "decisional fuera de la abstracción."),
        measurement=("exp107 ({n} seeds): ESCASO payoff {sl}(ρ0)->{sh}(ρ{hi}), +{sg}; ABUNDANTE {al}->{ah}, +{ag} "
                     "(satura).").format(n=n_seeds, sl=_f(sc[str(lo)]), sh=_f(sc[str(hi)]), hi=hi, sg=_f(sg),
                                         al=_f(ab[str(lo)]), ah=_f(ab[str(hi)]), ag=_f(ag)),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (el buen criterio para elegir vale cuando lo bueno escasea, no bajo abundancia).")

    kl = ("REAL (exp107): el payoff DECISIONAL de la calibración del selector ESCALA con la escasez -- bajo ESCASEZ (q=0.08) "
          "paga +{sg} (de azar {sl} a casi-óptimo {sh}); bajo ABUNDANCIA (q=0.9) SATURA (+{ag}, irrelevante). Demuestra "
          "POSITIVAMENTE que R-VALOR es DECISIONAL (121) y confirma el diagnóstico de 122 (necesita escasez). TECHO: "
          "abstracción numpy (corr-ρ sintética, bondad binaria; ρ exógeno -- en el lazo real lo provee la cura 119); "
          "demuestra el PRINCIPIO, no lo re-mide en un lazo real de escasez (frontera: tarea dura / SCALE).").format(
              sg=_f(sg), sl=_f(sc[str(lo)]), sh=_f(sc[str(hi)]), ag=_f(ag))
    ceilings.add(CeilingRecord(
        subsystem="Payoff DECISIONAL de R-VALOR — la calibración del selector PAGA en una decisión de asignación bajo ESCASEZ (de azar a casi-óptimo) y SATURA bajo abundancia; demuestra positivamente que R-VALOR es una brújula decisional",
        known_limit=kl,
        blockers=[{"text": "abstracción numpy: estimador con corr-ρ SINTÉTICA y bondad binaria; demuestra el PRINCIPIO limpio pero no lo re-mide en el lazo real (el lazo real -122- satura porque el modelo domina la tarea)", "kind": "diseno"},
                  {"text": "el ρ (calibración) es EXÓGENO aquí; en el lazo real lo provee la cura de durabilidad (119) -- la conexión 119->payoff-decisional está argumentada (calibración preservada) pero no medida end-to-end en un régimen de escasez", "kind": "diseno"},
                  {"text": "demostrar el payoff decisional EN un lazo real con escasez genuina (tarea dura donde lo bueno escasee) o a SCALE queda como frontera; numpy/juguete", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP107.ref, S_C121.ref, S_C122.ref]))
    notes.append("1 techo 'real': la calibración paga en la decisión bajo escasez (de azar a casi-óptimo), satura bajo abundancia -> R-VALOR es brújula decisional (capstone positivo).")

    dstmt = ("North-Star R-VALOR (CAPSTONE POSITIVO del arco): la señal de valor calibrada PAGA en una DECISIÓN de "
             "asignación de recurso ESCASO -- bajo escasez la calibración lleva el payoff de azar a casi-óptimo (+{sg}), "
             "bajo abundancia satura (irrelevante). Esto DEMUESTRA POSITIVAMENTE que R-VALOR es una BRÚJULA DECISIONAL "
             "(121) y explica por qué el toy de 122 (que el modelo domina -> abundancia) no podía aislarlo. Decisión: "
             "R-VALOR (el valor endógeno calibrado) se usa para ASIGNAR bajo escasez (presupuesto de verificación, "
             "atención, cómputo), exactamente donde la teoría de asignación (83-114) opera; la cura de durabilidad (119) "
             "mantiene la brújula confiable en lazos sostenidos. Cierra el arco coherentemente. Próximo: re-medir el payoff "
             "decisional en un lazo real con escasez genuina o a SCALE.").format(sg=_f(sg))
    drat = ("exp107 (tier5, propio, {n} seeds, numpy): ESCASO payoff {sl}(ρ0)->{sh}(ρ{hi}), +{sg}; ABUNDANTE satura "
            "(+{ag}). Convergente con payoff-selector∝escasez (tier2), demuestra positivamente 121 (tier5) y confirma el "
            "diagnóstico de 122 (tier5). APOYADA: R-VALOR es una brújula decisional que paga bajo escasez.").format(
                n=n_seeds, sl=_f(sc[str(lo)]), sh=_f(sc[str(hi)]), hi=hi, sg=_f(sg), ag=_f(ag))
    dec = Decision(id="D-V4-85", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP107), _to_plain(S_C121), _to_plain(S_C122)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-85 ACEPTADA por el ledger (tier5 exp107 + tier5 exp105 + tier5 exp106).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-85:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle123_decisional_scarcity',
                                description='CYCLE 123 (RESET v4, H-V4-9c: la calibración del selector PAGA en la decisión bajo escasez, satura bajo abundancia -- CAPSTONE POSITIVO; R-VALOR es brújula decisional).')
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
    print("RESUMEN — CYCLE 123 (RESET v4): la calibración del selector PAGA en la decisión bajo ESCASEZ (capstone positivo; R-VALOR = brújula decisional) — H-V4-9c")
    print("=" * 78)
    print("veredicto H-V4-9c:", status.upper() if status else "?")
    print("  bajo escasez la calibración lleva el payoff de azar a casi-óptimo; bajo abundancia satura. Demuestra positivamente que R-VALOR es decisional (121) y confirma 122.")
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
