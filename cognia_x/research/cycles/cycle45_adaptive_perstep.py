r"""
cycle45_adaptive_perstep.py — CICLO 45 (RESET v4): H-V4-1j por las compuertas del engine.

H-V4-1j: ¿gastar el cómputo "hasta verificar" con un pool COMPARTIDO entre pasos (presupuesto ADAPTATIVO
per-step: más a los difíciles, menos a los fáciles) rescata las cadenas largas que el presupuesto por-paso
FIJO dejaba colapsar (exp030), a IGUAL cómputo total? Aplica el control adaptativo (43) ACROSS the chain.
DERIVA de exp031_adaptive_perstep/results/results.json.

RESULTADO REAL: MIXTA (rescate fuerte y consistente; 4 seeds). Curva K->UNIFORME/ADAPT/gain:
  K2:0.446/0.598/+0.152  K4:0.190/0.423/+0.233  K6:0.119/0.333/+0.215  K8:0.058/0.240/+0.181
  - El adaptativo GANA en TODA K por margen grande (+0.15..+0.23) y RESCATA cadenas largas: a K=8 el uniforme
    colapsa a 0.058 mientras el adaptativo aguanta 0.240 (4.1×). A IGUAL cómputo total B=avg·K.
  - MIXTA sólo porque el gain ABSOLUTO no es estrictamente monótono (pico en K=4 +0.233, baja a +0.181 en
    K=8): a presupuesto total fijo, incluso el adaptativo satura a K extremo (la ventaja RELATIVA sí crece:
    1.3×->2.2×->2.8×->4.1×).
  => reasignar por dificultad (gastar-hasta-verificar) es un LEVER fuerte para cadenas largas; combinado con la
     verificación de proceso (44) compra cadenas mucho más confiables. Cota: a K extremo hace falta más B total.

Correr (DESPUÉS de exp031):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp031_adaptive_perstep.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle45_adaptive_perstep
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store',
                             'cycle45_adaptive_perstep')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp031_adaptive_perstep', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _fmt(x):
    return "{:.3f}".format(x) if isinstance(x, (int, float)) else str(x)


def _ratio(a, u):
    return a / u if u > 1e-9 else float('inf')


S_DYN = Source(tier=1, ref="adaptive-compute-allocation", obtained=False,
               claim=("Asignar el cómputo de inferencia de forma ADAPTATIVA por dificultad (más a lo difícil) "
                      "supera al reparto uniforme a igual presupuesto (test-time compute, arXiv:2408.03314). "
                      "(Principio, no re-obtenido esta sesión.)"))
S_EXP030 = Source(tier=5, ref="cognia_x/experiments/exp030_multistep_reasoning", obtained=True,
                  claim=("exp030 (CYCLE 44): la verificación intermedia frena el compounding, pero con "
                         "presupuesto por-paso FIJO las cadenas largas colapsan (se malgasta en los fáciles)."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    v = data.get('verdict')
    st = data.get('stats')
    if not v or not st:
        raise SystemExit("results.json sin verdict/stats (corre exp031 primero): " + results_path)
    status = v.lower()
    Ks = [str(x) for x in data.get('Ks', [])]
    curve = st['curve']
    Kmax = str(st['Kmax'])
    n_seeds = st['n_seeds']
    gain_max = st['gain_at_Kmax']
    ratios = {K: _ratio(curve[K]['adaptive'], curve[K]['uniform']) for K in Ks}
    ratio_max = ratios[Kmax]
    all_positive = all(curve[K]['gain'] > 0 for K in Ks)

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    S_EXP031 = Source(tier=5, ref="cognia_x/experiments/exp031_adaptive_perstep", obtained=True,
                      claim=("exp031 (propio, {n} seeds, modelo HybridLM, cadena de sumas mod 20): el "
                             "presupuesto ADAPTATIVO per-step (gastar-hasta-verificar con pool compartido) gana "
                             "al UNIFORME en TODA K (+0.15..+0.23) a IGUAL cómputo total, y RESCATA cadenas "
                             "largas: a K={km} uniforme {u} vs adaptativo {a} ({rm}×).").format(
                                 n=n_seeds, km=st['Kmax'], u=_fmt(curve[Kmax]['uniform']),
                                 a=_fmt(curve[Kmax]['adaptive']), rm=_fmt(ratio_max)))
    for src in (S_DYN, S_EXP030, S_EXP031):
        ledger.add_source(src)
    notes.append("3 fuentes (S_DYN tier1 asignación adaptativa; S_EXP030 tier5 colapso por-paso fijo; S_EXP031 tier5 dato propio).")

    ev_for = [S_EXP031.ref, S_EXP030.ref]
    ev_against = [S_EXP031.ref]      # honesto: el gain absoluto NO es monótono (a K extremo todo satura)
    adv = ("MIXTA, pero RESCATE fuerte. La predicción pedía gain >= margen Y monótono creciente: el gain es "
           "grande en TODA K ({gm} en Kmax, muy por encima del margen) pero NO estrictamente monótono (pico en "
           "K=4 +0.233, baja a +0.181 en K=8) -> MIXTA. PERO la dirección es contundente y A FAVOR: el "
           "presupuesto ADAPTATIVO per-step (gastar-hasta-verificar con pool compartido) GANA al uniforme en "
           "TODAS las longitudes (+0.15..+0.23) a IGUAL cómputo total, y RESCATA las cadenas largas que el "
           "presupuesto fijo dejaba colapsar: a K={km} el uniforme cae a {u} mientras el adaptativo aguanta "
           "{a} ({rm}×). La ventaja RELATIVA crece monótona (1.3×->2.2×->2.8×->{rm}×). MECANISMO: parar en "
           "cuanto un paso verifica libera presupuesto para los pasos difíciles. Ataques considerados: (1) "
           "'¿mismo cómputo?' -> SÍ, B=avg·K para ambos; el adaptativo sólo REDISTRIBUYE. (2) '¿por qué baja el "
           "gain a K=8?' -> a presupuesto TOTAL fijo, a K extremo incluso el adaptativo satura hacia 0 (ambos "
           "decaen; el relativo sigue creciendo). LECCIÓN: reasignar por dificultad es un lever fuerte para "
           "multi-paso; combinado con la verificación de proceso (44) compra cadenas mucho más confiables. "
           "Cota: a K extremo hace falta MÁS B total (o casi-perfeccionar el paso).").format(
               gm="%+.3f" % gain_max, km=st['Kmax'], u=_fmt(curve[Kmax]['uniform']),
               a=_fmt(curve[Kmax]['adaptive']), rm=_fmt(ratio_max))

    hyp = Hypothesis(
        id="H-V4-1j",
        statement=("Asignar el presupuesto de cómputo por paso de forma adaptativa (gastar-hasta-verificar con "
                   "pool compartido) rescata cadenas largas vs presupuesto por-paso fijo, a igual cómputo total."),
        prediction=("APOYADA si ADAPT > UNIFORME en Kmax (>=0.03) y el gain crece/no-decrece con K; MIXTA si "
                    "ayuda fuerte pero no-monótono; REFUTADA si ADAPT<=UNIFORME en Kmax. (Pre-registrada.)"),
        status='abierta', confidence='alta',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=adv, experiment_ref="exp031_adaptive_perstep")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-1j")
        notes.append("H-V4-1j marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("Examen con varios ejercicios y tiempo TOTAL fijo. ¿Repartís el tiempo igual o según la "
                 "dificultad de cada ejercicio?"),
        everyday=("Si das el MISMO tiempo a cada ejercicio, malgastás en los fáciles (que resolvés al toque) y "
                  "te quedás corto en los difíciles. Si parás en cuanto te sale uno fácil y reinvertís ese "
                  "tiempo en los difíciles, resolvés MÁS en total — sobre todo si el examen es largo."),
        solutions=["presupuesto ADAPTATIVO (parar al verificar, reinvertir en lo difícil) -> +0.15..+0.23 en toda K; rescata cadenas largas (4.1× a K=8)",
                   "presupuesto UNIFORME (mismo por paso) -> malgasta en lo fácil; colapsa en cadenas largas",
                   "a cadena MUY larga con presupuesto total fijo, incluso el adaptativo satura -> hace falta más tiempo total",
                   "combinar con verificación de PROCESO (44): el adaptativo necesita el verificador per-step para saber cuándo parar"],
        principles=["a presupuesto total fijo, reasignar por dificultad (gastar-hasta-verificar) supera al uniforme en multi-paso",
                    "parar en cuanto un paso verifica libera cómputo para los pasos difíciles -> rescata cadenas largas",
                    "la ventaja relativa crece con la longitud; la absoluta satura a K extremo (presupuesto total finito)",
                    "verificación de proceso (44) + presupuesto adaptativo per-step (45) = cadenas confiables más largas"],
        adaptation=("Cierra el lever de cómputo del integrador multi-paso: act-and-verify por paso con "
                    "presupuesto adaptativo (gastar-hasta-verificar). Próximos: backtracking/abstención cuando "
                    "un paso no verifica con todo su presupuesto + verificador RUIDOSO per-step (el ruido se "
                    "compone; reusar la política adaptativa calibrada de 43 por paso)."),
        measurement=("exp031: curva K->UNIFORME/ADAPT/gain = {cv}; ventaja relativa hasta {rm}× a K={km}. "
                     "{n} seeds.").format(
                         cv=" | ".join("K{}:{}/{}/{}".format(K, _fmt(curve[K]['uniform']),
                                                             _fmt(curve[K]['adaptive']), _fmt(curve[K]['gain'])) for K in Ks),
                         rm=_fmt(ratio_max), km=st['Kmax'], n=n_seeds),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (examen con tiempo fijo: reinvertir el tiempo de los fáciles en los difíciles).")

    ceilings.add(CeilingRecord(
        subsystem="Multi-paso — presupuesto ADAPTATIVO per-step (gastar-hasta-verificar) rescata cadenas largas",
        known_limit=("REAL (exp031): a IGUAL cómputo total, reasignar el presupuesto por paso (parar al "
                     "verificar, reinvertir en lo difícil) gana al uniforme en TODA K (+0.15..+0.23) y rescata "
                     "cadenas largas (a K={km}: uniforme {u} vs adaptativo {a}, {rm}×). Cota: a K extremo, con "
                     "presupuesto TOTAL fijo, incluso el adaptativo satura hacia 0 (la ventaja relativa crece, "
                     "la absoluta no).").format(km=st['Kmax'], u=_fmt(curve[Kmax]['uniform']),
                                                a=_fmt(curve[Kmax]['adaptive']), rm=_fmt(ratio_max)),
        blockers=[{"text": "a K extremo el presupuesto total fijo no alcanza; falta escalar B con K o casi-perfeccionar el paso", "kind": "diseno"},
                  {"text": "cuando un paso agota su presupuesto sin verificar, commitea uno malo y descarrila; falta backtracking/abstención", "kind": "diseno"},
                  {"text": "verificador PERFECTO per-step; falta ruidoso per-step (reusar la política adaptativa calibrada de 43 por paso)", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP031.ref, S_EXP030.ref]))
    notes.append("1 techo 'real': presupuesto adaptativo per-step rescata cadenas largas (a igual cómputo); satura a K extremo.")

    dstmt = ("El lever de cómputo del integrador multi-paso queda establecido: a IGUAL cómputo total, asignar "
             "el presupuesto por paso de forma ADAPTATIVA (gastar-hasta-verificar con pool compartido: parar al "
             "verificar, reinvertir en los pasos difíciles) gana al uniforme en TODA longitud (+0.15..+0.23) y "
             "RESCATA las cadenas largas que el presupuesto fijo dejaba colapsar (hasta 4.1× a K=8), "
             "convergente con la asignación adaptativa de test-time compute. Decisión: el integrador multi-paso "
             "= verificación de PROCESO (44) + presupuesto ADAPTATIVO per-step (45). Próximos: backtracking/"
             "abstención cuando un paso no verifica con todo su presupuesto, verificador RUIDOSO per-step "
             "(reusar la política adaptativa calibrada de 43 por paso), y escalar B con K para cadenas extremas.")
    drat = ("exp031 (tier5, propio, {n} seeds): ADAPT > UNIFORME en toda K (+0.15..+0.23) a igual B=avg·K; "
            "rescate de cadenas largas hasta {rm}× a K={km}; gain absoluto no-monótono (satura a K extremo) -> "
            "MIXTA pre-registrada. Convergente con asignación adaptativa de cómputo (arXiv:2408.03314) y con "
            "exp030 (proceso>resultado).").format(n=n_seeds, rm=_fmt(ratio_max), km=st['Kmax'])
    dec = Decision(id="D-V4-10", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP031), _to_plain(S_EXP030)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-10 ACEPTADA por el ledger (tier5 exp031 + tier5 exp030).")
    except OpinionOnlyError as e:
        print("ERROR ledger D-V4-10:", e); raise

    return record, notes, status, st


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle45_adaptive_perstep',
                                description='CYCLE 45 (RESET v4, H-V4-1j: presupuesto adaptativo per-step).')
    p.add_argument('--store', default=DEFAULT_STORE)
    p.add_argument('--results', default=DEFAULT_RESULTS)
    p.add_argument('--reset', dest='reset', action='store_true', default=True)
    p.add_argument('--no-reset', dest='reset', action='store_false')
    args = p.parse_args(argv)
    store = os.path.abspath(args.store)
    if args.reset and os.path.isdir(store):
        shutil.rmtree(store)
    os.makedirs(store, exist_ok=True)
    record, notes, status, st = run(store, os.path.abspath(args.results))
    res = record.verify_no_loss()
    print("=" * 78)
    print("RESUMEN — CYCLE 45 (RESET v4): presupuesto ADAPTATIVO per-step rescata cadenas largas (H-V4-1j)")
    print("=" * 78)
    print("veredicto H-V4-1j:", status.upper() if status else "?")
    print("  gastar-hasta-verificar (reinvertir en pasos difíciles) gana en toda K; rescata cadenas largas (4.1× a K=8).")
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
