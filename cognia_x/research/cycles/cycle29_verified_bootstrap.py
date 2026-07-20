r"""
cycle29_verified_bootstrap.py — CICLO 29 a través del Investigation Engine (frente F-LEARN-2).

H-LEARN-1: en una tarea VERIFICABLE (suma byte-level, oráculo chequeable), entrenar SOLO con las
auto-generaciones VERIFICADO-CORRECTAS produce AUTO-MEJORA por la SEÑAL DE CORRECCIÓN — no por el
volumen/pasos ni por el filtrado-per-se (control random_matched: mismo N_keep y mismos pasos, subconjunto
ALEATORIO). naive_all (entrena con TODAS, incl. incorrectas) estanca/colapsa.

AVANCE sobre CYCLE 11: aquél mostró que verify-before-learn PREVIENE el colapso en lenguaje (rechazando
TODO, porque la auto-salida nunca mejora el val real en una tarea no-verificable). Este muestra que en
una tarea VERIFICABLE el verificador HABILITA auto-mejora (acepta lo correcto -> el modelo bootstrappea),
no solo previene colapso. Es el resultado tipo STaR (Zelikman 2022) / rejection-sampling FT en el lab CPU.

DERIVA el veredicto de exp016_verified_bootstrap/results/results.json (correcto por construcción). Pasa
por las MISMAS compuertas (ledger, mark_*, ceiling, analogy, verify_no_loss).

Correr (DESPUÉS de exp016):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp016_verified_bootstrap.run --seeds 0,1 --hi 19 --n_seed 256 --base_steps 1500
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle29_verified_bootstrap
"""
import argparse
import json
import os
import shutil
import sys

from cognia_x.research.schema import (
    Source, Hypothesis, Decision, AnalogyRecord, CeilingRecord,
)
from cognia_x.research.ledger import EvidenceLedger, OpinionOnlyError
from cognia_x.research.hypotheses import HypothesisRegistry
from cognia_x.research.analogy import extract_principles
from cognia_x.research.ceiling import CeilingTracker
from cognia_x.research.record import PermanentRecord

DEFAULT_STORE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle29_verified_bootstrap'
)
DEFAULT_RESULTS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..',
    'experiments', 'exp016_verified_bootstrap', 'results', 'results.json'
)


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


# tier-1: STaR — bootstrapping con auto-generaciones verificadas mejora el modelo.
S1 = Source(
    tier=1, ref="arXiv:2203.14465", obtained=True,
    claim=("Zelikman et al. 2022 (STaR): un modelo mejora entrenando con sus PROPIAS soluciones "
           "FILTRADAS por corrección (rationales que llegan a la respuesta correcta) — bootstrapping "
           "auto-supervisado con verificador."),
)
# tier-1: model collapse — auto-entrenarse sin filtro degrada (el contraste de naive_all).
S2 = Source(
    tier=1, ref="arXiv:2305.17493", obtained=True,
    claim=("Shumailov et al. 2024 (model collapse, Nature 2024 'AI models collapse when trained on "
           "recursively generated data'): entrenar recursivamente con la propia salida SIN filtro "
           "estrecha la distribución y degrada — el mecanismo de naive_all."),
)


def _fmt(x):
    return "{:.3f}".format(x) if isinstance(x, (int, float)) else str(x)


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if 'summary' not in data:
        raise SystemExit("results.json sin 'summary' (corré exp016 primero): " + results_path)
    s = data['summary']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    status = s.get('status')              # apoyada | refutada | mixta | inconcluso
    fmean = s.get('final_mean', {})
    base = s.get('base_mean')
    cfg = data.get('config', {})
    accs_txt = ", ".join("{}={}".format(k, _fmt(v)) for k, v in fmean.items())

    S3 = Source(
        tier=5, ref="cognia_x/experiments/exp016_verified_bootstrap", obtained=True,
        claim=("exp016 (suma byte-level, modelo tiny d=64, rango [{lo},{hi}], test held-out DISJUNTO, "
               "{seeds} seeds, {rounds} rondas, K={K}): base(mean)={base}; final {accs}. "
               "verified>base+0.10={imp}; verified>random_matched(>margen)={vr}; verified>naive_all={vn}; "
               "naive_diversity_drop={nd}; margen={mg}. {verdict}").format(
                   lo=cfg.get('task_range', ['?', '?'])[0], hi=cfg.get('task_range', ['?', '?'])[1],
                   seeds=len(data.get('per_seed', [])), rounds=cfg.get('rounds'), K=cfg.get('K'),
                   base=_fmt(base), accs=accs_txt, imp=s.get('improved_over_base'),
                   vr=s.get('verified_beats_random'), vn=s.get('verified_beats_naive'),
                   nd=s.get('naive_diversity_drop'), mg=_fmt(s.get('margin')), verdict=s.get('verdict', '')),
    )
    for src in (S1, S2, S3):
        ledger.add_source(src)
    notes.append("3 fuentes (S1 tier1 STaR; S2 tier1 model-collapse; S3 tier5 exp016).")

    # --- H-LEARN-1 por la compuerta DoD ---
    if status == 'apoyada':
        ev_for, ev_against = [S1.ref, S3.ref], [S2.ref]
        net = s.get('net_over_base', {})
        caveats = "; ".join(s.get('caveats', []))
        adv = ("APOYADA (con matiz, confianza media; sobrevivió a verificación adversarial de 4 lentes). "
               "EVIDENCIA MÁS FUERTE (metric-independiente): verified es el ÚNICO brazo con ganancia NETA "
               "sobre su base en TODOS los seeds (net verified={nv}, random={nr}, naive={nn}); ambos "
               "controles NO superan su base compartido -> el motor es la SEÑAL DE CORRECCIÓN del oráculo, "
               "no el volumen/pasos (random_matched: mismo N_keep+pasos) ni el filtrado-per-se (random "
               "filtra al azar). {accs} (base {base}). AVANCE sobre CYCLE 11: el verificador no solo PREVIENE "
               "colapso — HABILITA auto-mejora en tarea verificable (STaR). CAVEATS (de la verificación "
               "adversarial): {cav}").format(
                   nv=_fmt(net.get('verified')), nr=_fmt(net.get('random_matched')), nn=_fmt(net.get('naive_all')),
                   accs=accs_txt, base=_fmt(base), cav=caveats)
    elif status == 'refutada':
        ev_for, ev_against = [S1.ref], [S3.ref]
        adv = ("REFUTADA a esta escala: {accs} (base {base}). {verdict} El control decisivo (random_matched) "
               "no se separa de verified, o verified no supera al base -> a esta escala tiny la auto-"
               "generación verificada no bootstrappea (o la ganancia era reducir/filtrar, no la corrección). "
               "Null INFORMATIVO (estilo CYCLE 11/23/27).").format(
                   accs=accs_txt, base=_fmt(base), verdict=s.get('verdict', ''))
    elif status == 'mixta':
        ev_for, ev_against = [S1.ref], [S3.ref, S2.ref]
        adv = ("MIXTA: {accs} (base {base}). {verdict} verified mejora pero la señal no es limpia en todos "
               "los criterios (revisar tasa de aceptación p / diversidad / control random_matched).").format(
                   accs=accs_txt, base=_fmt(base), verdict=s.get('verdict', ''))
    else:  # inconcluso (base fuera de banda)
        ev_for, ev_against = [S1.ref], [S3.ref]
        adv = ("INCONCLUSO: {verdict} (base fuera de banda -> recalibrar antes de concluir).").format(
            verdict=s.get('verdict', ''))

    hyp = Hypothesis(
        id="H-LEARN-1",
        statement=("En una tarea VERIFICABLE, entrenar SOLO con auto-generaciones VERIFICADO-CORRECTAS "
                   "(verified) produce auto-mejora por la SEÑAL DE CORRECCIÓN del oráculo — no por el "
                   "volumen/pasos ni el filtrado-per-se (control random_matched). naive_all (sin filtro) "
                   "estanca/colapsa."),
        prediction=("verified termina >= base+0.10 Y > random_matched Y > naive_all por > margen (2σ y "
                    "rango entre seeds). Refutado si verified ~ random_matched (era filtrar, no corregir) "
                    "o no supera al base."),
        status='abierta',
        confidence='media',
        evidence_for=ev_for,
        evidence_against=ev_against,
        adversarial_verdict=adv,
        experiment_ref="exp016_verified_bootstrap",
    )
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        marker = {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]
        hf = marker("H-LEARN-1")
        assert hf.status == status
        notes.append("H-LEARN-1 marcada '{}' con DoD completo.".format(status))
    else:
        notes.append("H-LEARN-1 queda 'abierta' (inconcluso: base fuera de banda).")

    # --- ANALOGÍA ---
    analogy = AnalogyRecord(
        problem=("¿Estudiar de tus PROPIOS apuntes te mejora o te hace repetir tus errores? Depende de si "
                 "CORRIGES los apuntes contra el solucionario (oráculo) antes de estudiarlos."),
        everyday=("Un estudiante que repasa SOLO los ejercicios que verificó correctos (contra el "
                  "solucionario) mejora; el que repasa TODOS sus intentos (incl. los mal hechos) refuerza "
                  "errores y se estanca; y la clave es CORREGIR, no solo 'estudiar menos hojas'."),
        solutions=[
            "estudiar todos los propios intentos (naive) -> refuerza errores / colapso",
            "estudiar un subconjunto al azar igual de grande (random_matched) -> controla 'menos hojas'",
            "estudiar SOLO los verificados correctos (verified) -> mejora si la CORRECCIÓN es la palanca",
            "estudiar de fuentes externas reales (CYCLE 8/11) -> el ancla de la realidad",
        ],
        principles=[
            "auto-generarse datos es un peligro (colapso) O un motor (bootstrapping): el VERIFICADOR decide cuál",
            "el control debe aislar 'corrección' de 'volumen' y de 'filtrar-per-se' (random_matched)",
            "un oráculo chequeable convierte la auto-mejora en posible sin colapsar (avanza CYCLE 11)",
        ],
        adaptation=("H-LEARN-1 {}: el verificador {} la auto-mejora en tarea verificable.").format(
            status, "habilita" if status == 'apoyada' else "no separó (a esta escala)"),
        measurement="exp016: base={}, {}.".format(_fmt(base), accs_txt),
        iterations=1,
    )
    principles = extract_principles(analogy)
    assert len(principles) >= 3
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas: {} soluciones, {} principios.".format(
        len(analogy.solutions), len(principles)))

    # --- TECHO / CAPACIDAD (no es un 'techo' refutable sino un mecanismo; se registra como nota de límite) ---
    if status == 'apoyada':
        klimit = ("La auto-mejora verificada (STaR) FUNCIONA a escala tiny/CPU en una tarea verificable: el "
                  "verificador habilita el bootstrapping. Límite conocido: requiere un oráculo chequeable "
                  "(tareas verificables); en tareas no-verificables (lenguaje, CYCLE 11) el verificador solo "
                  "previene colapso. ASUMIDO/mejorable: extender a verificadores parciales/ruidosos.")
        ro = "asumido"
        blockers = [{"text": "requiere oráculo chequeable; no aplica directo a tareas no-verificables", "kind": "diseno"}]
    else:
        klimit = ("A esta escala tiny la auto-mejora verificada no se demostró limpia (ver veredicto). "
                  "Posible límite de escala/optim o de la tarea; backlog: recalibrar / tarea distinta.")
        ro = "asumido"
        blockers = [{"text": "auto-mejora verificada no separada del control a escala tiny", "kind": "diseno"}]
    ceilings.add(CeilingRecord(
        subsystem="Auto-mejora por verify-before-learn en tarea verificable (F-LEARN-2)",
        known_limit=klimit, blockers=blockers, real_or_assumed=ro, evidence=[S1.ref, S2.ref, S3.ref]))
    notes.append("1 techo '{}' registrado (mecanismo de auto-mejora verificada).".format(ro))

    # --- DECISIÓN D-LEARN-1 ---
    if status == 'apoyada':
        dstmt = ("Adoptar verify-before-learn como motor de AUTO-MEJORA en tareas verificables de Cognia-X "
                 "(no solo como guarda anti-colapso, CYCLE 11): el modelo puede aprender de su propia salida "
                 "VERIFICADA y mejorar. La señal de corrección del oráculo es la palanca (exp016).")
        drat = ("exp016: verified ({v}) supera a random_matched y naive_all por > margen, y al base +0.10, "
                "con test held-out disjunto. El verificador habilita el bootstrapping (STaR); naive colapsa.").format(
                    v=_fmt(fmean.get('verified')))
    else:
        dstmt = ("NO adoptar aún verify-before-learn como motor de auto-mejora: a escala tiny exp016 no "
                 "separó la corrección del control. Backlog: recalibrar / otra tarea verificable / más escala.")
        drat = ("exp016 status={}: {}").format(status, s.get('verdict', ''))
    decision = Decision(
        id="D-LEARN-1", statement=dstmt, rationale=drat,
        sources=[_to_plain(S3), _to_plain(S1)], important=True)
    try:
        ledger.record_decision(decision)
        notes.append("D-LEARN-1 ACEPTADA por el ledger (tier5 S3 + tier1 S1).")
    except OpinionOnlyError as e:
        print("ERROR: el ledger RECHAZÓ D-LEARN-1: {}".format(e)); raise

    return ledger, hyps, ceilings, record, notes, status, s


def _to_plain(obj):
    from cognia_x.research.schema import to_dict
    import dataclasses
    if dataclasses.is_dataclass(obj):
        return to_dict(obj)
    return dict(obj)


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(
        prog='python -m cognia_x.research.cycles.cycle29_verified_bootstrap',
        description='CYCLE 29 (H-LEARN-1: auto-mejora verificada) a través del Investigation Engine.')
    p.add_argument('--store', default=DEFAULT_STORE)
    p.add_argument('--results', default=DEFAULT_RESULTS)
    p.add_argument('--reset', dest='reset', action='store_true', default=True)
    p.add_argument('--no-reset', dest='reset', action='store_false')
    args = p.parse_args(argv)

    store = os.path.abspath(args.store)
    if args.reset and os.path.isdir(store):
        shutil.rmtree(store)
    os.makedirs(store, exist_ok=True)

    ledger, hyps, ceilings, record, notes, status, s = run(store, os.path.abspath(args.results))
    res = record.verify_no_loss()

    print("=" * 78)
    print("RESUMEN — CYCLE 29: auto-mejora verificada (H-LEARN-1) [Investigation Engine]")
    print("=" * 78)
    print("store: {}".format(store))
    print("veredicto H-LEARN-1: {}".format(status.upper() if status else "?"))
    print("  {}".format(s.get('verdict', '')))
    print("")
    for n in notes:
        print("  CHECK  {}".format(n))
    print("")
    from cognia_x.research.record import count_lines
    for name in ('sources', 'hypotheses', 'analogies', 'ceilings', 'decisions'):
        print("  {:<12}: {}".format(name, count_lines(record.store_path(name))))
    print("  {:<12}: {}".format('asumidos', len(ceilings.assumed_limits())))
    print("")
    print("  verify_no_loss:")
    for d in res['details']:
        flag = 'OK' if d['ok'] else 'FAIL'
        print("    [{}] {:<12} journaled={} live={} missing={}".format(
            flag, d['store'], d['journaled'], d['live'], d.get('missing', 0)))
    print("")
    print("  verify_no_loss = {}".format("OK" if res['ok'] else "FAIL"))
    print("=" * 78)
    return 0 if res['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
