r"""
cycle145_continuous_capacity.py — CICLO 145 (RESET v4, rama control/acción, ATACA el artefacto recurrente K=1 de 139/142/143):
H-V4-10q por las compuertas del engine.

VEREDICTO: MIXTA (núcleo real + claim central RE-ACOTADO por verificación adversarial de 2 agentes; 15mo ciclo). El experimento
AUTO-DOCUMENTA.

NÚCLEO (robusto en g/D/RHO/seeds): bajo capacidad CONTINUA (presupuesto B repartido por water-filling) la ventaja del criterio de
VALOR (keystone w·ctrl) sobre el mejor factor-solo SOBREVIVE a presupuesto ESCASO y ESCALA con la disociación ctrl-rel -> la ventaja
del keystone NO es ESPECÍFICA del top-K discreto.

RE-ACOTADO (la verificación bajó de APOYADA a MIXTA):
  (1) escaso-continuo ES CONCENTRADO: a presupuesto escaso el water-filling reparte ~soft top-k (ratio de participación ~1.8 a B
      chico) -> B-chico = winner-take-all BLANDO; el K=1 NO se DISUELVE, se REINTERPRETA como concentración-bajo-escasez.
  (2) la continua NO decae 'igual que la discreta': RESIDUAL PERMANENTE (~log) vs la discreta que llega a 0 sólo en K=D (trivial).
  (3) el decaimiento-en-B es g-DEPENDIENTE: con g=√a (marginal infinita en 0) la ventaja es PLANA -> el paralelo continuo≈discreto
      sólo vale para beneficios de marginal finita en 0.
  (4) value=oracle (tautológico) + álgebra de producto -> RECOMBINACIÓN de 142 (capacidad×disociación) en forma continua.

=> la ventaja del valor NO es un artefacto de la selección DISCRETA (robusto), PERO el continuo escaso es un winner-take-all BLANDO
-> NO 'quita' el caveat K=1, lo REINTERPRETA como concentración-bajo-escasez. MIXTA EXITOSA: la verificación cazó el overclaim 'sin
winner-take-all / decae igual' (15mo ciclo).

DERIVA de exp129_continuous_capacity/results/results.json.
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle145_continuous_capacity')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp129_continuous_capacity', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="la ventaja del criterio de VALOR (keystone=ctrl×rel) sobre los factores de un eje es un fenómeno de CONCENTRACIÓN bajo ESCASEZ de capacidad, no una patología de la selección DISCRETA top-K: bajo capacidad CONTINUA (water-filling de un presupuesto) la ventaja SOBREVIVE a presupuesto escaso y escala con la disociación (NO es discreto-específica), pero a presupuesto escaso el water-filling CONCENTRA (~soft top-k) -> el 'artefacto K=1' no se disuelve, se REINTERPRETA como concentración-bajo-escasez; el paralelo de decaimiento continuo↔discreto es g-dependiente.", obtained=False,
                     claim=("La ventaja del valor sobrevive capacidad continua y escala con disociación (no discreto-específica), "
                            "pero el continuo escaso es un winner-take-all BLANDO -> el K=1 se reinterpreta como concentración-bajo-"
                            "escasez, no se disuelve. (Principio.)"))
S_ARTEFACTO = Source(tier=5, ref="cognia_x/experiments/{exp123 (139), exp126 (142), exp127 (143)} — el artefacto K=1 winner-take-all recurrente", obtained=True,
                     claim=("Los CYCLEs 139/142/143 hallaron repetidamente que la ventaja del criterio de valor sobre un factor "
                            "EVAPORA a K>=#modos buenos en la selección discreta top-K (artefacto K=1). H-V4-10q pregunta si es una "
                            "patología del top-K o sólo escasez: bajo capacidad CONTINUA la ventaja SOBREVIVE (no discreto-específica) "
                            "PERO escaso-continuo ES concentrado -> el K=1 se reinterpreta, no se disuelve."))
S_VERIF = Source(tier=4, ref="verificación adversarial de 2 agentes (lentes tautología-concentración / robustez-g; probes reales numpy)", obtained=True,
                 claim=("La verificación adversarial (15mo ciclo) CONFIRMÓ el núcleo (robusto en g/D/RHO/seeds: la ventaja sobrevive "
                        "continuo + escala con disociación) PERO bajó de APOYADA a MIXTA: (1) escaso-continuo ES CONCENTRADO (ratio "
                        "de participación ~1.8 a B chico = soft top-2) -> NO 'sin winner-take-all'; (2) residual permanente vs la "
                        "discreta que llega a 0 sólo en K=D (trivial); (3) decaimiento g-DEPENDIENTE (con g=√a la ventaja es plana); "
                        "(4) value=oracle tautológico + álgebra de producto -> recombinación de 142."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp129 primero): " + results_path)

    ca1 = sm['adv_cont']['anti'][0]; aca = sm['auc_cont']['anti']; aci = sm['auc_cont']['indep']; acc = sm['auc_cont']['corr']
    prs = sm['pr_scarce']; pra = sm['pr_abund']; cres = sm['cont_residual']
    cs0 = sm['adv_cont_sqrt']['anti'][0]; csN = sm['adv_cont_sqrt']['anti'][-1]
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim129 = ("exp129 (propio, {n} seeds, numpy, post-verificación de 2 agentes): {V}. NÚCLEO (robusto g/D/RHO/seeds): bajo "
                "capacidad CONTINUA (water-filling de un presupuesto B) la ventaja del criterio de VALOR (keystone w·ctrl) sobre el "
                "mejor factor-solo SOBREVIVE a presupuesto escaso (anti +{ca1}) y ESCALA con la disociación (AUC anti={aca}>indep="
                "{aci}>corr={acc}) -> NO es específica del top-K discreto. RE-ACOTADO: escaso-continuo ES CONCENTRADO (participación "
                "{prs} a B chico = soft top-2 -> el K=1 se reinterpreta, no se disuelve); residual permanente +{cres}; decaimiento "
                "g-DEPENDIENTE (g=√a plana {cs0}->{csN}); value=oracle tautológico + álgebra de producto -> recombinación de 142.").format(
                    n=n_seeds, V=status.upper(), ca1=_f(ca1), aca=_f(aca), aci=_f(aci), acc=_f(acc), prs=_f(prs), cres=_f(cres),
                    cs0=_f(cs0), csN=_f(csN))
    S_EXP129 = Source(tier=5, ref="cognia_x/experiments/exp129_continuous_capacity", obtained=True, claim=claim129)
    for src in (S_PRINCIPLE, S_ARTEFACTO, S_VERIF, S_EXP129):
        ledger.add_source(src)
    notes.append("4 fuentes (S_PRINCIPLE tier2 la ventaja es concentración-bajo-escasez, no discreto-específica; S_ARTEFACTO tier5 el K=1 recurrente de 139/142/143; S_VERIF tier4 verificación adversarial; S_EXP129 tier5 dato propio {}).".format(status.upper()))

    ev_for = [S_EXP129.ref, S_PRINCIPLE.ref]
    ev_against = [S_EXP129.ref, S_VERIF.ref]
    advtext = ("{V} (ATACA el artefacto recurrente K=1 de 139/142/143; caracterización honesta tras verificación adversarial de 2 "
               "agentes, 15mo ciclo): los CYCLEs 139/142/143 hallaron una y otra vez que la ventaja del criterio de VALOR (keystone "
               "w·ctrl) sobre un factor de un eje EVAPORA a K>=#modos buenos en la selección DISCRETA top-K -- un 'artefacto K=1 "
               "winner-take-all' que la verificación marcó repetidamente. H-V4-10q pregunta: ¿es ese colapso una PATOLOGÍA de la "
               "selección discreta, o sólo la manifestación discreta de la ESCASEZ? NÚCLEO (robusto en g/D/RHO/seeds): bajo "
               "capacidad CONTINUA (presupuesto B repartido por water-filling) la ventaja SOBREVIVE a presupuesto ESCASO (anti "
               "+{ca1}) y ESCALA con la DISOCIACIÓN ctrl-rel (AUC continua anti={aca}>indep={aci}>corr={acc}) -> la ventaja del "
               "keystone NO es ESPECÍFICA del top-K discreto (refuta la lectura 'todo era winner-take-all del top-K'). PERO el "
               "claim de que esto 'QUITA el caveat K=1 / es escasez SIN winner-take-all' se RE-ACOTÓ BIDIRECCIONALMENTE: (1) "
               "escaso-continuo ES CONCENTRADO -- a presupuesto escaso el water-filling reparte ~soft top-k (ratio de participación "
               "{prs} a B chico, ~soft top-2; sube a {pra} a B grande): B-chico = un winner-take-all BLANDO, NO 'sin "
               "concentración'. El K=1 NO se DISUELVE: se REINTERPRETA como concentración-bajo-escasez (K=1 ≈ B-chico). (2) la "
               "continua NO decae 'igual que la discreta': tiene RESIDUAL PERMANENTE (anti +{cres} a B grande, ~log) mientras la "
               "discreta llega a 0 sólo en K=D (el punto TRIVIAL select-all, no un decaimiento real). (3) el decaimiento-en-B es "
               "g-DEPENDIENTE -- con g=√a (marginal infinita en 0) la ventaja es INVARIANTE en B (anti {cs0}->{csN}, plana) -> el "
               "paralelo continuo≈discreto SÓLO vale para beneficios de marginal FINITA en 0 (log/exp/frac). (4) value=oracle por "
               "construcción (tautológico) y el contenido es ÁLGEBRA DE PRODUCTO (un producto w·ctrl no se aproxima bien por un "
               "solo factor, peor al decorrelacionar w,ctrl = el ρ_wb barrido) -> RECOMBINACIÓN de 142 (capacidad×disociación) en "
               "forma continua. => RESULTADO HONESTO: la ventaja del valor NO es un artefacto de la selección DISCRETA (sobrevive "
               "continuo + escala con disociación, robusto en g/D/RHO/seeds) -- esto SÍ aporta -- PERO el continuo escaso es un "
               "winner-take-all BLANDO, así que NO 'quita' el caveat K=1: lo REINTERPRETA como concentración-bajo-escasez; el "
               "paralelo de decaimiento es g-dependiente y la magnitud es álgebra de producto (recombinación de 142). MIXTA "
               "EXITOSA: la verificación cazó el overclaim 'sin winner-take-all / decae exactamente igual' (15mo ciclo). Frontera: "
               "la ventaja del valor en un mecanismo de asignación REAL (atención/cómputo), no toy; SCALE.").format(
                   V=status.upper(), ca1=_f(ca1), aca=_f(aca), aci=_f(aci), acc=_f(acc), prs=_f(prs), pra=_f(pra),
                   cres=_f(cres), cs0=_f(cs0), csN=_f(csN))

    hyp = Hypothesis(
        id="H-V4-10q",
        statement=("¿El 'artefacto K=1 winner-take-all' (139/142/143, la ventaja del valor evapora a K>=#modos en top-K) es una "
                   "patología de la selección DISCRETA, o sólo escasez de capacidad? Bajo capacidad CONTINUA (water-filling de un "
                   "presupuesto B) la ventaja del valor SOBREVIVE a presupuesto escaso y ESCALA con la disociación (NO es "
                   "discreto-específica) -- PERO escaso-continuo ES concentrado (~soft top-k), residual permanente, decaimiento "
                   "g-dependiente, value=oracle (recombinación de 142). Alcance: numpy, lineal, water-filling cóncavo."),
        prediction=("APOYADA si el continuo DISUELVE el winner-take-all (la ventaja sobrevive SIN concentración). REFUTADA si la "
                    "ventaja desaparece bajo continuo (era discreto-específica). MIXTA si sobrevive+escala (no discreto-específica) "
                    "pero el escaso-continuo es concentrado (reinterpreta, no disuelve, el K=1). (Pre-registrada; verificación "
                    "adversarial de 2 agentes.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp129_continuous_capacity")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-10q")
        notes.append("H-V4-10q marcada '{}': la ventaja del valor sobrevive capacidad continua + escala con disociación (no es discreto-específica, robusto g/D/RHO/seeds), PERO escaso-continuo es un winner-take-all BLANDO (soft top-k) -> el K=1 se REINTERPRETA como concentración-bajo-escasez, no se disuelve; decaimiento g-dependiente; recombinación de 142.".format(status))

    analogy = AnalogyRecord(
        problem=("Una crítica que volvía siempre: 'tu ventaja sólo aparece cuando obligás a elegir UNA sola cosa; si podés elegir "
                 "varias, desaparece -- es un truco de la regla de elegir-de-a-una'. ¿Es un truco de esa regla, o algo más real?"),
        everyday=("Algo más real, pero la crítica no se disuelve, se reinterpreta. Cambiaste la regla: en vez de 'elegí K cosas', "
                  "ahora 'repartí un presupuesto continuo'. Y la ventaja de mirar el VALOR completo (en vez de un solo aspecto) "
                  "SIGUE estando cuando el presupuesto es chico, y crece cuanto más separados están los dos aspectos -- así que NO "
                  "era un truco de 'elegir-de-a-una'. PERO cuando el presupuesto es chico, repartir 'continuo' igual te pone ~70% en "
                  "una sola cosa: es elegir-de-a-una con borde borroso. O sea, no eliminaste el 'elegí-una', lo volviste a meter en "
                  "forma blanda. Y que la ventaja 'baje al agrandar el presupuesto' depende de cómo modeles los rendimientos "
                  "decrecientes: con una forma se desvanece, con otra se queda plana. Moraleja honesta: la ventaja es real y no es "
                  "un artefacto de la regla discreta, pero 'escasez' y 'elegir-de-a-una blando' son lo mismo en el extremo -- no "
                  "los separaste."),
        solutions=["bajo capacidad continua la ventaja del valor sobrevive a presupuesto escaso y escala con la disociación -> NO es específica de la selección discreta top-K",
                   "PERO a presupuesto escaso el water-filling concentra (~soft top-k) -> el K=1 no se disuelve, se reinterpreta como concentración-bajo-escasez",
                   "el paralelo de decaimiento continuo↔discreto es g-dependiente (con g=√a la ventaja es plana) y la continua tiene residual permanente",
                   "value=oracle por construcción + álgebra de producto -> es una recombinación de 142 (capacidad×disociación) en forma continua"],
        principles=["la ventaja del valor sobre un factor es un fenómeno de CONCENTRACIÓN bajo ESCASEZ, no de la discreteness de la selección -- pero escasez y winner-take-all blando coinciden en el extremo escaso",
                    "antes de afirmar que un mecanismo (continuo) DISUELVE un artefacto (K=1), MEDIR la concentración (ratio de participación): a presupuesto escaso el continuo es soft top-k",
                    "un paralelo de decaimiento entre dos regímenes puede ser g-dependiente (depende de la forma de los retornos) -- testear más de una concavidad",
                    "META: 15mo ciclo seguido con verificación adversarial -- cazó un overclaim BIDIRECCIONAL ('sin winner-take-all' + 'decae exactamente igual')"],
        adaptation=("La crítica del artefacto K=1 (139/142/143) decía que la ventaja del valor podía ser un truco de la selección "
                    "discreta winner-take-all. Este ciclo la ataca con capacidad CONTINUA (water-filling) y obtiene un MIXTA "
                    "honesto: la ventaja SOBREVIVE bajo continuo + escala con disociación (robusto en g/D/RHO/seeds) -> NO es "
                    "discreto-específica (esto SÍ refuta la lectura 'todo era top-K'). PERO el continuo escaso ES concentrado "
                    "(~soft top-k, ratio de participación ~1.8) -> NO 'quita' el caveat K=1, lo REINTERPRETA como "
                    "concentración-bajo-escasez; el paralelo de decaimiento es g-dependiente y la magnitud es álgebra de producto "
                    "(recombinación de 142). APORTE: la ventaja del valor no es un artefacto de la selección discreta + el marco "
                    "honesto 'escasez = concentración blanda'. META-LECCIÓN: 15mo ciclo seguido con verificación adversarial. "
                    "Próximo: la ventaja del valor en un mecanismo de asignación REAL (atención/cómputo); SCALE."),
        measurement=("exp129 ({n} seeds): núcleo anti +{ca1} (escaso), AUC continua anti={aca}>indep={aci}>corr={acc}; "
                     "RE-ACOTADO: participación {prs} a B chico (soft top-2), residual +{cres}, g=√a plana {cs0}->{csN}.").format(
                         n=n_seeds, ca1=_f(ca1), aca=_f(aca), aci=_f(aci), acc=_f(acc), prs=_f(prs), cres=_f(cres),
                         cs0=_f(cs0), csN=_f(csN)),
        iterations=1)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (la ventaja es real y no es truco de la regla discreta, pero 'escasez' y 'elegir-de-a-una blando' coinciden en el extremo escaso -- no se separaron).")

    kl = ("REAL (exp129, {V} post-verificación adversarial de 2 agentes): bajo capacidad CONTINUA la ventaja del criterio de VALOR "
          "sobre el mejor factor-solo SOBREVIVE a presupuesto escaso y ESCALA con la disociación (robusto en g/D/RHO/seeds) -> NO es "
          "específica de la selección DISCRETA top-K. TECHO/ALCANCE: el escaso-continuo ES CONCENTRADO (~soft top-k, participación "
          "{prs} a B chico) -> el K=1 NO se disuelve, se REINTERPRETA como concentración-bajo-escasez; residual permanente +{cres} "
          "(vs la discreta trivial a K=D); decaimiento g-DEPENDIENTE (g=√a plana); value=oracle tautológico + álgebra de producto "
          "(recombinación de 142); numpy/lineal. Frontera: la ventaja en un mecanismo de asignación REAL; SCALE.").format(
              V=status.upper(), prs=_f(prs), cres=_f(cres))
    ceilings.add(CeilingRecord(
        subsystem="ATACAR el artefacto recurrente K=1 (139/142/143) con capacidad CONTINUA — bajo water-filling de un presupuesto la ventaja del criterio de VALOR sobre el mejor factor-solo SOBREVIVE a presupuesto escaso y ESCALA con la disociación (robusto g/D/RHO/seeds) -> NO es específica del top-K discreto. PERO escaso-continuo es un winner-take-all BLANDO (soft top-k) -> el K=1 se REINTERPRETA como concentración-bajo-escasez, NO se disuelve; residual permanente; decaimiento g-dependiente; value=oracle (recombinación de 142). Alcance: numpy, lineal",
        known_limit=kl,
        blockers=[{"text": "CONCENTRACIÓN (el modo de fallo central del overclaim): el claim 'el continuo QUITA el winner-take-all' es FALSO en el extremo escaso -- a presupuesto chico el water-filling reparte ~soft top-k (ratio de participación {prs} a B chico ≈ 1.8 modos efectivos; sube a {pra} a B grande). B-chico = winner-take-all BLANDO. El K=1 NO se DISUELVE: se REINTERPRETA como concentración-bajo-escasez (K=1 ≈ B-chico, ambos concentrados). Lo NO-trivial/load-bearing: la ventaja SOBREVIVE el continuo y ESCALA con la disociación (robusto g/D/RHO/seeds) -> NO es discreto-específica".format(prs=_f(prs), pra=_f(pra)), "kind": "diseno"},
        {"text": "RESIDUAL g-DEPENDIENTE + TAUTOLOGÍA: (a) la continua (g=log) tiene RESIDUAL PERMANENTE (+{cres} a B grande) mientras la discreta llega a 0 sólo en K=D (el punto TRIVIAL select-all) -> 'decae igual que la discreta' es apples-to-oranges. (b) el decaimiento-en-B es g-DEPENDIENTE: con g=√a (marginal infinita en 0) la ventaja es INVARIANTE en B (plana {cs0}->{csN}) -> el paralelo continuo≈discreto sólo vale para beneficios de marginal finita en 0. (c) value=oracle por construcción (tautológico) y el contenido es álgebra de producto (w·ctrl no se aproxima por un factor, peor al decorrelacionar) -> RECOMBINACIÓN de 142".format(cres=_f(cres), cs0=_f(cs0), csN=_f(csN)), "kind": "diseno"},
        {"text": "ALCANCE: numpy/toy, sustrato keystone lineal (v=w·ctrl), water-filling de retornos cóncavos, costo de control cuadrático. NO cubre: un mecanismo de asignación REAL (atención/cómputo en un modelo), la no-linealidad (135-136)/acoplamiento (137), el lazo real, SCALE. El aporte neto -la ventaja del valor NO es discreto-específica- es una RECOMBINACIÓN de 142 en forma continua", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP129.ref, S_ARTEFACTO.ref, S_VERIF.ref]))
    notes.append("1 techo 'real': la ventaja del valor sobrevive capacidad continua + escala con disociación (no discreto-específica, robusto g/D/RHO/seeds); pero escaso-continuo es un winner-take-all BLANDO (soft top-k) -> el K=1 se reinterpreta como concentración-bajo-escasez, no se disuelve; decaimiento g-dependiente; recombinación de 142.")

    dstmt = ("North-Star R-VALOR (ATACA el artefacto recurrente K=1 de 139/142/143): {V}. Bajo capacidad CONTINUA (water-filling) la "
             "ventaja del criterio de VALOR (keystone w·ctrl) sobre el mejor factor-solo SOBREVIVE a presupuesto escaso (anti +{ca1}) "
             "y ESCALA con la disociación (AUC anti={aca}>indep={aci}>corr={acc}) -> NO es específica del top-K discreto. PERO "
             "escaso-continuo ES concentrado (~soft top-k, participación {prs} a B chico) -> el K=1 se REINTERPRETA como "
             "concentración-bajo-escasez, NO se disuelve; residual permanente; decaimiento g-dependiente; value=oracle (recombinación "
             "de 142). Decisión: adoptar que la ventaja del valor NO es un artefacto de la selección discreta (robusto), PERO "
             "reconocer que escasez = concentración-blanda (el K=1 se reinterpreta, no se quita). META-DECISIÓN: 15mo ciclo con "
             "verificación adversarial (cazó el overclaim 'sin winner-take-all'). Próximo: la ventaja en un mecanismo de asignación "
             "real; SCALE.").format(V=status.upper(), ca1=_f(ca1), aca=_f(aca), aci=_f(aci), acc=_f(acc), prs=_f(prs))
    drat = ("exp129 (tier5, propio, {n} seeds, numpy, post-verificación de 2 agentes): la ventaja del valor sobrevive capacidad "
            "continua + escala con disociación (no discreto-específica, robusto g/D/RHO/seeds) PERO escaso-continuo es un "
            "winner-take-all blando (soft top-k) -> el K=1 se reinterpreta, no se disuelve; decaimiento g-dependiente; recombinación "
            "de 142. Convergente con el principio (tier2) y la verificación (tier4); ataca -sin disolver- el artefacto K=1 de "
            "139/142/143 (tier5). MIXTA: núcleo real (no discreto-específica) + claim central re-acotado.").format(n=n_seeds)
    dec = Decision(id="D-V4-107", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP129), _to_plain(S_ARTEFACTO), _to_plain(S_VERIF)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-107 ACEPTADA por el ledger (tier5 exp129 + tier5 artefacto-K1-139/142/143 + tier4 verificación adversarial).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-107:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle145_continuous_capacity',
                                description='CYCLE 145 (RESET v4, H-V4-10q MIXTA: la ventaja del valor sobrevive capacidad CONTINUA + escala con disociación -no es discreto-específica- PERO escaso-continuo es un winner-take-all BLANDO -> el K=1 se reinterpreta como concentración-bajo-escasez, no se disuelve; 15mo ciclo con verificación adversarial).')
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
    print("RESUMEN — CYCLE 145 (RESET v4): el artefacto K=1 es concentración-bajo-escasez (no patología del top-K, pero no se disuelve) — H-V4-10q " + (status.upper() if status else "?"))
    print("=" * 78)
    print("veredicto H-V4-10q:", status.upper() if status else "?")
    print("  NÚCLEO (robusto g/D/RHO/seeds): bajo capacidad CONTINUA la ventaja del VALOR sobre el mejor factor-solo SOBREVIVE a presupuesto escaso y ESCALA con la disociación -> NO es específica del top-K discreto. RE-ACOTADO: escaso-continuo ES CONCENTRADO (~soft top-k) -> el K=1 se REINTERPRETA como concentración-bajo-escasez, no se disuelve; residual permanente; decaimiento g-dependiente; value=oracle (recombinación de 142).")
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
