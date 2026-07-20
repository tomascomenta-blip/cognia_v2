r"""
cycle143_relevance_isolation.py — CICLO 143 (RESET v4, rama control/acción, ATACA el caveat de 139: aislar la relevancia bajo
CICLOS donde reach≠relevancia): H-V4-10o por las compuertas del engine.

VEREDICTO: MIXTA (núcleo real bajo escasez + 3 acotaciones por verificación adversarial de 2 agentes; 13mo ciclo seguido).

QUÉ SOBREVIVE (robusto en radio/T/seeds): construyendo un sustrato cíclico con reach≠relevancia (modos relevante-ALCANZABLE,
relevante-INALCANZABLE, alcanzable-IRRELEVANTE) y bajo CAPACIDAD ESCASA (K=1) con drivers irrelevantes COMPITIENDO, la
reach-relevancia estimada |b̂·(I-Â)^{-T}ŵ| AÍSLA el driver relevante-alcanzable donde ctrl_only/rel_only/null-ŵ no pueden;
estimable leakage-free.

QUÉ NO SOBREVIVE (retractado por la verificación -- el experimento lo AUTO-DOCUMENTA):
  (1) el aislamiento es CONDICIONAL a K<#drivers: a K=#drivers EVAPORA (ctrl_only=reach, ŵ≡unos deja de romper) -- el MISMO
      artefacto K=1 winner-take-all que la verificación de 139 YA RETRACTÓ (no se barría K).
  (2) el 'cierre de 139' depende de los DECOYS, no de la disociación per se: con n_decoy=0 ŵ≡unos NO rompe -- REPRODUCE 139 exacto.
  (3) TAUTOLOGÍA: reach con params VERDADEROS = oracle por construcción (sin sim_check); rel_only=0 es estructural (b,w disjuntos);
      el 'ŵ≡unos rompe' es artefacto de decoys SIMÉTRICOS.

=> el sustrato disocia genuinamente reach de relevancia y, BAJO ESCASEZ DE CAPACIDAD + decoys, la relevancia ES load-bearing
(consistente con 142), PERO NO cierra el caveat de 139 incondicionalmente. MIXTA EXITOSA: la verificación cazó el re-uso del
artefacto K=1 + la tautología antes del ledger (13mo ciclo).

DERIVA de exp127_relevance_isolation/results/results.json.
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle143_relevance_isolation')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp127_relevance_isolation', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="bajo un sustrato cíclico donde reach≠relevancia, la relevancia se vuelve LOAD-BEARING (necesaria para componer la reach-relevancia del keystone) SÓLO bajo capacidad ESCASA (K<#drivers controlables) con drivers irrelevantes compitiendo; a capacidad K>=#drivers el efecto EVAPORA (la selección bruta captura el relevante de regalo) -- el mismo artefacto K=1 que la verificación de 139 ya retractó. El cierre del caveat de 139 (la relevancia colineal) depende de la multiplicidad/simetría de los decoys + la escasez, no de la disociación per se; y el nivel reach=oracle es tautológico por construcción.", obtained=False,
                     claim=("Bajo ciclos con reach≠relevancia, la relevancia es load-bearing sólo bajo capacidad escasa + decoys "
                            "competidores; evapora a K>=#drivers (artefacto K=1 de 139) y el cierre depende de los decoys, no de la "
                            "disociación per se. (Principio.)"))
S_C139 = Source(tier=5, ref="cognia_x/experiments/exp123_cyclic_substrate (CYCLE 139, caveat de relevancia colineal + artefacto K=1) + exp121 (CYCLE 137)", obtained=True,
                claim=("CYCLE 139 dejó como caveat que bajo ciclos la relevancia era COLINEAL con la reach (ŵ≡unos NO rompía) y "
                       "RETRACTÓ un gap que era artefacto de K=1 winner-take-all. H-V4-10o ataca el caveat con un sustrato "
                       "reach≠relevancia: lo cierra CONDICIONALMENTE (bajo K<#drivers + decoys) pero RE-INTRODUCE el mismo artefacto "
                       "K=1 que 139 retractó."))
S_VERIF = Source(tier=4, ref="verificación adversarial de 2 agentes (lentes tautología-definicional / robustez-K-decoys; probes reales numpy)", obtained=True,
                 claim=("La verificación adversarial (13mo ciclo) CONFIRMÓ el núcleo robusto (radio 0.75-0.99/T/seeds: el agente "
                        "aísla la reach leakage-free) PERO CAZÓ: el aislamiento EVAPORA a K>=#drivers (el artefacto K=1 de 139, no se "
                        "barría K); con n_decoy=0 ŵ≡unos NO rompe (reproduce 139 -> el cierre depende de los decoys); reach=oracle "
                        "por construcción (tautológico, sin sim_check); rel_only=0 es estructural; el 'ŵ≡unos rompe' es artefacto de "
                        "decoys simétricos."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp127 primero): " + results_path)

    reach = sm['reach']; cto = sm['ctrl_only']; rel = sm['rel_only']; rmc = sm['reach_minus_ctrl']; rmr = sm['reach_minus_rel']
    sh = sm['shuffle_reach']; on = sm['ones_reach']; ndrv = sm['n_drivers']
    kfull = sm['by_K'][str(ndrv)] if str(ndrv) in sm['by_K'] else sm['by_K'][list(sm['by_K'].keys())[-1]]
    ndob = sm['nodecoy_ones_break']; n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim127 = ("exp127 (propio, {n} seeds, numpy, post-verificación de 2 agentes): {V}. NÚCLEO (robusto en radio/T/seeds): bajo un "
                "sustrato cíclico con reach≠relevancia y capacidad ESCASA K=1 + decoys, la reach-relevancia estimada aísla el driver "
                "relevante-alcanzable (reach {rh}; +{rmc} sobre ctrl_only, +{rmr} sobre rel_only; shuffle-ŵ y ŵ≡unos rompen). "
                "RETRACTADO: EVAPORA a K={ndrv}=#drivers (reach-ctrl {gke}, reach-ones {gko}: el artefacto K=1 de 139); n_decoy=0 "
                "reproduce 139 (ones-break {ndob}); reach=oracle por construcción (tautológico); rel_only=0 estructural.").format(
                    n=n_seeds, V=status.upper(), rh=_f(reach), rmc=_f(rmc), rmr=_f(rmr), ndrv=ndrv,
                    gke=_f(kfull['reach'] - kfull['ctrl_only']), gko=_f(kfull['reach'] - kfull['ones_reach']), ndob=_f(ndob))
    S_EXP127 = Source(tier=5, ref="cognia_x/experiments/exp127_relevance_isolation", obtained=True, claim=claim127)
    for src in (S_PRINCIPLE, S_C139, S_VERIF, S_EXP127):
        ledger.add_source(src)
    notes.append("4 fuentes (S_PRINCIPLE tier2 la relevancia es load-bearing sólo bajo escasez+decoys, evapora a K>=#drivers; S_C139 tier5 caveat colineal + artefacto K=1; S_VERIF tier4 verificación adversarial; S_EXP127 tier5 dato propio {}).".format(status.upper()))

    ev_for = [S_EXP127.ref, S_PRINCIPLE.ref]
    ev_against = [S_EXP127.ref, S_VERIF.ref]
    advtext = ("{V} (ATACA el caveat de 139 -aislar la relevancia bajo ciclos donde reach≠relevancia-; caracterización honesta tras "
               "verificación adversarial de 2 agentes, 13mo ciclo): el CYCLE 139 dejó que bajo ciclos la relevancia era COLINEAL con "
               "la reach (ŵ≡unos NO rompía -> el factor load-bearing era la reach, no la relevancia). QUÉ SOBREVIVE (robusto en "
               "radio/T/seeds): construyendo un sustrato con reach≠relevancia (modos relevante-ALCANZABLE, relevante-INALCANZABLE "
               "b=0, alcanzable-IRRELEVANTE w=0) y bajo CAPACIDAD ESCASA K=1 con drivers irrelevantes COMPITIENDO, la reach-"
               "relevancia estimada |b̂·(I-Â)^{{-T}}ŵ| (b̂,Â,ŵ de un stream) AÍSLA el único driver relevante-alcanzable: reach {rh} "
               "(pick correcto), +{rmc} sobre ctrl_only ({cto}, la RELEVANCIA añade) y +{rmr} sobre rel_only ({rel}, la REACH añade); "
               "shuffle-ŵ rompe (reach->{sh}) Y ŵ≡unos rompe (reach->{on}); estimable leakage-free (converge desde abajo con T, "
               "robusto a radio 0.75-0.99 -- la fragilidad de (I-A)^-1 de 139 NO materializa). QUÉ NO SOBREVIVE (retractado por la "
               "verificación de 2 agentes): (1) el aislamiento es CONDICIONAL a K<#drivers -- a K={ndrv} (=#drivers controlables) "
               "EVAPORA (reach-ctrl_only {gke}, reach-ones {gko}): ctrl_only captura el relevante por barrido bruto y ŵ≡unos deja de "
               "romper; es EXACTAMENTE el artefacto K=1 winner-take-all que la verificación de 139 YA RETRACTÓ (yo NO barría K en la "
               "1ra versión -- inconsistencia auto-cazada). (2) el 'cierre de 139' depende de los DECOYS, no de la disociación per "
               "se: con n_decoy=0 (un solo driver, el relevante) ŵ≡unos NO rompe (ones-break {ndob}) -- REPRODUCE 139 EXACTO. (3) "
               "TAUTOLOGÍA: reach con params VERDADEROS = oracle por construcción (sin sim_check, a diferencia de 139); rel_only=0 es "
               "ESTRUCTURAL (b y w nunca co-localizados en el sustrato) -> 'reach bate a rel_only' es definicional; el 'ŵ≡unos "
               "rompe' es un artefacto de decoys SIMÉTRICOS (clones geométricos -> reach les da score idéntico -> 1/#drivers). => "
               "RESULTADO HONESTO: el sustrato disocia genuinamente reach de relevancia y, BAJO ESCASEZ DE CAPACIDAD (K<#drivers) + "
               "decoys competidores, la relevancia ES load-bearing (consistente con 142: el producto importa bajo escasez de "
               "capacidad×disociación); PERO NO cierra el caveat de 139 incondicionalmente -- re-introduce el artefacto K=1 de 139, "
               "el nivel reach=1.0 es tautológico, y el 'ŵ≡unos rompe' depende de la multiplicidad/simetría de decoys. APORTE: la "
               "honestidad de que el 'cierre' es condicional + la conexión con 142 (relevancia load-bearing bajo escasez). MIXTA "
               "EXITOSA: la verificación cazó el re-uso del artefacto K=1 de 139 + la tautología antes del ledger (13mo ciclo). "
               "Frontera: un test del aislamiento que NO dependa de K=1 (capacidad continua / decoys asimétricos); SCALE.").format(
                   V=status.upper(), rh=_f(reach), rmc=_f(rmc), cto=_f(cto), rmr=_f(rmr), rel=_f(rel), sh=_f(sh), on=_f(on),
                   ndrv=ndrv, gke=_f(kfull['reach'] - kfull['ctrl_only']), gko=_f(kfull['reach'] - kfull['ones_reach']),
                   ndob=_f(ndob))

    hyp = Hypothesis(
        id="H-V4-10o",
        statement=("Bajo un sustrato cíclico donde reach≠relevancia (relevante-alcanzable, relevante-INALCANZABLE, alcanzable-"
                   "IRRELEVANTE), el agente que descubre b̂/Â/ŵ de un stream AÍSLA ambos factores del keystone (la reach-relevancia "
                   "valora el relevante-alcanzable y AMBOS controles nulos rompen) -- pero SÓLO bajo capacidad ESCASA (K<#drivers) "
                   "con decoys competidores; a K>=#drivers EVAPORA (artefacto K=1 de 139), el cierre depende de los decoys (n_decoy=0 "
                   "reproduce 139), y reach=oracle es tautológico. Alcance: numpy, lineal, ciclo simétrico."),
        prediction=("APOYADA si el aislamiento es INCONDICIONAL (no depende de K=1 ni de los decoys) y no-tautológico. MIXTA si el "
                    "aislamiento es real bajo escasez+decoys pero condicional a K<#drivers / depende de los decoys / reach=oracle "
                    "tautológico. REFUTADA si ni a K=1 aísla. (Pre-registrada; verificación adversarial de 2 agentes.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp127_relevance_isolation")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-10o")
        notes.append("H-V4-10o marcada '{}': el sustrato disocia reach de relevancia y bajo escasez de capacidad (K=1)+decoys la relevancia es load-bearing (robusto en radio/T/seeds), PERO evapora a K>=#drivers (el artefacto K=1 de 139), el cierre depende de los decoys (n_decoy=0 reproduce 139), y reach=oracle es tautológico. No cierra el caveat de 139 incondicionalmente.".format(status))

    analogy = AnalogyRecord(
        problem=("Querías mostrar que para decidir qué tocar en una red con efectos que rebotan hay que mirar DOS cosas (hasta dónde "
                 "llegás × cuánto importa), no una sola -- algo que en el intento anterior (139) no se vio porque las dos cosas "
                 "venían pegadas. ¿Lo lograste?"),
        everyday=("Sí pero con asterisco grande. Armaste un caso donde 'lo que podés mover' y 'lo que importa' están de verdad "
                  "separados (hay cosas importantes que NO podés tocar, y cosas que podés tocar que NO importan), y ahí sí: para "
                  "elegir bien hace falta mirar las dos. PERO sólo funciona si tenés que elegir UNA sola cosa entre VARIAS "
                  "parecidas: si podés elegir tantas como opciones hay, agarrás la buena de regalo y da igual mirar la importancia "
                  "-- exactamente el problema que vos mismo habías marcado antes (139) y acá lo volviste a meter sin querer. Y el "
                  "'ahora sí se nota la importancia' depende de haber puesto señuelos: sin señuelos, vuelve a no notarse (igual que "
                  "139). Encima 'cuánto llega' lo medís con la misma fórmula que define el valor, así que ese número es medio "
                  "tramposo. Moraleja honesta: el caso disocia de verdad las dos cosas, pero el 'cierre' es condicional (escasez + "
                  "señuelos), no general."),
        solutions=["construir un sustrato con reach≠relevancia (relevante-inalcanzable + alcanzable-irrelevante) disocia genuinamente los dos factores",
                   "bajo capacidad escasa (K<#drivers) + decoys competidores, la relevancia ES load-bearing (ambos controles rompen)",
                   "PERO evapora a K>=#drivers (el artefacto K=1 winner-take-all que 139 ya había retractado) -- barrer K es obligatorio",
                   "el 'cierre de 139' depende de los decoys (n_decoy=0 reproduce 139) y el nivel reach=oracle es tautológico"],
        principles=["la relevancia bajo ciclos es load-bearing sólo bajo ESCASEZ de capacidad + decoys competidores -- consistente con 142 (el producto importa bajo escasez de capacidad×disociación)",
                    "BARRER LA CAPACIDAD K es obligatorio antes de titular un efecto de selección: el artefacto K=1 winner-take-all reaparece (139 lo retractó, 143 lo re-introdujo sin querer)",
                    "un 'control nulo rompe' que depende de la multiplicidad/simetría de decoys + K=1 no aísla el factor de forma incondicional",
                    "META: 13mo ciclo seguido con verificación adversarial -- aquí cazó el RE-USO de un artefacto ya retractado (autoconsistencia del ledger) + tautología"],
        adaptation=("El CYCLE 139 dejó como frontera #1 'aislar la relevancia bajo ciclos donde reach≠relevancia'. Este ciclo lo "
                    "ataca construyendo el sustrato disociado y obtiene un MIXTA honesto: bajo ESCASEZ de capacidad (K=1) + decoys "
                    "competidores la relevancia ES load-bearing (el agente aísla ambos factores, robusto en radio/T/seeds) -- pero "
                    "NO cierra el caveat incondicionalmente: el efecto EVAPORA a K>=#drivers (el MISMO artefacto K=1 que la "
                    "verificación de 139 retractó -- re-introducido sin barrer K), el 'cierre' depende de los decoys (n_decoy=0 "
                    "reproduce 139), y reach=oracle es tautológico (sin sim_check). APORTE: la honestidad de que el cierre es "
                    "CONDICIONAL (escasez+decoys) + la conexión con 142 (la relevancia es load-bearing bajo escasez de capacidad). "
                    "META-LECCIÓN: 13mo ciclo seguido con verificación adversarial -- aquí cazó el re-uso de un artefacto ya "
                    "retractado por el propio lab (la verificación protege la AUTOCONSISTENCIA del ledger). Próximo: un test del "
                    "aislamiento que no dependa de K=1 (capacidad continua / decoys asimétricos); SCALE."),
        measurement=("exp127 ({n} seeds): K=1 reach {rh} (+{rmc} sobre ctrl_only, +{rmr} sobre rel_only; shuffle->{sh}, ŵ≡unos->{on} "
                     "rompen); EVAPORA a K={ndrv}: reach-ctrl {gke}, reach-ones {gko}; n_decoy=0 ones-break {ndob} (reproduce 139); "
                     "reach=oracle por construcción.").format(
                         n=n_seeds, rh=_f(reach), rmc=_f(rmc), rmr=_f(rmr), sh=_f(sh), on=_f(on), ndrv=ndrv,
                         gke=_f(kfull['reach'] - kfull['ctrl_only']), gko=_f(kfull['reach'] - kfull['ones_reach']), ndob=_f(ndob)),
        iterations=1)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (el caso disocia de verdad reach de relevancia, pero el 'cierre' es condicional -escasez+señuelos- y re-mete el artefacto K=1 de 139; reach=oracle es tramposo).")

    kl = ("REAL (exp127, {V} post-verificación adversarial de 2 agentes): bajo un sustrato cíclico con reach≠relevancia y capacidad "
          "ESCASA K=1 + decoys, la relevancia es LOAD-BEARING (el agente aísla la reach-relevancia leakage-free, robusto en radio "
          "0.75-0.99/T/seeds: reach {rh}, +{rmc} sobre ctrl_only, +{rmr} sobre rel_only, ambos controles rompen). TECHO/ALCANCE: "
          "CONDICIONAL a K<#drivers -- a K={ndrv} EVAPORA (el artefacto K=1 de 139); el cierre depende de los DECOYS (n_decoy=0 "
          "reproduce 139, ones-break {ndob}); reach=oracle por construcción (tautológico, sin sim_check); rel_only=0 estructural; "
          "el ŵ≡unos-rompe es artefacto de decoys simétricos; numpy/lineal/ciclo. Frontera: aislamiento sin dependencia de K=1 "
          "(capacidad continua/decoys asimétricos); SCALE.").format(
              V=status.upper(), rh=_f(reach), rmc=_f(rmc), rmr=_f(rmr), ndrv=ndrv, ndob=_f(ndob))
    ceilings.add(CeilingRecord(
        subsystem="AISLAR la relevancia bajo CICLOS donde reach≠relevancia (ataca el caveat de 139) — bajo capacidad ESCASA (K<#drivers) + decoys competidores, la relevancia es LOAD-BEARING (el agente aísla la reach-relevancia leakage-free, robusto en radio/T/seeds). CONDICIONAL: evapora a K>=#drivers (el artefacto K=1 de 139), el cierre depende de los decoys (n_decoy=0 reproduce 139), reach=oracle por construcción (tautológico), rel_only=0 estructural. NO cierra el caveat de 139 incondicionalmente. Alcance: numpy, lineal, ciclo simétrico",
        known_limit=kl,
        blockers=[{"text": "ARTEFACTO K=1 RE-INTRODUCIDO (el modo de fallo central, auto-cazado): el aislamiento EVAPORA a K={ndrv} (=#drivers controlables): reach-ctrl_only {gke}, reach-ones {gko} -> ctrl_only captura el relevante por barrido bruto y ŵ≡unos deja de romper. Es EXACTAMENTE el artefacto K=1 winner-take-all que la verificación de 139 YA RETRACTÓ; la 1ra versión NO barría K (hardcodeaba KSEL=1). Lo NO-trivial/load-bearing: el sustrato disocia genuinamente reach de relevancia y BAJO ESCASEZ (K<#drivers)+decoys la relevancia ES necesaria (consistente con 142)".format(ndrv=ndrv, gke=_f(kfull['reach'] - kfull['ctrl_only']), gko=_f(kfull['reach'] - kfull['ones_reach'])), "kind": "diseno"},
        {"text": "DEPENDENCIA DE DECOYS + TAUTOLOGÍA: (a) el 'cierre de 139' depende de los DECOYS, no de la disociación per se -- con n_decoy=0 (un solo driver) ŵ≡unos NO rompe (ones-break {ndob}), REPRODUCE 139 exacto; el 'ŵ≡unos rompe' es un artefacto de decoys SIMÉTRICOS (clones geométricos -> reach les da score idéntico -> 1/#drivers). (b) reach con params VERDADEROS = oracle por construcción (sin sim_check, a diferencia de 139); rel_only=0 es ESTRUCTURAL (b,w nunca co-localizados) -> 'reach bate a rel_only' es definicional. Lo no-tautológico: la ESTIMACIÓN (b̂,Â,ŵ de un stream) recupera la reach leakage-free y converge desde abajo".format(ndob=_f(ndob)), "kind": "diseno"},
        {"text": "ALCANCE: numpy/toy, sustrato lineal con ciclo SIMÉTRICO (decoys = clones geométricos), radio<1, capacidad winner-take-all (K=1). NO cubre: capacidad CONTINUA (no elegir-K-de-D), decoys ASIMÉTRICOS, no-linealidad (135-136), el lazo real, SCALE. El cierre INCONDICIONAL del caveat de 139 (aislamiento sin dependencia de K=1) queda ABIERTO", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP127.ref, S_C139.ref, S_VERIF.ref]))
    notes.append("1 techo 'real': bajo ciclos con reach≠relevancia y escasez de capacidad+decoys la relevancia es load-bearing (robusto en radio/T/seeds); pero evapora a K>=#drivers (artefacto K=1 de 139), el cierre depende de los decoys, y reach=oracle es tautológico. No cierra 139 incondicionalmente.")

    dstmt = ("North-Star R-VALOR (ATACA el caveat de 139: aislar la relevancia bajo ciclos donde reach≠relevancia): {V}. Construyendo "
             "un sustrato disociado (reach≠relevancia) y bajo capacidad ESCASA K=1 + decoys, la relevancia es LOAD-BEARING (el agente "
             "aísla la reach-relevancia leakage-free, robusto en radio/T/seeds: reach {rh}, +{rmc} sobre ctrl_only, +{rmr} sobre "
             "rel_only, ambos controles rompen). PERO el aislamiento EVAPORA a K={ndrv}=#drivers (el artefacto K=1 de 139, "
             "re-introducido), el cierre depende de los decoys (n_decoy=0 reproduce 139), y reach=oracle es tautológico. Decisión: NO "
             "declarar cerrado el caveat de 139; adoptar que la relevancia es load-bearing bajo ESCASEZ de capacidad+decoys "
             "(consistente con 142). META-DECISIÓN: 13mo ciclo con verificación adversarial (cazó el re-uso del artefacto K=1). "
             "Próximo: aislamiento sin dependencia de K=1; SCALE.").format(
                 V=status.upper(), rh=_f(reach), rmc=_f(rmc), rmr=_f(rmr), ndrv=ndrv)
    drat = ("exp127 (tier5, propio, {n} seeds, numpy, post-verificación de 2 agentes): el sustrato disocia reach de relevancia y bajo "
            "escasez (K=1)+decoys la relevancia es load-bearing (robusto en radio/T/seeds) PERO evapora a K>=#drivers (el artefacto "
            "K=1 de 139), el cierre depende de los decoys (n_decoy=0 reproduce 139), y reach=oracle es tautológico. Convergente con el "
            "principio (tier2) y la verificación (tier4); ataca -sin cerrar incondicionalmente- el caveat de 139 (tier5). MIXTA: "
            "aislamiento condicional a escasez+decoys, no incondicional.").format(n=n_seeds)
    dec = Decision(id="D-V4-105", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP127), _to_plain(S_C139), _to_plain(S_VERIF)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-105 ACEPTADA por el ledger (tier5 exp127 + tier5 exp123/C139 + tier4 verificación adversarial).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-105:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle143_relevance_isolation',
                                description='CYCLE 143 (RESET v4, H-V4-10o MIXTA: bajo ciclos con reach≠relevancia y escasez de capacidad+decoys la relevancia es load-bearing, pero evapora a K>=#drivers -el artefacto K=1 de 139- y el cierre depende de los decoys; 13mo ciclo con verificación adversarial).')
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
    print("RESUMEN — CYCLE 143 (RESET v4): aislar la relevancia bajo ciclos reach≠relevancia (ataca el caveat de 139) — H-V4-10o " + (status.upper() if status else "?"))
    print("=" * 78)
    print("veredicto H-V4-10o:", status.upper() if status else "?")
    print("  NÚCLEO (robusto radio/T/seeds): bajo escasez de capacidad K=1 + decoys, la relevancia es LOAD-BEARING (el agente aísla la reach-relevancia leakage-free). ACOTADO: EVAPORA a K>=#drivers (el artefacto K=1 de 139, re-introducido); el cierre depende de los decoys (n_decoy=0 reproduce 139); reach=oracle por construcción (tautológico). No cierra el caveat de 139 incondicionalmente.")
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
