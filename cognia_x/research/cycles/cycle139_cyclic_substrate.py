r"""
cycle139_cyclic_substrate.py — CICLO 139 (RESET v4, rama control/acción, EXTIENDE el sustrato ACOPLADO de 137 al régimen con
CICLOS / radio espectral cercano a 1): H-V4-10m por las compuertas del engine. ¿Sobrevive el keystone valor=ctrl×rel a un
sustrato con feedback (ciclos), y cuál es la forma correcta de la controlabilidad-por-alcance?

VEREDICTO: MIXTA (núcleo APOYADO + 4 overclaims RETRACTADOS por verificación adversarial de 4 agentes; 9no ciclo seguido). Ataca
el caveat EXPLÍCITO de 137 ("válido con radio espectral<1; acople con ciclos cerca de radio 1 degrada — frontera").

QUÉ SOBREVIVE (núcleo, leakage-free, sim-validado): la reach de estado-estacionario CRUDA del 137 (R_inf=(I-Â)^{-1}) es
NUMÉRICAMENTE FRÁGIL cerca de radio espectral 1 -- bajo capacidad K=1 (winner-take-all) con escalas temporales en competencia,
MIS-RANKEA el modo top (apuesta al lazo lento casi-crítico que reach-∞∝1/(1-radio) infla pero cuyo beneficio no se materializó en
el horizonte). Una reach REGULARIZADA (horizonte-finito, descontada, o cap-de-autovalor) lo cura. Es un CAVEAT REAL al 137 (cuyo
dominio es radio<1 con buen condicionamiento). El producto |b̂·R^T·ŵ| es ESTIMABLE de un stream leakage-free.

QUÉ NO SOBREVIVE (retractado/acotado por la verificación adversarial -- el experimento lo AUTO-DOCUMENTA):
  (1) El gap titular (reach_H >> reach_inf) es ARTEFACTO de K=1 WINNER-TAKE-ALL: a K>=2 EVAPORA (gap_true~0). reach_inf identifica
      el CONJUNTO correcto de modos relevantes; sólo invierte el orden #1<->#2 que K=1 castiga al máximo.
  (2) La forma HORIZONTE-H específica NO es privilegiada: una reach-∞ REGULARIZADA por CAP-DE-AUTOVALOR (SIN conocer H) IGUALA a
      reach_H. La novedad es REGULARIZAR el modo casi-crítico, no el horizonte.
  (3) La RELEVANCIA es COLINEAL / no-aislada: con ŵ≡unos reach_H~0.99 (el control shuffle-ŵ daba falso positivo). El factor
      load-bearing es la CONTROLABILIDAD-REACH, no la relevancia (que 134-137 ya aisló).
  (4) "Falla cerca de radio 1" requiere COMPETENCIA de escalas temporales: con un ÚNICO lazo reach_inf=1.0 hasta radio 0.99.
  (+) El pilar "es la FORMA" tiene ventana angosta a∈[~0.45,0.65]; a=0.6 cerca del borde.

=> RESULTADO HONESTO: la reach-∞ cruda del 137 es frágil cerca de radio 1 y necesita REGULARIZACIÓN (caveat real al 137), pero NO
se establece que la forma horizonte-H sea única ni que el efecto sobreviva a K>=2 ni que la relevancia se aísle aquí. MIXTA EXITOSA:
la verificación adversarial (4 agentes) corrigió 4 overclaims antes del ledger (9no ciclo seguido).

DERIVA de exp123_cyclic_substrate/results/results.json.

Correr (DESPUÉS de exp123):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp123_cyclic_substrate.run --seeds 200
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle139_cyclic_substrate
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle139_cyclic_substrate')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp123_cyclic_substrate', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="bajo un sustrato con CICLOS (feedback, radio espectral->1) la reach de estado-estacionario CRUDA del 137 ((I-A)^{-1}) es NUMÉRICAMENTE FRÁGIL: el modo casi-crítico la infla (∝1/(1-radio)) y bajo selección winner-take-all (K=1) mis-rankea el modo top. Una reach REGULARIZADA (horizonte-finito R_H=Σ_{k<H}A^k, descontada (I-γA)^{-1}, o cap-de-autovalor SIN H) lo cura -- la familia de regularizaciones es equivalente; la forma horizonte-H no es privilegiada. PERO el efecto requiere capacidad K=1 + competencia de escalas temporales (a K>=2 evapora) y la relevancia es colineal en este régimen. Caveat de CONDICIONAMIENTO al 137 (cuyo dominio es radio<1 con buen condicionamiento).", obtained=False,
                     claim=("Bajo ciclos la reach de estado-estacionario CRUDA del 137 es frágil cerca de radio 1 y necesita "
                            "REGULARIZACIÓN (varias formas equivalentes: horizonte-finito, descontada, cap-de-autovalor); la forma "
                            "horizonte específica NO es única. El efecto es un artefacto de selección K=1 (evapora a K>=2) y la "
                            "relevancia es colineal. Caveat de condicionamiento al 137. (Principio.)"))
S_C137 = Source(tier=5, ref="cognia_x/experiments/exp121_coupled_discovery (CYCLE 137 reach-relevancia acoplada de estado-estacionario)", obtained=True,
                claim=("CYCLE 137 (empírico): bajo acople el agente compone la reach-relevancia de estado-estacionario "
                       "|b̂·(I-Â)^{-T}ŵ|, VÁLIDA con radio espectral<1 (DAG, radio=a=0.6); dejó como frontera EXPLÍCITA 'acople con "
                       "ciclos cerca de radio 1 degrada'. H-V4-10m (MIXTA) la ACOTA: la reach-∞ cruda es frágil cerca de radio 1 y "
                       "necesita regularización (caveat de condicionamiento), pero la forma específica no es privilegiada y el "
                       "efecto depende de K=1."))
S_VERIF = Source(tier=4, ref="verificación adversarial de 4 agentes (lentes tautología-oracle / leakage-control-nulo / fairness-baseline / robustez-configs; probes reales sobre exp123)", obtained=True,
                 claim=("La verificación adversarial (9no ciclo) confirmó el NÚCLEO leakage-free (reach_inf_true falla = es la forma; "
                        "estimable converge desde abajo; Â=0 colapsa; sim_check valida la física) PERO CAZÓ 4 OVERCLAIMS -> MIXTA: "
                        "(1) el gap titular es artefacto de K=1 winner-take-all (a K>=2 gap_true~0: reach_inf identifica el conjunto "
                        "correcto, sólo invierte #1<->#2); (2) la forma horizonte-H no es privilegiada (una reach-∞ regularizada por "
                        "cap-de-autovalor SIN H la iguala -> la novedad es regularizar el modo casi-crítico); (3) la relevancia es "
                        "colineal (ŵ≡unos da reach_H~0.99, el control shuffle daba falso positivo); (4) 'falla cerca de radio 1' "
                        "requiere competencia de escalas temporales (un único lazo no falla). El pilar 'es la forma' tiene ventana "
                        "angosta a∈[~0.45,0.65]."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp123 primero): " + results_path)

    rli = sm['rlo_reach_inf']
    rii = sm['rhi_reach_inf']; rih = sm['rhi_reach_H']; rid = sm['rhi_reach_disc']; rir = sm['rhi_reach_inf_reg']
    riit = sm['rhi_reach_inf_true']; riht = sm['rhi_reach_H_true']
    gk1 = sm['gap_k1_true']; gk2 = sm['gap_k2_true']
    ones = sm['ones_reach_H']; z0 = sm['zeroA_reach_H']; cto = sm['rhi_ctrl_only']
    so = sm['slowonly_reach_inf']; fo = sm['fastonly_reach_inf']
    t0 = sm['Tmin_reachH']; tN = sm['Tmax_reachH']; sclo = sm['sim_check_lo']; schi = sm['sim_check_hi']
    n_over = sm['n_overclaims']
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim123 = ("exp123 (propio, {n} seeds, numpy, post-verificación de 4 agentes): MIXTA. NÚCLEO: la reach de estado-estacionario "
                "CRUDA del 137 ((I-Â)^-1) es FRÁGIL cerca de radio 1 (a radio bajo reach_inf {rli}; a radio→1/H=5/K=1 reach_inf "
                "{rii} vs reach_H {rih}); ES LA FORMA (reach_inf_true {riit} vs reach_H_true {riht}); la REGULARIZACIÓN la cura "
                "(reach_disc {rid}, reach_inf_reg {rir} cap-autovalor SIN H). Estimable leakage-free (T {t0}->{tN}; Â:=0 {z0}); "
                "sim_check {sclo}/{schi}. RETRACTADO ({no}/4 overclaims): (1) gap ARTEFACTO de K=1 (gap_true K1 +{gk1}->K2 +{gk2}); "
                "(2) forma horizonte NO privilegiada (reach_inf_reg {rir}≈reach_H {rih}); (3) relevancia COLINEAL (ŵ≡unos {ones} "
                "no colapsa a ctrl {cto}); (4) requiere COMPETENCIA (slow_only {so}/fast_only {fo} no fallan). Caveat de "
                "condicionamiento al 137.").format(
                    n=n_seeds, rli=_f(rli), rii=_f(rii), rih=_f(rih), riit=_f(riit), riht=_f(riht), rid=_f(rid), rir=_f(rir),
                    t0=_f(t0), tN=_f(tN), z0=_f(z0), sclo=_f(sclo), schi=_f(schi), no=n_over, gk1=_f(gk1), gk2=_f(gk2),
                    ones=_f(ones), cto=_f(cto), so=_f(so), fo=_f(fo))
    S_EXP123 = Source(tier=5, ref="cognia_x/experiments/exp123_cyclic_substrate", obtained=True, claim=claim123)
    for src in (S_PRINCIPLE, S_C137, S_VERIF, S_EXP123):
        ledger.add_source(src)
    notes.append("4 fuentes (S_PRINCIPLE tier2 reach-∞ cruda frágil bajo ciclos, familia de regularizaciones equivalente; S_C137 tier5 reach-∞ acoplada -frontera ciclos-; S_VERIF tier4 verificación adversarial -4 overclaims cazados-; S_EXP123 tier5 dato propio MIXTA).")

    ev_for = [S_EXP123.ref, S_PRINCIPLE.ref]
    ev_against = [S_EXP123.ref, S_VERIF.ref]
    advtext = ("{V} (EXTIENDE el sustrato ACOPLADO de 137 al régimen con CICLOS / radio espectral->1; NÚCLEO APOYADO + {no} "
               "overclaims RETRACTADOS tras verificación adversarial de 4 agentes, 9no ciclo seguido; leakage-free, sim-validada): "
               "¿sobrevive el keystone valor=ctrl×rel a un sustrato con feedback, y cuál es la forma correcta de la controlabilidad-"
               "por-alcance? NÚCLEO APOYADO (EVIDENCIA A FAVOR): la reach de estado-estacionario CRUDA del 137 (R_inf=(I-Â)^{{-1}}) "
               "es NUMÉRICAMENTE FRÁGIL cerca de radio 1. A radio BAJO (a+g=0.6) la reach-∞ y la finita COINCIDEN (reach_inf {rli}: "
               "reproduce 137, el horizonte no importa cuando A^k decae). A radio→1 (a+g=0.95) con H=5, K=1, la reach-∞ CRUDA "
               "MIS-RANKEA el modo top (reach_inf {rii} vs reach_H {rih}) y NO es ruido de estimación: con params VERDADEROS "
               "reach_inf_true {riit} vs reach_H_true {riht} -> ES LA FORMA (mecanismo: el modo casi-crítico la infla "
               "∝1/(1-radio), pero su beneficio no se materializó en el horizonte; ventana a∈[~0.45,0.65]). La REGULARIZACIÓN la "
               "cura: reach_disc {rid} (descontada) y reach_inf_reg {rir} (cap-de-autovalor, SIN conocer H) recuperan. ESTIMABLE "
               "leakage-free (converge desde abajo T={t0}->{tN}; Â:=0 colapsa a {z0} = la dinámica es load-bearing); sim_check "
               "{sclo}/{schi} (la fórmula del oracle = la física simulada impulso-a-impulso). EVIDENCIA EN CONTRA (retractado por la "
               "verificación de 4 agentes -- todos reprodujeron los probes): (1) el GAP TITULAR (reach_H >> reach_inf) es un "
               "ARTEFACTO de K=1 WINNER-TAKE-ALL -- a K=2 EVAPORA (gap_true K1 +{gk1} -> K2 +{gk2}): reach_inf identifica el CONJUNTO "
               "correcto de modos relevantes, sólo invierte el orden #1<->#2 que la selección top-1 castiga al máximo. (2) la forma "
               "HORIZONTE-H específica NO es privilegiada -- una reach-∞ REGULARIZADA por cap-de-autovalor SIN conocer H IGUALA a "
               "reach_H ({rir}≈{rih}); la novedad genuina es REGULARIZAR el modo casi-crítico, NO el horizonte. (3) la RELEVANCIA es "
               "COLINEAL / no-aislada en este régimen -- con ŵ≡unos (relevancia ELIMINADA manteniendo la estructura) reach_H {ones} "
               "(NO colapsa a ctrl_only {cto}): el control shuffle-ŵ daba un FALSO POSITIVO; el factor load-bearing demostrado es la "
               "CONTROLABILIDAD-REACH, no la relevancia (que 134-137 ya aisló por separado). (4) 'falla cerca de radio 1' requiere "
               "COMPETENCIA de escalas temporales -- con un ÚNICO lazo (slow_only {so}/fast_only {fo}) reach_inf NO falla hasta radio "
               "0.99; el driver es H < tiempo-de-mezcla del lazo lento CON un competidor más rápido por la capacidad K. => MIXTA: la "
               "reach-∞ cruda del 137 es frágil cerca de radio 1 y necesita REGULARIZACIÓN (caveat REAL de CONDICIONAMIENTO al 137, "
               "cuyo dominio es radio<1 con buen condicionamiento), pero NO se establece que la forma horizonte-H sea única (varias "
               "regularizaciones empatan) ni que el efecto sobreviva a K>=2 ni que la relevancia se aísle aquí. MIXTA EXITOSA: la "
               "verificación adversarial corrigió 4 overclaims antes del ledger (9no ciclo seguido). Generaliza el alcance del "
               "keystone (130 costo, 132 esfuerzo, 133/137 red) con un caveat de CONDICIONAMIENTO bajo ciclos.").format(
                   V=status.upper(), no=n_over, rli=_f(rli), rii=_f(rii), rih=_f(rih), riit=_f(riit), riht=_f(riht),
                   rid=_f(rid), rir=_f(rir), t0=_f(t0), tN=_f(tN), z0=_f(z0), sclo=_f(sclo), schi=_f(schi),
                   gk1=_f(gk1), gk2=_f(gk2), ones=_f(ones), cto=_f(cto), so=_f(so), fo=_f(fo))

    hyp = Hypothesis(
        id="H-V4-10m",
        statement=("Bajo un sustrato con CICLOS (feedback, radio espectral->1) la reach de estado-estacionario CRUDA del 137 "
                   "((I-A)^{-1}) es NUMÉRICAMENTE FRÁGIL: el modo casi-crítico la infla y bajo capacidad K=1 mis-rankea el modo top; "
                   "una reach REGULARIZADA (horizonte-finito R_H=Σ_{k<H}A^k, descontada, o cap-de-autovalor SIN H) lo cura -- la "
                   "forma horizonte-H específica NO es privilegiada (la familia de regularizaciones es equivalente). El efecto "
                   "requiere capacidad K=1 + competencia de escalas temporales (a K>=2 evapora) y la relevancia es colineal en este "
                   "régimen. Caveat de CONDICIONAMIENTO al 137 (cuyo dominio es radio<1 con buen condicionamiento). Alcance: lineal, "
                   "ciclo de 2, radio<1, D=8 fijo, ventana a∈[~0.45,0.65]."),
        prediction=("APOYADA si la forma horizonte-H es ÚNICA/privilegiada, el gap es robusto a K, y la relevancia se aísla. MIXTA "
                    "si la reach-∞ cruda es frágil y la regularización la cura (núcleo real) PERO el gap es artefacto de K=1, la "
                    "forma no es privilegiada (varias regularizaciones empatan) y la relevancia es colineal. REFUTADA si la reach-∞ "
                    "cruda NO es frágil. (Pre-registrada; verificación adversarial de 4 agentes: tautología/leakage/fairness/"
                    "robustez.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp123_cyclic_substrate")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-10m")
        notes.append("H-V4-10m marcada '{}': núcleo apoyado (la reach-∞ cruda del 137 es frágil cerca de radio 1, la regularización la cura, es la forma, estimable, sim-validada) + 4 overclaims retractados (K=1 artefacto, forma no privilegiada, relevancia colineal, requiere competencia).".format(status))

    analogy = AnalogyRecord(
        problem=("Tenés una regla para decidir qué vale la pena tocar en una red con efectos que se propagan: 'mirá hasta dónde "
                 "llega tu empujón por la red × cuánto importa' (137, alcance de estado-estacionario). ¿Sirve cuando la red tiene "
                 "LAZOS DE FEEDBACK que casi no se apagan (un eco que rebota mucho)?"),
        everyday=("A medias, y por razones distintas a las que parece. La cuenta de 'hasta dónde llega al final' se VUELVE LOCA "
                  "cuando hay un eco casi infinito (un lazo casi-crítico): le da un número gigante a ese eco. Si tenés que elegir "
                  "UNA sola cosa, esa cuenta te hace apostar al eco -- y pierde, porque el eco tarda muchísimo. PERO: (a) si podés "
                  "elegir DOS cosas, ya no importa: igual agarrás las dos que sirven; el problema era 'elegí una sola'. (b) No hace "
                  "falta la fórmula sofisticada de 'contá hasta tu horizonte': basta con AMORTIGUAR el eco loco (cualquier freno "
                  "sirve) y la cuenta se arregla. (c) Y resulta que en este ejemplo 'cuánto importa' coincidía con 'hasta dónde "
                  "llega', así que ni siquiera estabas usando de verdad la importancia. Moraleja: la regla del eco-infinito es "
                  "FRÁGIL (hay que amortiguarla), pero la 'mejora' que creías -contar hasta el horizonte- no es especial (cualquier "
                  "freno vale) y el efecto sólo se nota cuando tenés que elegir una sola cosa."),
        solutions=["la reach de estado-estacionario CRUDA del 137 es NUMÉRICAMENTE FRÁGIL cerca de radio 1 (el modo casi-crítico la infla): necesita REGULARIZACIÓN",
                   "la familia de regularizaciones es EQUIVALENTE (horizonte-finito, descontada, cap-de-autovalor SIN H): la forma horizonte-H no es privilegiada",
                   "el gap titular es un ARTEFACTO de selección winner-take-all (K=1): a K>=2 evapora -- reach_inf identifica el conjunto correcto, sólo invierte el orden",
                   "la relevancia es COLINEAL en este régimen (no-aislada): el factor load-bearing demostrado es la controlabilidad-reach, no la relevancia"],
        principles=["bajo ciclos la reach-∞ cruda del 137 es FRÁGIL cerca de radio 1 y necesita regularización (caveat de condicionamiento); la forma específica de regularización no es privilegiada",
                    "un GAP grande bajo selección top-1 puede ser una mera inversión de ranking #1<->#2 que evapora con más capacidad (K>=2) -- barrer K antes de titular un gap",
                    "un CONTROL NULO mal elegido (shuffle) da falso positivo donde uno bien elegido (ŵ≡unos) revela COLINEALIDAD -- el control correcto ELIMINA el factor, no lo permuta",
                    "META: 9no ciclo seguido en que la verificación adversarial corrige overclaims (aquí 4: K=1 artefacto, forma no única, relevancia colineal, requiere competencia) antes del ledger"],
        adaptation=("El lab atacó la frontera EXPLÍCITA que 137 dejó abierta ('acople con ciclos cerca de radio 1 degrada') y "
                    "obtiene un MIXTA honesto. SOBREVIVE (núcleo): la reach de estado-estacionario CRUDA del 137 es NUMÉRICAMENTE "
                    "FRÁGIL cerca de radio 1 (el modo casi-crítico la infla y mis-rankea bajo K=1); una regularización la cura; es "
                    "la forma (reach_inf_true falla); estimable leakage-free; sim-validada. Es un caveat REAL de CONDICIONAMIENTO al "
                    "137 (cuyo dominio es radio<1 con buen condicionamiento). NO SOBREVIVE (retractado por la verificación "
                    "adversarial de 4 agentes): (1) el gap titular es artefacto de K=1 winner-take-all (evapora a K>=2); (2) la "
                    "forma horizonte-H no es privilegiada (cap-de-autovalor SIN H la iguala -> la novedad es regularizar el "
                    "casi-crítico, no el horizonte); (3) la relevancia es colineal (ŵ≡unos no colapsa -> el control shuffle daba "
                    "falso positivo); (4) 'falla cerca de radio 1' requiere competencia de escalas temporales. META-LECCIÓN: 9no "
                    "ciclo seguido en que la verificación adversarial corrige overclaims antes del ledger -- aquí 4, incluido un "
                    "control nulo mal elegido (la lección de 134: el control correcto ELIMINA el factor, no lo permuta). Próximo: "
                    "aislar la relevancia bajo ciclos (estructura donde reach != relevancia); el efecto de K (capacidad) sobre el "
                    "valor; el puente EFE (138) bajo condicionamiento; el lazo real; SCALE."),
        measurement=("exp123 ({n} seeds): radio bajo reach_inf {rli} (reproduce 137); radio→1/H=5/K=1 reach_inf {rii} vs reach_H "
                     "{rih}; ES LA FORMA reach_inf_true {riit} vs {riht}; regularización reach_disc {rid}/reach_inf_reg {rir}; "
                     "RETRACTADO: gap K1 +{gk1}->K2 +{gk2}; reach_inf_reg {rir}≈reach_H {rih}; ŵ≡unos {ones} (ctrl {cto}); slow_only "
                     "{so}/fast_only {fo}; estimable T {t0}->{tN}, Â:=0 {z0}; sim_check {sclo}/{schi}.").format(
                         n=n_seeds, rli=_f(rli), rii=_f(rii), rih=_f(rih), riit=_f(riit), riht=_f(riht), rid=_f(rid),
                         rir=_f(rir), gk1=_f(gk1), gk2=_f(gk2), ones=_f(ones), cto=_f(cto), so=_f(so), fo=_f(fo),
                         t0=_f(t0), tN=_f(tN), z0=_f(z0), sclo=_f(sclo), schi=_f(schi)),
        iterations=1)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (la regla del eco-infinito es FRÁGIL -hay que amortiguarla- pero la 'mejora' de contar-hasta-el-horizonte no es especial -cualquier freno vale- y el efecto sólo se ve si elegís una sola cosa).")

    kl = ("REAL (exp123, MIXTA post-verificación adversarial de 4 agentes, leakage-free, sim-validada): bajo un sustrato con CICLOS "
          "la reach de estado-estacionario CRUDA del 137 ((I-A)^{{-1}}) es NUMÉRICAMENTE FRÁGIL cerca de radio espectral 1 (el modo "
          "casi-crítico la infla, mis-rankea bajo K=1); una REGULARIZACIÓN (horizonte-finito, descontada, cap-de-autovalor SIN H) la "
          "cura; es la FORMA (reach_inf_true {riit} vs reach_H_true {riht}, ventana a∈[~0.45,0.65]). Estimable leakage-free (T "
          "{t0}->{tN}, Â:=0 {z0}); sim_check {schi}. RETRACTADO: el gap es artefacto de K=1 (evapora a K>=2: gap_true K1 +{gk1}->K2 "
          "+{gk2}); la forma horizonte NO es privilegiada (reach_inf_reg SIN H {rir}≈reach_H {rih}); la relevancia es COLINEAL "
          "(ŵ≡unos {ones} no colapsa a ctrl {cto}); 'falla' requiere competencia (slow_only {so}/fast_only {fo}). TECHO/ALCANCE: "
          "lineal, ciclo de 2, radio<1, D=8 fijo, K=1; oracle horizonte-H (reach_H_true=oracle por construcción). Frontera: aislar "
          "la relevancia bajo ciclos; el efecto de K; el puente EFE (138) bajo condicionamiento; lazo real; SCALE.").format(
              riit=_f(riit), riht=_f(riht), t0=_f(t0), tN=_f(tN), z0=_f(z0), schi=_f(schi), gk1=_f(gk1), gk2=_f(gk2),
              rir=_f(rir), rih=_f(rih), ones=_f(ones), cto=_f(cto), so=_f(so), fo=_f(fo))
    ceilings.add(CeilingRecord(
        subsystem="CONTROLABILIDAD del keystone R-VALOR (valor=ctrl×rel) bajo sustrato con CICLOS / radio espectral->1 — caveat de CONDICIONAMIENTO a la frontera 'ciclos cerca de radio 1' de 137. NÚCLEO: la reach de estado-estacionario CRUDA del 137 ((I-A)^-1) es NUMÉRICAMENTE FRÁGIL cerca de radio 1 (el modo casi-crítico la infla, mis-rankea bajo K=1); una REGULARIZACIÓN (horizonte-finito R_H=Σ_{k<H}A^k, descontada, o cap-de-autovalor SIN H) la cura; es la forma (reach_inf_true falla); estimable leakage-free; sim-validada. RETRACTADO (4 overclaims): gap artefacto de K=1 (evapora a K>=2); forma horizonte no privilegiada; relevancia colineal; requiere competencia de escalas temporales. Alcance: lineal, ciclo de 2, radio<1, D=8 fijo, K=1",
        known_limit=kl,
        blockers=[{"text": "OVERCLAIM 1 (cazado): el GAP titular reach_H>>reach_inf es ARTEFACTO de K=1 WINNER-TAKE-ALL -- a K>=2 EVAPORA (gap_true K1 +{gk1} -> K2 +{gk2}, en todo el barrido de H, hat Y true). reach_inf NO 'falla': identifica el CONJUNTO correcto de modos relevantes; sólo invierte el orden #1<->#2 que la selección top-1 castiga al máximo. El experimento NO barría K -> no revelaba la evaporación. Lección (cf. 134): barrer la capacidad antes de titular un gap de selección".format(gk1=_f(gk1), gk2=_f(gk2)), "kind": "diseno"},
                  {"text": "OVERCLAIM 2+3 (cazados): (2) la forma HORIZONTE-H específica NO es privilegiada -- una reach-∞ REGULARIZADA por cap-de-autovalor SIN conocer H IGUALA a reach_H (reach_inf_reg {rir}≈reach_H {rih}); la novedad genuina es REGULARIZAR el modo casi-crítico (cualquier freno: horizonte, descuento, cap), no el horizonte per se; el baseline ctrl_only era un strawman. (3) la RELEVANCIA es COLINEAL / no-aislada -- con ŵ≡unos (relevancia ELIMINADA) reach_H {ones} (NO colapsa a ctrl_only {cto}); el control shuffle-ŵ daba un FALSO POSITIVO (inyecta un patrón activamente-equivocado, no elimina la relevancia). El factor load-bearing demostrado es la CONTROLABILIDAD-REACH; la relevancia ya la aisló 134-137 por separado".format(rir=_f(rir), rih=_f(rih), ones=_f(ones), cto=_f(cto)), "kind": "diseno"},
                  {"text": "OVERCLAIM 4 + ALCANCE (cazados): (4) 'falla cerca de radio 1' requiere COMPETENCIA de escalas temporales -- con un ÚNICO lazo (slow_only {so}/fast_only {fo}) reach_inf NO falla hasta radio 0.99; el driver real es H < tiempo-de-mezcla del lazo lento CON un competidor más rápido por la capacidad K, no 'radio alto rompe la fórmula'. El pilar 'es la FORMA' (reach_inf_true falla) tiene ventana angosta a∈[~0.45,0.65] (a=0.7 lo rompe). ALCANCE: sustrato LINEAL, ciclo de 2, radio<1 (para que (I-A)^-1 exista; comparación de FORMA, no divergencia), D=8 fijo (índices ruidosos hardcoded), oracle = costo acumulado Σ_{{t<H}}G_t (reach_H_true=oracle por construcción -- la lección de 138). NO cubre: relevancia aislada bajo ciclos, no-linealidad (135-136), radio>=1, el puente EFE (138) bajo condicionamiento".format(so=_f(so), fo=_f(fo)), "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP123.ref, S_C137.ref, S_VERIF.ref]))
    notes.append("1 techo 'real': la reach-∞ cruda del 137 es frágil cerca de radio 1 (caveat de condicionamiento) y necesita regularización; pero la forma no es única, el gap es artefacto de K=1, la relevancia es colineal. 4 overclaims auto-documentados.")

    dstmt = ("North-Star R-VALOR (EXTIENDE el sustrato ACOPLADO de 137 al régimen con CICLOS / radio espectral->1; caveat de "
             "CONDICIONAMIENTO a la frontera de 137): MIXTA. NÚCLEO -- la reach de estado-estacionario CRUDA del 137 ((I-A)^{{-1}}) es "
             "NUMÉRICAMENTE FRÁGIL cerca de radio 1 (el modo casi-crítico la infla, mis-rankea bajo K=1); una REGULARIZACIÓN "
             "(horizonte-finito, descontada, o cap-de-autovalor SIN H) la cura; es la forma (reach_inf_true {riit} vs reach_H_true "
             "{riht}); estimable leakage-free, sim-validada. RETRACTADO (4 overclaims, verificación adversarial de 4 agentes): el gap "
             "es artefacto de K=1 (evapora a K>=2, +{gk1}->+{gk2}); la forma horizonte NO es privilegiada (reach_inf_reg SIN H "
             "{rir}≈reach_H {rih}); la relevancia es COLINEAL (ŵ≡unos {ones} no colapsa a ctrl {cto}); 'falla' requiere competencia "
             "(slow_only {so}). Decisión: adoptar que la reach-∞ del 137 necesita REGULARIZACIÓN bajo ciclos (cualquier freno del "
             "modo casi-crítico), NO una forma horizonte específica; el caveat es de condicionamiento. META-DECISIÓN: 9no ciclo con "
             "verificación adversarial (4 overclaims corregidos, incl. un control nulo mal elegido). Próximo: aislar la relevancia "
             "bajo ciclos; el efecto de K; el puente EFE (138) bajo condicionamiento; lazo real; SCALE.").format(
                 riit=_f(riit), riht=_f(riht), gk1=_f(gk1), gk2=_f(gk2), rir=_f(rir), rih=_f(rih), ones=_f(ones), cto=_f(cto),
                 so=_f(so))
    drat = ("exp123 (tier5, propio, {n} seeds, numpy, post-verificación de 4 agentes): la reach-∞ cruda del 137 es frágil cerca de "
            "radio 1 (mis-rankea bajo K=1) y la regularización la cura -- es la forma (reach_inf_true {riit} vs reach_H_true {riht}), "
            "estimable leakage-free, sim-validada. PERO el gap es artefacto de K=1 (evapora a K>=2), la forma horizonte no es "
            "privilegiada (reach_inf_reg SIN H la iguala) y la relevancia es colineal (ŵ≡unos no colapsa). Convergente con el "
            "principio (tier2) y la verificación (tier4); ACOTA la frontera 'ciclos' de 137 (tier5). MIXTA: núcleo apoyado (caveat "
            "de condicionamiento) + 4 overclaims retractados.").format(n=n_seeds, riit=_f(riit), riht=_f(riht))
    dec = Decision(id="D-V4-101", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP123), _to_plain(S_C137), _to_plain(S_VERIF)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-101 ACEPTADA por el ledger (tier5 exp123 + tier5 exp121/C137 + tier4 verificación adversarial).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-101:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle139_cyclic_substrate',
                                description='CYCLE 139 (RESET v4, H-V4-10m MIXTA: la reach-∞ cruda del 137 es frágil cerca de radio 1 -necesita regularización- pero el gap es artefacto de K=1, la forma horizonte no es única, la relevancia es colineal; 9no ciclo con verificación adversarial).')
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
    print("RESUMEN — CYCLE 139 (RESET v4): la reach-∞ cruda del 137 es FRÁGIL bajo ciclos (necesita regularización) — H-V4-10m MIXTA")
    print("=" * 78)
    print("veredicto H-V4-10m:", status.upper() if status else "?")
    print("  NÚCLEO APOYADO: la reach de estado-estacionario CRUDA del 137 ((I-A)^-1) es NUMÉRICAMENTE FRÁGIL cerca de radio 1 (mis-rankea bajo K=1); una regularización (horizonte-finito/descontada/cap-de-autovalor SIN H) la cura; es la forma, estimable leakage-free, sim-validada. RETRACTADO (4 overclaims): gap artefacto de K=1 (evapora a K>=2); forma horizonte NO privilegiada; relevancia COLINEAL; requiere competencia de escalas temporales.")
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
