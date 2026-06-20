r"""
cycle31_real_verifier.py — CICLO 31 a través del Investigation Engine (frente F-LEARN-2).

H-LEARN-3: la auto-mejora verificada (H-LEARN-1/2) generaliza de un oráculo de FORMA CERRADA a un
VERIFICADOR CHEQUEABLE REAL (un sandbox que EJECUTA la expresión generada por el modelo). Y un verificador
real DÉBIL se REWARD-HACKEA: el modelo aprende a emitir el target literal (echo "N", que evalúa a N pero no
computa), inflando la aceptación sin competencia real; el verificador FUERTE (exige un operador) lo bloquea.

DERIVA el veredicto de exp018_real_verifier/results/results.json (real_acc del verificador FUERTE en test
held-out + degenerate del brazo verified_weak). Pasa por las compuertas (ledger, mark_*, ceiling, analogy).

Correr (DESPUÉS de exp018):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp018_real_verifier.run --seeds 0,1,2
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle31_real_verifier
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle31_real_verifier')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp018_real_verifier', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


S1 = Source(tier=1, ref="arXiv:2203.14465", obtained=True,
            claim=("Zelikman et al. 2022 (STaR): bootstrapping con auto-generaciones filtradas por un "
                   "verificador; aquí se prueba con un verificador chequeable REAL (ejecución), no un oráculo."))
S2 = Source(tier=1, ref="arXiv:1606.06565", obtained=True,
            claim=("Amodei et al. 2016 (Concrete Problems in AI Safety): reward hacking — un agente explota "
                   "una recompensa/verificador imperfecto (ej. soluciones triviales que satisfacen la métrica "
                   "sin resolver la tarea). Predice que un verificador DÉBIL será gameado."))


def _fmt(x):
    return "{:.3f}".format(x) if isinstance(x, (int, float)) else str(x)


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if 'summary' not in data:
        raise SystemExit("results.json sin 'summary' (corré exp018 primero): " + results_path)
    s = data['summary']
    ledger, hyps, ceilings, record = EvidenceLedger(store), HypothesisRegistry(store), CeilingTracker(store), PermanentRecord(store)
    notes = []
    status = s.get('status')
    rm = s.get('real_mean', {})
    base = s.get('base_real')
    degw = s.get('verified_weak_degenerate', {})
    hacked = s.get('weak_hacked')
    accs = ", ".join("{}={}".format(k, _fmt(v)) for k, v in rm.items())

    S3 = Source(tier=5, ref="cognia_x/experiments/exp018_real_verifier", obtained=True,
                claim=("exp018 (síntesis de expresiones, VERIFICADOR REAL = sandbox que ejecuta la salida, "
                       "test held-out DISJUNTO, {n} seeds): real_acc(media-rondas) base={base}; {accs}. "
                       "verified_weak degenerate base->final={db}->{df}, hacked={hk}. {verdict}").format(
                           n=len(data.get('per_seed', [])), base=_fmt(base), accs=accs,
                           db=degw.get('base'), df=degw.get('final'), hk=hacked, verdict=s.get('verdict', '')))
    for src in (S1, S2, S3):
        ledger.add_source(src)
    notes.append("3 fuentes (S1 tier1 STaR; S2 tier1 reward-hacking; S3 tier5 exp018).")

    if status == 'apoyada':
        ev_for, ev_against = [S1.ref, S3.ref], [S2.ref]
        adv = ("APOYADA: con un VERIFICADOR REAL (sandbox que EJECUTA la expresión), verified_strong sube "
               "real_acc sobre base en todos los seeds y supera a verified_weak/naive ({accs}, base {base}). "
               "{hack} -> la auto-mejora verificada generaliza del oráculo de forma cerrada (H-LEARN-1/2) a un "
               "verificador chequeable REAL, y la CALIDAD del verificador real es decisiva (un débil se gamea). "
               "CAVEAT: escala tiny, tarea de síntesis aprendida desde una regla canónica sembrada.").format(
                   accs=accs, base=_fmt(base),
                   hack=("verified_weak SE REWARD-HACKEA (degenerate sube {}->{}): aprende a emitir el target "
                         "literal, inflando la aceptación débil sin competencia real".format(degw.get('base'), degw.get('final'))
                         if hacked else "verified_weak NO se hackeó espontáneamente a esta escala (el loop no-RL no "
                         "descubrió el echo); el verificador fuerte igual domina"))
    elif status == 'refutada':
        ev_for, ev_against = [S2.ref], [S3.ref]
        adv = ("REFUTADA a esta escala: verified_strong NO sube real_acc sobre base ({accs}, base {base}) -> el "
               "modelo tiny no auto-mejora con el verificador real en esta tarea de síntesis (límite de "
               "capacidad/tarea, no del mecanismo). Null informativo.").format(accs=accs, base=_fmt(base))
    else:
        ev_for, ev_against = [S1.ref], [S3.ref, S2.ref]
        adv = ("MIXTA: verified_strong mejora pero no separa claramente de los controles ({accs}); señal "
               "ambigua a esta escala.").format(accs=accs)

    hyp = Hypothesis(
        id="H-LEARN-3",
        statement=("La auto-mejora verificada generaliza a un VERIFICADOR CHEQUEABLE REAL (sandbox que ejecuta "
                   "la salida): verified_strong sube real_acc; un verificador real DÉBIL se reward-hackea (echo "
                   "del target) -> la calidad del verificador real es decisiva."),
        prediction=("verified_strong sube real_acc sobre base (todos los seeds) y supera a verified_weak/naive; "
                    "verified_weak eleva su 'degenerate' (echo). Refutado si strong no mejora o no separa."),
        status='abierta', confidence='media', evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=adv, experiment_ref="exp018_real_verifier")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-LEARN-3")
        notes.append("H-LEARN-3 marcada '{}' con DoD completo.".format(status))
    else:
        notes.append("H-LEARN-3 queda 'abierta'.")

    analogy = AnalogyRecord(
        problem=("Verificar tus ejercicios EJECUTÁNDOLOS (corriendo el código) en vez de mirar un solucionario. "
                 "¿Mejoras? ¿Y si el verificador es débil, hacés trampa para 'pasar' sin resolver?"),
        everyday=("Un test automático real (corre tu código) es mejor verificador que un oráculo, PERO si el test "
                  "es débil aprendés a pasarlo con trucos (devolver la respuesta esperada sin computar) — gaming."),
        solutions=["verificador real fuerte (ejecuta + exige computación) -> auto-mejora honesta",
                   "verificador real débil (solo chequea el valor) -> el modelo lo gamea con el echo",
                   "oráculo de forma cerrada (exp016/017) -> funciona pero no es 'real'",
                   "medir real_acc (competencia real) aparte de weak_acc (lo que el verificador débil acepta)"],
        principles=["un verificador que EJECUTA la salida es más realista que un oráculo, y suficiente para auto-mejorar",
                    "un verificador débil se reward-hackea (Amodei 2016): la calidad del verificador es decisiva",
                    "separar 'lo que el verificador acepta' de 'la competencia real' detecta el gaming"],
        adaptation=("H-LEARN-3 {}: la auto-mejora con verificador real {} a esta escala.").format(
            status, "funciona (con verificador fuerte)" if status == 'apoyada' else "no se demostró"),
        measurement="exp018: real_acc {} (base {}); weak degenerate {}->{}.".format(accs, _fmt(base), degw.get('base'), degw.get('final')),
        iterations=1)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada.")

    ceilings.add(CeilingRecord(
        subsystem="Auto-mejora con verificador chequeable REAL (sandbox de ejecución) — F-LEARN-2",
        known_limit=("exp018: la auto-mejora con un verificador real (ejecuta la salida) {}. Un verificador "
                     "real DÉBIL es gameable (reward hacking, Amodei 2016) -> exigir verificador FUERTE. "
                     "Específico de la escala tiny + tarea de síntesis sembrada con regla canónica.").format(
                         "funciona con verificador fuerte" if status == 'apoyada' else "no se demostró ("+str(status)+")"),
        blockers=[{"text": "un verificador real débil se reward-hackea (echo del target)", "kind": "diseno"},
                  {"text": "síntesis con modelo tiny: capacidad limitada (requiere sembrar una regla canónica)", "kind": "diseno"}],
        real_or_assumed="asumido", evidence=[S1.ref, S2.ref, S3.ref]))
    notes.append("1 techo 'asumido' registrado (verificador real + reward-hacking).")

    if status == 'apoyada':
        dstmt = ("Adoptar verificadores chequeables REALES (que EJECUTAN la salida) para la auto-mejora de "
                 "Cognia-X, exigiendo que sean FUERTES (un verificador débil se reward-hackea, exp018). Junto "
                 "con D-LEARN-2 (FP-rate < ε*): la calidad del verificador real es un requisito de primera clase.")
        drat = ("exp018: verified_strong sube real_acc ({}) con un verificador real; verified_weak {}.").format(
            accs, "se gamea (degenerate sube)" if hacked else "domina menos / fuerte gana")
    else:
        dstmt = ("NO adoptar conclusión sobre verificadores reales aún: exp018 status={} a escala tiny "
                 "(la síntesis excede al modelo). Backlog: modelo mayor o tarea verificable más simple.").format(status)
        drat = s.get('verdict', '')
    dec = Decision(id="D-LEARN-3", statement=dstmt, rationale=drat, sources=[_to_plain(S3), _to_plain(S1)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-LEARN-3 ACEPTADA por el ledger (tier5 S3 + tier1 S1).")
    except OpinionOnlyError as e:
        print("ERROR ledger D-LEARN-3:", e); raise

    return ledger, hyps, ceilings, record, notes, status, s


def _to_plain(obj):
    from cognia_x.research.schema import to_dict
    import dataclasses
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle31_real_verifier',
                                description='CYCLE 31 (H-LEARN-3: verificador real + reward-hacking).')
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
    print("RESUMEN — CYCLE 31: verificador REAL (sandbox) + reward-hacking (H-LEARN-3)")
    print("=" * 78)
    print("veredicto H-LEARN-3:", status.upper() if status else "?")
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
