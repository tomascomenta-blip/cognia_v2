r"""
cycle125_selective_budget.py — CICLO 125 (RESET v4, rama R-VALOR, EJE DEL PRESUPUESTO; unifica 123+124): H-V4-9e por las
compuertas del engine. APOYADA: 123 mostró que la calibración paga bajo ESCASEZ; 124 que las apuestas son
regime-direccionales (escasez->UPSIDE, abundancia->DOWNSIDE). Ambos FIJARON el presupuesto (m=5). Este ciclo barre el
presupuesto m y halla una ASIMETRÍA: el DOWNSIDE bajo abundancia es BUDGET-FRÁGIL (decae apenas m supera el nº de opciones
malas, que son pocas), el UPSIDE bajo escasez es BUDGET-ROBUSTO (persiste casi hasta m=n). => bajo abundancia ensanchar un
poco el presupuesto es una MITIGACIÓN BARATA de una señal posiblemente-rota; bajo escasez no hay sustituto de presupuesto
para la calidad de la calibración.

DERIVA de exp109_selective_budget/results/results.json.

Correr (DESPUÉS de exp109):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp109_selective_budget.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle125_selective_budget
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle125_selective_budget')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp109_selective_budget', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="el valor de seleccionar por calibración depende del presupuesto m relativo al supply de la MINORÍA relevante: bajo abundancia la minoría son las opciones malas (pocas) y un presupuesto que las supera FUERZA a incluir buenas (anula el daño de una señal rota); bajo escasez la minoría son las buenas (fracción ínfima) y ensanchar el presupuesto casi no ayuda al azar. Asimetría presupuesto-fragilidad de las dos caras de la selección", obtained=False,
                     claim=("El valor de seleccionar por una señal calibrada depende del PRESUPUESTO m relativo al supply de "
                            "la MINORÍA relevante. Bajo ABUNDANCIA la minoría son las opciones MALAS (pocas): un presupuesto "
                            "que supera su número FUERZA al selector anti-calibrado a incluir buenas, anulando el daño -> el "
                            "DOWNSIDE es BUDGET-FRÁGIL. Bajo ESCASEZ la minoría son las BUENAS (fracción ínfima): ensanchar "
                            "el presupuesto casi no ayuda al azar a alcanzarlas -> el UPSIDE es BUDGET-ROBUSTO. Asimetría "
                            "de presupuesto entre las dos caras del doble filo. (Principio.)"))
S_C123 = Source(tier=5, ref="cognia_x/experiments/exp107_decisional_scarcity", obtained=True,
                claim=("CYCLE 123: la calibración del selector PAGA bajo ESCASEZ y SATURA bajo abundancia (presupuesto fijo "
                       "m=5). H-V4-9e barre el presupuesto m."))
S_C124 = Source(tier=5, ref="cognia_x/experiments/exp108_calibration_stakes", obtained=True,
                claim=("CYCLE 124: las apuestas son regime-direccionales (escasez->UPSIDE, abundancia->DOWNSIDE; presupuesto "
                       "fijo m=5). H-V4-9e halla la ASIMETRÍA del presupuesto entre esas dos caras."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp109 primero): " + results_path)

    dat, dam, dd = sm['down_abund_tight'], sm['down_abund_mod'], sm['down_decay']
    ust, usm = sm['up_scarce_tight'], sm['up_scarce_mod']
    tm, mm, nb = sm['tight_m'], sm['moderate_m'], sm['n_bad_abund']
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim109 = ("exp109 (propio, {n} seeds, numpy, barre presupuesto m): ASIMETRÍA. DOWNSIDE abundante BUDGET-FRÁGIL "
                "(m{tm}=+{dat} -> m{mm}=+{dam}, decae {dd}; codo en #malas≈{nb}); UPSIDE escaso BUDGET-ROBUSTO "
                "(m{tm}=+{ust} -> m{mm}=+{usm}). Bajo abundancia ensanchar el presupuesto mitiga barato una señal rota; bajo "
                "escasez no hay sustituto de presupuesto para la calibración.").format(
                    n=n_seeds, tm=tm, dat=_f(dat), mm=mm, dam=_f(dam), dd=_f(dd), nb=nb, ust=_f(ust), usm=_f(usm))
    S_EXP109 = Source(tier=5, ref="cognia_x/experiments/exp109_selective_budget", obtained=True, claim=claim109)
    for src in (S_PRINCIPLE, S_C123, S_C124, S_EXP109):
        ledger.add_source(src)
    notes.append("4 fuentes (S_PRINCIPLE tier2 asimetría presupuesto-fragilidad; S_C123 tier5 escasez; S_C124 tier5 direcciones; S_EXP109 tier5 dato propio).")

    ev_for = [S_EXP109.ref, S_PRINCIPLE.ref]
    ev_against = [S_EXP109.ref]
    advtext = ("{V} (EJE DEL PRESUPUESTO -- unifica 123+124): 123 y 124 fijaron el presupuesto (m=5). H-V4-9e lo barre "
               "(m∈[1..40], n=60) × régimen q × dirección ρ∈{{anti,azar,bien}} y halla una ASIMETRÍA entre las dos caras del "
               "doble filo (124). El DOWNSIDE bajo ABUNDANCIA es BUDGET-FRÁGIL: grande a presupuesto ajustado (m={tm}: "
               "+{dat}) pero DECAE fuerte a presupuesto moderado (m={mm}: +{dam}, decae {dd}). MECANISMO: bajo abundancia la "
               "minoría son las opciones MALAS (~{nb} de 60); una vez que m supera ese número, el selector anti-calibrado se "
               "ve FORZADO a incluir buenas (no hay suficientes malas para llenar el presupuesto) y el daño se desvanece. El "
               "UPSIDE bajo ESCASEZ es BUDGET-ROBUSTO: sigue alto al MISMO m moderado (m={mm}: +{usm} vs m={tm}: +{ust}). "
               "MECANISMO: bajo escasez la minoría son las BUENAS (fracción ínfima); ensanchar el presupuesto casi no ayuda "
               "al azar a alcanzarlas, así que la calibración sigue marcando la diferencia. => REFINA 124 con el eje del "
               "presupuesto: bajo ABUNDANCIA, ensanchar un poco el presupuesto es una MITIGACIÓN BARATA de una señal "
               "posiblemente-rota (anti-calibrada); bajo ESCASEZ no hay sustituto de presupuesto para la CALIDAD de la "
               "calibración. Operacionalmente: el presupuesto y la calibración son SUSTITUTOS bajo abundancia (para evitar "
               "minas) pero COMPLEMENTOS bajo escasez (para capturar gemas). EVIDENCIA: el principio asimetría-de-presupuesto "
               "(tier2) lo predice por el supply de la minoría relevante. EVIDENCIA EN CONTRA / caveats: abstracción numpy "
               "(corr-ρ sintética, bondad binaria, ρ exógeno); demuestra el PRINCIPIO limpio, reproducible smoke(40)≈"
               "full(200); no lo re-mide en el lazo real.").format(
                   V=status.upper(), tm=tm, dat=_f(dat), mm=mm, dam=_f(dam), dd=_f(dd), nb=nb, usm=_f(usm), ust=_f(ust))

    hyp = Hypothesis(
        id="H-V4-9e",
        statement=("El doble filo de la calibración (124) tiene una ASIMETRÍA del PRESUPUESTO: el DOWNSIDE bajo abundancia "
                   "es BUDGET-FRÁGIL (decae apenas m supera el nº de opciones malas), el UPSIDE bajo escasez es "
                   "BUDGET-ROBUSTO (persiste). Presupuesto y calibración son SUSTITUTOS bajo abundancia (evitar minas) y "
                   "COMPLEMENTOS bajo escasez (capturar gemas)."),
        prediction=("APOYADA si: (a) el downside abundante a m ajustado > 0.40; (b) decae a m moderado (< 0.30, decaída > "
                    "0.40: budget-frágil); (c) el upside escaso al MISMO m moderado sigue > 0.30 (budget-robusto). REFUTADA "
                    "si el downside abundante no decae con m o el upside escaso también colapsa. MIXTA en otro caso. "
                    "(Pre-registrada, numpy, 200 seeds, barrido m×q×ρ.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp109_selective_budget")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-9e")
        notes.append("H-V4-9e marcada '{}' con DoD completo (asimetría del presupuesto: downside abundante frágil, upside escaso robusto).".format(status))

    analogy = AnalogyRecord(
        problem=("¿Cuánto puede COMPENSAR el presupuesto a un criterio malo o de más? Si tengo que elegir cosas para "
                 "presentar, ¿me salva agarrar unas pocas de más cuando mi criterio está al revés -- y depende de si lo "
                 "bueno es raro o común?"),
        everyday=("Si casi todo es bueno (90 de 100) y mi criterio está al REVÉS, agarrando 5 me voy derecho a las 6 cosas "
                  "malas (desastre) -- PERO si agarro 20, ya no me alcanzan las malas para llenar la cuota y me llevo "
                  "buenas igual: ensanchar un poco el presupuesto me SALVA de un criterio roto. En cambio si lo bueno es "
                  "raro (8 de 100), agarre 5 o agarre 20, al azar sigo sin pescar casi nada bueno -- acá el presupuesto NO "
                  "sustituye a tener buen criterio. Conclusión: cuando lo bueno abunda, un poco más de presupuesto tapa un "
                  "criterio malo (sustitutos); cuando lo bueno escasea, sólo el buen criterio sirve (complementos)."),
        solutions=["bajo abundancia el DOWNSIDE de un selector roto es BUDGET-FRÁGIL: un presupuesto que supera el nº de malas anula el daño",
                   "bajo escasez el UPSIDE de un buen selector es BUDGET-ROBUSTO: ensanchar el presupuesto no sustituye a la calibración",
                   "presupuesto y calibración son SUSTITUTOS bajo abundancia (evitar minas), COMPLEMENTOS bajo escasez (capturar gemas)",
                   "operacional: bajo abundancia, ensanchar un poco el presupuesto mitiga barato una señal posiblemente-rota"],
        principles=["el valor de la calibración depende del presupuesto m relativo al supply de la MINORÍA relevante (malas bajo abundancia, buenas bajo escasez)",
                    "el downside abundante es budget-frágil (m supera #malas -> daño anulado); el upside escaso es budget-robusto",
                    "presupuesto y calibración: SUSTITUTOS bajo abundancia, COMPLEMENTOS bajo escasez",
                    "refina 124: el doble filo no es simétrico en el presupuesto -- la cara catastrófica (abundancia) es la barata de mitigar"],
        adaptation=("El lab UNIFICA 123 (escasez) y 124 (direcciones) bajo el eje del PRESUPUESTO y halla una asimetría "
                    "operativamente útil: la cara CATASTRÓFICA del doble filo (downside de una señal anti-calibrada bajo "
                    "abundancia) es BARATA de mitigar -- basta ensanchar el presupuesto por encima del nº de opciones malas "
                    "para forzar la inclusión de buenas. La cara VALIOSA (upside bajo escasez) NO tiene sustituto de "
                    "presupuesto: hay que invertir en la calidad de la calibración. Política: bajo abundancia (régimen donde "
                    "vive un modelo competente), proteger contra una brújula posiblemente-rota con un presupuesto de "
                    "selección un poco holgado; bajo escasez, invertir en la calibración de la señal (cura 119) porque el "
                    "presupuesto no la reemplaza. Próximo: medir esta asimetría en un lazo real / a SCALE; el costo conjunto "
                    "(presupuesto × calidad de señal) bajo cada régimen."),
        measurement=("exp109 ({n} seeds): DOWNSIDE abundante m{tm}=+{dat}->m{mm}=+{dam} (frágil, codo #malas≈{nb}); UPSIDE "
                     "escaso m{tm}=+{ust}->m{mm}=+{usm} (robusto).").format(
                         n=n_seeds, tm=tm, dat=_f(dat), mm=mm, dam=_f(dam), nb=nb, ust=_f(ust), usm=_f(usm)),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (el presupuesto tapa un criterio roto bajo abundancia, no sustituye al buen criterio bajo escasez).")

    kl = ("REAL (exp109): asimetría del PRESUPUESTO en el doble filo de la calibración. El DOWNSIDE bajo abundancia es "
          "BUDGET-FRÁGIL (m{tm}=+{dat} -> m{mm}=+{dam}, decae {dd}; codo en #malas≈{nb}): un presupuesto que supera el nº de "
          "malas fuerza a incluir buenas y anula el daño de una señal anti-calibrada. El UPSIDE bajo escasez es "
          "BUDGET-ROBUSTO (m{tm}=+{ust} -> m{mm}=+{usm}): ensanchar el presupuesto no sustituye a la calibración. Presupuesto "
          "y calibración: SUSTITUTOS bajo abundancia, COMPLEMENTOS bajo escasez. TECHO: abstracción numpy (corr-ρ sintética, "
          "bondad binaria, ρ exógeno); demuestra el PRINCIPIO, no lo re-mide en lazo real (frontera: lazo real / SCALE / "
          "costo conjunto presupuesto×señal).").format(
              tm=tm, dat=_f(dat), mm=mm, dam=_f(dam), dd=_f(dd), nb=nb, ust=_f(ust), usm=_f(usm))
    ceilings.add(CeilingRecord(
        subsystem="Asimetría de PRESUPUESTO de R-VALOR — el downside de una señal anti-calibrada (abundancia) es budget-frágil (mitigable ensanchando el presupuesto sobre el nº de malas); el upside de una buena calibración (escasez) es budget-robusto (sin sustituto de presupuesto). Presupuesto y calibración: sustitutos bajo abundancia, complementos bajo escasez",
        known_limit=kl,
        blockers=[{"text": "abstracción numpy: estimador con corr-ρ SINTÉTICA (incl. anti) y bondad binaria; demuestra el PRINCIPIO de la asimetría de presupuesto limpio pero no lo re-mide en el lazo real", "kind": "diseno"},
                  {"text": "el ρ (calibración, incl. anti) es EXÓGENO; en el lazo real la calibración la fija la dinámica de auto-entrenamiento y la cura 119 -- la conexión señal-anti-real -> downside-budget-frágil está argumentada, no medida end-to-end", "kind": "diseno"},
                  {"text": "el costo CONJUNTO (presupuesto m × calidad de señal ρ) bajo cada régimen, y la transición exacta del codo de fragilidad con (q,n), quedan como frontera; numpy/juguete", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP109.ref, S_C123.ref, S_C124.ref]))
    notes.append("1 techo 'real': asimetría del presupuesto -- downside abundante budget-frágil (mitigable barato), upside escaso budget-robusto; presupuesto/calibración sustitutos vs complementos por régimen.")

    dstmt = ("North-Star R-VALOR (EJE DEL PRESUPUESTO -- unifica 123+124): el doble filo de la calibración tiene una "
             "ASIMETRÍA del presupuesto. El DOWNSIDE catastrófico de una señal anti-calibrada (abundancia) es BUDGET-FRÁGIL "
             "(m{tm}=+{dat} -> m{mm}=+{dam}): ensanchar el presupuesto por encima del nº de opciones malas anula el daño. El "
             "UPSIDE de una buena calibración (escasez) es BUDGET-ROBUSTO (m{tm}=+{ust} -> m{mm}=+{usm}): el presupuesto no "
             "sustituye a la calibración. Decisión: presupuesto y calibración son SUSTITUTOS bajo abundancia (proteger contra "
             "una brújula rota con un presupuesto holgado) y COMPLEMENTOS bajo escasez (invertir en la calidad de la señal, "
             "cura 119, porque el presupuesto no la reemplaza). Próximo: medir la asimetría en un lazo real / a SCALE; el "
             "costo conjunto presupuesto×señal por régimen.").format(
                 tm=tm, dat=_f(dat), mm=mm, dam=_f(dam), ust=_f(ust), usm=_f(usm))
    drat = ("exp109 (tier5, propio, {n} seeds, numpy, barre el presupuesto m): DOWNSIDE abundante budget-frágil (decae {dd} "
            "de m{tm} a m{mm}, codo #malas≈{nb}); UPSIDE escaso budget-robusto (+{usm} a m{mm}). Convergente con el principio "
            "asimetría-de-presupuesto (tier2), unifica 123 (tier5) y 124 (tier5). APOYADA: presupuesto y calibración son "
            "sustitutos bajo abundancia, complementos bajo escasez.").format(
                n=n_seeds, dd=_f(dd), tm=tm, mm=mm, nb=nb, usm=_f(usm))
    dec = Decision(id="D-V4-87", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP109), _to_plain(S_C123), _to_plain(S_C124)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-87 ACEPTADA por el ledger (tier5 exp109 + tier5 exp107 + tier5 exp108).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-87:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle125_selective_budget',
                                description='CYCLE 125 (RESET v4, H-V4-9e: asimetría del presupuesto en el doble filo de la calibración -- downside abundante budget-frágil, upside escaso budget-robusto; sustitutos vs complementos por régimen).')
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
    print("RESUMEN — CYCLE 125 (RESET v4): asimetría del PRESUPUESTO -- downside abundante BUDGET-FRÁGIL, upside escaso BUDGET-ROBUSTO (sustitutos vs complementos) — H-V4-9e")
    print("=" * 78)
    print("veredicto H-V4-9e:", status.upper() if status else "?")
    print("  presupuesto y calibración son SUSTITUTOS bajo abundancia (presupuesto holgado tapa una señal rota) y COMPLEMENTOS bajo escasez (sólo la calibración captura las gemas). Unifica 123+124.")
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
