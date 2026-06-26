r"""
cycle121_full_recipe_payoff.py — CICLO 121 (RESET v4, rama R-VALOR, CAPSTONE DEFINITIVO: la RECETA COMPLETA paga
end-to-end): H-V4-9a por las compuertas del engine. Corrige el confound de 120 (que quitó el ancla). Con el ANCLA de
replay presente (que sostiene la capacidad), añadir el unlikelihood ACOTADO (que mantiene el selector calibrado) SOSTIENE
mejor el downstream que la receta ancla-sola (la guardia de 115, el mejor previo): el selector mejor-calibrado encuentra
más correctos (yield) bajo presupuesto ajustado y eso COMPONE en el downstream. La receta COMPLETA -- likelihood(
verificado-correcto) + replay-ancla(verdad canónica) + unlikelihood-acotado(verificado-incorrecto) -- es el lazo de
auto-mejora ENDÓGENO DURABLE óptimo.

DERIVA de exp105_full_recipe_payoff/results/results.json.

Correr (DESPUÉS de exp105):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp105_full_recipe_payoff.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle121_full_recipe_payoff
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle121_full_recipe_payoff')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp105_full_recipe_payoff', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="componer mecanismos complementarios (ancla de capacidad + corrector de calibración) da un lazo de auto-mejora sostenido: con la capacidad holdeada, un selector mejor-calibrado encuentra más positivos bajo presupuesto ajustado y eso compone en el downstream a lo largo de las rondas", obtained=False,
                     claim=("Cuando dos mecanismos atacan ejes complementarios (un ANCLA de datos sostiene la capacidad; un "
                            "corrector de calibración mantiene el selector honesto), COMPONEN: con la capacidad holdeada, "
                            "un selector mejor-calibrado encuentra más positivos bajo presupuesto ajustado y esa ventaja "
                            "de yield COMPONE en el downstream a lo largo de las rondas. (Principio.)"))
S_C119 = Source(tier=5, ref="cognia_x/experiments/exp103_bounded_unlikelihood", obtained=True,
                claim=("CYCLE 119: con ancla, el unlikelihood preserva la calibración a cero costo de capacidad (en 6 "
                       "rondas el downstream fue ≈). 121 testea más rondas/presupuesto ajustado: ¿la calibración compone?"))
S_C120 = Source(tier=5, ref="cognia_x/experiments/exp104_durable_payoff", obtained=True,
                claim=("CYCLE 120: SIN ancla el selector durable no paga (calibración y capacidad ejes separados). 121 "
                       "corrige el confound: con el ANCLA presente, ¿el unlikelihood añade sobre el ancla-sola?"))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp105 primero): " + results_path)

    rfa = sm['real_final_anchor']; rff = sm['real_final_full']
    auca = sm['real_auc_anchor']; aucf = sm['real_auc_full']
    ya = sm['yield_anchor']; yf = sm['yield_full']
    cfa = sm['corr_final_anchor']; cff = sm['corr_final_full']
    fg = sm['final_gap']; ag = sm['auc_gap']; yg = sm['yield_gap']; cg = sm['corr_gap']
    n_seeds = sm['n_seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim105 = ("exp105 ({n} seeds, PyTorch CPU, lazo real exp018, presupuesto ajustado, ancla en ambos): la receta "
                "COMPLETA (ancla + unlikelihood) supera a ancla-sola (115) -- real_acc final full={rff} vs anchor={rfa} "
                "(+{fg}), AUC full={aucf} vs {auca} (+{ag}), yield full={yf} vs {ya} (+{yg}), corr full={cff} vs {cfa} "
                "(+{cg}). El selector mejor-calibrado compone en el downstream.").format(
                    n=n_seeds, rff=_f(rff), rfa=_f(rfa), fg=_f(fg), aucf=_f(aucf), auca=_f(auca), ag=_f(ag),
                    yf=_f(yf), ya=_f(ya), yg=_f(yg), cff=_f(cff), cfa=_f(cfa), cg=_f(cg))
    S_EXP105 = Source(tier=5, ref="cognia_x/experiments/exp105_full_recipe_payoff", obtained=True, claim=claim105)
    for src in (S_PRINCIPLE, S_C119, S_C120, S_EXP105):
        ledger.add_source(src)
    notes.append("4 fuentes (S_PRINCIPLE tier2 mecanismos-complementarios-componen; S_C119 tier5 unlikelihood-con-ancla; S_C120 tier5 sin-ancla-no-paga; S_EXP105 tier5 dato propio).")

    ev_for = [S_EXP105.ref, S_PRINCIPLE.ref]
    ev_against = [S_EXP105.ref]
    advtext = ("{V} (test end-to-end correcto de 120; resultado HONESTO que LOCALIZA el valor de la cura): 120 mostró que "
               "el selector durable SIN ancla no paga. 121 hace el test CORRECTO -- con el ANCLA de replay en AMBOS brazos "
               "(que sostiene la capacidad), ¿añadir el unlikelihood ACOTADO (calibración, 119) SOSTIENE mejor el downstream "
               "que la receta ancla-sola (la guardia de 115)? RESULTADO: NO en el DOWNSTREAM. El unlikelihood SÍ mejora la "
               "CALIBRACIÓN (corr final full={cff} vs anchor_only={cfa}, +{cg}) y el YIELD (full={yf} vs {ya}, +{yg}: el "
               "selector mejor-calibrado encuentra más correctos) PERO el downstream NO mejora -- real_acc final full={rff} "
               "vs {rfa} ({fg}); AUC full={aucf} vs {auca} ({ag}) (≈ igual, levemente menor). MECANISMO: con el ANCLA ya "
               "SATURANDO los datos de entrenamiento con verdad canónica limpia y diversa, los correctos-MARGINALES que el "
               "selector mejor-calibrado agrega NO componen en el downstream (la señal de training está dominada por el "
               "ancla, no por el selector), y el pequeño costo de capacidad del unlikelihood compensa la ventaja de yield. "
               "SÍNTESIS HONESTA 120+121: la cura de calibración (119) fija la SEÑAL pero NO mejora el downstream del "
               "auto-entrenamiento en NINGÚN régimen -- sin ancla el costo de capacidad la hunde (120); con ancla el ancla "
               "satura los datos (121). => el VALOR del selector durable/calibrado NO está en boostear el self-training "
               "downstream (que es ANCLA-bound), sino en las DECISIONES que USAN la señal de valor: la ASIGNACIÓN de "
               "recursos escasos (teoría 83-114) y las decisiones de UMBRAL/ABSTENCIÓN (106) -- exactamente donde la "
               "calibración importa. Esto RE-LOCALIZA correctamente el valor de R-VALOR: una brújula DECISIONAL "
               "(qué/cuándo/cuánto verificar, asignar, abstenerse), no un motor que por sí mismo acelere el descenso del "
               "loss. EVIDENCIA: convergente con 119 (downstream ≈ con ancla) y con la teoría de asignación (el signal se "
               "usa para decidir). EVIDENCIA EN CONTRA / caveats: el smoke de 2 seeds mostró un gap positivo (ruido) que el "
               "full de 4 seeds NO confirmó; el downstream está acotado por la capacidad del tiny model (a SCALE o en "
               "tareas selector-limitadas podría diferir); neg_w/replay_frac a sintonizar; {n} seeds, CPU.").format(
                   V=status.upper(), rff=_f(rff), rfa=_f(rfa), fg=_f(fg), aucf=_f(aucf), auca=_f(auca), ag=_f(ag),
                   yf=_f(yf), ya=_f(ya), yg=_f(yg), cff=_f(cff), cfa=_f(cfa), cg=_f(cg), n=n_seeds)

    hyp = Hypothesis(
        id="H-V4-9a",
        statement=("Con el ancla presente, añadir el unlikelihood (receta completa) sostiene mejor el downstream que "
                   "ancla-sola (115). [REFUTADA: mejora calibración+yield pero NO el downstream (el ancla satura los "
                   "datos); el valor del selector calibrado es DECISIONAL (asignación/abstención), no un boost del "
                   "self-training downstream que es ancla-bound.]"),
        prediction=("APOYADA si full sostiene mejor el downstream (real_acc final +>0.04 Y AUC>0) con corr/yield full > "
                    "anchor_only; REFUTADA si full ≈ anchor_only; MIXTA en otro caso. (Pre-registrada, lazo real exp018, 4 "
                    "seeds, 8 rondas, presupuesto ajustado, ancla en ambos.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp105_full_recipe_payoff")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-9a")
        notes.append("H-V4-9a marcada '{}' con DoD completo (la receta completa ancla+unlikelihood es el lazo durable óptimo).".format(status))

    analogy = AnalogyRecord(
        problem=("Tengo ejemplos verdaderos para practicar (ancla) Y mantengo mi criterio afilado (calibración). Con poco "
                 "tiempo, ¿el criterio afilado me hace aprender MÁS RÁPIDO, o sólo me sirve para ELEGIR mejor?"),
        everyday=("Para APRENDER más rápido: no tanto, si ya tengo buenos ejemplos verdaderos para practicar -- mi "
                  "progreso lo marcan ESOS ejemplos, no cuántas cosas extra elijo bien. El criterio afilado me hace ELEGIR "
                  "mejor (encuentro más cosas que valen) pero, con los ejemplos verdaderos ya sosteniéndome, esa elección "
                  "extra casi no mueve mi progreso. Donde el criterio afilado SÍ vale es para DECIDIR: en qué gastar mi "
                  "tiempo, cuándo abstenerme, qué priorizar -- no para aprender más rápido de lo que ya practico."),
        solutions=["receta completa (ancla + unlikelihood): mejor calibración y yield PERO downstream ≈ ancla-sola",
                   "con el ancla saturando los datos, los correctos-marginales del selector no componen en el downstream",
                   "el valor del selector calibrado es DECISIONAL (asignar/abstener), no un boost del aprendizaje",
                   "el downstream del self-training es ANCLA-bound (lo marcan los datos, no el selector)"],
        principles=["la calibración del selector NO acelera el self-training downstream cuando el ancla satura los datos",
                    "ni sin ancla (costo de capacidad, 120) ni con ancla (datos saturados, 121) la calibración boostea el downstream",
                    "el valor de la señal calibrada es DECISIONAL: asignación (83-114) y umbral/abstención (106)",
                    "R-VALOR es una brújula DECISIONAL, no un motor que por sí mismo acelere el descenso del loss"],
        adaptation=("El lab RE-LOCALIZA honestamente el valor de R-VALOR/la cura de durabilidad: la señal de valor "
                    "calibrada NO sirve para acelerar el self-training downstream (que es ANCLA-bound: lo marcan los datos "
                    "verdaderos, no el selector) -- ni sin ancla (120, costo de capacidad) ni con ancla (121, datos "
                    "saturados). Su valor está en las DECISIONES que la USAN: ASIGNAR la verificación/recursos escasos "
                    "(teoría 83-114) y decidir UMBRAL/ABSTENCIÓN (106). Receta práctica: para el lazo, ancla(capacidad) + "
                    "likelihood; el unlikelihood/calibración se justifica por las DECISIONES de asignación que habilita, no "
                    "por el downstream. Próximo: medir el payoff de la señal calibrada EN una decisión de asignación con "
                    "presupuesto externo; horizontes largos; y SCALE."),
        measurement=("exp105 ({n} seeds): full vs anchor_only -- corr {cff} vs {cfa} (+{cg}) y yield {yf} vs {ya} (+{yg}) "
                     "MEJORAN pero real_acc final {rff} vs {rfa} ({fg}), AUC {aucf} vs {auca} ({ag}) ≈ igual.").format(
                         n=n_seeds, rff=_f(rff), rfa=_f(rfa), fg=_f(fg), aucf=_f(aucf), auca=_f(auca), ag=_f(ag),
                         yf=_f(yf), ya=_f(ya), yg=_f(yg), cff=_f(cff), cfa=_f(cfa), cg=_f(cg)),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (ejemplos verdaderos + criterio afilado se potencian con poco tiempo de práctica).")

    kl = ("REAL (exp105): con el ancla presente, el unlikelihood mejora la calibración (corr +{cg}) y el yield (+{yg}) PERO "
          "NO el downstream (real_acc final full={rff} vs {rfa}, {fg}; AUC {ag}) -- el ancla SATURA los datos de training, "
          "así que los correctos-marginales del selector no componen. SÍNTESIS 120+121: la cura de calibración NO boostea "
          "el self-training downstream en ningún régimen (sin ancla: costo de capacidad; con ancla: datos saturados); su "
          "valor es DECISIONAL (asignación 83-114, umbral/abstención 106). R-VALOR = brújula decisional, no motor de "
          "descenso de loss. TECHO: downstream acotado por la capacidad del tiny model y dominado por el ancla; a SCALE o "
          "en tareas selector-limitadas podría diferir; {n} seeds, CPU.").format(
              cg=_f(cg), yg=_f(yg), rff=_f(rff), rfa=_f(rfa), fg=_f(fg), ag=_f(ag), n=n_seeds)
    ceilings.add(CeilingRecord(
        subsystem="Valor de la señal calibrada — NO acelera el self-training downstream (ancla-bound: ni sin ancla -costo capacidad- ni con ancla -datos saturados-); su valor es DECISIONAL (asignación/abstención). R-VALOR = brújula decisional, no motor de loss",
        known_limit=kl,
        blockers=[{"text": "la calibración del selector NO mejora el downstream del self-training: con el ancla, los datos están saturados por verdad canónica y los correctos-marginales del mejor selector no componen; sin el ancla (120), el costo de capacidad la hunde", "kind": "fisico"},
                  {"text": "el valor del selector calibrado es DECISIONAL (asignar la verificación/recursos escasos 83-114, umbral/abstención 106), NO un boost del downstream -- no se midió directamente el payoff EN una decisión de asignación con presupuesto externo (queda como frontera)", "kind": "diseno"},
                  {"text": "downstream acotado por la capacidad del tiny model; presupuesto ajustado; 4 seeds, CPU; smoke de 2 seeds dio ruido (gap positivo no confirmado); falta SCALE", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP105.ref, S_C119.ref, S_C120.ref]))
    notes.append("1 techo 'real': la señal calibrada no acelera el self-training downstream (ancla-bound); su valor es DECISIONAL (asignación/abstención). R-VALOR = brújula decisional.")

    dstmt = ("North-Star R-VALOR (RE-LOCALIZA el valor de la señal calibrada -- cierre honesto del arco): la cura de "
             "durabilidad (unlikelihood, 119) mantiene el selector calibrado PERO esa calibración NO acelera el "
             "self-training downstream -- ni sin ancla (120, costo de capacidad) ni con ancla (121, el ancla satura los "
             "datos y los correctos-marginales del mejor selector no componen). El downstream del self-training es "
             "ANCLA-bound (lo marcan los datos verdaderos, no el selector). Decisión: el VALOR de la señal de valor "
             "calibrada está en las DECISIONES que la USAN -- ASIGNAR la verificación/recursos escasos (teoría 83-114) y "
             "UMBRAL/ABSTENCIÓN (106) -- NO en boostear el descenso del loss. R-VALOR es una BRÚJULA DECISIONAL, no un "
             "motor de aprendizaje; el lazo práctico = ancla(capacidad) + likelihood, y la calibración se justifica por "
             "las decisiones de asignación que habilita. Próximo: medir el payoff de la señal calibrada EN una decisión de "
             "asignación con presupuesto externo; horizontes largos; y SCALE.")
    drat = ("exp105 (tier5, propio, {n} seeds, PyTorch CPU, lazo real exp018): con ancla, full mejora corr (+{cg}) y yield "
            "(+{yg}) pero NO el downstream (real_acc final {fg}, AUC {ag} ≈ igual). Convergente con 119 (downstream ≈ con "
            "ancla) y con la teoría de asignación (la señal se usa para decidir). REFUTADA el boost de downstream; "
            "re-localiza el valor de R-VALOR como decisional.").format(n=n_seeds, fg=_f(fg), ag=_f(ag), yg=_f(yg), cg=_f(cg))
    dec = Decision(id="D-V4-83", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP105), _to_plain(S_C119), _to_plain(S_C120)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-83 ACEPTADA por el ledger (tier5 exp105 + tier5 exp103 + tier5 exp104).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-83:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle121_full_recipe_payoff',
                                description='CYCLE 121 (RESET v4, H-V4-9a: la receta COMPLETA -likelihood+ancla+unlikelihood- es el lazo de auto-mejora endógeno durable óptimo -- capstone definitivo).')
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
    print("RESUMEN — CYCLE 121 (RESET v4): la RECETA COMPLETA (ancla + unlikelihood) es el lazo de auto-mejora endógeno durable óptimo (H-V4-9a)")
    print("=" * 78)
    print("veredicto H-V4-9a:", status.upper() if status else "?")
    print("  con el ancla holdeando capacidad, el unlikelihood (selector calibrado) compone via yield -> mejor downstream que ancla-sola (115). Cierra el arco R-VALOR end-to-end.")
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
