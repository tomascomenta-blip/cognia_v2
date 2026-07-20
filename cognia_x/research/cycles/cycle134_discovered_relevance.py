r"""
cycle134_discovered_relevance.py — CICLO 134 (RESET v4, rama control/acción, CIERRA el supuesto 'relevancia DADA' del arco
127-133; APOYADA con caracterización de DOS EJES tras VERIFICACIÓN ADVERSARIAL): H-V4-10h por las compuertas del engine. ¿Puede
el agente DESCUBRIR el R-VALOR COMPLETO -- AMBOS factores del keystone (129: valor = controlabilidad × relevancia) -- de UN SOLO
stream de experiencia-acción, sin que se le den ni la controlabilidad ni la relevancia?

Todo el arco generalizó la CONTROLABILIDAD (129->130->132->133) pero la RELEVANCIA siempre fue DADA. 128 mostró que la
controlabilidad se DESCUBRE actuando (mapa acción->estado). Este ciclo cierra el otro factor: la RELEVANCIA se descubre del mapa
estado->META (credit assignment lineal, G~x -> ŵ). RESULTADO VERIFICADO: el NÚCLEO RESISTE -- valor_ambos (ŵ·b̂², ambos estimados
de la misma experiencia) bate a cada factor solo, converge al oracle (T~30), es genuinamente peor que oracle a T bajo y = azar a
σ_u=0 (NO oracle relabeled), y la relevancia es GENUINAMENTE descubierta (sobrevive a G binario/ruidoso/sparse).

EJEMPLO DEL MÉTODO (4to ciclo consecutivo, con 131/132/133): una 1ra versión titulaba una ASIMETRÍA ("controlabilidad action-
gated, relevancia pasivamente barata"). Una VERIFICACIÓN ADVERSARIAL (4 agentes) la halló INVERTIDA/contingente y la reencuadró en
DOS EJES de fallo COMPLEMENTARIOS: EJE 1 (action-gating, lógico) la controlabilidad necesita Var(u)>0 (sin actuar no se identifica;
recuperación GRADUAL) pero es BARATA al actuar; EJE 2 (data/signal-gating) la RELEVANCIA es el CUELLO del COSTO DE DATOS (a ruido
de meta σ_g alto cuesta ~100× más que la ctrl; abl_ctrl=1.0 siempre, abl_rel se desploma) y requiere meta LINEAL-descomponible
(bajo meta PAR el credit-assignment lineal recupera 0.00). Resistió: sin leakage, arms pareados, NO el confound de 133.

DERIVA de exp118_discovered_relevance/results/results.json.

Correr (DESPUÉS de exp118):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp118_discovered_relevance.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle134_discovered_relevance
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle134_discovered_relevance')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp118_discovered_relevance', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="un agente puede DESCUBRIR el R-VALOR COMPLETO (ambos factores del keystone valor=ctrl×rel) de UN solo stream de experiencia-acción -- la controlabilidad del mapa acción->estado (R-INTERVENCIÓN, 128) y la relevancia del mapa estado->meta (credit assignment); los dos factores tienen ejes de fallo COMPLEMENTARIOS: la controlabilidad es action-gated (necesita Var(u)>0) pero barata, la relevancia es el cuello del COSTO DE DATOS (escala con el ruido de la meta) y requiere una meta lineal-descomponible en el estado observado. R-VALOR endógeno de la experiencia", obtained=False,
                     claim=("El R-VALOR completo (valor=controlabilidad×relevancia) es DESCUBRIBLE de un solo stream de "
                            "experiencia-acción: la controlabilidad del mapa acción->estado (128) y la relevancia del mapa "
                            "estado->meta (credit assignment). Los dos factores tienen ejes de fallo COMPLEMENTARIOS: la "
                            "controlabilidad es ACTION-gated (Var(u)>0 es necesidad lógica de identificación) pero barata al "
                            "actuar; la relevancia es el CUELLO del COSTO DE DATOS (escala con el ruido de la meta) y requiere "
                            "una meta ~lineal-descomponible en el estado observado (bajo no-linealidad par el credit-assignment "
                            "lineal falla). (Principio.)"))
S_C128 = Source(tier=5, ref="cognia_x/experiments/exp112_control_discovery", obtained=True,
                claim=("CYCLE 128: la CONTROLABILIDAD se DESCUBRE actuando (estimar |b̂| del mapa acción->estado; R-INTERVENCIÓN "
                       "medida). H-V4-10h cierra el OTRO factor: la RELEVANCIA se descubre del mapa estado->meta (credit "
                       "assignment), y el producto con AMBOS estimados de la misma experiencia gobierna la asignación."))
S_C129 = Source(tier=5, ref="cognia_x/experiments/exp113_value_factorization", obtained=True,
                claim=("CYCLE 129 (keystone): el control reconstruye R-VALOR = controlabilidad × relevancia, con la RELEVANCIA "
                       "DADA. H-V4-10h cierra el supuesto 'relevancia dada' del arco 127-133: ambos factores caen de una "
                       "experiencia de acción; R-VALOR totalmente endógeno."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp118 primero): " + results_path)

    bc = sm['beats_ctrl']; br = sm['beats_rel']; bp = sm['beats_pred']; cv = sm['converges']; gr = sm['grows']
    rb = sm['random_baseline']; cbn = sm['corr_b_noaction']; cba = sm['corr_b_action']; bna = sm['both_noaction']
    ach = sm['abl_ctrl_hi_sg']; arh = sm['abl_rel_hi_sg']; rmc = sm['rel_minus_ctrl_cost']; cwh = sm['corr_w_hi_sg']
    cw0 = sm['corr_w_srel0']; cwd = sm['corr_w_srel_default']; cwe = sm['corr_w_even']; bev = sm['both_even']
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim118 = ("exp118 (propio, {n} seeds, numpy, post-verificación adversarial de 4 agentes): el agente DESCUBRE el R-VALOR "
                "COMPLETO (ambos factores) de UN stream de experiencia. valor_ambos bate a cada factor (vs ctrl +{bc}, vs rel "
                "+{br}, vs pred +{bp}), converge al oracle ({cv}, sube +{gr}; = azar {rb} a σ_u=0, NO oracle relabeled). DOS EJES: "
                "EJE1 ctrl action-gated (corr(b̂,b) {cbn}@σ_u=0 -> {cba}@σ_u-alto, recuperación gradual, barata); EJE2 rel = cuello "
                "del COSTO DE DATOS (a σ_g alto abl_ctrl {ach} vs abl_rel {arh}, rel-ctrl={rmc}; corr(ŵ,w)={cwh}) + requiere meta "
                "lineal (meta par: corr(ŵ,w)={cwe}, valor_ambos azar {bev}). Caveat: sin excitación pasiva colapso simétrico "
                "(corr(ŵ,w) {cwd}->{cw0}).").format(
                    n=n_seeds, bc=_f(bc), br=_f(br), bp=_f(bp), cv=_f(cv), gr=_f(gr), rb=_f(rb), cbn=_f(cbn), cba=_f(cba),
                    ach=_f(ach), arh=_f(arh), rmc=_f(rmc), cwh=_f(cwh), cwe=_f(cwe), bev=_f(bev), cwd=_f(cwd), cw0=_f(cw0))
    S_EXP118 = Source(tier=5, ref="cognia_x/experiments/exp118_discovered_relevance", obtained=True, claim=claim118)
    for src in (S_PRINCIPLE, S_C128, S_C129, S_EXP118):
        ledger.add_source(src)
    notes.append("4 fuentes (S_PRINCIPLE tier2 R-VALOR descubrible de una experiencia con ejes complementarios; S_C128 tier5 la controlabilidad descubierta actuando; S_C129 tier5 el keystone con relevancia dada; S_EXP118 tier5 dato propio post-verificación de 4 agentes).")

    ev_for = [S_EXP118.ref, S_PRINCIPLE.ref]
    ev_against = [S_EXP118.ref]
    advtext = ("{V} (el agente descubre el R-VALOR COMPLETO de una experiencia, con DOS EJES de fallo honestos; 4to EJEMPLO "
               "consecutivo de verificación adversarial corrigiendo un overclaim): ¿descubre el agente AMBOS factores del "
               "keystone (129) -- controlabilidad del mapa acción->estado (128) y relevancia del mapa estado->meta (credit "
               "assignment) -- de UN solo stream, sin que se le den? NÚCLEO VERIFICADO: valor_ambos (ŵ·b̂², ambos estimados de la "
               "misma experiencia) bate a cada factor solo (vs ctrl +{bc}, vs rel +{br}, vs predicción +{bp}), converge al oracle "
               "({cv}, sube +{gr}), es genuinamente peor que oracle a T bajo y = azar {rb} a σ_u=0 (NO oracle relabeled, cierra el "
               "confound de 133), y la relevancia es GENUINAMENTE descubierta (sobrevive a G binario/ruidoso/sparse: un escalar "
               "de meta NO es relevancia por-modo dada). CARACTERIZACIÓN HONESTA en DOS EJES de fallo COMPLEMENTARIOS (la 1ra "
               "versión titulaba 'controlabilidad action-gated, relevancia pasivamente barata' -- la verificación adversarial la "
               "halló INVERTIDA): EJE 1 (action-gating, lógico) la CONTROLABILIDAD ∂x'/∂u necesita Var(u)>0 -- a σ_u=0 no se "
               "identifica (corr(b̂,b)={cbn}, valor_ambos cae a azar {bna}), recuperación GRADUAL (dosis-respuesta), pero a "
               "exploración positiva es BARATA (corr(b̂,b)={cba} a σ_u alto, T~30 para todo σ_g). EJE 2 (data/signal-gating) la "
               "RELEVANCIA es el CUELLO del COSTO DE DATOS -- a σ_g alto abl_ctrl(estima ctrl)={ach} (la ctrl nunca es el cuello) "
               "vs abl_rel(estima rel)={arh} (rel-ctrl={rmc}; corr(ŵ,w)={cwh}); y REQUIERE una meta ~lineal-descomponible -- bajo "
               "meta PAR (G=Σw·x²) el credit-assignment lineal recupera corr(ŵ,w)={cwe} y valor_ambos cae a azar ({bev}). CAVEAT "
               "estimación≠decisión: la relevancia es estimable pasivamente sólo si el estado relevante varía pasivamente (s_rel: "
               "corr(ŵ,w) {cwd}->{cw0}, colapso SIMÉTRICO con la ctrl a σ_u=0); la decisión MULTIPLICATIVA no cobra la relevancia "
               "conocida sin actuar (0·ŵ). => cierra el supuesto 'relevancia DADA' del arco 127-133: la controlabilidad se paga "
               "con ACCIÓN (R-INTERVENCIÓN, barata), la relevancia con DATOS+SEÑAL (cuello del costo de datos; meta lineal). "
               "EVIDENCIA: el principio (tier2) lo predice; une 128 (tier5) con el keystone 129 (tier5). EVIDENCIA EN CONTRA / "
               "caveats: numpy, sustrato INDEPENDIENTE y meta LINEAL en el default (los caveats EJE2 muestran el quiebre); el "
               "eval usa control ridge oracle (aísla la asignación).").format(
                   V=status.upper(), bc=_f(bc), br=_f(br), bp=_f(bp), cv=_f(cv), gr=_f(gr), rb=_f(rb), cbn=_f(cbn),
                   bna=_f(bna), cba=_f(cba), ach=_f(ach), arh=_f(arh), rmc=_f(rmc), cwh=_f(cwh), cwe=_f(cwe), bev=_f(bev),
                   cwd=_f(cwd), cw0=_f(cw0))

    hyp = Hypothesis(
        id="H-V4-10h",
        statement=("El agente DESCUBRE el R-VALOR COMPLETO (ambos factores del keystone valor=ctrl×rel) de UN solo stream de "
                   "experiencia-acción -- controlabilidad del mapa acción->estado (128) y relevancia del mapa estado->meta "
                   "(credit assignment); valor_ambos bate a cada factor solo y converge al oracle (la relevancia es genuinamente "
                   "descubierta, no dada). Los dos factores tienen ejes de fallo COMPLEMENTARIOS: la controlabilidad es ACTION-"
                   "gated (Var(u)>0, recuperación gradual) pero barata; la relevancia es el CUELLO del COSTO DE DATOS (escala con "
                   "el ruido de la meta) y requiere una meta lineal-descomponible. Cierra el supuesto 'relevancia dada' del arco "
                   "127-133."),
        prediction=("APOYADA si valor_ambos bate a cada factor solo y converge al oracle al crecer la experiencia (con la "
                    "caracterización honesta de dos ejes); REFUTADA si descubrir la relevancia no ayuda; MIXTA si el núcleo se "
                    "sostiene parcialmente. (Pre-registrada en su 2da versión tras verificación adversarial de 4 agentes que "
                    "halló invertida la asimetría inicial: numpy, barridos T/σ_g/σ_u-fino/s_rel/forma-de-meta, 200 seeds.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp118_discovered_relevance")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-10h")
        notes.append("H-V4-10h marcada '{}' con DoD completo (el agente descubre ambos factores de una experiencia; asimetría inicial INVERTIDA corregida por verificación adversarial a DOS EJES complementarios).".format(status))

    analogy = AnalogyRecord(
        problem=("Si querés saber qué cosas IMPORTAN y cuáles podés MOVER, y nadie te lo dice, ¿podés averiguar las DOS cosas "
                 "con la misma experiencia de jugar/probar? ¿Y cuál de las dos es más difícil de averiguar?"),
        everyday=("Sí, las dos salen de la misma experiencia, pero por caminos distintos y con costos distintos. Qué podés MOVER "
                  "lo aprendés EMPUJANDO y mirando qué se mueve (si no empujás nunca, no hay forma de saberlo -- pero apenas "
                  "empujás un poco, se aprende rápido y barato). Qué IMPORTA lo aprendés mirando cómo cambia el PUNTAJE final "
                  "cuando cambian las cosas (no hace falta empujar: alcanza con que las cosas varíen). PERO eso es más caro en "
                  "datos: si el puntaje es muy ruidoso o depende de las cosas de forma rara (no proporcional), cuesta muchísimo "
                  "más -- o no se puede. Moraleja: para saber qué controlás tenés que ACTUAR (barato); para saber qué importa "
                  "necesitás MUCHA SEÑAL CLARA del puntaje."),
        solutions=["el R-VALOR completo (qué importa × qué controlás) es DESCUBRIBLE de un solo stream de experiencia de acción",
                   "la controlabilidad se descubre del mapa acción->estado (hay que ACTUAR; R-INTERVENCIÓN) pero es barata al actuar",
                   "la relevancia se descubre del mapa estado->meta (credit assignment); no hace falta actuar, pero es el cuello del COSTO DE DATOS (escala con el ruido de la meta) y requiere una meta lineal-descomponible",
                   "los dos factores tienen ejes de fallo COMPLEMENTARIOS: acción (ctrl) vs datos+señal (rel); el producto con ambos estimados gobierna la asignación y bate a cada factor solo"],
        principles=["el R-VALOR completo es descubrible de una experiencia de acción: ctrl del mapa acción->estado, rel del mapa estado->meta",
                    "la controlabilidad es ACTION-gated (necesita Var(u)>0) pero barata; la relevancia es el cuello del COSTO DE DATOS y requiere meta lineal-descomponible",
                    "los dos factores del keystone tienen ejes de fallo COMPLEMENTARIOS (acción vs datos/señal), no una asimetría simple",
                    "META: 4to ciclo consecutivo donde la verificación adversarial corrige un overclaim (asimetría invertida) antes del ledger -> institucionalizarla"],
        adaptation=("El lab cierra el supuesto 'relevancia DADA' que sostuvo todo el arco control/acción (127-133): hasta ahora la "
                    "controlabilidad se generalizaba ciclo a ciclo pero la relevancia se daba por conocida. H-V4-10h muestra que "
                    "el R-VALOR COMPLETO (ambos factores del keystone) es DESCUBRIBLE de UN solo stream de experiencia: la "
                    "controlabilidad del mapa acción->estado (128) y la relevancia del mapa estado->meta (credit assignment). El "
                    "producto con ambos estimados bate a cada factor solo y converge al oracle. CARACTERIZACIÓN HONESTA (corregida "
                    "por verificación adversarial): los dos factores tienen ejes de fallo COMPLEMENTARIOS -- la controlabilidad es "
                    "ACTION-gated (necesita Var(u)>0; sin actuar no se identifica, recuperación gradual) pero barata al actuar; la "
                    "relevancia es el CUELLO del COSTO DE DATOS (a ruido de meta alto cuesta ~100× más que la ctrl) y requiere una "
                    "meta lineal-descomponible en el estado observado (bajo meta par el credit-assignment lineal falla). META-"
                    "LECCIÓN: 4to ciclo seguido (con 131/132/133) en que la verificación adversarial corrige un overclaim (aquí, "
                    "una asimetría 'relevancia barata' INVERTIDA respecto del costo de datos) antes del ledger; institucionalizar "
                    "la compuerta. Próximo: relevancia bajo sustrato ACOPLADO (133) -- credit assignment con colinealidad; meta "
                    "no-lineal aprendible (base rica, R-PRIOR 89-92); el lazo real; active inference formal."),
        measurement=("exp118 ({n} seeds): valor_ambos bate a cada factor (+{bc}/+{br}/+{bp}) y converge al oracle ({cv}, azar "
                     "{rb}); EJE1 corr(b̂,b) {cbn}@σ_u=0->{cba}; EJE2 a σ_g alto abl_ctrl {ach} vs abl_rel {arh}; meta par corr(ŵ,w) "
                     "{cwe}; sin excitación pasiva corr(ŵ,w) {cwd}->{cw0}.").format(
                         n=n_seeds, bc=_f(bc), br=_f(br), bp=_f(bp), cv=_f(cv), rb=_f(rb), cbn=_f(cbn), cba=_f(cba),
                         ach=_f(ach), arh=_f(arh), cwe=_f(cwe), cwd=_f(cwd), cw0=_f(cw0)),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (qué controlás se aprende EMPUJANDO -barato-; qué importa se aprende del PUNTAJE -caro en datos, requiere señal clara-).")

    kl = ("REAL (exp118, post-verificación adversarial de 4 agentes): el R-VALOR COMPLETO (ambos factores del keystone) es "
          "DESCUBRIBLE de UN stream de experiencia -- valor_ambos bate a cada factor (+{bc}/+{br}/+{bp}), converge al oracle "
          "({cv}, = azar {rb} a σ_u=0). DOS EJES de fallo COMPLEMENTARIOS: EJE1 ctrl ACTION-gated (corr(b̂,b) {cbn}@σ_u=0->{cba}, "
          "gradual, barata); EJE2 rel = cuello del COSTO DE DATOS (a σ_g alto abl_rel {arh} vs abl_ctrl {ach}) + requiere meta "
          "lineal (par: corr(ŵ,w) {cwe}). TECHO: numpy, sustrato INDEPENDIENTE y meta LINEAL en el default; eval con control "
          "oracle (aísla la asignación). Frontera: relevancia bajo sustrato acoplado (133, colinealidad), meta no-lineal "
          "aprendible (R-PRIOR), lazo real, active inference.").format(
              bc=_f(bc), br=_f(br), bp=_f(bp), cv=_f(cv), rb=_f(rb), cbn=_f(cbn), cba=_f(cba), arh=_f(arh), ach=_f(ach),
              cwe=_f(cwe))
    ceilings.add(CeilingRecord(
        subsystem="Descubrimiento del R-VALOR COMPLETO de una experiencia — ambos factores del keystone (valor=ctrl×rel) son descubribles de UN stream de acción (ctrl del mapa acción->estado, 128; rel del mapa estado->meta, credit assignment); cierra el supuesto 'relevancia dada' del arco 127-133. DOS EJES de fallo COMPLEMENTARIOS: la controlabilidad es action-gated (Var(u)>0) pero barata; la relevancia es el cuello del COSTO DE DATOS y requiere meta lineal-descomponible (asimetría inicial 'relevancia barata' INVERTIDA, corregida por verificación adversarial)",
        known_limit=kl,
        blockers=[{"text": "numpy; el sustrato es de modos INDEPENDIENTES y la meta es LINEAL en el estado observado en el default; los caveats EJE2 muestran el quiebre (meta par G=Σw·x² rompe el credit-assignment lineal; relevancia bajo acople/colinealidad es frontera); el eval usa control ridge ORACLE (aísla la asignación, no mide un controlador imperfecto)", "kind": "diseno"},
                  {"text": "la relevancia es estimable pasivamente SÓLO si el estado relevante varía pasivamente (s_rel>0); con s_rel->0 colapsa SIMÉTRICO con la controlabilidad a σ_u=0. Y la decisión MULTIPLICATIVA no cobra la relevancia conocida sin actuar (b̂=0 -> 0·ŵ -> azar); la recuperación al actuar es dosis-respuesta GRADUAL, no escalón", "kind": "diseno"},
                  {"text": "META/honestidad: la 1ra versión titulaba una ASIMETRÍA ('controlabilidad action-gated, relevancia pasivamente barata'); una VERIFICACIÓN ADVERSARIAL (4 agentes) la halló INVERTIDA en el costo de datos (la RELEVANCIA es el cuello, no la ctrl) y contingente al sustrato (excitación pasiva s=0.3) -> reencuadrada en DOS EJES complementarios. 4to ciclo seguido (con 131/132/133) que exige institucionalizar la compuerta", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP118.ref, S_C128.ref, S_C129.ref]))
    notes.append("1 techo 'real': el R-VALOR completo es descubrible de una experiencia; dos ejes de fallo complementarios (ctrl action-gated/barata, rel data-cost/lineal); asimetría inicial INVERTIDA corregida por verificación adversarial.")

    dstmt = ("North-Star R-VALOR (cierra el supuesto 'relevancia DADA' del arco 127-133 + caracterización de DOS EJES): el "
             "R-VALOR COMPLETO (ambos factores del keystone valor=ctrl×rel) es DESCUBRIBLE de UN solo stream de experiencia-acción "
             "-- la controlabilidad del mapa acción->estado (128) y la relevancia del mapa estado->meta (credit assignment); "
             "valor_ambos bate a cada factor solo (+{bc}/+{br}) y converge al oracle ({cv}; = azar {rb} a σ_u=0, NO oracle "
             "relabeled), y la relevancia es GENUINAMENTE descubierta (sobrevive a G binario/ruidoso/sparse). DOS EJES de fallo "
             "COMPLEMENTARIOS: la CONTROLABILIDAD es ACTION-gated (necesita Var(u)>0; recuperación gradual) pero BARATA al actuar; "
             "la RELEVANCIA es el CUELLO del COSTO DE DATOS (a σ_g alto abl_rel {arh} vs abl_ctrl {ach}, ~100× más cara) y requiere "
             "una meta LINEAL-descomponible (meta par: corr(ŵ,w) {cwe}, valor_ambos azar {bev}). Decisión: el agente descubre su "
             "criterio de valor COMPLETO actuando+observando-la-meta; la controlabilidad se paga con ACCIÓN (R-INTERVENCIÓN), la "
             "relevancia con DATOS+SEÑAL. META-DECISIÓN: 4to ciclo seguido (con 131/132/133) donde la verificación adversarial "
             "corrige un overclaim (asimetría 'relevancia barata' INVERTIDA) -> institucionalizarla. Próximo: relevancia bajo "
             "acople (133), meta no-lineal aprendible (R-PRIOR), lazo real, active inference.").format(
                 bc=_f(bc), br=_f(br), cv=_f(cv), rb=_f(rb), arh=_f(arh), ach=_f(ach), cwe=_f(cwe), bev=_f(bev))
    drat = ("exp118 (tier5, propio, {n} seeds, numpy, post-verificación de 4 agentes): valor_ambos bate a cada factor (+{bc}/"
            "+{br}/+{bp}), converge al oracle ({cv}); EJE1 ctrl action-gated (corr(b̂,b) {cbn}@σ_u=0); EJE2 rel = cuello de costo de "
            "datos (a σ_g alto abl_rel {arh} < abl_ctrl {ach}) + meta lineal (par corr(ŵ,w) {cwe}). Convergente con el principio "
            "(tier2); une 128 (tier5) con el keystone 129 (tier5). APOYADA: el núcleo (descubrir ambos factores) resiste; la "
            "asimetría inicial fue corregida a dos ejes.").format(
                n=n_seeds, bc=_f(bc), br=_f(br), bp=_f(bp), cv=_f(cv), cbn=_f(cbn), arh=_f(arh), ach=_f(ach), cwe=_f(cwe))
    dec = Decision(id="D-V4-96", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP118), _to_plain(S_C128), _to_plain(S_C129)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-96 ACEPTADA por el ledger (tier5 exp118 + tier5 exp112 + tier5 exp113).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-96:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle134_discovered_relevance',
                                description='CYCLE 134 (RESET v4, H-V4-10h APOYADA: el agente descubre el R-VALOR COMPLETO -ambos factores- de una experiencia; dos ejes de fallo complementarios; asimetría inicial corregida por verificación adversarial de 4 agentes).')
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
    print("RESUMEN — CYCLE 134 (RESET v4): el agente DESCUBRE el R-VALOR COMPLETO (ambos factores) de una experiencia; dos ejes de fallo complementarios — H-V4-10h")
    print("=" * 78)
    print("veredicto H-V4-10h:", status.upper() if status else "?")
    print("  el R-VALOR completo (ctrl×rel) es descubrible de un stream de acción; la ctrl del mapa acción->estado (action-gated, barata), la rel del mapa estado->meta (cuello del costo de datos, requiere meta lineal). Asimetría inicial 'relevancia barata' INVERTIDA, corregida por verificación adversarial de 4 agentes (4to ciclo seguido).")
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
