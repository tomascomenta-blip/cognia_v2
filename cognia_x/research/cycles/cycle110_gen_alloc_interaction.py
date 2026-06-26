r"""
cycle110_gen_alloc_interaction.py — CICLO 110 (RESET v4, rama R-VALOR, PIVOT generación↔asignación, bridge a creatividad
pillar #4): H-V4-8o por las compuertas del engine. APOYADA: la DIVERSIDAD del generador (temperatura) y la CALIDAD de la
asignación son COMPLEMENTARIAS -- subir la diversidad del generador paga (o daña menos) MÁS bajo BUENA asignación
(confianza: el filtro aprovecha la exploración) que bajo asignación POBRE (al azar: la diversidad mete más basura sin
filtrar). Interacción temp×alloc POSITIVA en el lazo cerrado real. => R-VALOR (la política de asignación) gobierna cuánta
EXPLORACIÓN del generador conviene: un puente generación–selección.

DERIVA de exp094_gen_alloc_interaction/results/results.json.

Correr (DESPUÉS de exp094):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp094_gen_alloc_interaction.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle110_gen_alloc_interaction
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle110_gen_alloc_interaction')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp094_gen_alloc_interaction', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


S_PRINCIPLE = Source(tier=2, ref="exploración–explotación + el valor de la exploración depende de la calidad del FILTRO/selector: con buena selección (verificar/quedarse con lo mejor) una distribución de propuestas más ANCHA paga; con selección pobre la exploración mete ruido. Puente generación–selección", obtained=False,
                     claim=("El valor de la EXPLORACIÓN (diversidad del generador) depende de la calidad del SELECTOR: con "
                            "un filtro bueno (verificar/quedarse con lo mejor) una distribución de propuestas más ANCHA "
                            "paga (más candidatos buenos descubiertos, el filtro descarta el ruido); con un selector "
                            "pobre, la diversidad sólo agrega ruido al entrenamiento. Generación y selección son "
                            "complementarias. (Principio.)"))
S_ARC = Source(tier=5, ref="cognia_x/experiments/exp091_composed_recipe", obtained=True,
               claim=("El arco 93-107 asignó sobre un pool DADO (selección). H-V4-8o abre la palanca de GENERACIÓN "
                      "(diversidad/temperatura) y mide su interacción con la calidad de la asignación."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp094 primero): " + results_path)

    cte = sm['conf_temp_effect']
    rte = sm['rand_temp_effect']
    it = sm['interaction']
    pf = sm['pos_frac']
    csc = _mean(sm['conf_strong_corr_by_seed'])
    n_seeds = sm['n_seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim094 = ("exp094 (propio, {n} seeds, PyTorch CPU, lazo cerrado real exp018): subir la temperatura del generador "
                "tiene efecto {cte} bajo conf-alloc vs {rte} bajo random-alloc -> INTERACCIÓN temp×alloc=+{it} ({pf:.0%} "
                "seeds positiva). Diversidad del generador y calidad de asignación COMPLEMENTARIAS. corr(conf,strong)="
                "{csc}.").format(n=n_seeds, cte=_f(cte), rte=_f(rte), it=_f(it), pf=pf, csc=_f(csc))
    S_EXP094 = Source(tier=5, ref="cognia_x/experiments/exp094_gen_alloc_interaction", obtained=True, claim=claim094)
    for src in (S_PRINCIPLE, S_ARC, S_EXP094):
        ledger.add_source(src)
    notes.append("3 fuentes (S_PRINCIPLE tier2 exploración×calidad-del-filtro; S_ARC tier5 el arco asignó sobre pool dado; S_EXP094 tier5 dato propio).")

    ev_for = [S_EXP094.ref, S_PRINCIPLE.ref]
    ev_against = [S_EXP094.ref]
    advtext = ("{V} (PIVOT generación↔asignación; bridge a creatividad pillar #4): todo el arco 93-107 asignó sobre un "
               "pool DADO (selección de qué verificar). Pero el pool lo produce el GENERADOR, y su DIVERSIDAD "
               "(temperatura) es una palanca aparte. H-V4-8o pregunta si diversidad-del-generador y calidad-de-asignación "
               "son COMPLEMENTARIAS, con un diseño 2×2 (temp∈{{low,high}} × alloc∈{{conf,random}}) en el lazo cerrado "
               "real. RESULTADO: subir la temperatura del generador tiene efecto {cte} en el downstream bajo BUENA "
               "asignación (conf) vs {rte} bajo asignación POBRE (random) -> INTERACCIÓN temp×alloc = +{it} ({pf:.0%} de "
               "los seeds positiva). MECANISMO: con buena asignación (verificar lo más prometedor por confianza), una "
               "distribución de propuestas más ANCHA paga -- el filtro descubre y se queda con los candidatos buenos que "
               "la diversidad genera, y DESCARTA el ruido; con asignación al azar, subir la diversidad sólo mete MÁS "
               "basura en el entrenamiento (el filtro no la frena) -> colapsa el downstream. => la DIVERSIDAD del "
               "generador y la CALIDAD de la asignación son COMPLEMENTARIAS: R-VALOR (la política de asignación) gobierna "
               "cuánta EXPLORACIÓN del generador conviene -- con mejor selección, MÁS exploración. Es un puente "
               "generación–selección (conecta el lazo de auto-mejora con la creatividad/pillar #4: la creatividad sólo "
               "paga si hay un buen juez que la filtre). corr(conf,strong)={csc} (confianza calibrada). MECANISMO DE DOS "
               "LADOS (honesto): la conf-alloc a baja diversidad NARROWS (CYCLE 93/94: se encasilla en sus generaciones "
               "más confiadas) -> NECESITA la diversidad del generador para destrabar su propio narrowing (de ahí el gran "
               "+{cte}); la random-alloc no filtra -> la diversidad alta sólo le mete basura ({rte}). EVIDENCIA EN CONTRA "
               "/ caveat CLAVE: el MEJOR config absoluto NO es conf+high sino RANDOM+LOW (pool limpio y diverso a baja "
               "temp) -> 'más diversidad es mejor' es FALSO incondicionalmente; la afirmación robusta es la "
               "INTERACCIÓN/CO-SINTONÍA (con filtro nítido conviene/se tolera MÁS diversidad; sin filtro, MENOS), NO un "
               "óptimo global de 'conf+high'. Además conf-alloc SOLA (sin la guardia de diversidad de CYCLE 94) narrows y "
               "por eso pierde a random_low -- el filtro 'bueno' COMPLETO incluiría la guardia. Otros caveats: 2 niveles "
               "de temperatura (no barrido fino); modelo tiny, tarea sembrada, {n} seeds, CPU; presupuesto por "
               "conteo.").format(V=status.upper(), cte=_f(cte), rte=_f(rte), it=_f(it), pf=pf, csc=_f(csc), n=n_seeds)

    hyp = Hypothesis(
        id="H-V4-8o",
        statement=("La diversidad del generador (temperatura) y la calidad de la asignación son COMPLEMENTARIAS: subir la "
                   "diversidad paga (o daña menos) más bajo buena asignación (el filtro la aprovecha) que bajo asignación "
                   "pobre (interacción temp×alloc positiva); R-VALOR gobierna cuánta exploración del generador conviene."),
        prediction=("APOYADA si INTERACCIÓN=(conf_high−conf_low)−(random_high−random_low) > 0.02 y positiva en la mayoría "
                    "de los seeds; REFUTADA si interacción ≈ 0; MIXTA si inconsistente por seed. (Pre-registrada, lazo "
                    "real exp018, 2×2, 4 seeds.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp094_gen_alloc_interaction")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-8o")
        notes.append("H-V4-8o marcada '{}' con DoD completo (interacción generación×asignación).".format(status))

    analogy = AnalogyRecord(
        problem=("Tengo dos perillas: cuánta VARIEDAD de ideas genero (lluvia de ideas amplia o conservadora) y qué tan "
                 "bien ELIJO cuáles probar (un buen jurado o al azar). ¿Conviene generar más variedad cuando tengo buen "
                 "jurado, o da igual?"),
        everyday=("Conviene MÁS variedad cuando tengo buen jurado: el jurado pesca las ideas buenas que la variedad "
                  "produce y tira el resto, así que la lluvia de ideas amplia paga. Si elijo al azar, generar más "
                  "variedad me HUNDE -- termino probando (y aprendiendo de) puras ideas malas sin filtro. Las dos "
                  "perillas se potencian: un buen jurado HABILITA ser más creativo; sin jurado, la creatividad es "
                  "ruido."),
        solutions=["buena asignación (jurado) + alta diversidad: paga (el filtro aprovecha la exploración)",
                   "asignación al azar + alta diversidad: hunde (entreno en basura sin filtrar)",
                   "la interacción es positiva -> diversidad y selección son COMPLEMENTARIAS",
                   "R-VALOR (la política de asignación) gobierna cuánta exploración del generador conviene"],
        principles=["el valor de la diversidad del generador depende de la calidad del SELECTOR/filtro",
                    "con buena asignación conviene MÁS exploración; con asignación pobre, menos",
                    "generación y selección son complementarias (interacción positiva)",
                    "puente a creatividad (pillar #4): la creatividad sólo paga si hay un buen juez que la filtre"],
        adaptation=("El lab ABRE la palanca de GENERACIÓN junto a la de asignación: la política R-VALOR no sólo decide qué "
                    "verificar, también determina cuánta DIVERSIDAD del generador conviene. Con buena asignación, subir la "
                    "exploración del generador paga (el filtro la aprovecha); con asignación pobre, daña. Política del "
                    "lazo: co-sintonizar diversidad del generador y calidad del filtro (más filtro -> más diversidad). "
                    "Bridge a creatividad (pillar #4). Próximo: barrido fino de la temperatura para el óptimo bajo cada "
                    "asignación; diversidad como objetivo explícito del generador; y SCALE."),
        measurement=("exp094 ({n} seeds, lazo real): efecto-temp conf={cte} vs random={rte} -> interacción=+{it} ({pf:.0%} "
                     "seeds positiva).").format(n=n_seeds, cte=_f(cte), rte=_f(rte), it=_f(it), pf=pf),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (dos perillas: variedad de ideas × calidad del jurado; se potencian).")

    kl = ("REAL (exp094): la diversidad del generador y la calidad de la asignación son COMPLEMENTARIAS en el lazo cerrado "
          "real -- subir la temperatura del generador rinde {cte} en el downstream bajo conf-alloc vs {rte} bajo "
          "random-alloc (interacción +{it}, {pf:.0%} seeds positiva). Con buena asignación conviene MÁS exploración; con "
          "asignación pobre la diversidad mete basura. TECHO: el MEJOR config absoluto es RANDOM+LOW (pool limpio+diverso) "
          "-> 'más diversidad mejor' no es incondicional; la afirmación robusta es la INTERACCIÓN/co-sintonía, no un "
          "óptimo global. conf-alloc SOLA narrows (CYCLE 93/94) y por eso parte de su ganancia con diversidad es destrabar "
          "su propio narrowing; el filtro 'bueno' completo incluiría la guardia de diversidad (94). 2 niveles de "
          "temperatura; presupuesto por conteo; tarea sembrada, {n} seeds, CPU.").format(
              cte=_f(cte), rte=_f(rte), it=_f(it), pf=pf, n=n_seeds)
    ceilings.add(CeilingRecord(
        subsystem="Generación↔asignación — diversidad del generador y calidad de la asignación COMPLEMENTARIAS (buena selección habilita más exploración); puente a creatividad pillar #4",
        known_limit=kl,
        blockers=[{"text": "2 niveles de temperatura (low/high), no un barrido fino -> se mide el SIGNO de la interacción, no el óptimo absoluto de diversidad bajo cada asignación", "kind": "diseno"},
                  {"text": "el MEJOR config absoluto es RANDOM+LOW (pool limpio y diverso), NO conf+high -> 'más diversidad mejor' es FALSO incondicionalmente; lo robusto es el SIGNO de la interacción/co-sintonía. conf-alloc SOLA narrows (CYCLE 93/94), así que parte de su ganancia con diversidad es destrabar su propio narrowing; el filtro completo incluiría la guardia de diversidad (94)", "kind": "diseno"},
                  {"text": "presupuesto de verificación por CONTEO (no costo); tarea de síntesis sembrada, 4 seeds, CPU; barrido del óptimo, diversidad como objetivo explícito y SCALE pendientes", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP094.ref, S_ARC.ref]))
    notes.append("1 techo 'real': generación y asignación complementarias (buena selección habilita más exploración del generador).")

    dstmt = ("North-Star R-VALOR (PIVOT generación↔asignación; bridge a creatividad pillar #4): la diversidad del "
             "generador (temperatura) y la calidad de la asignación son COMPLEMENTARIAS -- subir la diversidad paga (o "
             "daña menos) MÁS bajo buena asignación (el filtro la aprovecha) que bajo asignación pobre (interacción "
             "temp×alloc positiva en el lazo real). Decisión: R-VALOR (la política de asignación) gobierna cuánta "
             "EXPLORACIÓN del generador conviene; co-sintonizar diversidad-del-generador y calidad-del-filtro (más filtro "
             "-> más diversidad). Conecta el lazo de auto-mejora (93-107) con la creatividad (pillar #4): la creatividad "
             "sólo paga si hay un buen juez que la filtre. Próximo: barrido fino del óptimo de temperatura por "
             "asignación; diversidad como objetivo explícito; y SCALE.")
    drat = ("exp094 (tier5, propio, {n} seeds, PyTorch CPU, lazo real exp018): efecto-temp conf={cte} vs random={rte} -> "
            "interacción=+{it} ({pf:.0%} seeds positiva). Convergente con el principio exploración×calidad-del-filtro "
            "(tier2) y con el arco que asignó sobre pool dado (tier5). APOYADA la complementariedad.").format(
                n=n_seeds, cte=_f(cte), rte=_f(rte), it=_f(it), pf=pf)
    dec = Decision(id="D-V4-72", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP094), _to_plain(S_ARC)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-72 ACEPTADA por el ledger (tier5 exp094 + tier5 exp091).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-72:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle110_gen_alloc_interaction',
                                description='CYCLE 110 (RESET v4, H-V4-8o: diversidad del generador y calidad de asignación COMPLEMENTARIAS -- APOYADA; bridge a creatividad).')
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
    print("RESUMEN — CYCLE 110 (RESET v4): diversidad del generador y calidad de asignación COMPLEMENTARIAS (H-V4-8o)")
    print("=" * 78)
    print("veredicto H-V4-8o:", status.upper() if status else "?")
    print("  con buena asignación conviene MÁS exploración del generador (el filtro la aprovecha); con asignación pobre, la diversidad daña.")
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
