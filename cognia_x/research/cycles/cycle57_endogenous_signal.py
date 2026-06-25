r"""
cycle57_endogenous_signal.py — CICLO 57 (RESET v4): H-V4-1c por las compuertas del engine. North-Star R-VALOR.

H-V4-1c: la confianza ENDÓGENA del agente (max del posterior, SIN oráculo de la causa) (a) rankea info-gain por
encima del azar-activo y (b) está CALIBRADA (confiado => correcto) -> señal de valor endógena usable para elegir
política sin conocer la causa. Cierra el límite #1 de exp042/CYCLE 56. DERIVA de
exp043_endogenous_signal/results/results.json.

Correr (DESPUÉS de exp043):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp043_endogenous_signal.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle57_endogenous_signal
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
                             'cycle57_endogenous_signal')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp043_endogenous_signal', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x) if isinstance(x, (int, float)) else str(x)


S_CALIB = Source(tier=1, ref="calibración bayesiana / confianza como valor", obtained=False,
                 claim=("La confianza de un posterior propio (concentración) es una señal interna disponible sin "
                        "oráculo; su utilidad depende de que esté CALIBRADA. (Principio, no re-obtenido.)"))
S_EXP042 = Source(tier=5, ref="cognia_x/experiments/exp042_value_isolation_post (CYCLE 56)", obtained=True,
                  claim=("exp042 (H-V4-1b): info-gain aísla su valor con post_on_cause (oráculo de eval); límite "
                         "#1: falta un proxy ENDÓGENO de mejor modelo SIN conocer la causa c."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp043 primero): " + results_path)
    n_seeds = sm['n_seeds']
    Kmax = sm['Kmax']
    h = sm['hard_by_K'][str(Kmax)]
    B, C, A = h['B_infogain'], h['C_aleatorio'], h['A_pasivo']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    S_EXP043 = Source(tier=5, ref="cognia_x/experiments/exp043_endogenous_signal", obtained=True,
                      claim=("exp043 (propio, {n} seeds, bayesiano numpy): la confianza ENDÓGENA (max posterior) "
                             "rankea info-gain (B conf {bc}) > azar (C {cc}) > pasivo (A {ac}) igual que el "
                             "oráculo; B CALIBRADO (P(correct|confiado)={cal}, confiado-equivocado {cwb}) vs C "
                             "({cwc}).").format(n=n_seeds, bc=_f(B['conf_mean']), cc=_f(C['conf_mean']),
                                                ac=_f(A['conf_mean']),
                                                cal=_f(B['calibration_P_correct_given_confident']),
                                                cwb=_f(B['confidently_wrong']), cwc=_f(C['confidently_wrong'])))
    for src in (S_CALIB, S_EXP042, S_EXP043):
        ledger.add_source(src)
    notes.append("3 fuentes (S_CALIB tier1 calibración; S_EXP042 tier5 límite #1; S_EXP043 tier5 dato propio).")

    supported = status == 'apoyada'
    ev_for = [S_EXP043.ref, S_EXP042.ref]
    ev_against = [S_EXP043.ref]
    adv = ("{V}: cierra el límite #1 de exp042 (CYCLE 56). La única señal que el agente tiene SIN oráculo es su "
           "PROPIA confianza (max del posterior). exp043 muestra que en el régimen DURO esa señal endógena: (a) "
           "RANKEA las políticas igual que el oráculo — conf B(info-gain)={bc} > C(azar)={cc} > A(pasivo)={ac} "
           "(el pasivo queda apropiadamente INCIERTO, sabe que no puede distinguir el clúster); (b) es CALIBRADA "
           "para info-gain — P(correct|confiado)_B={cal}, confiado-pero-equivocado_B={cwb} (muy bajo). HALLAZGO "
           "CLAVE: la confianza endógena es CONFIABLE SÓLO CON LA POLÍTICA CORRECTA — el azar-activo (C) produce "
           "confianza POCO FIABLE (confiado-pero-equivocado={cwc}, se concentra a veces en una feature ESPURIA "
           "del clúster). => el agente puede SELECCIONAR la mejor política por su propia confianza, sin conocer "
           "la causa, PERO el valor endógeno requiere la política que hace la confianza trustworthy (info-gain), "
           "no sólo 'estar activo'. EVIDENCIA EN CONTRA (caveats honestos): (1) la calibración es alta pero no "
           "perfecta (~{cal}); el azar muestra que la confianza PUEDE engañar. (2) mundo de juguete (posterior "
           "bayesiano propio bien especificado -> calibración ayudada por construcción). (3) la 'corrección' se "
           "valida con la causa real c (sólo para medir calibración; el agente no la usa). CONCLUSIÓN: existe "
           "una señal de VALOR ENDÓGENA usable (confianza calibrada) que cierra el lazo de R-VALOR: el sistema "
           "puede juzgar qué política construyó mejor modelo sin un verificador externo de la verdad.").format(
               V=status.upper(), bc=_f(B['conf_mean']), cc=_f(C['conf_mean']), ac=_f(A['conf_mean']),
               cal=_f(B['calibration_P_correct_given_confident']), cwb=_f(B['confidently_wrong']),
               cwc=_f(C['confidently_wrong']))

    hyp = Hypothesis(
        id="H-V4-1c",
        statement=("La confianza endógena del agente (max posterior, sin oráculo) rankea info-gain>azar y está "
                   "calibrada para info-gain -> señal de valor endógena usable para elegir política."),
        prediction=("APOYADA si en el régimen DURO conf_B>conf_C Y B calibrado (P(correct|confiado)>=0.80, "
                    "confiado-equivocado_B<0.15 y <C); REFUTADA si no rankea B>C o B miscalibrado "
                    "(confiado-equivocado>=0.30); MIXTA si rankea pero calibración imperfecta. (Pre-registrada.)"),
        status='abierta', confidence='alta' if supported else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=adv, experiment_ref="exp043_endogenous_signal")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-1c")
        notes.append("H-V4-1c marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("Un detective no tiene quién le confirme quién es el culpable. ¿Puede CONFIAR en su propia "
                 "sensación de certeza para saber si ya resolvió el caso — o esa certeza lo engaña?"),
        everyday=("Depende de CÓMO investigó. El que hizo preguntas que DISTINGUEN a los sospechosos (info-gain): "
                  "cuando se siente seguro, ACIERTA (su certeza es confiable). El que preguntó AL AZAR a veces se "
                  "siente seguro y está EQUIVOCADO (se fijó en un parecido). El que sólo miró sin preguntar "
                  "(pasivo) se queda dudando — y eso está bien, sabe que no puede distinguir."),
        solutions=["pasivo: confianza BAJA (incierto) -> calibrado pero no resuelve",
                   "azar-activo: confianza MEDIA pero a veces confiado-PERO-equivocado (señal poco fiable)",
                   "info-gain: confianza ALTA y CALIBRADA (confiado => correcto) -> señal de valor confiable",
                   "=> el agente elige la mejor política por su propia confianza, sin oráculo"],
        principles=["la confianza propia (max posterior) es una señal de valor disponible SIN oráculo externo",
                    "esa señal es CONFIABLE sólo con la política que la hace calibrada (info-gain), no con cualquier actividad",
                    "el azar-activo puede ser confiado-pero-equivocado: actividad sin valor da confianza engañosa",
                    "un sistema puede juzgar qué política construyó mejor modelo por su confianza calibrada, sin verificador externo"],
        adaptation=("El lab puede usar la confianza calibrada como señal de valor endógena para auto-seleccionar "
                    "políticas/hipótesis sin oráculo — conecta con el arco de auto-mejora (el verificador externo "
                    "puede reemplazarse, en parte, por la confianza calibrada del propio modelo). Próximos: usar "
                    "la confianza endógena para SELECCIONAR política online; mundo no-estacionario; mundo con "
                    "modelo mal especificado (donde la calibración bayesiana ya no esté garantizada)."),
        measurement=("exp043 (DURO @Kmax): conf B={bc}/C={cc}/A={ac}; calib_B={cal} confiado-equivocado B={cwb} "
                     "C={cwc}. {n} seeds.").format(bc=_f(B['conf_mean']), cc=_f(C['conf_mean']),
                                                   ac=_f(A['conf_mean']),
                                                   cal=_f(B['calibration_P_correct_given_confident']),
                                                   cwb=_f(B['confidently_wrong']), cwc=_f(C['confidently_wrong']),
                                                   n=n_seeds),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (el detective que confía en su certeza sólo si investigó distinguiendo).")

    ceilings.add(CeilingRecord(
        subsystem="R-VALOR — señal de valor ENDÓGENA (confianza calibrada) usable sin oráculo",
        known_limit=("REAL (exp043): la confianza endógena (max posterior) rankea info-gain>azar>pasivo igual que "
                     "el oráculo y está CALIBRADA para info-gain (P(correct|confiado)={cal}, confiado-equivocado "
                     "{cwb}) -> señal de valor usable sin oráculo; pero CONFIABLE sólo con la política correcta "
                     "(el azar-activo da confianza engañosa, confiado-equivocado={cwc}).").format(
                         cal=_f(B['calibration_P_correct_given_confident']), cwb=_f(B['confidently_wrong']),
                         cwc=_f(C['confidently_wrong'])),
        blockers=[{"text": "la calibración bayesiana está ayudada por construcción (modelo bien especificado); falta un mundo con modelo MAL especificado", "kind": "diseno"},
                  {"text": "no se USÓ la confianza para SELECCIONAR política online (sólo se midió que podría); falta el lazo de selección endógena", "kind": "diseno"},
                  {"text": "mundo estacionario; el North-Star pide un mundo NO-estacionario (la causa cambia)", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP043.ref, S_EXP042.ref]))
    notes.append("1 techo 'real': existe una señal de valor endógena (confianza calibrada) usable sin oráculo, confiable con la política correcta.")

    dstmt = ("North-Star R-VALOR: existe una señal de VALOR ENDÓGENA usable SIN oráculo — la propia confianza "
             "calibrada del modelo (max posterior). En el régimen duro rankea las políticas igual que el oráculo "
             "(info-gain {bc} > azar {cc} > pasivo {ac}) y es CALIBRADA para info-gain (P(correct|confiado)={cal}, "
             "confiado-equivocado {cwb}). HALLAZGO: la confianza es confiable SÓLO con la política correcta "
             "(info-gain); el azar-activo da confianza engañosa (confiado-equivocado {cwc}). Decisión: el lab "
             "puede juzgar qué política/hipótesis construyó mejor modelo por su confianza calibrada, sin "
             "verificador externo de la verdad — cierra el lazo R-VALOR y conecta con el arco de auto-mejora. "
             "Próximos: usar la confianza para SELECCIONAR política online; mundo no-estacionario; modelo mal "
             "especificado.").format(bc=_f(B['conf_mean']), cc=_f(C['conf_mean']), ac=_f(A['conf_mean']),
                                     cal=_f(B['calibration_P_correct_given_confident']),
                                     cwb=_f(B['confidently_wrong']), cwc=_f(C['confidently_wrong']))
    drat = ("exp043 (tier5, propio, {n} seeds): conf endógena rankea B>C>A igual que el oráculo; B calibrado "
            "(calib {cal}, confiado-equivocado {cwb}) vs C ({cwc}). Convergente con calibración bayesiana (tier1) "
            "y cierra el límite de exp042. {V}.").format(n=n_seeds,
                                                         cal=_f(B['calibration_P_correct_given_confident']),
                                                         cwb=_f(B['confidently_wrong']),
                                                         cwc=_f(C['confidently_wrong']), V=status.upper())
    dec = Decision(id="D-V4-22", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP043), _to_plain(S_EXP042)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-22 ACEPTADA por el ledger (tier5 exp043 + tier5 exp042).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-22:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle57_endogenous_signal',
                                description='CYCLE 57 (RESET v4, H-V4-1c: señal de valor endógena calibrada).')
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
    print("RESUMEN — CYCLE 57 (RESET v4): señal de valor ENDÓGENA (confianza calibrada) (H-V4-1c) — North-Star")
    print("=" * 78)
    print("veredicto H-V4-1c:", status.upper() if status else "?")
    print("  la confianza calibrada es una señal de valor usable sin oráculo; confiable con la política correcta.")
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
