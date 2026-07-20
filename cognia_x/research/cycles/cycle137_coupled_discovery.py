r"""
cycle137_coupled_discovery.py — CICLO 137 (RESET v4, rama control/acción, UNIFICA el sustrato ACOPLADO de 133 con la relevancia
DESCUBIERTA de 134): H-V4-10k por las compuertas del engine. ¿Descubre el agente el R-VALOR de un sustrato ACOPLADO de UN solo
stream -- la controlabilidad (b̂), el ACOPLE (Â) y la relevancia (ŵ por credit-assignment) todos estimados-, y los COMPONE en la
REACH-relevancia que 133 mostró necesaria?

VEREDICTO: APOYADA. Cierra la frontera explícita de 134 (la colinealidad del credit-assignment bajo acople) y unifica el arco
control/acción 127-136.

CONTEXTO. 133 (exp117) mostró que bajo acople el keystone valor=ctrl×rel sobrevive pero la controlabilidad debe ser de ALCANCE-POR-
LA-RED (reach); el LOCAL (w·b̂²) falla porque no elige al DRIVER controlable-pero-directamente-irrelevante que regula al TARGET.
PERO 133 dio la relevancia w DADA. 134 (exp118) mostró que la relevancia se DESCUBRE por credit-assignment (G ~ x) PERO en un
sustrato INDEPENDIENTE. Este ciclo es la INTERSECCIÓN: descubrir la relevancia POR CREDIT-ASSIGNMENT bajo un sustrato ACOPLADO.

RESULTADO (exp121, 200 seeds). El agente descubre b̂ (controlabilidad), Â (acople, system-ID) y ŵ (relevancia, credit-assignment)
de UN stream y los compone: composed_i = |b̂_i · ((I-Â)^{-T} ŵ)_i|. A κ=0 composed=local=1.000 (recupera 134). Bajo acople fuerte
(κ=0.9) composed RECUPERA la decisión oracle (1.000, corr(m̂,m)=0.99) mientras el LOCAL FALLA (0.415, +0.585): hay que RETRO-
PROPAGAR la relevancia por el acople estimado. El reach COMPLETO es necesario (en multihop el 1-salto FALLA 0.365 vs composed
0.998; no es straw-man: en base el 1-hop basta). Robusto a estructura (base/multihop/distractor; el local cae en las tres). HALLAZGO
clave: la COLINEALIDAD del credit-assignment NO confunde ŵ (corr_w=1.00) -- OLS de G sobre el estado COMPLETO recupera la relevancia
DIRECTA limpiamente (el target está en la regresión y absorbe el crédito); el fallo del local NO es por ŵ confundido sino porque la
relevancia DIRECTA ≠ relevancia-de-decisión bajo acople. El costo de datos está en estimar Â (a T=30 composed=0.76, corr_m=0.69 ->
1.000 a T>=300): el reach se paga estimando el acople (D×D params), no la relevancia.

CAVEAT honesto (anticipa la verificación adversarial, cf. 133): composed tiene la FORMA del oracle con cantidades estimadas; el
contenido SUSTANTIVO es (i) el LOCAL (forma equivocada) FALLA y (ii) composed converge al oracle GENUINAMENTE DESDE ABAJO (T=30:
0.76, NO oracle-relabeled). El acople es DAG (estable, radio espectral a=0.6); acople con ciclos / autovalores cerca de 1 (donde
(I-Â)^{-1} explota) es frontera.

DERIVA de exp121_coupled_discovery/results/results.json.

Correr (DESPUÉS de exp121):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp121_coupled_discovery.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle137_coupled_discovery
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle137_coupled_discovery')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp121_coupled_discovery', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="el R-VALOR de un sustrato ACOPLADO es descubrible de UN solo stream de experiencia-acción: la controlabilidad (b̂) y el ACOPLE (Â) por system-ID actuando (128), la relevancia DIRECTA (ŵ) por credit-assignment (134); el valor-de-decisión es la REACH-relevancia |b̂·(I-Â)^{-T}ŵ| (133). La colinealidad del estado acoplado NO confunde el credit-assignment (OLS sobre el estado completo recupera la relevancia directa); el costo de datos del reach está en estimar el acople.", obtained=False,
                     claim=("El R-VALOR de un sustrato ACOPLADO es totalmente endógeno de una experiencia de acción: b̂ (ctrl), Â "
                            "(acople) y ŵ (relevancia directa) se estiman del mismo stream, y la REACH-relevancia |b̂·(I-Â)^{-T}ŵ| "
                            "gobierna la decisión. El keystone LOCAL (b̂·ŵ) falla bajo acople (la relevancia directa ≠ relevancia-"
                            "de-decisión); el reach COMPLETO es necesario (1-hop falla en multi-hop). La colinealidad del credit-"
                            "assignment NO rompe ŵ (OLS sobre el estado completo es insesgado); el costo de datos del reach está en "
                            "estimar el acople Â (D×D), no la relevancia. (Principio.)"))
S_C133 = Source(tier=5, ref="cognia_x/experiments/exp117_coupled_substrate", obtained=True,
                claim=("CYCLE 133: bajo acople el keystone sobrevive pero la controlabilidad debe ser de ALCANCE-POR-LA-RED (reach) "
                       "y la selección adaptativa; el LOCAL falla (relevancia directa = proxy infiel del alcance). PERO con la "
                       "relevancia w DADA. H-V4-10k cierra ese supuesto: descubre la relevancia por credit-assignment bajo acople."))
S_C134 = Source(tier=5, ref="cognia_x/experiments/exp118_discovered_relevance", obtained=True,
                claim=("CYCLE 134: la relevancia se DESCUBRE del mapa estado->meta (credit assignment) PERO en un sustrato "
                       "INDEPENDIENTE; la frontera explícita era la relevancia bajo sustrato ACOPLADO (colinealidad del credit-"
                       "assignment). H-V4-10k la cierra: la colinealidad NO confunde ŵ; el reach con Â estimado recupera."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp121 primero): " + results_path)

    c0 = sm['k0_composed']; l0 = sm['k0_local']; ch = sm['khi_composed']; lh = sm['khi_local']
    cw = sm['khi_corr_w']; cm = sm['khi_corr_m']; gap = sm['gap_hi']
    cto = sm['khi_ctrl_only']; noT = sm['khi_composed_noT']; rnet = sm['reach_net']; wfg = sm['wrongform_gap']
    tmin = sm['Tmin_composed']; tmax = sm['Tmax_composed']
    mhc = sm['multihop_composed']; mh1 = sm['multihop_1hop']; b1 = sm['base_1hop']
    sc = sm['struct_composed']; sl = sm['struct_local']
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim121 = ("exp121 (propio, {n} seeds, numpy, post-verificación adversarial de 3 agentes): el agente DESCUBRE el R-VALOR de un "
                "sustrato ACOPLADO de UN stream (b̂, Â, ŵ estimados) y lo compone en la REACH-relevancia |b̂·(I-Â)^{{-T}}ŵ|. "
                "Load-bearing = GAPS + NECESIDAD DE LA FORMA, no el nivel 1.000 (forma=oracle por construcción): (i) composed "
                "converge DESDE ABAJO (T=30 {tmin} -> {tmax}; no oracle-relabeled); (ii) la FORMA es necesaria: la transpuesta "
                "INCORRECTA FALLA (composed_noT {noT}, +{wfg}), el 1-hop FALLA en multihop ({mh1} vs {mhc}), el LOCAL FALLA ({lh}). "
                "Baseline JUSTO: NET sobre control puro (ctrl_only {cto}) = +{rnet} (el +{gap} sobre el local sobre-vende: el local "
                "se auto-sabotea < ctrl_only). Robusto a estructura/seeds/a/D. Colinealidad NO confunde ŵ (corr_w={cw}). Caveats: "
                "gap máximo en el extremo adversarial (driver direct-rel=0); válido con radio espectral<1 (DAG lo garantiza).").format(
                    n=n_seeds, tmin=_f(tmin), tmax=_f(tmax), noT=_f(noT), wfg=_f(wfg), mh1=_f(mh1), mhc=_f(mhc), lh=_f(lh),
                    cto=_f(cto), rnet=_f(rnet), gap=_f(gap), cw=_f(cw))
    S_EXP121 = Source(tier=5, ref="cognia_x/experiments/exp121_coupled_discovery", obtained=True, claim=claim121)
    for src in (S_PRINCIPLE, S_C133, S_C134, S_EXP121):
        ledger.add_source(src)
    notes.append("4 fuentes (S_PRINCIPLE tier2 R-VALOR acoplado descubrible de un stream; S_C133 tier5 reach con w dada; S_C134 tier5 relevancia descubierta en sustrato independiente; S_EXP121 tier5 dato propio).")

    ev_for = [S_EXP121.ref, S_PRINCIPLE.ref]
    ev_against = [S_EXP121.ref]
    advtext = ("{V} (con CARACTERIZACIÓN HONESTA tras verificación adversarial de 3 agentes -leakage-free verificado-; unifica "
               "128+133+134; 7mo ciclo): ¿descubre el agente la controlabilidad (b̂), el ACOPLE (Â por system-ID) y la relevancia "
               "(ŵ por credit-assignment) de UN solo stream, y los COMPONE en la REACH-relevancia |b̂·(I-Â)^{{-T}}ŵ| que 133 mostró "
               "necesaria? RESULTADO: SÍ, pero lo LOAD-BEARING son los GAPS y la NECESIDAD DE LA FORMA, NO el nivel 1.000 (que es el "
               "beneficio saturado del top-K; la forma composed COINCIDE con el oracle por construcción). Se prueba (i) la "
               "ESTIMACIÓN DE UN STREAM BASTA y (ii) la FORMA es NECESARIA. (i) composed converge GENUINAMENTE DESDE ABAJO (T=30 "
               "{tmin} sub-identificado -> {tmax} a T>=300; corr_m≈0.69->0.99; NO oracle-relabeled, cierra el caveat de 133). (ii) "
               "FORMA necesaria por TRES falsadores: la transpuesta INCORRECTA |b̂·(I-Â)^{{-1}}ŵ| (reach hacia adelante, no el "
               "adjoint) FALLA (composed_noT {noT}, +{wfg}); el reach de 1-salto FALLA en MULTIHOP ({mh1} vs {mhc}; el reach de "
               "profundidad>=diámetro es necesario, (I-Â)^{{-1}} lo implementa AGNÓSTICO al diámetro); y el LOCAL (b̂·ŵ, el keystone "
               "de 134) FALLA ({lh}). BASELINE JUSTO (corrección de la verificación): el LOCAL es un foil DÉBIL -se auto-sabotea, "
               "cae por DEBAJO de control puro porque b̂·ŵ anula al driver con ŵ_driver≈0-; la contribución NETA del reach es sobre "
               "CONTROL PURO (ctrl_only=|b̂|={cto}): reach_net=+{rnet} (el +{gap} sobre el local SOBRE-VENDE). El shuffle de ŵ "
               "colapsa composed a ctrl_only (la propagación de relevancia es LOAD-BEARING, no espuria por |b̂|). HALLAZGO sobre la "
               "frontera de 134: la COLINEALIDAD del credit-assignment NO confunde ŵ (corr_w={cw}) -- OLS de G sobre el estado "
               "COMPLETO recupera la relevancia DIRECTA limpiamente (el target absorbe el crédito); el fallo del local NO es por ŵ "
               "confundido sino porque la relevancia DIRECTA ≠ relevancia-de-decisión bajo acople. EVIDENCIA: el principio (tier2); "
               "une 133 (tier5) con 134 (tier5). EVIDENCIA EN CONTRA / caveats HONESTOS (verificación de 3 agentes, todos "
               "core_survives): (a) el GAP sobre el local es máximo en el EXTREMO ADVERSARIAL (driver direct-rel=0); con relevancia "
               "directa moderada del driver el local se recupera y el gap->0 -- el fallo del local es CONDICIONAL (umbral = direct-"
               "rel del competidor), no general. (b) el costo D² del system-ID es para la FIDELIDAD del reach completo (corr_m); la "
               "DECISIÓN recupera barato (T_recover sub-cuadrático en D, composed bate al local a D∈{{8,16,24}}). (c) válido mientras "
               "el sustrato sea dinámicamente ESTABLE (radio espectral<1; el DAG lo garantiza, radio=a=0.6; acople con CICLOS cerca "
               "de radio 1 degrada y la ventaja se anula -- FRONTERA fuera del dominio). (d) numpy, eval con sensibilidad de estado-"
               "estacionario VERDADERA. => el R-VALOR de un sustrato ACOPLADO es endógeno de una experiencia (estimación de un "
               "stream basta + la forma reach es necesaria); cierra la frontera 'relevancia bajo sustrato acoplado' de 134 y el "
               "arco control/acción 127-136.").format(
                   V=status.upper(), tmin=_f(tmin), tmax=_f(tmax), noT=_f(noT), wfg=_f(wfg), mh1=_f(mh1), mhc=_f(mhc),
                   lh=_f(lh), cto=_f(cto), rnet=_f(rnet), gap=_f(gap), cw=_f(cw))

    hyp = Hypothesis(
        id="H-V4-10k",
        statement=("El agente DESCUBRE el R-VALOR de un sustrato ACOPLADO de UN solo stream de experiencia-acción -- la "
                   "controlabilidad (b̂), el ACOPLE (Â por system-ID) y la relevancia DIRECTA (ŵ por credit-assignment) todos "
                   "estimados-, y los COMPONE en la REACH-relevancia |b̂·(I-Â)^{-T}ŵ| que 133 mostró necesaria. El keystone LOCAL "
                   "(b̂·ŵ) falla bajo acople (relevancia directa ≠ relevancia-de-decisión); el reach COMPLETO es necesario (1-hop "
                   "falla en multi-hop). La colinealidad del credit-assignment NO confunde ŵ; el costo de datos del reach está en "
                   "estimar el acople. Unifica 128+133+134 y cierra la frontera 'relevancia bajo sustrato acoplado' de 134."),
        prediction=("APOYADA si composed (todo descubierto) recupera la decisión oracle bajo acople y bate al local (que falla), "
                    "robusto a estructura; REFUTADA si componer el reach con cantidades descubiertas no ayuda; MIXTA si la "
                    "colinealidad confunde ŵ y el local no falla, o composed se rompe a κ extremo. (Pre-registrada: numpy, barrido "
                    "κ/T/σ_g/estructura, reach completo vs 1-hop, 200 seeds; métrica = la DECISIÓN top-K por sensibilidad reach.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp121_coupled_discovery")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-10k")
        notes.append("H-V4-10k marcada '{}' con DoD completo: el agente descubre el R-VALOR acoplado (b̂+Â+ŵ) de un stream y lo compone en la reach-relevancia; el local falla, el reach completo es necesario, la colinealidad no confunde ŵ.".format(status))

    analogy = AnalogyRecord(
        problem=("Querés saber sobre qué cosa CONVIENE EMPUJAR para mover un PUNTAJE, en un mundo donde empujar una cosa MUEVE a "
                 "otras (las cosas están enganchadas) y nadie te dice ni qué controlás, ni cómo están enganchadas, ni qué importa. "
                 "¿Podés averiguar las TRES cosas con la misma experiencia de jugar, y combinarlas para elegir bien?"),
        everyday=("Sí, las tres salen de la misma experiencia. Qué podés MOVER lo aprendés empujando (si empujás esto, ¿qué se "
                  "mueve?). Cómo están ENGANCHADAS lo aprendés mirando cómo lo que empujaste arrastra a lo demás. Qué IMPORTA lo "
                  "aprendés mirando cómo cambia el puntaje. Y para elegir bien tenés que COMBINAR: la cosa que más conviene empujar "
                  "NO es la que directamente importa, sino la que podés mover Y que -siguiendo los enganches- termina moviendo lo "
                  "que importa. Empujar una palanca aburrida que está enganchada a la cosa importante es mejor que empujar la cosa "
                  "importante si esa no se deja empujar. La trampa: mirar sólo 'qué importa directamente' (la palanca aburrida "
                  "parece inútil) -- hay que seguir los enganches hasta el final (no alcanza con un solo salto)."),
        solutions=["el R-VALOR de un mundo ENGANCHADO (acoplado) es descubrible de un stream: qué controlás (b̂), cómo engancha (Â), qué importa (ŵ)",
                   "el valor-de-decisión es la REACH-relevancia: |controlabilidad × relevancia-retro-propagada-por-los-enganches|, todo estimado",
                   "elegir por la relevancia DIRECTA (el keystone local) falla: no elige la palanca aburrida que mueve lo importante",
                   "hay que seguir los enganches hasta el FINAL (reach completo); un solo salto no basta en cadenas largas; estimar los enganches es el costo de datos"],
        principles=["el R-VALOR de un sustrato ACOPLADO es endógeno de un stream: controlabilidad + acople + relevancia directa, compuestos en la reach-relevancia",
                    "la relevancia DIRECTA (descubierta limpiamente aun bajo colinealidad) ≠ relevancia-de-decisión bajo acople: hay que retro-propagarla por el acople estimado",
                    "el reach COMPLETO es necesario (1-hop falla en multi-hop); el costo de datos del reach está en estimar el acople (D×D), no la relevancia",
                    "META: unifica 128 (descubrir el acople actuando) + 133 (reach-por-la-red) + 134 (descubrir la relevancia); cierra el arco control/acción 127-136"],
        adaptation=("El lab cierra la frontera explícita de 134 ('relevancia bajo sustrato acoplado, colinealidad del credit-"
                    "assignment') e UNIFICA el arco control/acción (127-136). 128 mostró que la controlabilidad se descubre "
                    "actuando; 133 que bajo acople hace falta el reach (con w DADA); 134 que la relevancia se descubre por credit-"
                    "assignment (en sustrato INDEPENDIENTE). 137 junta todo: el agente descubre b̂, Â y ŵ de UN stream y los compone "
                    "en la reach-relevancia |b̂·(I-Â)^{-T}ŵ|; el local (relevancia directa) falla, el reach completo es necesario, y "
                    "-hallazgo sobre la frontera de 134- la COLINEALIDAD del credit-assignment NO confunde ŵ (OLS sobre el estado "
                    "completo es insesgado: el target absorbe el crédito), así que el fallo del local NO es por ŵ confundido sino "
                    "porque la relevancia directa ≠ relevancia-de-decisión bajo acople; el costo de datos del reach está en estimar "
                    "el acople. CONCLUSIÓN del arco control/acción: el R-VALOR (=ctrl×rel, ahora reach-relevancia bajo acople) es "
                    "TOTALMENTE endógeno de una experiencia de acción, incluso cuando el sustrato engancha los modos. POLÍTICA: "
                    "estimar el acople y retro-propagar la relevancia descubierta; no usar la relevancia directa bajo acople. "
                    "Próximo: acople con CICLOS / autovalores cerca de 1 (donde (I-Â)^{-1} explota); el lazo de acción-consecuencia "
                    "REAL; active inference formal; SCALE."),
        measurement=("exp121 ({n} seeds): κ=0 composed {c0}=local {l0}; κ=0.9 composed {ch} (corr_m {cm}) vs local {lh} (+{gap}); "
                     "reach completo necesario (multihop composed {mhc} vs 1hop {mh1}); colinealidad no confunde ŵ (corr_w {cw}); "
                     "costo de datos en Â (T=30 composed {tmin} -> {tmax}).").format(
                         n=n_seeds, c0=_f(c0), l0=_f(l0), ch=_f(ch), cm=_f(cm), lh=_f(lh), gap=_f(gap), mhc=_f(mhc),
                         mh1=_f(mh1), cw=_f(cw), tmin=_f(tmin), tmax=_f(tmax)),
        iterations=1)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (qué mover + cómo engancha + qué importa, todo de jugar; conviene empujar la palanca aburrida enganchada a lo importante, siguiendo los enganches hasta el final).")

    kl = ("REAL (exp121): el R-VALOR de un sustrato ACOPLADO es descubrible de UN stream (b̂+Â+ŵ) y se compone en la reach-relevancia "
          "|b̂·(I-Â)^{{-T}}ŵ|. κ=0.9: composed {ch} (corr_m {cm}) recupera el oracle, el LOCAL FALLA {lh}; reach completo necesario "
          "(multihop 1hop {mh1} vs composed {mhc}); colinealidad no confunde ŵ (corr_w {cw}); costo de datos en Â (T=30 {tmin} -> "
          "{tmax}). TECHO: numpy; acople DAG (estable, radio espectral a=0.6); composed tiene la FORMA del oracle (el contenido es "
          "el fallo del local + convergencia desde abajo); eval con sensibilidad estado-estacionario verdadera. Frontera: acople "
          "con CICLOS / autovalores ~1 ((I-Â)^{{-1}} explota), lazo real, active inference, SCALE.").format(
              ch=_f(ch), cm=_f(cm), lh=_f(lh), mh1=_f(mh1), mhc=_f(mhc), cw=_f(cw), tmin=_f(tmin), tmax=_f(tmax))
    ceilings.add(CeilingRecord(
        subsystem="Descubrimiento del R-VALOR de un sustrato ACOPLADO de UN stream — el agente estima la controlabilidad (b̂), el ACOPLE (Â por system-ID) y la relevancia directa (ŵ por credit-assignment) y los COMPONE en la REACH-relevancia |b̂·(I-Â)^{-T}ŵ| que 133 mostró necesaria; el keystone LOCAL (b̂·ŵ) falla bajo acople, el reach COMPLETO es necesario (1-hop falla en multi-hop), la colinealidad del credit-assignment NO confunde ŵ. Cierra la frontera 'relevancia bajo sustrato acoplado' de 134 y unifica el arco control/acción 127-136",
        known_limit=kl,
        blockers=[{"text": "composed tiene la FORMA del oracle (|b̂·(I-Â)^{-T}ŵ| vs |b·(I-A)^{-T}w|) con cantidades estimadas -- el contenido SUSTANTIVO NO es 'reach=oracle' (sería tautológico) sino (i) la estimación de UN stream basta (composed converge DESDE ABAJO: T=30 composed=0.76, corr_m≈0.69, NO oracle-relabeled) y (ii) la FORMA es NECESARIA: la transpuesta INCORRECTA |b̂·(I-Â)^{-1}ŵ| FALLA (composed_noT≈0.49), el 1-hop falla en multi-hop, el local falla. Lo load-bearing son los GAPS, no el nivel 1.000 (beneficio saturado del top-K). Cierra el caveat de 133", "kind": "diseno"},
                  {"text": "BASELINE: el LOCAL (b̂·ŵ) es un foil DÉBIL -se auto-sabotea, cae por DEBAJO de control puro (ctrl_only=|b̂|≈0.51) porque b̂·ŵ anula al driver con ŵ_driver≈0-; la contribución NETA del reach es sobre CONTROL PURO (reach_net≈+0.49), no el +0.59 sobre el local. Y el gap es MÁXIMO en el EXTREMO ADVERSARIAL (driver direct-rel=0): con relevancia directa moderada del driver el local se RECUPERA (umbral = direct-rel del competidor) -- el fallo del local es CONDICIONAL, no general. El shuffle de ŵ colapsa composed a ctrl_only (la relevancia es load-bearing, no espuria)", "kind": "diseno"},
                  {"text": "numpy; el acople es DAG (estable, radio espectral = a = 0.6 para todo κ); válido mientras el sustrato sea dinámicamente ESTABLE (radio<1) -- un acople con CICLOS cerca de radio 1 (donde (I-Â)^{-1} se amplifica/explota) degrada y la ventaja se anula: FRONTERA fuera del dominio. El costo D² del system-ID es para la FIDELIDAD del reach completo (corr_m); la DECISIÓN recupera barato (T_recover sub-cuadrático en D; composed bate al local a D∈{8,16,24}). 'reach completo' = profundidad>=diámetro del camino (un k-hop con k=diámetro empata; (I-Â)^{-1} lo implementa agnóstico al diámetro). eval con sensibilidad estado-estacionario VERDADERA", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP121.ref, S_C133.ref, S_C134.ref]))
    notes.append("1 techo 'real': el R-VALOR acoplado es descubrible de un stream (b̂+Â+ŵ -> reach-relevancia); el local falla, el reach completo es necesario, la colinealidad no confunde ŵ; costo de datos en el acople. Acople con ciclos = frontera.")

    dstmt = ("North-Star R-VALOR (cierra la frontera 'relevancia bajo sustrato acoplado' de 134 y unifica el arco control/acción "
             "127-136; caracterización HONESTA post-verificación): el R-VALOR de un sustrato ACOPLADO es endógeno de una experiencia "
             "de acción. El agente descubre b̂ (ctrl), Â (acople, system-ID) y ŵ (relevancia, credit-assignment) de UN stream y los "
             "compone en la REACH-relevancia |b̂·(I-Â)^{{-T}}ŵ|. Lo probado: (i) la ESTIMACIÓN DE UN STREAM BASTA (composed converge "
             "DESDE ABAJO, T=30 {tmin} -> {tmax}; no oracle-relabeled) y (ii) la FORMA es NECESARIA (la transpuesta INCORRECTA "
             "FALLA composed_noT {noT}; el 1-hop FALLA en multihop {mh1} vs {mhc}; el LOCAL FALLA {lh}). El nivel 1.000 es el "
             "beneficio saturado del top-K (forma=oracle por construcción); lo load-bearing son los GAPS. BASELINE JUSTO: la "
             "contribución NETA del reach sobre control puro (ctrl_only {cto}) es +{rnet} (el +{gap} sobre el local sobre-vende: el "
             "local se auto-sabotea < control puro). La COLINEALIDAD NO confunde ŵ (corr_w {cw}): el fallo del local es porque la "
             "relevancia DIRECTA ≠ relevancia-de-decisión bajo acople. Decisión: estimar el acople y retro-propagar la relevancia "
             "descubierta (no usar la relevancia directa bajo acople). META-DECISIÓN: 7mo ciclo con verificación adversarial. "
             "Caveats: gap máximo en el extremo adversarial (driver direct-rel=0; condicional); válido con radio espectral<1 (DAG). "
             "Próximo: acople con ciclos, lazo real, active inference, SCALE.").format(
                 tmin=_f(tmin), tmax=_f(tmax), noT=_f(noT), mh1=_f(mh1), mhc=_f(mhc), lh=_f(lh), cto=_f(cto), rnet=_f(rnet),
                 gap=_f(gap), cw=_f(cw))
    drat = ("exp121 (tier5, propio, {n} seeds, numpy, post-verificación de 3 agentes): el agente descubre b̂+Â+ŵ de un stream y "
            "compone la reach-relevancia; load-bearing = la estimación de un stream basta (composed converge desde abajo) + la "
            "forma es necesaria (transpuesta incorrecta {noT} falla, 1-hop falla en multihop, local falla); reach_net sobre control "
            "puro +{rnet}; colinealidad no confunde ŵ. Convergente con el principio (tier2); une 133 (tier5) con 134 (tier5). "
            "APOYADA: el R-VALOR acoplado es endógeno de una experiencia (estimación de un stream + forma necesaria).").format(
                n=n_seeds, noT=_f(noT), rnet=_f(rnet))
    dec = Decision(id="D-V4-99", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP121), _to_plain(S_C133), _to_plain(S_C134)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-99 ACEPTADA por el ledger (tier5 exp121 + tier5 exp117 + tier5 exp118).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-99:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle137_coupled_discovery',
                                description='CYCLE 137 (RESET v4, H-V4-10k APOYADA: el agente descubre el R-VALOR de un sustrato ACOPLADO -b̂+Â+ŵ- de un stream y lo compone en la reach-relevancia; unifica 128+133+134; 7mo ciclo con verificación adversarial).')
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
    print("RESUMEN — CYCLE 137 (RESET v4): el agente descubre el R-VALOR de un sustrato ACOPLADO (b̂+Â+ŵ) de un stream y lo compone en la reach-relevancia — H-V4-10k APOYADA")
    print("=" * 78)
    print("veredicto H-V4-10k:", status.upper() if status else "?")
    print("  el R-VALOR acoplado es endógeno de una experiencia: ctrl (b̂) + acople (Â, system-ID) + relevancia (ŵ, credit-assignment) -> reach-relevancia |b̂·(I-Â)^-T ŵ|. El LOCAL falla bajo acople, el reach COMPLETO es necesario, la colinealidad NO confunde ŵ. Unifica 128+133+134; cierra la frontera de 134.")
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
