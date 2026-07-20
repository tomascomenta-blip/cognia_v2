r"""
cycle95_submodular_value.py — CICLO 95 (RESET v4, rama R-VALOR, gap #4: objetivo NO-aditivo): H-V4-8a por las compuertas
del engine. APOYADA: bajo un objetivo SUBMODULAR (cobertura / rendimientos decrecientes), la asignación por valor
ABSOLUTO (top-k por valor estimado, la política implícita de todo el arco 83-94) DESPERDICIA picks en ítems redundantes
del mismo tipo; el valor MARGINAL (greedy por ganancia respecto del conjunto ya elegido) CUBRE los tipos y recupera el
óptimo (≈ oracle). Bajo objetivo ADITIVO ambas COINCIDEN (top-k = óptimo). => R-VALOR debe ser MARGINAL (contextual al
conjunto), no absoluto, cuando el objetivo no es aditivo. Formaliza el tema de diversidad (CYCLE 49-50/94): la diversidad
ES el valor cuando el objetivo es de cobertura; y conecta con que empowerment/info-gain ya eran valores MARGINALES.

DERIVA de exp079_submodular_value/results/results.json.

Correr (DESPUÉS de exp079):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp079_submodular_value.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle95_submodular_value
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle95_submodular_value')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp079_submodular_value', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="optimización submodular: el greedy por ganancia MARGINAL es (1−1/e)-óptimo para funciones monótonas submodulares; el valor marginal (no absoluto) es el objeto correcto cuando hay rendimientos decrecientes/cobertura", obtained=False,
                     claim=("Para un objetivo monótono SUBMODULAR (cobertura, diversidad, rendimientos decrecientes), el "
                            "greedy que en cada paso añade el ítem de mayor GANANCIA MARGINAL respecto del conjunto "
                            "actual es (1−1/e)≈0.63-óptimo (Nemhauser 1978); elegir por valor ABSOLUTO (top-k) es "
                            "subóptimo (elige redundantes). El valor relevante es MARGINAL (contextual al conjunto), no "
                            "absoluto. (Principio; conecta con empowerment/info-gain como valores marginales del lab.)"))
S_ARC = Source(tier=5, ref="cognia_x/experiments/exp078_closed_loop_guard", obtained=True,
               claim=("Todo el arco 83-94 (incl. el lazo cerrado 93-94) asignó top-k por valor estimado, asumiendo un "
                      "objetivo ADITIVO (perf_of = suma de valores independientes); la diversidad apareció sólo como un "
                      "matiz empírico (narrowing). H-V4-8a ataca esa suposición con un objetivo NO-aditivo."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp079 primero): " + results_path)

    gs = sm['gap_submodular']
    ga = sm['gap_additive']
    mog = sm['marginal_oracle_gap_sub']
    al = sm['additive_loss_sub']
    g = sm['grid']
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim079 = ("exp079 (propio, {n} seeds, numpy): bajo SUBMODULAR (cobertura) marginal_greedy={mg} ≈ oracle (gap {mo}) "
                ">> additive_greedy={ag} (+{gs}); bajo ADDITIVE coinciden (gap {ga}); additive pierde {al} vs oracle bajo "
                "submodular. => el valor debe ser MARGINAL bajo objetivos no-aditivos.").format(
                    n=n_seeds, mg=_f(g['submodular']['marginal_greedy']), mo=_f(mog), ag=_f(g['submodular']['additive_greedy']),
                    gs=_f(gs), ga=_f(ga), al=_f(al))
    S_EXP079 = Source(tier=5, ref="cognia_x/experiments/exp079_submodular_value", obtained=True, claim=claim079)
    for src in (S_PRINCIPLE, S_ARC, S_EXP079):
        ledger.add_source(src)
    notes.append("3 fuentes (S_PRINCIPLE tier2 submodular/marginal greedy; S_ARC tier5 suposición aditiva de 83-94; S_EXP079 tier5 dato propio).")

    ev_for = [S_EXP079.ref]
    ev_against = [S_EXP079.ref, S_ARC.ref, S_PRINCIPLE.ref]
    advtext = ("{V} (gap #4: objetivo NO-aditivo): todo el arco 83-94 asignó 'top-k por valor estimado' y midió perf_of = "
               "suma de valores INDEPENDIENTES de los ítems -- un objetivo ADITIVO. El caso REAL es a menudo SUBMODULAR "
               "(cobertura / rendimientos decrecientes: no sirve elegir 10 copias de lo mismo). H-V4-8a lo testea con un "
               "objetivo de cobertura value(S)=Σ_t max_{{i∈S,t_i=t}} q_i (sólo cuenta el mejor por tipo). RESULTADO: bajo "
               "SUBMODULAR, la asignación por valor ABSOLUTO (top-k, la política implícita) DESPERDICIA picks en ítems "
               "redundantes del mismo tipo (additive_greedy={ag}), mientras el valor MARGINAL (greedy por ganancia "
               "respecto del conjunto ya elegido) CUBRE los tipos y recupera el óptimo: marginal_greedy={mg} (+{gs}, ≈ "
               "oracle gap {mo}); el additive pierde {al} vs oracle. Bajo objetivo ADDITIVE ambas COINCIDEN (gap {ga}: "
               "sin redundancia, top-k = óptimo) -> el gap es ESPECÍFICO de la no-aditividad, no un artefacto. => R-VALOR "
               "debe ser MARGINAL (contextual al conjunto), no absoluto, cuando el objetivo no es aditivo. CONECTA dos "
               "hilos: (1) formaliza la DIVERSIDAD (CYCLE 49-50/94, que era un matiz empírico de narrowing) como la "
               "estructura del VALOR cuando el objetivo es de cobertura -- la diversidad ES el valor; (2) reconcilia con "
               "que el empowerment/info-gain del lab (CYCLE 24/56/79-80) YA eran valores MARGINALES (de la consecuencia), "
               "no absolutos. EVIDENCIA EN CONTRA / caveats: g de cobertura sintético, tipos+calidad uniformes "
               "(correlacionar calidad↔tipo agrandaría el gap), greedy-marginal con q ruidoso pero tipos observables; el "
               "óptimo submodular exacto es NP-hard (se usó el greedy (1−1/e) y la cota type-max como oracle). El gap "
               "absoluto (~{gs}) es modesto bajo uniformidad (top-k cubre tipos por azar a k>T) pero ROBUSTO y "
               "direccional; crece con la redundancia.").format(
                   V=status.upper(), ag=_f(g['submodular']['additive_greedy']), mg=_f(g['submodular']['marginal_greedy']),
                   gs=_f(gs), mo=_f(mog), al=_f(al), ga=_f(ga))

    hyp = Hypothesis(
        id="H-V4-8a",
        statement=("Bajo un objetivo NO-aditivo (submodular/cobertura), la asignación por valor ABSOLUTO (top-k, la "
                   "política implícita de 83-94) es subóptima (elige redundantes) y el valor MARGINAL (greedy por "
                   "ganancia respecto del conjunto) recupera el óptimo; bajo objetivo aditivo coinciden -> R-VALOR debe "
                   "ser MARGINAL cuando el objetivo no es aditivo."),
        prediction=("APOYADA si bajo submodular marginal > additive (+>0.05) Y ≈ oracle (gap <=0.05) Y bajo additive "
                    "coinciden (|gap|<=0.03); REFUTADA si additive ≈ marginal aun bajo submodular; MIXTA en otro caso. "
                    "(Pre-registrada, numpy, 48 seeds, objetivo de cobertura.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp079_submodular_value")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-8a")
        notes.append("H-V4-8a marcada '{}' con DoD completo (abre gap #4: objetivo no-aditivo).".format(status))

    analogy = AnalogyRecord(
        problem=("Tengo presupuesto para llevar 10 cosas a una isla y quiero CUBRIR mis necesidades (comida, agua, "
                 "abrigo, fuego, herramienta...). ¿Llevo las 10 'mejores' cosas sueltas, o la mejor de cada necesidad?"),
        everyday=("La mejor de cada necesidad. Si llevo las 10 'mejores' por puntaje suelto, termino con 6 cuchillos "
                  "buenísimos y sin agua -- redundante. Lo que vale no es el puntaje ABSOLUTO de cada cosa sino cuánto "
                  "SUMA a lo que ya tengo: una vez cubierta el agua, otra cantimplora no aporta. Cuando lo importante es "
                  "CUBRIR (no acumular), el valor de cada cosa depende de las demás."),
        solutions=["valor marginal (qué cubre lo que aún no tengo): cubre todas las necesidades = óptimo",
                   "valor absoluto (top-k por puntaje): acumula redundante en lo mismo, deja huecos",
                   "si las cosas NO compiten (objetivo aditivo): top-k = óptimo (no hay redundancia)",
                   "el greedy marginal es ~63%-óptimo garantizado para cobertura (submodular)"],
        principles=["bajo objetivo submodular (cobertura) el valor es MARGINAL (respecto del conjunto), no absoluto",
                    "elegir por valor absoluto (top-k) desperdicia presupuesto en redundantes",
                    "bajo objetivo aditivo el valor marginal = absoluto (top-k óptimo): el gap es de la no-aditividad",
                    "la diversidad ES el valor cuando el objetivo es de cobertura (formaliza CYCLE 49-50/94)"],
        adaptation=("El lab REFINA la política R-VALOR: bajo objetivos no-aditivos (cobertura/diversidad, los realistas), "
                    "asignar por valor MARGINAL (greedy por ganancia respecto del conjunto), no por valor absoluto top-k. "
                    "Esto formaliza el matiz de diversidad (49-50/94) y reconcilia con empowerment/info-gain (ya "
                    "marginales). En el lazo de auto-mejora (93-94), la guardia dedup+replay era una APROXIMACIÓN a la "
                    "selección marginal; la versión principista es greedy-marginal sobre un objetivo de cobertura. "
                    "Próximo: combinar selección marginal con el lazo cerrado real; correlacionar calidad↔tipo; SCALE."),
        measurement=("exp079 ({n} seeds): submodular marginal={mg} ≈ oracle (gap {mo}) >> additive={ag} (+{gs}); "
                     "additive obj coincide (gap {ga}); additive pierde {al} vs oracle bajo submodular.").format(
                         n=n_seeds, mg=_f(g['submodular']['marginal_greedy']), mo=_f(mog),
                         ag=_f(g['submodular']['additive_greedy']), gs=_f(gs), ga=_f(ga), al=_f(al)),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (llevar la mejor de cada necesidad vs las 10 'mejores' sueltas).")

    kl = ("REAL (exp079): bajo un objetivo NO-aditivo (submodular/cobertura) la asignación por valor ABSOLUTO (top-k) es "
          "subóptima (additive_greedy={ag}, pierde {al} vs oracle) y el valor MARGINAL (greedy por ganancia respecto del "
          "conjunto) recupera el óptimo (marginal_greedy={mg}, +{gs}, ≈ oracle); bajo objetivo aditivo coinciden (gap "
          "{ga}). El valor debe ser MARGINAL cuando el objetivo no es aditivo. TECHO: g de cobertura sintético, tipos+"
          "calidad uniformes, óptimo submodular vía greedy/type-max (exacto es NP-hard).").format(
              ag=_f(g['submodular']['additive_greedy']), al=_f(al), mg=_f(g['submodular']['marginal_greedy']), gs=_f(gs), ga=_f(ga))
    ceilings.add(CeilingRecord(
        subsystem="R-VALOR bajo objetivo NO-aditivo (gap #4) — el valor debe ser MARGINAL (greedy por ganancia), no absoluto (top-k), bajo submodularidad/cobertura",
        known_limit=kl,
        blockers=[{"text": "g de cobertura SINTÉTICO con tipos+calidad uniformes; correlacionar calidad↔tipo agrandaría el gap. El óptimo submodular exacto es NP-hard (se usó greedy (1−1/e) + cota type-max como oracle)", "kind": "diseno"},
                  {"text": "tipos OBSERVABLES y calidad ruidosa; si los tipos también fueran latentes/ruidosos la cobertura sería más difícil de estimar (liga con R-PRIOR: estimar la estructura del objetivo)", "kind": "diseno"},
                  {"text": "no se combinó la selección marginal con el LAZO CERRADO real (93-94) ni con SCALE; la guardia dedup+replay de 94 es una aproximación a la selección marginal -- falta la versión principista en el lazo", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP079.ref, S_ARC.ref]))
    notes.append("1 techo 'real': bajo objetivo no-aditivo el valor es MARGINAL; abre el gap #4 (objetivos no-aditivos/cobertura).")

    dstmt = ("North-Star R-VALOR (gap #4: objetivo NO-aditivo): bajo objetivos SUBMODULARES (cobertura/diversidad, los "
             "realistas) la asignación por valor ABSOLUTO (top-k, la política implícita de 83-94) es subóptima -- "
             "desperdicia presupuesto en redundantes -- y el valor MARGINAL (greedy por ganancia respecto del conjunto) "
             "recupera el óptimo; bajo objetivo aditivo coinciden. Decisión: la política R-VALOR usa valor MARGINAL "
             "(contextual al conjunto) cuando el objetivo no es aditivo. Esto FORMALIZA el matiz de diversidad (49-50/94) "
             "como la estructura del valor (la diversidad ES el valor en cobertura) y reconcilia con empowerment/info-gain "
             "(ya marginales). La guardia dedup+replay (94) es una aproximación; la versión principista es greedy-marginal. "
             "Próximo: selección marginal en el lazo cerrado real; calidad↔tipo correlacionados; objetivo vector; SCALE.")
    drat = ("exp079 (tier5, propio, {n} seeds, numpy): submodular marginal={mg} ≈ oracle (gap {mo}) >> additive={ag} "
            "(+{gs}); additive obj coincide (gap {ga}); additive pierde {al} vs oracle. Convergente con submodular/marginal "
            "greedy (tier2, Nemhauser) y con la suposición aditiva del arco (tier5). APOYADA: el valor es marginal bajo "
            "no-aditividad.").format(n=n_seeds, mg=_f(g['submodular']['marginal_greedy']), mo=_f(mog),
                                     ag=_f(g['submodular']['additive_greedy']), gs=_f(gs), ga=_f(ga), al=_f(al))
    dec = Decision(id="D-V4-57", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP079), _to_plain(S_ARC)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-57 ACEPTADA por el ledger (tier5 exp079 + tier5 exp078).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-57:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle95_submodular_value',
                                description='CYCLE 95 (RESET v4, H-V4-8a: bajo objetivo submodular el valor debe ser MARGINAL, no absoluto -- APOYADA; abre gap #4).')
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
    print("RESUMEN — CYCLE 95 (RESET v4): el valor debe ser MARGINAL bajo objetivo no-aditivo (H-V4-8a) — abre gap #4")
    print("=" * 78)
    print("veredicto H-V4-8a:", status.upper() if status else "?")
    print("  submodular: marginal_greedy ≈ oracle >> additive top-k; additive obj: coinciden. El valor es marginal, no absoluto.")
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
