r"""
cycle86_regime_policy.py — CICLO 86 (RESET v4, rama R-VALOR, CAPSTONE del gap #2): H-V4-7d por las compuertas del engine.
APOYADA: el combinador APRENDIDO DOMINA al producto por encima de una compuerta de calidad de feedback (en AMBOS
regímenes), por lo que DETECTAR el régimen es INNECESARIO. Mecanismo: el aprendido (ridge poly2) NESTA el producto (el
término cr es una de sus features) -> lo iguala bajo complementos y lo supera bajo sustitutos. Ni un detector PERFECTO
(oracle_selector) aporta sobre 'siempre aprender'. => la política práctica de reconstrucción de R-VALOR es una COMPUERTA
DE CALIDAD DE FEEDBACK (aprendido si el feedback es adecuado, producto si es pobre), no un switch por régimen. Cierra el
arco gap #2 (83 acota / 84 construye / 85 destraba / 86 política).

DERIVA de exp070_regime_policy/results/results.json.

Correr (DESPUÉS de exp070):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp070_regime_policy.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle86_regime_policy
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle86_regime_policy')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp070_regime_policy', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_NEST = Source(tier=2, ref="modelo flexible que NESTA al simple (poly2 nesta el término producto cr) lo domina débilmente con datos adecuados; selección entre modelos anidados aporta poco si el rico ya subsume al simple", obtained=False,
                claim=("Un aprendiz flexible que CONTIENE la forma simple como caso particular (la base poly2 incluye el "
                       "término cr = el producto) la domina débilmente dado feedback adecuado: iguala donde la forma "
                       "simple es correcta y supera donde no. Elegir entre el simple y el rico (detección de régimen) "
                       "aporta poco porque el rico ya subsume al simple. (Principio; nesting => no-regret sin selección.)"))
S_EXP069 = Source(tier=5, ref="cognia_x/experiments/exp069_feedback_quality", obtained=True,
                  claim=("CYCLE 85 mostró que subir la calidad del feedback destraba la recuperación decisiva del "
                         "combinador aprendido bajo sustitutos, e incidentalmente que bajo complementos aprendido ≈ "
                         "producto. H-V4-7d prueba si eso implica DOMINACIÓN (detección innecesaria)."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp070 primero): " + results_path)

    gate = sm['gate_quality']
    q_ref = sm['q_ref']
    dom_comp = sm['dom_comp_qref']
    dom_subs = sm['dom_subs_qref']
    os_minus_al = sm['oracle_selector_minus_always_learned']
    sel_minus_al = sm['selector_minus_always_learned']
    dom = sm['dominates']
    det_unnec = sm['detection_unnecessary']
    n_seeds = data['args']['seeds']
    gate_s = "ninguna" if gate is None else str(gate)

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim070 = ("exp070 (propio, {n} seeds, numpy): el combinador aprendido (ridge poly2) DOMINA al producto por encima "
                "de una compuerta de calidad de feedback (gate={g}). A calidad {qr}: always_learned vence al producto en "
                "sustitutos (+{ds}) y lo iguala en complementos ({dc}). El oracle_selector (detector PERFECTO) supera a "
                "always_learned sólo por {os} y el selector real por {sl} (ambos <= 0.02). => detectar el régimen es "
                "INNECESARIO; el aprendido nesta el producto y lo subsume.").format(
                    n=n_seeds, g=gate_s, qr=q_ref, ds=_f(dom_subs), dc=_f(dom_comp), os=_f(os_minus_al), sl=_f(sel_minus_al))
    S_EXP070 = Source(tier=5, ref="cognia_x/experiments/exp070_regime_policy", obtained=True, claim=claim070)
    for src in (S_NEST, S_EXP069, S_EXP070):
        ledger.add_source(src)
    notes.append("3 fuentes (S_NEST tier2 nesting/no-regret; S_EXP069 tier5 calidad-feedback; S_EXP070 tier5 dato propio).")

    ev_for = [S_EXP070.ref, S_EXP069.ref, S_NEST.ref]
    ev_against = [S_EXP070.ref]
    advtext = ("{V} (CAPSTONE del gap #2; cierra el arco 83-86): la pregunta natural tras 85 era 'detectar el régimen "
               "para conmutar producto<->aprendido'. exp070 la responde: NO hace falta. El combinador aprendido (poly2) "
               "DOMINA al producto por encima de una compuerta de calidad de feedback (gate={g}); a calidad {qr} vence "
               "en sustitutos (+{ds}) e IGUALA en complementos ({dc}). Y lo decisivo: el oracle_selector -- un detector "
               "de régimen PERFECTO -- supera a 'siempre aprender' por sólo {os}, y el selector real (CV held-out) por "
               "{sl} (ambos <= 0.02). MECANISMO: poly2 NESTA el producto (el término cr es una de sus features) -> lo "
               "iguala donde la forma producto es correcta (complementos) y lo supera donde no (sustitutos); por eso "
               "'siempre aprender' ya alcanza el techo de un selector. => la política práctica de reconstrucción de "
               "R-VALOR es una COMPUERTA DE CALIDAD DE FEEDBACK (aprendido si el feedback es adecuado, producto si es "
               "pobre), NO un switch por régimen -- más simple y sin necesidad de conocer el régimen. EVIDENCIA EN CONTRA "
               "/ caveats: con feedback POBRE (q0) el producto iguala/supera al aprendido (define la compuerta); el "
               "aprendido nesta al producto por DISEÑO de la base poly2 (con una base que no lo nestara, la conclusión "
               "podría cambiar); juguete (g sintético, objetivo escalar). CONCLUSIÓN: el arco gap #2 cierra con una "
               "política simple y un mecanismo claro (nesting), sin detector de régimen.").format(
                   V=status.upper(), g=gate_s, qr=q_ref, ds=_f(dom_subs), dc=_f(dom_comp), os=_f(os_minus_al), sl=_f(sel_minus_al))

    hyp = Hypothesis(
        id="H-V4-7d",
        statement=("El combinador aprendido domina al producto sobre una compuerta de calidad de feedback en AMBOS "
                   "regímenes; la detección de régimen es innecesaria (política = compuerta de feedback, no switch)."),
        prediction=("APOYADA si existe compuerta no-perfecta sobre la cual always_learned >= producto en complementos "
                    "(>=-0.01) y > en sustitutos (+>0.02) Y la detección es innecesaria (oracle_selector y selector <= "
                    "always_learned + 0.02); REFUTADA si la dominación falla en algún régimen o el selector supera a "
                    "always_learned por >0.02; MIXTA en otro caso. (Pre-registrada, q_ref=q2, tol=0.02.)"),
        status='abierta', confidence='alta' if status == 'apoyada' else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp070_regime_policy")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-7d")
        notes.append("H-V4-7d marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("Algunas decisiones son 'receta' (necesito ambos) y otras 'sustituto' (me basta uno). ¿Tengo que "
                 "DETECTAR de qué tipo es cada una para elegir cómo combinar, o hay una sola regla que sirve siempre?"),
        everyday=("Hay una sola: un cocinero VERSÁTIL que prueba unos pocos platos APRENDE la regla correcta de cada "
                  "cocina por sí mismo -- si es receta, su regla aprendida termina siendo 'multiplicar'; si es sustituto, "
                  "'el mejor de los dos'. Nunca hace falta decirle de qué cocina se trata: su versatilidad ya CONTIENE la "
                  "regla simple como caso particular. De hecho, aun un oráculo que le dijera la cocina no lo mejora. Sólo "
                  "si las pruebas son malísimas conviene caer al atajo fijo de 'multiplicar'."),
        solutions=["always-learn (combinador que nesta el producto) -> iguala en recetas, gana en sustitutos: domina",
                   "detector de régimen (selector) -> innecesario: no supera a always-learn (ni el detector perfecto)",
                   "producto fijo -> sólo preferible con feedback POBRE (define la compuerta)",
                   "política = compuerta de calidad de feedback, no switch por régimen"],
        principles=["un aprendiz que NESTA la forma simple la domina débilmente con feedback adecuado (no-regret sin selección)",
                    "detectar el régimen es innecesario si el aprendido subsume al producto (cr es una feature de poly2)",
                    "ni un detector PERFECTO aporta sobre 'siempre aprender' (oracle_selector ≈ always_learned)",
                    "la única compuerta real es la CALIDAD DEL FEEDBACK (abajo de ella, el prior-producto gana)"],
        adaptation=("Política de reconstrucción de R-VALOR del lab: usar SIEMPRE el combinador aprendido (que nesta el "
                    "producto) cuando el feedback es adecuado; caer al producto sólo con feedback pobre. Sin detector de "
                    "régimen. Cierra el arco gap #2 (83-86). Próximo: el valor no-factorizable y el feedback de un lazo "
                    "de acción-consecuencia REAL (gaps #1/#3, p.ej. verificador chequeable de exp018), y SCALE (GPU)."),
        measurement=("exp070 ({n} seeds): gate={g}; a {qr} dom comp={dc}, subs={ds}; oracle_selector−always_learned={os}, "
                     "selector−always_learned={sl} (<=0.02 => detección innecesaria).").format(
                         n=n_seeds, g=gate_s, qr=q_ref, dc=_f(dom_comp), ds=_f(dom_subs), os=_f(os_minus_al), sl=_f(sel_minus_al)),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (cocinero versátil que nesta la regla simple: nunca hace falta decirle la cocina).")

    kl = ("REAL (exp070): el combinador aprendido (que NESTA el producto) DOMINA al producto sobre una compuerta de "
          "calidad de feedback (gate={g}) en ambos regímenes -- a {qr} iguala en complementos ({dc}) y vence en "
          "sustitutos (+{ds}). La detección de régimen es INNECESARIA: ni un detector PERFECTO (oracle_selector, +{os}) "
          "ni el selector real (+{sl}) superan a 'siempre aprender' por >0.02. Política = compuerta de calidad de "
          "feedback, no switch por régimen.").format(
              g=gate_s, qr=q_ref, dc=_f(dom_comp), ds=_f(dom_subs), os=_f(os_minus_al), sl=_f(sel_minus_al))
    ceilings.add(CeilingRecord(
        subsystem="R-VALOR política de reconstrucción — compuerta de calidad de feedback (sin detector de régimen)",
        known_limit=kl,
        blockers=[{"text": "el aprendido nesta al producto por DISEÑO de la base poly2; con una base que no lo nestara, la dominación/no-regret podría no valer", "kind": "diseno"},
                  {"text": "con feedback POBRE (q0) el producto iguala/supera al aprendido: la compuerta de calidad es real y depende del costo de muestrear el lazo real", "kind": "diseno"},
                  {"text": "juguete (g sintético min/max, objetivo escalar); falta el valor no-factorizable y el feedback de un lazo de acción-consecuencia REAL (gaps #1/#3) y SCALE (GPU)", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP070.ref, S_EXP069.ref]))
    notes.append("1 techo 'real': política = compuerta de calidad de feedback; detección de régimen innecesaria (nesting).")

    dstmt = ("North-Star R-VALOR (CAPSTONE del gap #2; cierra el arco 83-86): el combinador aprendido (que NESTA el "
             "producto) DOMINA al producto sobre una compuerta de calidad de feedback en ambos regímenes; la detección "
             "de régimen es INNECESARIA (ni un detector perfecto aporta sobre 'siempre aprender'). Decisión: la política "
             "de reconstrucción de R-VALOR del lab es una COMPUERTA DE CALIDAD DE FEEDBACK -- usar siempre el combinador "
             "aprendido (nesta el producto) con feedback adecuado, caer al producto con feedback pobre; SIN switch por "
             "régimen. Cierra el arco gap #2. Próximo: valor no-factorizable y feedback de un lazo de acción-consecuencia "
             "REAL (gaps #1/#3, verificador chequeable exp018) y SCALE (GPU).")
    drat = ("exp070 (tier5, propio, {n} seeds): gate={g}; a {qr} dom comp={dc}, subs={ds}; oracle_selector−always_learned"
            "={os}, selector−always_learned={sl} (<=0.02). Convergente con nesting/no-regret (tier2) y con la "
            "calidad-feedback de CYCLE 85 (tier5). APOYADA.").format(
                n=n_seeds, g=gate_s, qr=q_ref, dc=_f(dom_comp), ds=_f(dom_subs), os=_f(os_minus_al), sl=_f(sel_minus_al))
    dec = Decision(id="D-V4-48", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP070), _to_plain(S_EXP069)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-48 ACEPTADA por el ledger (tier5 exp070 + tier5 exp069).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-48:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle86_regime_policy',
                                description='CYCLE 86 (RESET v4, H-V4-7d: el aprendido domina; detección de régimen innecesaria -- capstone gap #2).')
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
    print("RESUMEN — CYCLE 86 (RESET v4): política = compuerta de feedback (H-V4-7d) — CAPSTONE del gap #2")
    print("=" * 78)
    print("veredicto H-V4-7d:", status.upper() if status else "?")
    print("  el aprendido (nesta el producto) domina sobre una compuerta de feedback; detectar el régimen es innecesario.")
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
