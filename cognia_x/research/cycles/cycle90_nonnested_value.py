r"""
cycle90_nonnested_value.py — CICLO 90 (RESET v4, rama R-VALOR, hija de CYCLE 89; conecta con R-PRIOR/H-V4-3): H-V4-7h
por las compuertas del engine. MIXTA: cuando la media condicional del VERIFICADOR REAL NO es nesteable por el poly2
(dos bandas interiores en la feature estructural, no-monótona), el poly2 default del gap #2 FALLA (se queda short del
techo bayes por ~0.33 -- sólo captura el eje r nesteable); una base RICA no-paramétrica (binned) RECUPERA PARCIALMENTE
(+0.117 sobre poly2, y es data-hungry: +0.076 low->high vs +0.024 de poly2) pero NO alcanza el techo bayes a presupuesto/
resolución factible (short ~0.21: discretización de la grilla + costo de datos de un prior fino). El producto monótono
falla aún más (0.325). => DOS hallazgos honestos: (1) CONFIRMA que el poly2 NO es universal (cierra el eje no-nesteable
del caveat de CYCLE 89: existen valores reales donde la base del gap #2 falla); (2) recuperar un valor no-nesteable es
CARO -- exige una base que matchee la estructura Y suficiente feedback/resolución; el lever es el MATCH + RESOLUCIÓN del
prior (R-PRIOR/H-V4-3), y cuesta.

DERIVA de exp074_nonnested_value/results/results.json.

Correr (DESPUÉS de exp074):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp074_nonnested_value.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle90_nonnested_value
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle90_nonnested_value')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp074_nonnested_value', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="la BASE del estimador es un PRIOR (sesgo de aproximación): si el span de la base no contiene la media condicional real, el estimador se queda corto por más datos que reciba; una base más rica reduce el sesgo a costa de varianza/datos", obtained=False,
                     claim=("Teoría de aproximación / sesgo-varianza: un regresor lineal en una base fija (poly grado d) "
                            "sólo puede representar funciones en su SPAN; si la media condicional real no entra ahí, hay "
                            "un sesgo de aproximación IRREDUCIBLE con datos. Una base más rica (mayor grado, "
                            "no-paramétrica) reduce el sesgo pero exige más muestras (varianza) y resolución (la "
                            "discretización de una grilla pone su propio techo). La elección de la base ES un prior "
                            "sobre la estructura del valor. (Principio; liga con R-PRIOR/H-V4-3.)"))
S_EXP073 = Source(tier=5, ref="cognia_x/experiments/exp073_real_verifier_value", obtained=True,
                  claim=("CYCLE 89 mostró que la política R-VALOR sobrevive un verificador REAL cuando E[v|c,r] es SUAVE "
                         "y nesteable por el poly2; dejó como caveat el eje NO-NESTEABLE (media condicional que el poly2 "
                         "no pueda representar). H-V4-7h ataca ese eje."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp074 primero): " + results_path)

    bayes = sm['bayes']
    p2_short = sm['poly2_short_vs_bayes']
    bin_short = sm['bin_short_vs_bayes']
    bin_rec = sm['bin_recovers_vs_poly2']
    p4_rec = sm['poly4_recovers']
    bin_cost = sm['bin_budget_cost']
    p2_cost = sm['poly2_budget_cost']
    g = sm['grid']
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim074 = ("exp074 (propio, {n} seeds, numpy + sandbox exp018): con un valor REAL NO-nesteable por poly2 (dos bandas "
                "interiores en c), el poly2 default FALLA (short del techo bayes={by} por {ps}; sólo capta el eje r); la "
                "base RICA binned recupera PARCIALMENTE (+{br} sobre poly2, data-hungry: +{bc} low->high vs +{pc} de "
                "poly2) pero NO alcanza bayes (short {bs}); producto monótono peor ({pr}). poly4 intermedio "
                "(+{p4}).").format(
                    n=n_seeds, by=_f(bayes), ps=_f(p2_short), br=_f(bin_rec), bc=_f(bin_cost), pc=_f(p2_cost),
                    bs=_f(bin_short), pr=_f(g['high']['product']), p4=_f(p4_rec))
    S_EXP074 = Source(tier=5, ref="cognia_x/experiments/exp074_nonnested_value", obtained=True, claim=claim074)
    for src in (S_PRINCIPLE, S_EXP073, S_EXP074):
        ledger.add_source(src)
    notes.append("3 fuentes (S_PRINCIPLE tier2 base=prior/sesgo-aproximación; S_EXP073 tier5 caveat no-nesteable de CYCLE 89; S_EXP074 tier5 dato propio).")

    ev_for = [S_EXP074.ref]
    ev_against = [S_EXP074.ref, S_EXP073.ref, S_PRINCIPLE.ref]
    advtext = ("{V} (hija de CYCLE 89; ataca el eje NO-NESTEABLE del caveat): CYCLE 89 dejó que E[v|c,r] seguía SUAVE y "
               "nesteable por el poly2 (generador sintético). H-V4-7h hace que el verificador REAL tenga una media "
               "condicional NO-nesteable: DOS BANDAS INTERIORES en la feature estructural c ([0.2,0.4)∪[0.6,0.8), "
               "no-monótona), que derrota tanto al prior MONÓTONO (product) como a la PARÁBOLA (poly2, un solo pico). El "
               "valor lo sigue decidiendo el sandbox REAL (ejecuta el candidato). DOS HALLAZGOS: (1) poly2 FALLA -- short "
               "del techo bayes (rankear por E[v|c,r] real) por {ps} (poly2={p2} vs bayes={by}); sólo captura el eje r "
               "nesteable, no la estructura c. CONFIRMA que el poly2 default del gap #2 NO es universal: existen valores "
               "REALES donde su base no llega -> cierra el eje no-nesteable del caveat de CYCLE 89. (2) una base RICA "
               "no-paramétrica (binned 8×8) RECUPERA PARCIALMENTE (+{br} sobre poly2) y es DATA-HUNGRY (mejora +{bc} de "
               "low->high vs +{pc} de poly2) PERO NO alcanza el techo bayes (short {bs}) ni con T grande (probado hasta "
               "T=1000: satura ~0.65) ni con features casi limpias (satura ~0.69): el tope lo pone la DISCRETIZACIÓN de "
               "la grilla (celdas que cruzan bordes de banda + promedian el eje r) y el costo de datos de un prior fino. "
               "EVIDENCIA EN CONTRA / matiz HONESTO: NO es APOYADA limpia -- la base rica NO recupera del todo; recuperar "
               "un valor no-nesteable es CARO (base que matchee + feedback/resolución suficientes). NO es REFUTADA -- "
               "poly2 sí falla y la base rica sí mejora monótonamente con presupuesto. => el lever es el MATCH + "
               "RESOLUCIÓN del prior (la base) con la estructura del valor, y cuesta datos -- exactamente la tesis de "
               "R-PRIOR/H-V4-3 (la CALIDAD/forma del prior fija la eficiencia muestral). Caveats: g determinista-banda "
               "sintético, espacio 2D, base binned cuadrada (un prior MATCHEADO a bandas -- ej. features de banda -- "
               "recuperaría más barato); falta el generador de MODELO real y SCALE.").format(
                   V=status.upper(), ps=_f(p2_short), p2=_f(g['high']['learned_poly2']), by=_f(bayes),
                   br=_f(bin_rec), bc=_f(bin_cost), pc=_f(p2_cost), bs=_f(bin_short))

    hyp = Hypothesis(
        id="H-V4-7h",
        statement=("Cuando la media condicional del verificador REAL NO es nesteable por el poly2 (estructura "
                   "multi-banda/no-monótona en la feature), el poly2 default del gap #2 FALLA y una base RICA "
                   "(no-paramétrica) la RECUPERA -- la base del combinador es un PRIOR cuyo match con la estructura del "
                   "valor (no el poly2 per se) es el lever (R-PRIOR)."),
        prediction=("APOYADA si poly2 se queda corto del techo bayes (>0.08) Y la base rica recupera (>poly2+0.05 y "
                    "alcanza bayes a <=0.05); REFUTADA si poly2 alcanza bayes (la estructura era nesteable); MIXTA si "
                    "poly2 falla pero la base rica recupera sólo PARCIALMENTE (no alcanza bayes). (Pre-registrada, "
                    "sandbox real exp018, 48 seeds, 2 presupuestos.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp074_nonnested_value")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-7h")
        notes.append("H-V4-7h marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("Mi regla de pulgar (multiplicar dos corazonadas) funcionó con un juez sencillo. Pero el juez real "
                 "premia algo RARO -- ni los mansos ni los extremos, sólo dos zonas intermedias. ¿Mi regla sirve, o "
                 "necesito un mapa más detallado -- y cuánto me cuesta aprenderlo?"),
        everyday=("Mi regla simple NO sirve para un patrón de 'dos zonas buenas' (una regla que dice 'más es mejor' o "
                  "'el punto medio es mejor' nunca acierta dos zonas separadas). Un MAPA detallado (memorizar zona por "
                  "zona) sí captura el patrón -- PERO necesito muchas más visitas para llenar el mapa, y si mi mapa es "
                  "de cuadrícula gruesa, las casillas que caen a caballo del borde me confunden. Recupero BASTANTE, no "
                  "todo: el patrón raro se aprende, pero sale caro y nunca perfecto con cuadrícula gruesa."),
        solutions=["regla simple (poly2): no acierta dos zonas separadas (un solo pico) -> se queda corta",
                   "mapa detallado (binned): captura el patrón raro pero pide muchos más datos y satura por la cuadrícula",
                   "regla de pulgar monótona (product): la peor -- apuesta a 'más es mejor', justo lo que el patrón niega",
                   "un mapa MATCHEADO al patrón (features de banda) recuperaría más barato -> el prior correcto importa"],
        principles=["la base del estimador es un PRIOR: sólo representa lo que está en su span (sesgo de aproximación)",
                    "si la media condicional real no entra en el span, NO hay datos que la recuperen con esa base",
                    "una base más rica reduce el sesgo pero cuesta más datos (varianza) y su discretización pone techo",
                    "el lever es el MATCH + RESOLUCIÓN del prior con la estructura del valor (R-PRIOR), y cuesta"],
        adaptation=("El lab ACOTA el alcance de la política gap #2: el combinador poly2 (que dominaba en 83-89) NO es "
                    "universal -- falla cuando la media condicional del valor real no entra en su span (estructura "
                    "no-monótona/multi-banda). Una base más rica recupera PARCIALMENTE a costa de feedback. Política: "
                    "usar poly2 por DEFECTO (barato, robusto donde el valor es suave/conjuntivo, 89), escalar a una base "
                    "más rica SÓLO con evidencia de estructura no-nesteable + presupuesto de feedback. Liga gap #2 con "
                    "R-PRIOR/H-V4-3 (ABIERTA): la calidad/forma del prior fija la eficiencia muestral. Próximo: un prior "
                    "MATCHEADO a la estructura (features de banda/kernel) que recupere barato; el generador de MODELO "
                    "real (exp018, lazo cerrado); y SCALE."),
        measurement=("exp074 ({n} seeds, sandbox exp018): poly2 short de bayes={by} por {ps}; bin recupera +{br} sobre "
                     "poly2 pero short {bs} de bayes; bin data-hungry (+{bc} vs poly2 +{pc} low->high); product={pr} "
                     "(monótono, peor).").format(
                         n=n_seeds, by=_f(bayes), ps=_f(p2_short), br=_f(bin_rec), bs=_f(bin_short),
                         bc=_f(bin_cost), pc=_f(p2_cost), pr=_f(g['high']['product'])),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (la regla simple no acierta 'dos zonas buenas'; el mapa detallado sí pero sale caro).")

    kl = ("REAL (exp074): cuando la media condicional del verificador REAL NO es nesteable por el poly2 (dos bandas "
          "interiores en c), el poly2 default del gap #2 FALLA (short del techo bayes={by} por {ps}); una base RICA "
          "(binned) recupera PARCIALMENTE (+{br} sobre poly2, data-hungry) pero NO alcanza bayes (short {bs}: "
          "discretización + costo de datos). TECHO: recuperar un valor no-nesteable exige una base que matchee la "
          "estructura Y feedback/resolución suficientes; el poly2 no es universal, y la base rica es cara. El lever es "
          "el MATCH+RESOLUCIÓN del prior (R-PRIOR/H-V4-3).").format(by=_f(bayes), ps=_f(p2_short), br=_f(bin_rec), bs=_f(bin_short))
    ceilings.add(CeilingRecord(
        subsystem="R-VALOR con media condicional NO-nesteable — el poly2 del gap #2 no es universal; una base rica recupera parcial y caro (liga R-PRIOR)",
        known_limit=kl,
        blockers=[{"text": "la base poly2 tiene sesgo de aproximación IRREDUCIBLE cuando la media condicional real no está en su span (estructura no-monótona/multi-banda); ningún volumen de datos lo cierra con esa base", "kind": "fisico"},
                  {"text": "una base no-paramétrica (binned 8×8) recupera parcial pero satura por DISCRETIZACIÓN (celdas que cruzan bordes de banda + promedian el otro eje) y es data-hungry; probado hasta T=1000 y features casi limpias", "kind": "fisico"},
                  {"text": "un prior MATCHEADO a la estructura (features de banda / kernel adecuado) recuperaría más barato; no testeado. Falta el generador de MODELO real (lazo cerrado exp018), objetivo no-escalar y SCALE (GPU)", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP074.ref, S_EXP073.ref]))
    notes.append("1 techo 'real': el poly2 no es universal (sesgo de aproximación); la base rica recupera parcial y caro -> liga R-PRIOR/H-V4-3.")

    dstmt = ("North-Star R-VALOR (hija de CYCLE 89, ACOTA el alcance de la política gap #2; liga R-PRIOR/H-V4-3): cuando "
             "la media condicional del verificador REAL NO es nesteable por el poly2 (estructura multi-banda/no-monótona), "
             "el poly2 default FALLA (no es universal -- short del techo bayes) y una base RICA recupera sólo PARCIALMENTE "
             "(data-hungry, capada por discretización). Decisión: usar poly2 por DEFECTO (barato, robusto donde el valor "
             "es suave/conjuntivo, CYCLE 89), escalar a una base más rica/MATCHEADA SÓLO con evidencia de estructura "
             "no-nesteable + presupuesto de feedback. El lever es el MATCH+RESOLUCIÓN del prior (la base) con la "
             "estructura del valor -- exactamente R-PRIOR/H-V4-3 (ABIERTA). Próximo: un prior matcheado a la estructura "
             "(features de banda/kernel); el generador de MODELO real (lazo cerrado exp018); y SCALE (GPU).")
    drat = ("exp074 (tier5, propio, {n} seeds, numpy + sandbox exp018): poly2 short de bayes por {ps} (>0.08, FALLA); bin "
            "recupera +{br} sobre poly2 (>0.05) pero short {bs} de bayes (>0.05, recuperación PARCIAL) y data-hungry "
            "(+{bc} vs poly2 +{pc}). Convergente con el principio base=prior/sesgo-aproximación (tier2) y con el caveat "
            "no-nesteable de CYCLE 89 (tier5). MIXTA: poly2 no es universal (confirmado) PERO recuperar lo no-nesteable "
            "es caro/parcial.").format(n=n_seeds, ps=_f(p2_short), br=_f(bin_rec), bs=_f(bin_short), bc=_f(bin_cost), pc=_f(p2_cost))
    dec = Decision(id="D-V4-52", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP074), _to_plain(S_EXP073)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-52 ACEPTADA por el ledger (tier5 exp074 + tier5 exp073).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-52:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle90_nonnested_value',
                                description='CYCLE 90 (RESET v4, H-V4-7h: el poly2 no es universal -- falla en media no-nesteable; base rica recupera parcial/caro -- MIXTA; liga R-PRIOR).')
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
    print("RESUMEN — CYCLE 90 (RESET v4): el poly2 no es universal (media no-nesteable) — base rica recupera parcial/caro (H-V4-7h)")
    print("=" * 78)
    print("veredicto H-V4-7h:", status.upper() if status else "?")
    print("  poly2 falla (short bayes); bin recupera parcial y data-hungry, no alcanza bayes (discretización). Liga R-PRIOR/H-V4-3.")
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
