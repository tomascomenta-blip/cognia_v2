r"""
cycle97_nonstationary_value.py — CICLO 97 (RESET v4, rama R-VALOR, sintetiza el arco allocation 83-96 + el arco forgetting
58-74): H-V4-8c por las compuertas del engine. APOYADA: bajo no-estacionariedad (drift de la estructura del valor) el
combinador R-VALOR de asignación DEBE OLVIDAR (decay) -- el full-history se vuelve STALE (mezcla fases) y FALLA, el decay
RASTREA (≈ oracle); bajo estacionario coinciden (el decay no cuesta). Mismo crossover que CYCLE 73 (memoria), ahora en la
ASIGNACIÓN: el estimador de valor (qué vale) y el olvido (cuándo dejó de valer) son la misma señal en dos tiempos también
aquí.

DERIVA de exp081_nonstationary_value/results/results.json.

Correr (DESPUÉS de exp081):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp081_nonstationary_value.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle97_nonstationary_value
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle97_nonstationary_value')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp081_nonstationary_value', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="concept drift / aprendizaje no-estacionario: un estimador con ventana/decay rastrea una distribución que cambia; la memoria-de-toda-la-historia se vuelve un promedio stale (sesgo por mezcla de regímenes)", obtained=False,
                     claim=("Bajo concept drift, un estimador ponderado por recencia (decay/ventana) rastrea la "
                            "distribución actual; ajustar sobre TODA la historia mezcla regímenes -> promedio stale "
                            "sesgado. Es el mismo principio que el lab ya estableció para la MEMORIA (CYCLE 73: crossover "
                            "full/decay; 74: selector no-regret). (Principio.)"))
S_ARC = Source(tier=5, ref="cognia_x/experiments/exp073_real_verifier_value", obtained=True,
               claim=("El arco de ASIGNACIÓN R-VALOR (83-96, combinador ridge poly2 + allocation, incl. el lazo cerrado "
                      "93-96) SIEMPRE asumió valor ESTACIONARIO. El arco de FORGETTING (58-74) mostró para la MEMORIA que "
                      "el estimador debe olvidar bajo drift. H-V4-8c une ambos en la asignación."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp081 primero): " + results_path)

    dg = sm['drift_gain']
    sc = sm['stat_cost']
    fd = sm['full_degrades']
    og = sm['decay_oracle_gap_drift']
    g = sm['grid']
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim081 = ("exp081 (propio, {n} seeds, numpy): bajo DRIFT decay={dd} >> full_history={df} (+{dg}; el full cae −{fd} "
                "del estacionario, stale por mezcla de fases; decay ≈ oracle, gap {og}); bajo ESTACIONARIO full={fs} >= "
                "decay={ds} (costo de olvidar {sc}). El combinador de asignación debe olvidar bajo no-estacionariedad.").format(
                    n=n_seeds, dd=_f(g['drift']['decay']), df=_f(g['drift']['full_history']), dg=_f(dg), fd=_f(fd),
                    og=_f(og), fs=_f(g['stationary']['full_history']), ds=_f(g['stationary']['decay']), sc=_f(sc))
    S_EXP081 = Source(tier=5, ref="cognia_x/experiments/exp081_nonstationary_value", obtained=True, claim=claim081)
    for src in (S_PRINCIPLE, S_ARC, S_EXP081):
        ledger.add_source(src)
    notes.append("3 fuentes (S_PRINCIPLE tier2 concept-drift/recencia; S_ARC tier5 suposición estacionaria del arco allocation; S_EXP081 tier5 dato propio).")

    ev_for = [S_EXP081.ref]
    ev_against = [S_EXP081.ref, S_ARC.ref, S_PRINCIPLE.ref]
    advtext = ("{V} (sintetiza el arco ALLOCATION 83-96 + el arco FORGETTING 58-74): todo el arco de asignación R-VALOR "
               "(83-96, combinador ridge poly2 + allocation, incl. el lazo cerrado real 93-96) asumió que la estructura "
               "del valor es ESTACIONARIA. El valor REAL deriva (lo que vale la pena cambia). H-V4-8c testea si el "
               "combinador de asignación debe OLVIDAR. Valor = bump gaussiano cuyo centro se MUEVE cada D rondas (drift) "
               "vs fijo (estacionario); el agente ajusta un ridge poly2 sobre la experiencia observada y rankea. "
               "RESULTADO (crossover): bajo DRIFT el decay (pesos por recencia) RASTREA y el full-history FALLA -- "
               "decay={dd} >> full={df} (+{dg}); el full se vuelve STALE (mezcla bumps de fases distintas: cae de {fs} "
               "estacionario a {df} con drift, −{fd}); el decay queda ≈ oracle (gap {og}). Bajo ESTACIONARIO full={fs} >= "
               "decay={ds} (el decay paga un costo mínimo de olvidar, {sc}). => UNIFICA el arco de ASIGNACIÓN con el de "
               "FORGETTING: el estimador de valor (qué vale, R-VALOR) y el olvido (cuándo dejó de valer) son la MISMA "
               "señal en dos tiempos también para la ASIGNACIÓN, no sólo para la memoria (CYCLE 73). Replica el crossover "
               "full/decay de CYCLE 73 en el combinador de allocation. EVIDENCIA EN CONTRA / caveats HONESTOS: decay FIJO "
               "(0.8; el óptimo depende de la tasa de drift -> el selector no-regret de CYCLE 74 sería el cierre); valor "
               "bump sintético nesteable por poly2, feedback observado al azar (insesgado, no action-gated); drift "
               "abrupto por fases (no gradual); numpy/juguete. El decay no alcanza el oracle bajo drift (gap {og}: hay un "
               "lag de re-aprendizaje tras cada cambio).").format(
                   V=status.upper(), dd=_f(g['drift']['decay']), df=_f(g['drift']['full_history']), dg=_f(dg),
                   fs=_f(g['stationary']['full_history']), fd=_f(fd), og=_f(og), ds=_f(g['stationary']['decay']), sc=_f(sc))

    hyp = Hypothesis(
        id="H-V4-8c",
        statement=("Bajo no-estacionariedad (drift de la estructura del valor) el combinador R-VALOR de ASIGNACIÓN debe "
                   "OLVIDAR (decay/recencia): el full-history se vuelve stale y falla, el decay rastrea; bajo estacionario "
                   "coinciden. Unifica el arco de asignación (83-96) con el de forgetting (58-74)."),
        prediction=("APOYADA si bajo drift decay > full (+>0.05) Y bajo estacionario full >= decay (−0.03); REFUTADA si "
                    "bajo drift decay ≈ full; MIXTA en otro caso. (Pre-registrada, numpy, 48 seeds, crossover.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp081_nonstationary_value")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-8c")
        notes.append("H-V4-8c marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("Aprendí qué barrio tiene las mejores ofertas y siempre voy ahí. Pero las ofertas se MUDAN de barrio "
                 "cada tanto. ¿Me guío por TODO lo que vi en años o por lo RECIENTE?"),
        everyday=("Por lo reciente. Si promedio años, mi 'mapa de ofertas' mezcla barrios que ya no sirven -> me manda "
                  "a donde antes era bueno. Pesar lo reciente (olvidar lo viejo) me lleva al barrio bueno de AHORA. "
                  "Cuando las ofertas NO se mudan (estable), recordar todo no me cuesta nada y hasta afina un poco. El "
                  "olvido sólo paga cuando el mundo cambia."),
        solutions=["pesar por recencia (decay): rastrea dónde está el valor AHORA bajo drift",
                   "promediar toda la historia (full): stale bajo drift (mezcla regímenes)",
                   "bajo estable, full ≈ decay (recordar todo no cuesta)",
                   "decay FIJO no es óptimo a toda tasa de drift -> selector de tasa (CYCLE 74)"],
        principles=["bajo drift el estimador de valor debe DESCONTAR lo viejo (recencia), igual que la memoria (CYCLE 73)",
                    "ajustar sobre toda la historia mezcla regímenes -> promedio stale sesgado",
                    "qué vale (R-VALOR) y cuándo dejó de valer (olvido) son la misma señal en dos tiempos",
                    "el olvido sólo paga bajo no-estacionariedad; bajo estable, recordar todo iguala o gana"],
        adaptation=("El lab UNIFICA asignación y memoria: el combinador R-VALOR de ASIGNACIÓN debe olvidar (decay) bajo "
                    "drift de la estructura del valor, igual que el estimador de MEMORIA (CYCLE 73). En el lazo de "
                    "auto-mejora real (93-96), si lo que el modelo puede resolver / lo que vale verificar DERIVA, el "
                    "combinador de confianza/cobertura debe descontar la experiencia vieja. Próximo: selector de tasa de "
                    "olvido no-regret (reusar CYCLE 74) sobre el combinador de asignación; drift gradual; integrar con el "
                    "lazo cerrado real; y SCALE."),
        measurement=("exp081 ({n} seeds): drift decay={dd} >> full={df} (+{dg}, full cae −{fd}); estacionario full={fs} >= "
                     "decay={ds} (costo {sc}); decay gap oracle bajo drift {og}.").format(
                         n=n_seeds, dd=_f(g['drift']['decay']), df=_f(g['drift']['full_history']), dg=_f(dg), fd=_f(fd),
                         fs=_f(g['stationary']['full_history']), ds=_f(g['stationary']['decay']), sc=_f(sc), og=_f(og)),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (las ofertas se mudan de barrio: guiarse por lo reciente, no por años).")

    kl = ("REAL (exp081): bajo no-estacionariedad (drift de la estructura del valor) el combinador R-VALOR de asignación "
          "DEBE OLVIDAR -- decay={dd} >> full_history={df} bajo drift (+{dg}; el full stale cae −{fd}); bajo estacionario "
          "coinciden (full={fs} >= decay={ds}, costo {sc}). Unifica asignación (83-96) y forgetting (58-74). TECHO: decay "
          "FIJO (óptimo depende de la tasa de drift -> selector CYCLE 74); valor bump sintético; feedback al azar; drift "
          "abrupto; el decay no alcanza el oracle bajo drift (lag de re-aprendizaje, gap {og}).").format(
              dd=_f(g['drift']['decay']), df=_f(g['drift']['full_history']), dg=_f(dg), fd=_f(fd),
              fs=_f(g['stationary']['full_history']), ds=_f(g['stationary']['decay']), sc=_f(sc), og=_f(og))
    ceilings.add(CeilingRecord(
        subsystem="R-VALOR bajo no-estacionariedad en la ASIGNACIÓN — el combinador debe olvidar (decay) bajo drift; full-history stale (unifica con forgetting 58-74)",
        known_limit=kl,
        blockers=[{"text": "decay FIJO (0.8); el óptimo depende de la tasa de drift -> el selector de tasa no-regret de CYCLE 74 sería el cierre (no aplicado aquí)", "kind": "diseno"},
                  {"text": "valor bump gaussiano sintético nesteable por poly2; feedback observado al azar (insesgado, no action-gated); drift abrupto por fases (no gradual)", "kind": "diseno"},
                  {"text": "el decay no alcanza el oracle bajo drift (lag de re-aprendizaje tras cada cambio); no se integró con el lazo cerrado real (93-96) ni con SCALE", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP081.ref, S_ARC.ref]))
    notes.append("1 techo 'real': el combinador de asignación debe olvidar bajo drift; unifica con el arco de forgetting (58-74).")

    dstmt = ("North-Star R-VALOR (unifica ASIGNACIÓN 83-96 + FORGETTING 58-74): bajo no-estacionariedad (drift de la "
             "estructura del valor) el combinador R-VALOR de ASIGNACIÓN debe OLVIDAR (decay/recencia) -- el full-history "
             "se vuelve stale y falla, el decay rastrea (≈ oracle); bajo estacionario coinciden. Decisión: el estimador "
             "de valor para asignar usa recencia (decay) cuando la estructura del valor puede derivar; qué vale (R-VALOR) "
             "y cuándo dejó de valer (olvido) son la misma señal en dos tiempos también para la asignación, no sólo para "
             "la memoria (replica el crossover de CYCLE 73). Próximo: selector de tasa de olvido no-regret (CYCLE 74) "
             "sobre el combinador; drift gradual; integrar con el lazo cerrado real; y SCALE.")
    drat = ("exp081 (tier5, propio, {n} seeds, numpy): drift decay={dd} >> full={df} (+{dg}); estacionario full={fs} >= "
            "decay={ds} (costo {sc}). Convergente con concept-drift/recencia (tier2) y con el crossover full/decay de la "
            "MEMORIA (CYCLE 73, tier5). APOYADA: el combinador de asignación debe olvidar bajo drift.").format(
                n=n_seeds, dd=_f(g['drift']['decay']), df=_f(g['drift']['full_history']), dg=_f(dg),
                fs=_f(g['stationary']['full_history']), ds=_f(g['stationary']['decay']), sc=_f(sc))
    dec = Decision(id="D-V4-59", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP081), _to_plain(S_ARC)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-59 ACEPTADA por el ledger (tier5 exp081 + tier5 exp073).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-59:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle97_nonstationary_value',
                                description='CYCLE 97 (RESET v4, H-V4-8c: el combinador R-VALOR de asignación debe olvidar bajo drift -- APOYADA; unifica allocation + forgetting).')
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
    print("RESUMEN — CYCLE 97 (RESET v4): el combinador R-VALOR de asignación debe OLVIDAR bajo drift (H-V4-8c) — unifica allocation + forgetting")
    print("=" * 78)
    print("veredicto H-V4-8c:", status.upper() if status else "?")
    print("  crossover: bajo drift decay >> full (stale); bajo estacionario coinciden. Qué vale + cuándo dejó de valer = misma señal.")
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
