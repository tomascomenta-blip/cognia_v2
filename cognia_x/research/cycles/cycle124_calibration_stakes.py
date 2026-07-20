r"""
cycle124_calibration_stakes.py — CICLO 124 (RESET v4, rama R-VALOR, ESTRÉS ADVERSARIAL del capstone 123): H-V4-9d por las
compuertas del engine. APOYADA: 123 (exp107) demostró que la calibración del selector PAGA bajo ESCASEZ y SATURA bajo
ABUNDANCIA -- pero sólo barrió ρ≥0 (de azar a buena calibración). Este ciclo extiende a ρ<0 (estimador ACTIVAMENTE
MAL-CALIBRADO, "confiadamente equivocado" -- el peligro del sub-arco de fragilidad 115-119) y halla un patrón ANTI-DIAGONAL:
bajo ESCASEZ importa el UPSIDE de la buena calibración (capturar gemas raras; el suelo aleatorio ya es bajo), bajo
ABUNDANCIA importa el DOWNSIDE de la mal-calibración (un selector anti-calibrado encuentra fiablemente las raras MINAS ->
catástrofe). REFINA 123: "irrelevante bajo abundancia" vale SÓLO para el upside; una señal MALA es más peligrosa justo donde
te sentís seguro. => la señal de valor endógena es de DOBLE FILO, y su fiabilidad (la cura de durabilidad 119) importa en
AMBOS regímenes pero por razones OPUESTAS.

DERIVA de exp108_calibration_stakes/results/results.json.

Correr (DESPUÉS de exp108):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp108_calibration_stakes.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle124_calibration_stakes
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle124_calibration_stakes')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp108_calibration_stakes', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="las apuestas de un selector de valor son REGIME-DIRECCIONALES: bajo escasez de buenas opciones pesa el UPSIDE de la buena calibración (capturar las raras buenas; el azar ya es bajo), bajo abundancia pesa el DOWNSIDE de la mal-calibración (las raras malas son pocas pero un selector anti-correlacionado las encuentra fiablemente -> catástrofe). Valor/riesgo de la información de selección según el régimen", obtained=False,
                     claim=("Las apuestas de la calibración de un selector son REGIME-DIRECCIONALES. Bajo ESCASEZ (lo bueno "
                            "es raro) el suelo aleatorio es bajo, así que lo que paga es el UPSIDE de una buena calibración "
                            "(capturar las gemas raras). Bajo ABUNDANCIA (lo bueno es común) cualquier selector positivo "
                            "satura, así que la calibración 'no importa' PARA EL UPSIDE -- pero un selector ANTI-calibrado "
                            "elige preferentemente las raras opciones MALAS (pocas, pero las encuentra fiablemente) -> el "
                            "DOWNSIDE es catastrófico. La señal de valor es de DOBLE FILO; su fiabilidad importa en ambos "
                            "regímenes por razones opuestas. (Principio.)"))
S_C123 = Source(tier=5, ref="cognia_x/experiments/exp107_decisional_scarcity", obtained=True,
                claim=("CYCLE 123 demostró POSITIVAMENTE que la calibración del selector PAGA bajo ESCASEZ (de azar a "
                       "casi-óptimo) y SATURA bajo abundancia -- pero sólo barrió ρ≥0. H-V4-9d extiende a ρ<0 (anti-calibración)."))
S_C119 = Source(tier=5, ref="cognia_x/experiments/exp103_bounded_unlikelihood", obtained=True,
                claim=("CYCLE 119 halló la cura de durabilidad (unlikelihood acotado mantiene la calibración sin degenerar). "
                       "H-V4-9d muestra POR QUÉ esa fiabilidad importa: una señal anti-calibrada es catastrófica, sobre todo "
                       "bajo abundancia (donde 123 decía 'irrelevante')."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp108 primero): " + results_path)

    us, ds = sm['upside_scarce'], sm['downside_scarce']      # escasez: upside grande, downside chico
    ua, da = sm['upside_abund'], sm['downside_abund']        # abundancia: upside chico (satura), downside grande
    g = sm['grid']
    rhos = sorted([float(k) for k in g['escaso'].keys()])
    lo, mid, hi = rhos[0], 0.0, rhos[-1]
    sc = g['escaso']; ab = g['abundante']
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim108 = ("exp108 (propio, {n} seeds, numpy, extiende exp107 a ρ<0): patrón ANTI-DIAGONAL. ESCASEZ (q=0.08): "
                "UPSIDE(azar->bien) +{us} (azar {sm0}, anti {slo}, bien {shi}); DOWNSIDE(azar->anti) +{ds}. ABUNDANCIA "
                "(q=0.9): UPSIDE +{ua} (satura, azar {am0}->bien {ahi}); DOWNSIDE +{da} (anti {alo}). Bajo escasez pesa el "
                "upside; bajo abundancia pesa el downside de la mal-calibración.").format(
                    n=n_seeds, us=_f(us), sm0=_f(sc[str(mid)]), slo=_f(sc[str(lo)]), shi=_f(sc[str(hi)]), ds=_f(ds),
                    ua=_f(ua), am0=_f(ab[str(mid)]), ahi=_f(ab[str(hi)]), da=_f(da), alo=_f(ab[str(lo)]))
    S_EXP108 = Source(tier=5, ref="cognia_x/experiments/exp108_calibration_stakes", obtained=True, claim=claim108)
    for src in (S_PRINCIPLE, S_C123, S_C119, S_EXP108):
        ledger.add_source(src)
    notes.append("4 fuentes (S_PRINCIPLE tier2 apuestas regime-direccionales; S_C123 tier5 capstone que extiende; S_C119 tier5 la cura de durabilidad que esto justifica; S_EXP108 tier5 dato propio).")

    ev_for = [S_EXP108.ref, S_PRINCIPLE.ref]
    ev_against = [S_EXP108.ref]
    advtext = ("{V} (ESTRÉS ADVERSARIAL del capstone 123: extiende ρ a NEGATIVO -- anti-calibración): 123 demostró que la "
               "calibración PAGA bajo escasez y SATURA bajo abundancia, pero sólo barrió ρ≥0 (de azar a buena). La frase "
               "'irrelevante bajo abundancia' de 123 es verdadera SÓLO para el UPSIDE. H-V4-9d barre ρ∈[-0.9,+0.9] "
               "(ρ<0 = estimador ANTI-correlacionado con la bondad: el top-m elige los MENOS buenos -- el peligro "
               "'confiadamente equivocado' del sub-arco de fragilidad 115-119) × escasez q. RESULTADO ANTI-DIAGONAL: bajo "
               "ESCASEZ (q=0.08) el UPSIDE de la buena calibración es grande (+{us}: azar {sm0} -> bien {shi}) pero el "
               "DOWNSIDE de la anti-calibración es CHICO (+{ds}: el suelo aleatorio ya es ~0, la anti-calibración no puede "
               "empeorarlo mucho). Bajo ABUNDANCIA (q=0.9) el UPSIDE SATURA (+{ua}: irrelevante, cualquier selector positivo "
               "acierta) PERO el DOWNSIDE es CATASTRÓFICO (+{da}: azar {am0} -> anti {alo} -- un selector anti-calibrado "
               "elige preferentemente las raras opciones MALAS, que son pocas pero las encuentra fiablemente). => las "
               "apuestas de la calibración son REGIME-DIRECCIONALES: la escasez hace pesar el UPSIDE (capturar gemas raras), "
               "la abundancia hace pesar el DOWNSIDE (no pisar las raras minas). REFINA 123: 'irrelevante bajo abundancia' "
               "vale sólo para el upside; una señal de valor MALA es más peligrosa justo donde te sentirías seguro "
               "(abundancia). JUSTIFICA la cura de durabilidad (119): mantener la señal calibrada importa en AMBOS regímenes "
               "-- bajo escasez para capturar lo raro bueno, bajo abundancia para NO seleccionar lo raro malo. EVIDENCIA: el "
               "principio apuestas-regime-direccionales (tier2) lo predice. EVIDENCIA EN CONTRA / caveats: abstracción numpy "
               "(estimador con corr-ρ sintética, bondad binaria; ρ exógeno) -- demuestra el PRINCIPIO limpio, no lo re-mide "
               "en el lazo real; la afirmación robusta es el patrón anti-diagonal de las apuestas, reproducible smoke(40)≈"
               "full(200).").format(V=status.upper(), us=_f(us), sm0=_f(sc[str(mid)]), shi=_f(sc[str(hi)]), ds=_f(ds),
                                    ua=_f(ua), am0=_f(ab[str(mid)]), alo=_f(ab[str(lo)]), da=_f(da))

    hyp = Hypothesis(
        id="H-V4-9d",
        statement=("Las apuestas de la calibración del selector son REGIME-DIRECCIONALES: bajo ESCASEZ pesa el UPSIDE de la "
                   "buena calibración (capturar gemas raras), bajo ABUNDANCIA pesa el DOWNSIDE de la anti-calibración "
                   "(encuentra fiablemente las raras minas -> catástrofe). Refina 123 ('irrelevante bajo abundancia' vale "
                   "sólo para el upside) y justifica la cura de durabilidad 119 (la fiabilidad importa en ambos regímenes)."),
        prediction=("APOYADA si el patrón es ANTI-DIAGONAL: bajo escasez upside > 0.30 y downside < 0.20; bajo abundancia "
                    "upside < 0.20 (satura) y downside > 0.30. REFUTADA si el downside bajo abundancia NO es grande (la "
                    "mal-calibración no daña donde 123 dice 'irrelevante') o el upside bajo escasez no paga. MIXTA en otro "
                    "caso. (Pre-registrada, numpy, 200 seeds, barrido ρ∈[-0.9,+0.9]×q.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp108_calibration_stakes")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-9d")
        notes.append("H-V4-9d marcada '{}' con DoD completo (apuestas regime-direccionales: escasez->upside, abundancia->downside).".format(status))

    analogy = AnalogyRecord(
        problem=("¿Cuándo importa mi criterio para elegir, y de qué manera? ¿Importa igual cuando lo bueno es raro que "
                 "cuando casi todo es bueno -- y un MAL criterio hace daño igual en ambos casos?"),
        everyday=("Si de 100 cosas sólo 8 son buenas y tengo que elegir 5: un BUEN criterio me hace agarrar casi todas las "
                  "buenas (vale mucho), pero elegir mal no cambia gran cosa porque al azar ya agarraba casi nada bueno -- el "
                  "RIESGO de equivocarme es bajo (no había mucho que ganar). En cambio si 90 de 100 son buenas: elija como "
                  "elija agarro buenas (mi buen criterio no se nota), PERO si mi criterio está al REVÉS me hace ir "
                  "derechito a las pocas malas -> desastre. Conclusión: cuando lo bueno es raro, importa qué tan BUENO sea "
                  "mi criterio; cuando lo bueno abunda, importa que mi criterio no esté ROTO/al revés."),
        solutions=["bajo escasez de buenas opciones: pesa el UPSIDE -- una buena calibración paga enorme (de azar a casi-óptimo); una mala apenas daña (el azar ya era malo)",
                   "bajo abundancia: pesa el DOWNSIDE -- la buena calibración satura (irrelevante) pero la anti-calibración es catastrófica (elige fiablemente las raras malas)",
                   "las apuestas de la calibración son regime-DIRECCIONALES (anti-diagonal): escasez->upside, abundancia->downside",
                   "la señal de valor endógena es de DOBLE FILO; mantenerla fiable (cura 119) importa en AMBOS regímenes por razones opuestas"],
        principles=["las apuestas de la calibración de un selector son regime-direccionales (escasez pesa el upside, abundancia pesa el downside)",
                    "'la calibración es irrelevante bajo abundancia' (123) vale SÓLO para el upside; una señal MALA es catastrófica bajo abundancia",
                    "una señal de valor endógena es de DOBLE FILO: bajo escasez captura lo raro bueno, bajo abundancia puede pisar lo raro malo",
                    "justifica la cura de durabilidad (119): mantener la señal calibrada protege en ambos regímenes (gemas raras / minas raras)"],
        adaptation=("El lab REFINA el capstone 123 con su lado oscuro: extender el barrido a la anti-calibración (ρ<0) revela "
                    "que las apuestas de la señal de valor son REGIME-DIRECCIONALES. Bajo ESCASEZ lo que está en juego es el "
                    "UPSIDE (capturar las raras buenas); bajo ABUNDANCIA lo que está en juego es el DOWNSIDE (no seleccionar "
                    "las raras malas). Esto CORRIGE la lectura ingenua de 123 ('irrelevante bajo abundancia'): es irrelevante "
                    "SÓLO para ganar, no para perder -- una señal de valor endógena MAL-calibrada es más peligrosa justo bajo "
                    "abundancia, donde uno se sentiría a salvo. Política: la fiabilidad de la brújula (cura de durabilidad "
                    "119) no es un lujo de 'lazos largos' -- protege en AMBOS regímenes: bajo escasez para no perderse las "
                    "gemas, bajo abundancia para no caer en las minas. Próximo: re-medir el doble filo EN un lazo real (donde "
                    "el ρ lo provee la cura 119, no es exógeno) y a SCALE; cuantificar el costo esperado de una señal "
                    "anti-calibrada bajo distintos presupuestos."),
        measurement=("exp108 ({n} seeds): ESCASEZ upside +{us} / downside +{ds}; ABUNDANCIA upside +{ua} (satura) / "
                     "downside +{da} (catastrófico). Anti-diagonal.").format(n=n_seeds, us=_f(us), ds=_f(ds), ua=_f(ua), da=_f(da)),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (el criterio para elegir: bajo escasez importa qué tan bueno es; bajo abundancia importa que no esté roto/al revés).")

    kl = ("REAL (exp108): las apuestas de la calibración del selector son REGIME-DIRECCIONALES. Bajo ESCASEZ (q=0.08) pesa "
          "el UPSIDE (buena calibración +{us}; anti-calibración apenas daña +{ds}, el azar ya era ~0). Bajo ABUNDANCIA "
          "(q=0.9) pesa el DOWNSIDE (buena calibración satura +{ua} -irrelevante-; anti-calibración CATASTRÓFICA +{da}). "
          "Refina 123 ('irrelevante bajo abundancia' sólo para el upside) y justifica la cura 119 (la fiabilidad importa en "
          "AMBOS regímenes). TECHO: abstracción numpy (corr-ρ sintética, bondad binaria; ρ exógeno -- en el lazo real lo "
          "provee 119); demuestra el PRINCIPIO, no re-mide el doble filo en un lazo real (frontera: lazo real / SCALE / "
          "costo esperado por presupuesto).").format(us=_f(us), ds=_f(ds), ua=_f(ua), da=_f(da))
    ceilings.add(CeilingRecord(
        subsystem="Apuestas de R-VALOR — las apuestas de la calibración del selector son REGIME-DIRECCIONALES: bajo escasez pesa el UPSIDE de la buena calibración, bajo abundancia pesa el DOWNSIDE de la anti-calibración; la señal de valor es de doble filo",
        known_limit=kl,
        blockers=[{"text": "abstracción numpy: estimador con corr-ρ SINTÉTICA (incl. ρ<0 anti) y bondad binaria; demuestra el PRINCIPIO del doble filo limpio pero no lo re-mide en el lazo real", "kind": "diseno"},
                  {"text": "el ρ (calibración, incl. anti) es EXÓGENO; en el lazo real la calibración la fija la dinámica de auto-entrenamiento y la cura 119 -- la conexión 'señal anti-calibrada real -> downside catastrófico' está argumentada (fragilidad 115-118 produce sobreconfianza-incorrecta) pero no medida end-to-end", "kind": "diseno"},
                  {"text": "cuantificar el COSTO ESPERADO de una señal anti-calibrada bajo distintos presupuestos m y la transición upside<->downside según el régimen queda como frontera; numpy/juguete", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP108.ref, S_C123.ref, S_C119.ref]))
    notes.append("1 techo 'real': apuestas regime-direccionales (escasez->upside, abundancia->downside); la señal de valor es de doble filo (refina 123, justifica 119).")

    dstmt = ("North-Star R-VALOR (REFINAMIENTO del capstone 123 con su lado oscuro): las apuestas de la calibración del "
             "selector son REGIME-DIRECCIONALES. Bajo ESCASEZ pesa el UPSIDE de la buena calibración (+{us}, de azar a "
             "casi-óptimo; la anti-calibración apenas daña, +{ds}). Bajo ABUNDANCIA pesa el DOWNSIDE de la anti-calibración "
             "(+{da}, catastrófico) mientras el upside satura (+{ua}, irrelevante). => 'la calibración es irrelevante bajo "
             "abundancia' (123) vale SÓLO para el upside; una señal de valor endógena MAL-calibrada es más peligrosa justo "
             "donde uno se sentiría a salvo. Decisión: tratar la señal de valor endógena como de DOBLE FILO; la fiabilidad "
             "de la brújula (cura de durabilidad 119) protege en AMBOS regímenes -- bajo escasez para capturar lo raro "
             "bueno, bajo abundancia para no seleccionar lo raro malo. Próximo: re-medir el doble filo en un lazo real / a "
             "SCALE; costo esperado de una señal anti-calibrada por presupuesto.").format(us=_f(us), ds=_f(ds), da=_f(da), ua=_f(ua))
    drat = ("exp108 (tier5, propio, {n} seeds, numpy, extiende exp107 a ρ<0): patrón ANTI-DIAGONAL -- ESCASEZ upside +{us} / "
            "downside +{ds}; ABUNDANCIA upside +{ua} (satura) / downside +{da} (catastrófico). Convergente con el principio "
            "apuestas-regime-direccionales (tier2), refina 123 (tier5) y justifica la cura 119 (tier5). APOYADA: la señal de "
            "valor es de doble filo; la fiabilidad importa en ambos regímenes.").format(
                n=n_seeds, us=_f(us), ds=_f(ds), ua=_f(ua), da=_f(da))
    dec = Decision(id="D-V4-86", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP108), _to_plain(S_C123), _to_plain(S_C119)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-86 ACEPTADA por el ledger (tier5 exp108 + tier5 exp107 + tier5 exp103).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-86:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle124_calibration_stakes',
                                description='CYCLE 124 (RESET v4, H-V4-9d: las apuestas de la calibración del selector son regime-direccionales -- escasez->upside, abundancia->downside; la señal de valor es de doble filo, refina 123).')
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
    print("RESUMEN — CYCLE 124 (RESET v4): las apuestas de la calibración son REGIME-DIRECCIONALES (escasez->upside, abundancia->downside) — la señal de valor es de DOBLE FILO — H-V4-9d")
    print("=" * 78)
    print("veredicto H-V4-9d:", status.upper() if status else "?")
    print("  bajo escasez pesa el UPSIDE de la buena calibración; bajo abundancia pesa el DOWNSIDE de la anti-calibración (catastrófica). Refina 123, justifica 119.")
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
