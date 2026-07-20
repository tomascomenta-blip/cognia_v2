r"""
cycle132_nonlinear_keystone.py — CICLO 132 (RESET v4, rama control/acción, ROBUSTEZ del keystone a NO-LINEALIDAD; MIXTA tras
VERIFICACIÓN ADVERSARIAL): H-V4-10f por las compuertas del engine. ¿Sobrevive el keystone (129: el control reconstruye
R-VALOR = controlabilidad × relevancia) a control NO-LINEAL saturante? RESULTADO VERIFICADO: el PRINCIPIO sobrevive PERO la
controlabilidad debe ser de ALCANCE/ESFUERZO -- la PENDIENTE LOCAL (b̂ lineal, la del keystone 129) es CIEGA a la saturación.
valor_eff (alcance al esfuerzo U_max) es robustamente óptimo en TODO ancho de probe; valor_lin (pendiente local) a probe
genuinamente local COLAPSA a nivel relevancia (régimen sat) o por DEBAJO (régimen break: ganancia/alcance anti-correlados).

EJEMPLO DEL MÉTODO (2do ciclo consecutivo): una 1ra versión, con el ancho del probe σ_p=0.4 HARDCODEADO, daba "APOYADA: la
pendiente local basta, el keystone es robusto tal cual". Una VERIFICACIÓN ADVERSARIAL (workflow de 3 agentes) la corrigió:
σ_p=0.4 NO es local respecto de τ=0.3, así que b̂ ya sentía la saturación encubiertamente (proxy crudo de alcance); con probe
genuinamente local valor_lin se rompe. La intuición ORIGINAL ('necesita reach-aware') era correcta; el reencuadre a APOYADA
era el artefacto.

DERIVA de exp116_nonlinear_keystone/results/results.json.

Correr (DESPUÉS de exp116):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp116_nonlinear_keystone.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle132_nonlinear_keystone
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle132_nonlinear_keystone')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp116_nonlinear_keystone', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="bajo control NO-LINEAL saturante, la controlabilidad relevante para R-VALOR es el ALCANCE/ESFUERZO (cuán lejos podés empujar al esfuerzo de control), NO la pendiente local: la pendiente local es CIEGA a la saturación (un modo de pendiente alta pero alcance bajo no es controlable), y un estimador local mis-rankea; el alcance es la forma no-lineal del costo de acción. Controlabilidad de-alcance bajo no-linealidad", obtained=False,
                     claim=("Bajo control NO-LINEAL saturante, la controlabilidad que importa para R-VALOR es el ALCANCE/"
                            "ESFUERZO (cuán lejos podés empujar un modo al esfuerzo de control disponible), NO la PENDIENTE "
                            "LOCAL. Un estimador de pendiente local es CIEGO a la saturación: confunde un modo de pendiente "
                            "alta pero alcance bajo (inalcanzable) con uno verdaderamente controlable, y mis-rankea. El "
                            "alcance es la forma NO-LINEAL del costo/esfuerzo de acción. (Principio.)"))
S_C129 = Source(tier=5, ref="cognia_x/experiments/exp113_value_factorization", obtained=True,
                claim=("CYCLE 129 (keystone): el control reconstruye R-VALOR = controlabilidad × relevancia, con "
                       "controlabilidad estimada por la PENDIENTE LINEAL b̂. H-V4-10f testea su robustez a la no-linealidad: "
                       "el PRINCIPIO sobrevive pero la pendiente local b̂ NO -- hace falta reach-aware."))
S_C130 = Source(tier=5, ref="cognia_x/experiments/exp114_graded_value", obtained=True,
                claim=("CYCLE 130: la controlabilidad-DESCONTADA-por-costo b²/(b²+ρ) es el factor de control bajo costo "
                       "lineal. H-V4-10f lo GENERALIZA: bajo no-linealidad (saturación) la controlabilidad correcta es el "
                       "ALCANCE -- la forma no-lineal del costo/esfuerzo."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp116 primero): " + results_path)

    em = sm['eff_min']; ll = sm['lin_loc_sat']; rs = sm['rel_sat']; pc = sm['probe_contingent']
    lb = sm['lin_loc_break']; rb = sm['rel_break']
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim116 = ("exp116 (propio, {n} seeds, numpy, post-verificación adversarial): bajo control NO-LINEAL saturante, la "
                "controlabilidad de ALCANCE (valor_eff) es robustamente óptima en todo ancho de probe (min {em}); la PENDIENTE "
                "LOCAL (valor_lin) es CIEGA -- a probe local en saturación colapsa a {ll}≈relevancia ({rs}), sube +{pc} sólo "
                "al ensanchar el probe (reach-awareness encubierta), y con ganancia/alcance anti-correlados cae a {lb} < "
                "relevancia ({rb}). La controlabilidad del keystone debe ser de ALCANCE bajo no-linealidad.").format(
                    n=n_seeds, em=_f(em), ll=_f(ll), rs=_f(rs), pc=_f(pc), lb=_f(lb), rb=_f(rb))
    S_EXP116 = Source(tier=5, ref="cognia_x/experiments/exp116_nonlinear_keystone", obtained=True, claim=claim116)
    for src in (S_PRINCIPLE, S_C129, S_C130, S_EXP116):
        ledger.add_source(src)
    notes.append("4 fuentes (S_PRINCIPLE tier2 controlabilidad de-alcance bajo no-linealidad; S_C129 tier5 el keystone testeado; S_C130 tier5 cost-aware que se generaliza; S_EXP116 tier5 dato propio post-verificación).")

    ev_for = [S_EXP116.ref, S_PRINCIPLE.ref]
    ev_against = [S_EXP116.ref]
    advtext = ("{V} (el keystone sobrevive a la NO-LINEALIDAD SÓLO con controlabilidad de ALCANCE; 2do EJEMPLO consecutivo de "
               "verificación adversarial atrapando un artefacto): ¿sobrevive el keystone (129: el control reconstruye R-VALOR "
               "= controlabilidad × relevancia) a control NO-LINEAL saturante (x'=a·x+b·τ·tanh(u/τ)+ruido, efecto satura en "
               "±b·τ)? RESULTADO VERIFICADO: el PRINCIPIO valor=ctrl×rel sobrevive (le gana a relevancia-sola y a predicción "
               "bajo saturación) PERO la controlabilidad debe ser de ALCANCE/ESFUERZO, NO la pendiente local. La "
               "controlabilidad de ALCANCE (valor_eff = alcance al esfuerzo U_max) es robustamente óptima en TODO ancho de "
               "probe y régimen (min {em}). La PENDIENTE LOCAL del keystone 129 (valor_lin) es CIEGA a la saturación: a probe "
               "GENUINAMENTE LOCAL (σ_p≪τ) en saturación COLAPSA a {ll}≈relevancia ({rs}); su robustez es PROBE-WIDTH-"
               "CONTINGENTE (sube +{pc} al ensanchar el probe -- ahí b̂ deja de ser local y siente el alcance encubiertamente); "
               "y con ganancia/alcance ANTI-correlacionados (modos de pendiente ALTA pero alcance BAJO) valor_lin a probe "
               "local cae a {lb} -- PEOR que relevancia ({rb}): la pendiente local PREFIERE activamente los modos "
               "INALCANZABLES. => bajo no-linealidad la controlabilidad del keystone es el ALCANCE (cuán lejos podés empujar), "
               "que GENERALIZA la controlabilidad-descontada-por-costo de 130 (la saturación es la forma no-lineal del costo). "
               "META: la 1ra versión de este ciclo, con el ancho del probe σ_p=0.4 HARDCODEADO (no local respecto de τ=0.3), "
               "daba 'APOYADA: la pendiente local basta'; una VERIFICACIÓN ADVERSARIAL (3 agentes) la corrigió mostrando que "
               "esa robustez era el artefacto de un probe no-local que ve el alcance encubiertamente -- la intuición ORIGINAL "
               "('necesita reach-aware') era correcta. Es el 2do ciclo consecutivo (con 131) en que la verificación "
               "adversarial atrapa un artefacto antes del ledger -> institucionalizarla. EVIDENCIA: el principio (tier2) lo "
               "predice; generaliza 130 (tier5). EVIDENCIA EN CONTRA / caveats: numpy lineal-en-el-sustrato (la no-linealidad "
               "es sólo el tanh del control); el control es ORACLE (aísla la asignación); la afirmación robusta es que la "
               "controlabilidad de-alcance es σ-robusta y la local es ciega.").format(
                   V=status.upper(), em=_f(em), ll=_f(ll), rs=_f(rs), pc=_f(pc), lb=_f(lb), rb=_f(rb))

    hyp = Hypothesis(
        id="H-V4-10f",
        statement=("El keystone (valor=controlabilidad×relevancia) SOBREVIVE a control no-lineal saturante PERO sólo con "
                   "controlabilidad de ALCANCE/ESFUERZO (valor_eff robustamente óptimo en todo ancho de probe); la PENDIENTE "
                   "LOCAL del keystone 129 (valor_lin) es CIEGA a la saturación -- a probe local colapsa a relevancia (sat) o "
                   "por debajo (break, ganancia/alcance anti-correlados). La controlabilidad debe ser de alcance, "
                   "generalizando la controlabilidad-descontada-por-costo de 130."),
        prediction=("APOYADA si la pendiente local basta aun a probe local; REFUTADA si ni el alcance sobrevive; MIXTA si el "
                    "PRINCIPIO sobrevive con controlabilidad de alcance pero la pendiente local es ciega (probe-width-"
                    "contingente, colapsa a probe local). (Pre-registrada en su 2da versión tras verificación adversarial: "
                    "numpy, barrido del ancho de probe σ_p, 200 seeds.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp116_nonlinear_keystone")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-10f")
        notes.append("H-V4-10f marcada '{}' con DoD completo (keystone sobrevive a la no-linealidad sólo con controlabilidad de ALCANCE; la pendiente local es ciega; APOYADA inicial corregida por verificación adversarial).".format(status))

    analogy = AnalogyRecord(
        problem=("Si para mover algo hay un LÍMITE de cuánto podés empujarlo (se traba), ¿basta mirar qué tan FÁCIL arranca "
                 "(la respuesta inicial) para saber cuáles cosas controlás, o tenés que ver hasta DÓNDE llegan?"),
        everyday=("Tenés que ver hasta DÓNDE llegan. Una perilla que arranca facilísimo pero se traba enseguida (mucha "
                  "respuesta inicial, poco recorrido) NO te sirve para llegar lejos. Si elijo en qué perillas concentrarme "
                  "mirando sólo el arranque, me engaño: agarro las que reaccionan fuerte pero no llegan a ningún lado -- y "
                  "puede ser PEOR que elegir al azar. Para saber qué controlás de verdad tenés que EMPUJAR FUERTE y ver el "
                  "ALCANCE, no tantear suavecito."),
        solutions=["bajo control no-lineal (saturante), la controlabilidad real es el ALCANCE (cuán lejos llegás), no la respuesta inicial (pendiente local)",
                   "la pendiente local es CIEGA a la saturación: a tanteo suave no distingue una perilla de alto-arranque-poco-recorrido de una de recorrido largo",
                   "el keystone (valor=ctrl×rel) sobrevive a la no-linealidad PERO con controlabilidad de alcance; la lineal falla y puede ser peor que mirar sólo relevancia",
                   "el alcance es la forma no-lineal del costo/esfuerzo de 130: cuán lejos podés empujar al esfuerzo disponible"],
        principles=["bajo no-linealidad la controlabilidad de R-VALOR es el ALCANCE/ESFUERZO, no la pendiente local",
                    "un estimador de pendiente local es ciego a la saturación y mis-rankea (probe-width-contingente)",
                    "el PRINCIPIO valor=ctrl×rel sobrevive a la no-linealidad; su factor de controlabilidad NO es lineal",
                    "META: 2do ciclo consecutivo donde la verificación adversarial atrapa un artefacto (probe oculto) antes del ledger -> institucionalizarla"],
        adaptation=("El lab testea la robustez de su keystone (129) a la no-linealidad y obtiene un hallazgo más fino + una "
                    "lección de método. El PRINCIPIO valor=controlabilidad×relevancia SOBREVIVE al control no-lineal "
                    "saturante, PERO la controlabilidad debe ser de ALCANCE/ESFUERZO (cuán lejos podés empujar al esfuerzo de "
                    "control), no la PENDIENTE LOCAL de la versión lineal 129 -- que es CIEGA a la saturación y, a tanteo "
                    "genuinamente local, colapsa a nivel relevancia o por debajo (eligiendo modos de alto-arranque-bajo-"
                    "alcance). Esto GENERALIZA la controlabilidad-descontada-por-costo de 130 (la saturación es la forma "
                    "no-lineal del costo). Política: estimar la controlabilidad por ALCANCE al esfuerzo de control (sondear a "
                    "la escala del control), no por respuesta local. META-LECCIÓN: 2do ciclo seguido (con 131) en que la "
                    "verificación adversarial atrapa un artefacto (aquí, un ancho de probe oculto que fabricaba la robustez); "
                    "institucionalizar la verificación adversarial como compuerta. Próximo: la no-linealidad en el SUSTRATO "
                    "(no sólo en el control); el lazo real; active inference formal."),
        measurement=("exp116 ({n} seeds): valor_eff min {em} (robusto); valor_lin sat-local {ll}≈relev {rs} (+{pc} al "
                     "ensanchar el probe); break-local {lb} < relev {rb}.").format(
                         n=n_seeds, em=_f(em), ll=_f(ll), rs=_f(rs), pc=_f(pc), lb=_f(lb), rb=_f(rb)),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (para saber qué controlás bajo saturación mirá el ALCANCE -empujá fuerte-, no el arranque suave).")

    kl = ("REAL (exp116, post-verificación adversarial): el keystone (valor=ctrl×rel) SOBREVIVE a control NO-LINEAL saturante "
          "pero sólo con controlabilidad de ALCANCE/ESFUERZO (valor_eff robustamente óptimo, min {em}, en todo ancho de probe); "
          "la PENDIENTE LOCAL del keystone 129 (valor_lin) es CIEGA a la saturación -- a probe local colapsa a {ll}≈relevancia "
          "({rs}), probe-width-contingente (+{pc} al ensanchar), y con ganancia/alcance anti-correlados {lb} < relevancia "
          "({rb}). Generaliza la controlabilidad-descontada-por-costo de 130. TECHO: numpy, no-linealidad sólo en el control "
          "(tanh), control oracle (aísla la asignación); frontera: no-linealidad en el sustrato, lazo real, active inference.").format(
              em=_f(em), ll=_f(ll), rs=_f(rs), pc=_f(pc), lb=_f(lb), rb=_f(rb))
    ceilings.add(CeilingRecord(
        subsystem="Robustez del keystone a la NO-LINEALIDAD — el principio valor=ctrl×rel sobrevive al control no-lineal saturante PERO la controlabilidad debe ser de ALCANCE/ESFUERZO (valor_eff robusto); la PENDIENTE LOCAL (b̂ lineal del keystone 129) es ciega a la saturación y falla (probe-width-contingente, colapsa a probe local, peor que relevancia con ganancia/alcance anti-correlados); generaliza la controlabilidad-descontada-por-costo de 130",
        known_limit=kl,
        blockers=[{"text": "numpy; la no-linealidad está sólo en el CONTROL (tanh saturante), no en el sustrato; el control es ORACLE (aísla la asignación, no mide el efecto de un control basado en modelo estimado)", "kind": "diseno"},
                  {"text": "la controlabilidad de ALCANCE se estima con un probe AGRESIVO a ±U_max conocido; en un sistema real el esfuerzo de control disponible y la forma de la no-linealidad habría que descubrirlos -- el alcance asume U_max dado", "kind": "diseno"},
                  {"text": "META/honestidad: la 1ra versión daba APOYADA por un ARTEFACTO (ancho de probe σ_p=0.4 hardcodeado, no-local respecto de τ, que daba reach-awareness encubierta a la pendiente 'local'); corregido por verificación adversarial (3 agentes) -> 2do ciclo seguido (con 131) que exige institucionalizar esa compuerta", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP116.ref, S_C129.ref, S_C130.ref]))
    notes.append("1 techo 'real': el keystone sobrevive a la no-linealidad sólo con controlabilidad de ALCANCE; la pendiente local es ciega; APOYADA inicial corregida por verificación adversarial.")

    dstmt = ("North-Star R-VALOR (robustez del keystone a la NO-LINEALIDAD + lección de método): el PRINCIPIO valor="
             "controlabilidad×relevancia SOBREVIVE al control no-lineal saturante, PERO la controlabilidad debe ser de "
             "ALCANCE/ESFUERZO (valor_eff robustamente óptimo en todo ancho de probe, min {em}), NO la PENDIENTE LOCAL de la "
             "versión lineal 129 (valor_lin) -- que es CIEGA a la saturación: a probe local colapsa a relevancia ({ll}≈{rs}), "
             "es probe-width-contingente, y con ganancia/alcance anti-correlados es PEOR que relevancia ({lb}<{rb}). Decisión: "
             "estimar la controlabilidad por ALCANCE al esfuerzo de control (sondear a la escala del control), no por "
             "respuesta local; esto GENERALIZA la controlabilidad-descontada-por-costo de 130 (la saturación = forma no-lineal "
             "del costo). META-DECISIÓN: 2do ciclo seguido (con 131) donde la verificación adversarial atrapa un artefacto "
             "(ancho de probe oculto) -> institucionalizarla como compuerta. Próximo: no-linealidad en el sustrato, lazo real, "
             "active inference.").format(em=_f(em), ll=_f(ll), rs=_f(rs), lb=_f(lb), rb=_f(rb))
    drat = ("exp116 (tier5, propio, {n} seeds, numpy, post-verificación de 3 agentes): valor_eff robusto (min {em}) vs "
            "valor_lin ciego (sat-local {ll}≈relev {rs}, +{pc} contingente; break-local {lb}<relev {rb}). Convergente con el "
            "principio de controlabilidad-de-alcance (tier2); generaliza 130 (tier5); testea el keystone 129 (tier5). MIXTA: "
            "el principio sobrevive, la pendiente local no.").format(
                n=n_seeds, em=_f(em), ll=_f(ll), rs=_f(rs), pc=_f(pc), lb=_f(lb), rb=_f(rb))
    dec = Decision(id="D-V4-94", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP116), _to_plain(S_C129), _to_plain(S_C130)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-94 ACEPTADA por el ledger (tier5 exp116 + tier5 exp113 + tier5 exp114).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-94:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle132_nonlinear_keystone',
                                description='CYCLE 132 (RESET v4, H-V4-10f MIXTA: el keystone sobrevive a la no-linealidad sólo con controlabilidad de ALCANCE; la pendiente local es ciega; APOYADA inicial corregida por verificación adversarial).')
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
    print("RESUMEN — CYCLE 132 (RESET v4): el keystone sobrevive a la NO-LINEALIDAD sólo con controlabilidad de ALCANCE; la pendiente local es ciega — H-V4-10f")
    print("=" * 78)
    print("veredicto H-V4-10f:", status.upper() if status else "?")
    print("  el principio valor=ctrl×rel sobrevive, pero la controlabilidad debe ser de ALCANCE/ESFUERZO; la pendiente local (lineal, 129) es ciega a la saturación. Verificación adversarial corrigió un APOYADA artefactual (2do ciclo seguido).")
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
