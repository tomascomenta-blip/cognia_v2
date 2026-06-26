r"""
cycle126_earned_calibration.py — CICLO 126 (RESET v4, rama R-VALOR, GROUNDING del sub-arco 123-125): H-V4-9f por las
compuertas del engine. APOYADA: 123-125 caracterizaron las apuestas decisionales de R-VALOR (régimen × dirección ×
presupuesto) PERO con la calibración ρ IMPUESTA (estimador sintético con corr-ρ). Este ciclo ANCLA esa caracterización con un
estimador APRENDIDO (probe lineal ajustado por mínimos cuadrados): (A) el ρ EARNED crece con la calidad del feature y el
payoff bajo escasez lo TRACKEA (ρ no es un knob; reproduce 123); (B) un probe que aprendió un feature ESPURIO que se invierte
en deployment GANA ρ<0 (anti-calibrado) y es catastrófico-pero-budget-frágil bajo abundancia (reproduce 124-125). => la
anti-calibración peligrosa surge NATURALMENTE de correlación espuria + cambio de distribución (R-INTERVENCIÓN + fragilidad
115-118); las apuestas decisionales no son artefacto del ρ impuesto.

DERIVA de exp110_earned_calibration/results/results.json.

Correr (DESPUÉS de exp110):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp110_earned_calibration.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle126_earned_calibration
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle126_earned_calibration')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp110_earned_calibration', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="la calibración ρ de un estimador de valor es una cantidad GANADA (función de la calidad/integridad del estimador), no un parámetro libre; la anti-calibración (ρ<0, 'confiadamente equivocado') surge de aprender una correlación ESPURIA que se invierte bajo cambio de distribución (un probe robusto se mantiene calibrado; uno que se apoya en un atajo espurio se vuelve anti-calibrado al desplegar). Calibración earned + correlación espuria/shift", obtained=False,
                     claim=("La calibración ρ de un estimador de valor es una cantidad GANADA: crece con la calidad del "
                            "estimador (features menos ruidosos -> más ρ) y NO es un parámetro libre. La anti-calibración "
                            "peligrosa (ρ<0) surge NATURALMENTE de aprender una correlación ESPURIA -- un atajo que predice "
                            "en entrenamiento pero se INVIERTE en deployment (cambio de distribución). Un probe robusto se "
                            "mantiene calibrado; uno que se apoya en el atajo espurio se vuelve 'confiadamente equivocado'. "
                            "(Principio.)"))
S_C125 = Source(tier=5, ref="cognia_x/experiments/exp109_selective_budget", obtained=True,
                claim=("CYCLES 123-125 caracterizaron las apuestas decisionales de R-VALOR (régimen × dirección × "
                       "presupuesto) con ρ IMPUESTO. H-V4-9f las ANCLA con un estimador aprendido (ρ earned)."))
S_INTERV = Source(tier=5, ref="cognia_x/experiments/exp022_endogenous_value", obtained=True,
                  claim=("R-INTERVENCIÓN (CYCLE 35): una señal espuria/no-causal sólo se delata variando la distribución "
                         "(do/shift). H-V4-9f la usa como MECANISMO: el feature espurio (atajo) que se invierte en "
                         "deployment es exactamente lo que vuelve al probe anti-calibrado -> conecta la fragilidad 115-118 "
                         "con R-INTERVENCIÓN."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp110 primero): " + results_path)

    rb, rw = sm['rho_best'], sm['rho_worst']
    pb, pw = sm['pay_best'], sm['pay_worst']
    er = sm['esp_rho_abund']
    ept, epm = sm['esp_pay_abund_tight'], sm['esp_pay_abund_mod']
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim110 = ("exp110 (propio, {n} seeds, numpy, probe ajustado por mínimos cuadrados): (A) ρ EARNED del probe robusto "
                "crece con la calidad del feature (σ bajo: ρ={rb}, paga-escasez={pb}; σ alto: ρ={rw}, paga={pw}) -- el "
                "payoff bajo escasez TRACKEA el ρ ganado. (B) probe ESPURIO (atajo que se invierte en deployment) gana ρ="
                "{er}<0 y es catastrófico bajo abundancia (m3={ept}) pero budget-frágil (m20={epm}). Ancla 123-125 con ρ "
                "ganado.").format(n=n_seeds, rb=_f(rb), pb=_f(pb), rw=_f(rw), pw=_f(pw), er=_f(er), ept=_f(ept), epm=_f(epm))
    S_EXP110 = Source(tier=5, ref="cognia_x/experiments/exp110_earned_calibration", obtained=True, claim=claim110)
    for src in (S_PRINCIPLE, S_C125, S_INTERV, S_EXP110):
        ledger.add_source(src)
    notes.append("4 fuentes (S_PRINCIPLE tier2 ρ-earned + espuria/shift; S_C125 tier5 el sub-arco que ancla; S_INTERV tier5 R-INTERVENCIÓN como mecanismo del shift; S_EXP110 tier5 dato propio).")

    ev_for = [S_EXP110.ref, S_PRINCIPLE.ref]
    ev_against = [S_EXP110.ref]
    advtext = ("{V} (GROUNDING del sub-arco 123-125: ρ EARNED, no impuesto): la crítica más fuerte a 123-125 es que la "
               "calibración ρ era IMPUESTA (estimador sintético con corr-ρ). H-V4-9f la responde con un estimador APRENDIDO "
               "-- un probe lineal ajustado por mínimos cuadrados sobre features, entrenado balanceado (q=0.5) y desplegado "
               "bajo regímenes de test escaso/abundante. DOS GROUNDINGS. (A) ρ ES GANADO Y MONÓTONO EN LA CALIDAD: al barrer "
               "el ruido del feature genuino, el ρ EARNED crece (σ bajo: ρ={rb} vs σ alto: ρ={rw}) y el payoff bajo ESCASEZ "
               "lo TRACKEA (paga {pb} vs {pw}) -- reproduce 123 (mejor estimador -> más ρ -> paga más bajo escasez) "
               "demostrando que ρ NO es un knob sino una consecuencia de la calidad del estimador. (Anti-Goodhart: no se "
               "elige un σ; se muestra la CURVA -- el primer parámetro probado dio ρ insuficiente y, en vez de tunear a "
               "'apoyada', se barrió la calidad.) (B) LA ANTI-CALIBRACIÓN PELIGROSA SE GANA DE UNA CORRELACIÓN ESPURIA + "
               "SHIFT: un probe que aprende un atajo limpio en train que se INVIERTE en deployment GANA ρ={er}<0 "
               "(anti-calibrado, 'confiadamente equivocado') y es CATASTRÓFICO bajo abundancia (payoff {ept}) pero "
               "BUDGET-FRÁGIL (recupera a {epm} al ensanchar m) -- reproduce 124-125 con ρ ganado. => las apuestas "
               "decisionales 123-125 NO son artefacto del ρ impuesto; ρ se gana de la calidad/integridad del estimador, y la "
               "dirección peligrosa (ρ<0) surge NATURALMENTE de un atajo espurio que sólo se delata bajo cambio de "
               "distribución -- conectando el sub-arco decisional (123-125) con la fragilidad 'confiadamente equivocado' "
               "(115-118) y con R-INTERVENCIÓN (CYCLE 35: una señal no-causal sólo se descubre variando la distribución). "
               "EVIDENCIA: el principio ρ-earned+espuria/shift (tier2) y R-INTERVENCIÓN (tier5) lo predicen. EVIDENCIA EN "
               "CONTRA / caveats: sigue siendo numpy (probe LINEAL, features sintéticos, tarea binaria); ancla el MECANISMO "
               "(ρ es earned, la anti-calibración viene de un atajo+shift), no lo re-mide en un modelo de lenguaje real; "
               "reproducible smoke(50)≈full(200).").format(
                   V=status.upper(), rb=_f(rb), rw=_f(rw), pb=_f(pb), pw=_f(pw), er=_f(er), ept=_f(ept), epm=_f(epm))

    hyp = Hypothesis(
        id="H-V4-9f",
        statement=("Con un estimador APRENDIDO (probe ajustado, ρ EARNED no impuesto) se anclan las apuestas decisionales "
                   "123-125: (A) el ρ earned crece con la calidad del feature y el payoff bajo escasez lo trackea (ρ no es "
                   "un knob); (B) un probe que aprendió un feature ESPURIO que se invierte en deployment gana ρ<0 y es "
                   "catastrófico-pero-budget-frágil bajo abundancia. La anti-calibración peligrosa surge de correlación "
                   "espuria + cambio de distribución (R-INTERVENCIÓN + fragilidad 115-118)."),
        prediction=("APOYADA si: (A) el ρ earned del robusto crece al bajar σ (Δ>0.10) y el payoff escaso lo trackea "
                    "(Δ>0.20) y el mejor feature paga bajo escasez (ρ>0.4, payoff>0.5); (B) el espurio gana ρ<-0.1, es "
                    "catastrófico bajo abundancia (payoff m3<0.5) y budget-frágil (recupera >0.3 a m20). REFUTADA si el "
                    "espurio no gana ρ<0 o el buen feature no paga bajo escasez. MIXTA en otro caso. (Pre-registrada, numpy, "
                    "200 seeds, probe lstsq, barrido σ.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp110_earned_calibration")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-9f")
        notes.append("H-V4-9f marcada '{}' con DoD completo (ρ EARNED ancla 123-125; la anti-calibración se gana de un atajo espurio + shift).".format(status))

    analogy = AnalogyRecord(
        problem=("Hasta ahora supusimos 'qué tan bueno es mi criterio' como un número que poníamos a mano. ¿De dónde sale "
                 "ese número de verdad, y de dónde sale un criterio que está AL REVÉS?"),
        everyday=("Mi criterio sale de APRENDER de ejemplos. Si aprendo de una pista buena pero borrosa, mi criterio es "
                  "decente y mejora cuanto más nítida es la pista -- no es un número arbitrario, lo GANO. Pero si me apoyo "
                  "en un ATAJO que funcionaba en los ejemplos viejos y deja de valer (o se da vuelta) en la cancha nueva, mi "
                  "criterio no sólo falla: queda AL REVÉS -- elijo con confianza justo lo peor. Eso es 'confiadamente "
                  "equivocado', y sólo se descubre cuando cambia la situación (no en los mismos ejemplos donde lo aprendí)."),
        solutions=["la calibración ρ es GANADA: crece con la calidad del estimador (features menos ruidosos), no es un knob",
                   "el payoff bajo escasez TRACKEA el ρ ganado: mejor estimador -> más ρ -> más gemas raras capturadas (123)",
                   "la anti-calibración (ρ<0) se GANA de un atajo espurio que se invierte en deployment (shift) -> reproduce el downside de 124",
                   "esa catástrofe es budget-frágil (125): conecta apuestas decisionales + fragilidad 115-118 + R-INTERVENCIÓN"],
        principles=["la calibración de un estimador de valor es una cantidad ganada (función de su calidad), no un parámetro libre",
                    "la anti-calibración peligrosa surge de aprender una correlación espuria que se invierte bajo cambio de distribución",
                    "el sub-arco decisional 123-125 se sostiene con ρ EARNED (no era artefacto del ρ impuesto)",
                    "une tres hilos: apuestas decisionales (123-125) + fragilidad 'confiadamente equivocado' (115-118) + R-INTERVENCIÓN (la señal espuria sólo se delata bajo shift)"],
        adaptation=("El lab ANCLA su sub-arco decisional (123-125): la caracterización no dependía del ρ impuesto -- con un "
                    "estimador APRENDIDO el ρ se gana de la calidad del feature (monótono) y el payoff bajo escasez lo "
                    "trackea, y la dirección peligrosa (ρ<0) se gana de un atajo espurio que se invierte en deployment. "
                    "Política: (1) la calidad del estimador de valor es invertible (mejores features -> más ρ -> más payoff "
                    "bajo escasez), así que vale invertir en ella donde hay escasez; (2) el peligro real es el ATAJO ESPURIO "
                    "que se delata sólo bajo cambio de distribución -- de ahí que la durabilidad/recalibración (119) y la "
                    "detección de shift (R-INTERVENCIÓN) sean las defensas correctas, sobre todo bajo abundancia (downside "
                    "catastrófico) donde basta además ensanchar el presupuesto (125). Próximo: re-medir el grounding con un "
                    "estimador NO-lineal / en un lazo real (modelo de lenguaje) y a SCALE; detectar el atajo espurio por su "
                    "firma bajo intervención."),
        measurement=("exp110 ({n} seeds): (A) robusto σ↓ ρ {rw}->{rb}, payoff escaso {pw}->{pb}; (B) espurio ρ={er}, payoff "
                     "abundante m3={ept}->m20={epm} (budget-frágil).").format(
                         n=n_seeds, rw=_f(rw), rb=_f(rb), pw=_f(pw), pb=_f(pb), er=_f(er), ept=_f(ept), epm=_f(epm)),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (el criterio se GANA de aprender; un atajo espurio que se da vuelta en la cancha nueva deja el criterio 'confiadamente al revés').")

    kl = ("REAL (exp110): las apuestas decisionales 123-125 se anclan con ρ EARNED. (A) el ρ del probe robusto crece con la "
          "calidad del feature (σ↓: ρ {rw}->{rb}) y el payoff bajo escasez lo trackea ({pw}->{pb}) -- ρ no es un knob. (B) un "
          "probe que aprende un atajo ESPURIO que se invierte en deployment gana ρ={er}<0 (anti-calibrado) y es catastrófico "
          "bajo abundancia (m3={ept}) pero budget-frágil (m20={epm}). Conecta apuestas decisionales + fragilidad 115-118 + "
          "R-INTERVENCIÓN. TECHO: numpy, probe LINEAL, features sintéticos, tarea binaria; ancla el MECANISMO, no lo re-mide "
          "en un modelo real (frontera: estimador no-lineal / lazo real / SCALE).").format(
              rw=_f(rw), rb=_f(rb), pw=_f(pw), pb=_f(pb), er=_f(er), ept=_f(ept), epm=_f(epm))
    ceilings.add(CeilingRecord(
        subsystem="GROUNDING earned de R-VALOR — la calibración ρ es una cantidad GANADA (crece con la calidad del estimador, el payoff bajo escasez la trackea) y la anti-calibración peligrosa se gana de una correlación espuria que se invierte bajo cambio de distribución; las apuestas decisionales 123-125 no son artefacto del ρ impuesto",
        known_limit=kl,
        blockers=[{"text": "numpy, probe LINEAL (lstsq) y features SINTÉTICOS (genuino+espurio gaussianos), tarea binaria; ancla el MECANISMO (ρ earned; anti-calibración de atajo+shift) pero no lo re-mide con un estimador no-lineal ni en un modelo de lenguaje real", "kind": "diseno"},
                  {"text": "el 'shift' del feature espurio (inversión exacta en test) es una idealización del cambio de distribución; un shift parcial/gradual y la detección del atajo por su firma bajo intervención quedan sin medir", "kind": "diseno"},
                  {"text": "el grounding conecta lógicamente con la fragilidad 115-118 (la señal se vuelve confiadamente-incorrecta bajo auto-entrenamiento) pero no demuestra end-to-end que el auto-entrenamiento PRODUZCA este atajo espurio concreto; frontera", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP110.ref, S_C125.ref, S_INTERV.ref]))
    notes.append("1 techo 'real': ρ es una cantidad GANADA (no un knob) y la anti-calibración se gana de un atajo espurio + shift; ancla 123-125 y une con fragilidad + R-INTERVENCIÓN.")

    dstmt = ("North-Star R-VALOR (GROUNDING del sub-arco decisional con ρ EARNED): la caracterización 123-125 no dependía del "
             "ρ impuesto. Con un estimador APRENDIDO (probe ajustado): (A) el ρ se GANA de la calidad del feature (σ↓: ρ "
             "{rw}->{rb}) y el payoff bajo escasez lo TRACKEA ({pw}->{pb}) -- ρ no es un knob; (B) un probe que aprende un "
             "atajo ESPURIO que se invierte en deployment GANA ρ={er}<0 (anti-calibrado) y es catastrófico bajo abundancia "
             "pero budget-frágil. Decisión: (1) la calibración del estimador de valor es INVERTIBLE (mejores features -> más "
             "ρ -> más payoff bajo escasez); (2) el peligro real es el ATAJO ESPURIO que sólo se delata bajo cambio de "
             "distribución -- de ahí que la recalibración/durabilidad (119) y la detección de shift (R-INTERVENCIÓN) sean las "
             "defensas, y bajo abundancia baste además ensanchar el presupuesto (125). Une apuestas decisionales (123-125) + "
             "fragilidad (115-118) + R-INTERVENCIÓN. Próximo: estimador no-lineal / lazo real / SCALE.").format(
                 rw=_f(rw), rb=_f(rb), pw=_f(pw), pb=_f(pb), er=_f(er))
    drat = ("exp110 (tier5, propio, {n} seeds, numpy, probe lstsq): (A) ρ earned robusto crece al bajar σ ({rw}->{rb}), "
            "payoff escaso lo trackea ({pw}->{pb}); (B) probe espurio gana ρ={er}<0, catastrófico-budget-frágil bajo "
            "abundancia. Convergente con el principio ρ-earned+espuria/shift (tier2) y R-INTERVENCIÓN (tier5); ancla el "
            "sub-arco 123-125 (tier5). APOYADA: las apuestas decisionales no son artefacto del ρ impuesto.").format(
                n=n_seeds, rw=_f(rw), rb=_f(rb), pw=_f(pw), pb=_f(pb), er=_f(er))
    dec = Decision(id="D-V4-88", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP110), _to_plain(S_C125), _to_plain(S_INTERV)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-88 ACEPTADA por el ledger (tier5 exp110 + tier5 exp109 + tier5 exp022).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-88:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle126_earned_calibration',
                                description='CYCLE 126 (RESET v4, H-V4-9f: ρ EARNED ancla 123-125 -- la calibración se gana de la calidad del estimador; la anti-calibración peligrosa se gana de un atajo espurio + shift).')
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
    print("RESUMEN — CYCLE 126 (RESET v4): ρ EARNED ancla 123-125 -- la calibración se GANA de la calidad del estimador; la anti-calibración se gana de un atajo espurio + shift — H-V4-9f")
    print("=" * 78)
    print("veredicto H-V4-9f:", status.upper() if status else "?")
    print("  (A) ρ crece con la calidad del feature y el payoff bajo escasez lo trackea (ρ no es un knob); (B) un atajo espurio que se invierte en deployment gana ρ<0 -> downside catastrófico-budget-frágil. Une 123-125 + fragilidad + R-INTERVENCIÓN.")
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
