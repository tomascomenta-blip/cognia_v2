r"""
cycle59_adaptive_forgetting.py — CICLO 59 (RESET v4): H-V4-1e por las compuertas del engine. North-Star
R-VALOR x memoria. Olvido ADAPTATIVO dirigido por SORPRESA (unifica CYCLE 57 + 58).

H-V4-1e: el olvido adaptativo dirigido por sorpresa (olvidar SÓLO cuando las predicciones se contradicen) logra
el trade-off estabilidad-plasticidad ENDÓGENO — adapta sin saber cuándo cambió la causa, sin perder la fase 1.
Cierra los límites #1/#2 de exp044. DERIVA de exp045_adaptive_forgetting/results/results.json.

Correr (DESPUÉS de exp045):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp045_adaptive_forgetting.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle59_adaptive_forgetting
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
                             'cycle59_adaptive_forgetting')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp045_adaptive_forgetting', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_SURPRISE = Source(tier=1, ref="surprise/prediction-error -> change detection (Bayesian online change-point)", obtained=False,
                    claim=("La sorpresa (error de predicción / baja verosimilitud) señala un cambio de régimen; "
                           "modular el olvido por sorpresa adapta sin conocer el punto de cambio. (Principio.)"))
S_EXP043 = Source(tier=5, ref="cognia_x/experiments/exp043_endogenous_signal (CYCLE 57)", obtained=True,
                  claim=("exp043 (H-V4-1c): la confianza calibrada del agente es señal endógena; la sorpresa "
                         "(predicción contradicha) es su contracara -> dispara olvido."))
S_EXP044 = Source(tier=5, ref="cognia_x/experiments/exp044_nonstationary_forgetting (CYCLE 58)", obtained=True,
                  claim=("exp044 (H-V4-1d): el olvido FIJO adapta donde el committed se atasca, pero hay que "
                         "elegir el decay a priori y olvida siempre (límites #1/#2: adaptativo + detección endógena)."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp045 primero): " + results_path)
    ba = sm['by_arm']
    com, mild, agg, ada = ba['committed'], ba['fixed_mild'], ba['fixed_aggressive'], ba['adaptive']
    n_seeds = sm['n_seeds']
    K2 = data['params']['K2']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    S_EXP045 = Source(tier=5, ref="cognia_x/experiments/exp045_adaptive_forgetting", obtained=True,
                      claim=("exp045 (propio, {n} seeds, bayesiano numpy): el olvido ADAPTATIVO (olvida sólo "
                             "cuando la predicción se contradice) logra adaptación (post_c_new {an}) IGUAL que el "
                             "mejor decay fijo tuneado (fixed_mild {mn}) pero ENDÓGENO, y mantiene la fase 1 "
                             "(midpoint {am}) DOMINANDO al mismo floor constante (fixed_aggressive {gm}).").format(
                                 n=n_seeds, an=_f(ada['post_c_new_final']), mn=_f(mild['post_c_new_final']),
                                 am=_f(ada['post_c_old_midpoint']), gm=_f(agg['post_c_old_midpoint'])))
    for src in (S_SURPRISE, S_EXP043, S_EXP044, S_EXP045):
        ledger.add_source(src)
    notes.append("4 fuentes (S_SURPRISE tier1 change-point; S_EXP043 tier5 confianza/sorpresa; S_EXP044 tier5 olvido fijo; S_EXP045 tier5 dato propio).")

    ev_for = [S_EXP045.ref, S_EXP044.ref, S_EXP043.ref]
    ev_against = [S_EXP045.ref]
    adv = ("{V}: cierra los límites #1/#2 de exp044 (olvido ADAPTATIVO + detección de cambio ENDÓGENA). El "
           "agente olvida SÓLO cuando sus predicciones se CONTRADICEN (P(y_obs|posterior)<0.5 = sorpresa), sin "
           "que le digan cuándo cambió la causa. RESULTADO (4 brazos, misma política info-gain, distinto olvido): "
           "committed (decay=1) post_c_new={cn}/midpoint={cm} (atascado, estable); fixed_mild (0.9) {mn}/{mm} "
           "(adapta, estable); fixed_aggressive (0.6 CONSTANTE) {gn}/{gm} (olvida SIEMPRE -> DESTRUYE la fase 1); "
           "ADAPTIVE (floor 0.6 por SORPRESA) {an}/{am}. El ADAPTIVE logra el trade-off estabilidad-plasticidad "
           "ENDÓGENO: ADAPTA ({an}, +{g} sobre committed) IGUAL que el mejor decay fijo TUNEADO (fixed_mild "
           "{mn}) pero SIN tunear ni saber el punto de cambio, Y mantiene la fase 1 ({am}) MUY por encima del "
           "MISMO floor constante ({gm}). HALLAZGO CLAVE: el olvido SELECTIVO (por sorpresa) >> olvido CONSTANTE "
           "(mismo floor): committea cuando confirma, olvida cuando se contradice ({nf} pasos de olvido). Une "
           "CYCLE 57 (la sorpresa es la contracara de la confianza calibrada) + CYCLE 58 (olvido). EVIDENCIA EN "
           "CONTRA (caveats honestos): (1) el adaptive IGUALA, no SUPERA, al mejor decay fijo en adaptación "
           "(su ventaja es ser ENDÓGENO/untuned + dominar en estabilidad, no más plástico). (2) el trigger de "
           "sorpresa es un umbral simple (P<0.5); falta un olvido GRADUADO por magnitud de sorpresa. (3) mundo de "
           "juguete. CONCLUSIÓN: el sistema detecta el cambio por su propia sorpresa y modula el olvido sin "
           "supervisión -> R-VALOR x memoria CERRADO endógenamente: el valor de la info vieja cae cuando el "
           "modelo se sorprende, y el olvido la descarta.").format(
               V=status.upper(), cn=_f(com['post_c_new_final']), cm=_f(com['post_c_old_midpoint']),
               mn=_f(mild['post_c_new_final']), mm=_f(mild['post_c_old_midpoint']),
               gn=_f(agg['post_c_new_final']), gm=_f(agg['post_c_old_midpoint']),
               an=_f(ada['post_c_new_final']), am=_f(ada['post_c_old_midpoint']),
               g=_f(ada['post_c_new_final'] - com['post_c_new_final']), nf=_f(ada['n_forget_steps']))

    hyp = Hypothesis(
        id="H-V4-1e",
        statement=("El olvido adaptativo dirigido por sorpresa (olvidar sólo cuando la predicción se contradice) "
                   "logra el trade-off estabilidad-plasticidad endógeno: adapta sin saber cuándo cambió la causa, "
                   "sin perder la fase 1."),
        prediction=("APOYADA si el adaptive ADAPTA (post_c_new>=0.40, +>0.20 sobre committed) Y mantiene la fase 1 "
                    "(midpoint>=0.80, dominando al fixed_aggressive); REFUTADA si no adapta; MIXTA si su "
                    "estabilidad no domina al aggressive. (Pre-registrada.)"),
        status='abierta', confidence='alta' if status == 'apoyada' else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=adv, experiment_ref="exp045_adaptive_forgetting")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-1e")
        notes.append("H-V4-1e marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("¿Cómo sabés CUÁNDO soltar lo que aprendiste, sin que nadie te avise que el mundo cambió, y sin "
                 "olvidar de más cuando todo sigue igual?"),
        everyday=("Por tus propios ERRORES. Mientras acertás los ejercicios, seguís con lo que sabés (no olvidás). "
                  "Cuando de golpe fallás todo (sorpresa), 'algo cambió' -> soltás lo viejo y re-estudiás. Olvidar "
                  "SÓLO cuando te sorprendés es mejor que olvidar un poquito todo el tiempo (perdés lo bueno) o "
                  "nunca (te quedás trabado)."),
        solutions=["committed (nunca olvida) -> trabado en lo viejo",
                   "olvido CONSTANTE agresivo -> destruye lo aprendido aun cuando el mundo era estable",
                   "olvido CONSTANTE suave -> adapta pero hay que tunear el ritmo a priori",
                   "olvido ADAPTATIVO por sorpresa -> committea cuando confirma, olvida cuando se contradice (lo mejor de ambos, endógeno)"],
        principles=["la sorpresa (predicción contradicha) es una señal endógena de que el mundo cambió",
                    "olvidar SELECTIVAMENTE (por sorpresa) >> olvidar constante: estable cuando estable, plástico cuando cambió",
                    "el sistema detecta el cambio y modula el olvido SIN supervisión (sin saber el punto de cambio)",
                    "R-VALOR x memoria: el valor de la info vieja cae cuando el modelo se sorprende; el olvido la descarta"],
        adaptation=("El lab usa la sorpresa (contracara de la confianza calibrada del CYCLE 57) para modular el "
                    "olvido endógenamente. Próximos: olvido GRADUADO por magnitud de sorpresa (no umbral binario); "
                    "sorpresa acumulada/ventana (robustez al ruido); ligar a una memoria con escritura/olvido "
                    "explícitos (H-V4-5)."),
        measurement=("exp045: adaptive post_c_new {an}/midpoint {am} vs committed {cn}/{cm}, fixed_mild {mn}/{mm}, "
                     "fixed_aggressive {gn}/{gm}. {n} seeds.").format(
                         an=_f(ada['post_c_new_final']), am=_f(ada['post_c_old_midpoint']),
                         cn=_f(com['post_c_new_final']), cm=_f(com['post_c_old_midpoint']),
                         mn=_f(mild['post_c_new_final']), mm=_f(mild['post_c_old_midpoint']),
                         gn=_f(agg['post_c_new_final']), gm=_f(agg['post_c_old_midpoint']), n=n_seeds),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (soltar lo viejo por tus propios errores, sin que te avisen).")

    ceilings.add(CeilingRecord(
        subsystem="R-VALOR x MEMORIA — olvido ADAPTATIVO por sorpresa (detección de cambio endógena)",
        known_limit=("REAL (exp045): el olvido dirigido por sorpresa logra el trade-off estabilidad-plasticidad "
                     "ENDÓGENO — adapta (post_c_new {an}) igual que el mejor decay fijo tuneado SIN saber el "
                     "punto de cambio, y mantiene la fase 1 (midpoint {am}) dominando al mismo floor constante "
                     "({gm}). Olvido selectivo >> constante.").format(
                         an=_f(ada['post_c_new_final']), am=_f(ada['post_c_old_midpoint']),
                         gm=_f(agg['post_c_old_midpoint'])),
        blockers=[{"text": "el adaptive IGUALA (no supera) al mejor decay fijo en adaptación; su ventaja es ser endógeno/untuned", "kind": "diseno"},
                  {"text": "el trigger es un umbral binario (P<0.5); falta olvido GRADUADO por magnitud de sorpresa y ventana acumulada", "kind": "diseno"},
                  {"text": "mundo de juguete con un solo cambio; falta no-estacionariedad recurrente/gradual", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP045.ref, S_EXP044.ref]))
    notes.append("1 techo 'real': el olvido por sorpresa cierra la detección de cambio endógena (R-VALOR x memoria sin supervisión).")

    dstmt = ("North-Star R-VALOR x MEMORIA (cierre del sub-arco): el sistema detecta el cambio por su PROPIA "
             "SORPRESA (predicción contradicha = contracara de la confianza calibrada del CYCLE 57) y modula el "
             "OLVIDO sin supervisión: olvida cuando se contradice, committea cuando confirma. Logra el trade-off "
             "estabilidad-plasticidad ENDÓGENO — adapta (post_c_new {an}) igual que el mejor decay fijo tuneado "
             "SIN saber el punto de cambio, y mantiene la fase 1 ({am}) dominando al mismo floor constante "
             "({gm}). El olvido SELECTIVO >> constante. Decisión: el lab cierra R-VALOR x memoria endógenamente — "
             "el valor de la info vieja cae cuando el modelo se sorprende y el olvido la descarta, sin oráculo ni "
             "aviso externo. Matiz honesto: iguala (no supera) al mejor decay fijo en adaptación; su valor es ser "
             "endógeno. Próximos: olvido graduado por magnitud de sorpresa; no-estacionariedad recurrente; memoria "
             "con escritura/olvido explícitos (H-V4-5).").format(
                 an=_f(ada['post_c_new_final']), am=_f(ada['post_c_old_midpoint']),
                 gm=_f(agg['post_c_old_midpoint']))
    drat = ("exp045 (tier5, propio, {n} seeds): adaptive post_c_new {an}/midpoint {am} domina al committed "
            "(atascado {cn}) y al fixed_aggressive (estabilidad {gm}), igualando a fixed_mild ({mn}) sin tunear. "
            "Convergente con surprise/change-point (tier1) y une CYCLE 57+58. {V}.").format(
                n=n_seeds, an=_f(ada['post_c_new_final']), am=_f(ada['post_c_old_midpoint']),
                cn=_f(com['post_c_new_final']), gm=_f(agg['post_c_old_midpoint']),
                mn=_f(mild['post_c_new_final']), V=status.upper())
    dec = Decision(id="D-V4-24", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP045), _to_plain(S_EXP044)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-24 ACEPTADA por el ledger (tier5 exp045 + tier5 exp044).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-24:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle59_adaptive_forgetting',
                                description='CYCLE 59 (RESET v4, H-V4-1e: olvido adaptativo por sorpresa).')
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
    print("RESUMEN — CYCLE 59 (RESET v4): olvido ADAPTATIVO por sorpresa (H-V4-1e) — North-Star (cierre sub-arco)")
    print("=" * 78)
    print("veredicto H-V4-1e:", status.upper() if status else "?")
    print("  el sistema detecta el cambio por su propia sorpresa y modula el olvido sin supervisión.")
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
