r"""
cycle30_noisy_verifier.py — CICLO 30 a través del Investigation Engine (frente F-LEARN-2).

H-LEARN-2: la auto-mejora verificada (H-LEARN-1, CYCLE 29) DECAE al subir el ruido de FALSO POSITIVO del
verificador (acepta generaciones incorrectas); sobrevive hasta un umbral eps* y colapsa hacia el régimen
naive (eps=1). Con VOLUMEN y PASOS fijos (submuestreo a N fijo), la única variable es la CONTAMINACIÓN del
set de entrenamiento -> mide la robustez de la auto-mejora a la CALIDAD del verificador (puente hacia
verificadores reales, ruidosos/parciales).

DERIVA el veredicto de exp017_noisy_verifier/results/results.json (curva dosis-respuesta). Pasa por las
mismas compuertas (ledger, mark_*, ceiling, analogy, verify_no_loss).

Correr (DESPUÉS de exp017):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp017_noisy_verifier.run --seeds 0,1,2
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle30_noisy_verifier
"""
import argparse
import json
import os
import shutil
import sys

from cognia_x.research.schema import Source, Hypothesis, Decision, AnalogyRecord, CeilingRecord
from cognia_x.research.ledger import EvidenceLedger, OpinionOnlyError
from cognia_x.research.hypotheses import HypothesisRegistry
from cognia_x.research.analogy import extract_principles
from cognia_x.research.ceiling import CeilingTracker
from cognia_x.research.record import PermanentRecord

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle30_noisy_verifier')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp017_noisy_verifier', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


S1 = Source(tier=1, ref="arXiv:2203.14465", obtained=True,
            claim=("Zelikman et al. 2022 (STaR): el bootstrapping auto-supervisado depende del FILTRO por "
                   "corrección; si el filtro deja pasar soluciones incorrectas, la señal se degrada."))
S2 = Source(tier=1, ref="arXiv:2305.17493", obtained=True,
            claim=("Shumailov et al. 2024 (model collapse): entrenar con datos auto-generados CONTAMINADOS "
                   "(incorrectos) degrada el modelo; un verificador con falsos-positivos reintroduce ese riesgo."))


def _fmt(x):
    return "{:.3f}".format(x) if isinstance(x, (int, float)) else str(x)


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if 'summary' not in data:
        raise SystemExit("results.json sin 'summary' (corré exp017 primero): " + results_path)
    s = data['summary']
    ledger, hyps, ceilings, record = EvidenceLedger(store), HypothesisRegistry(store), CeilingTracker(store), PermanentRecord(store)
    notes = []
    status = s.get('status')
    net = s.get('net_by_eps_mean', {})
    eps_star = s.get('eps_star')
    net_txt = ", ".join("eps{}={}".format(k, _fmt(v)) for k, v in net.items())

    S3 = Source(tier=5, ref="cognia_x/experiments/exp017_noisy_verifier", obtained=True,
                claim=("exp017 (dosis-respuesta, suma byte-level, modelo tiny, test held-out DISJUNTO, "
                       "{seeds} seeds, VOLUMEN+pasos FIJOS -> sólo varía la contaminación): net-sobre-base de "
                       "verified vs eps(falso-positivo): {net}. decae={dec}, eps*={es}. {verdict}").format(
                           seeds=len(data.get('per_seed', [])), net=net_txt, dec=s.get('decays'),
                           es=eps_star, verdict=s.get('verdict', '')))
    for src in (S1, S2, S3):
        ledger.add_source(src)
    notes.append("3 fuentes (S1 tier1 STaR; S2 tier1 collapse/contaminación; S3 tier5 exp017).")

    if status == 'apoyada':
        ev_for, ev_against = [S1.ref, S3.ref], [S2.ref]
        adv = ("APOYADA: la auto-mejora DECAE con el ruido del verificador ({net}); sobrevive hasta eps*={es} "
               "y colapsa hacia naive al subir el falso-positivo. Con volumen+pasos FIJOS la única variable es "
               "la CONTAMINACIÓN -> confirma que la CALIDAD del verificador (su corrección) es el motor (refuerza "
               "H-LEARN-1). Implicación: un verificador real necesita FP-rate < eps* para habilitar auto-mejora. "
               "CAVEAT: escala tiny; eps* es específico de esta tarea/escala.").format(net=net_txt, es=eps_star)
    elif status == 'refutada':
        ev_for, ev_against = [S2.ref], [S3.ref]
        adv = ("REFUTADA: la curva NO decae con eps ({net}) -> el ruido del verificador no cambia el resultado "
               "a esta escala; tensión con H-LEARN-1 (si el filtro no importa, no era el motor). Revisar.").format(net=net_txt)
    elif status == 'mixta':
        ev_for, ev_against = [S1.ref], [S3.ref, S2.ref]
        adv = ("MIXTA: decae pero débil (no supera 2σ); señal de dosis-respuesta ambigua a esta escala ({net}).").format(net=net_txt)
    else:
        ev_for, ev_against = [S1.ref], [S3.ref]
        adv = ("INCONCLUSO: {verdict}").format(verdict=s.get('verdict', ''))

    hyp = Hypothesis(
        id="H-LEARN-2",
        statement=("La auto-mejora verificada DECAE al subir el ruido de FALSO POSITIVO del verificador "
                   "(acepta incorrectas); sobrevive hasta un umbral eps* y colapsa hacia naive. Con "
                   "volumen+pasos fijos, la única variable es la contaminación -> mide robustez a la calidad del verificador."),
        prediction=("net-sobre-base de verified decae monótono-ish con eps; net(eps=0) > net(eps=1) por > 2σ; "
                    "existe eps*>0 con net>0 consistente. Refutado si la curva es plana en eps."),
        status='abierta', confidence='media', evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=adv, experiment_ref="exp017_noisy_verifier")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-LEARN-2")
        notes.append("H-LEARN-2 marcada '{}' con DoD completo.".format(status))
    else:
        notes.append("H-LEARN-2 queda 'abierta' (inconcluso).")

    analogy = AnalogyRecord(
        problem=("Si el solucionario contra el que verificas tus ejercicios tiene ERRORES (acepta respuestas "
                 "incorrectas), ¿hasta cuánto error tolera tu auto-estudio antes de empeorar?"),
        everyday=("Estudiar con un solucionario un poco erróneo aún ayuda; con uno muy erróneo aprendes "
                  "errores (igual que no filtrar). Hay un umbral de calidad del solucionario."),
        solutions=["solucionario perfecto (eps=0) -> máxima auto-mejora",
                   "solucionario con pocos errores (eps chico) -> aún mejora (hasta eps*)",
                   "solucionario muy erróneo (eps grande) -> colapsa hacia estudiar-todo (naive)",
                   "medir la curva con volumen FIJO para aislar 'errores' de 'más ejercicios'"],
        principles=["la CALIDAD del verificador, no solo su existencia, gobierna la auto-mejora",
                    "hay un umbral de ruido (eps*) bajo el cual la auto-mejora sobrevive",
                    "controlar el volumen aísla la contaminación como la variable causal"],
        adaptation=("H-LEARN-2 {}: define el presupuesto de ruido (eps*) que un verificador real debe cumplir "
                    "para habilitar auto-mejora.").format(status),
        measurement="exp017: net vs eps = {} (eps*={}).".format(net_txt, eps_star), iterations=1)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada.")

    ro = "asumido"
    ceilings.add(CeilingRecord(
        subsystem="Robustez de la auto-mejora verificada al ruido del verificador (F-LEARN-2)",
        known_limit=("exp017: la auto-mejora tolera ruido del verificador hasta eps*={} (FP-rate); por encima "
                     "colapsa hacia naive. Un verificador real (código→sandbox, hechos→≥2 fuentes) debe tener "
                     "FP-rate < eps* para habilitar auto-mejora. Específico de tarea/escala (tiny). {}").format(
                         eps_star, "" if status == 'apoyada' else "Veredicto: " + str(status)),
        blockers=[{"text": "verificador con FP-rate > eps* reintroduce el colapso (contaminación)", "kind": "diseno"}],
        real_or_assumed=ro, evidence=[S1.ref, S2.ref, S3.ref]))
    notes.append("1 techo '{}' (presupuesto de ruido eps* del verificador).".format(ro))

    if status == 'apoyada':
        dstmt = ("La CALIDAD del verificador es un lever de primera clase: la auto-mejora verificada tolera "
                 "ruido hasta eps*={}, por encima colapsa. Al elegir verificadores reales para Cognia-X, exigir "
                 "FP-rate < eps* (o subir N/diversidad para compensar).").format(eps_star)
        drat = ("exp017 (volumen+pasos fijos): net-sobre-base decae con el FP-rate ({}); eps*={}.").format(net_txt, eps_star)
    else:
        dstmt = ("NO concluir sobre el presupuesto de ruido del verificador aún: exp017 status={} a esta escala.").format(status)
        drat = s.get('verdict', '')
    dec = Decision(id="D-LEARN-2", statement=dstmt, rationale=drat, sources=[_to_plain(S3), _to_plain(S1)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-LEARN-2 ACEPTADA por el ledger (tier5 S3 + tier1 S1).")
    except OpinionOnlyError as e:
        print("ERROR ledger D-LEARN-2:", e); raise

    return ledger, hyps, ceilings, record, notes, status, s


def _to_plain(obj):
    from cognia_x.research.schema import to_dict
    import dataclasses
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle30_noisy_verifier',
                                description='CYCLE 30 (H-LEARN-2: robustez al ruido del verificador).')
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
    print("RESUMEN — CYCLE 30: robustez de la auto-mejora al ruido del verificador (H-LEARN-2)")
    print("=" * 78)
    print("veredicto H-LEARN-2:", status.upper() if status else "?")
    print("  " + s.get('verdict', ''))
    print("")
    for n in notes:
        print("  CHECK ", n)
    print("")
    from cognia_x.research.record import count_lines
    for name in ('sources', 'hypotheses', 'analogies', 'ceilings', 'decisions'):
        print("  {:<12}: {}".format(name, count_lines(record.store_path(name))))
    print("  verify_no_loss =", "OK" if res['ok'] else "FAIL")
    print("=" * 78)
    return 0 if res['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
