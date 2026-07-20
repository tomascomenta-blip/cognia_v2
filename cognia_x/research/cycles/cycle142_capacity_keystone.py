r"""
cycle142_capacity_keystone.py — CICLO 142 (RESET v4, rama control/acción, EJE DE CAPACIDAD del keystone): H-V4-10n por las
compuertas del engine. ¿Cómo escala la ventaja del PRODUCTO R-VALOR (valor=ctrl×rel, keystone 129) sobre los factores de un solo
eje con la CAPACIDAD K del agente? (El CYCLE 139 reveló de pasada que K=1 era load-bearing.)

VEREDICTO: MIXTA (núcleo organizador real + novedad/especificidad acotada por verificación adversarial de 2 agentes; 12mo ciclo).

QUÉ SOBREVIVE (robusto en el régimen GRADUADO -- verificado en D/RHO/seeds/correlación-fina): el R-VALOR (producto) importa bajo
DOS escaseces que INTERACTÚAN -- CAPACIDAD (K bajo) y DISOCIACIÓN (ctrl≠rel). La ventaja del producto sobre el mejor factor-solo es
grande sólo cuando AMBAS escasean, decae por ambos ejes (AUC anti>indep>corr, monótona y suave en ρ_bw; K* relativo ≈0.7·D), y
EXPLICA el K=1-load-bearing de 139.

QUÉ NO SOBREVIVE (retractado/acotado por la verificación -- el experimento lo AUTO-DOCUMENTA):
  (1) 'decae con K / se desvanece a K=D' es PARCIALMENTE TRIVIAL: la (1−payoff) de la selección ALEATORIA también decae a ~0 en
      K=D (a K=D se eligen TODOS los modos -> payoff=1 por construcción). El contenido no-trivial es adv(K=1) y la pendiente interior.
  (2) RECOMBINACIÓN, no mecanismo nuevo: las curvas de ventaja anti/indep normalizadas por adv(K=1) son ~idénticas (forma universal
      de decaimiento); lo regime-específico es sólo adv(K=1) = el mis-ranking de un-factor de la DISOCIACIÓN (130). El aporte es la
      SÍNTESIS (escasez 123-126 × disociación 130 interactúan + explica 139), no un mecanismo nuevo.
  (3) VALIDITY-LIMIT: vale para (b,w) GRADUADOS (régimen canónico del keystone 130); con (b,w) BINARIOS el orden anti>indep INVIERTE.

DERIVA de exp126_capacity_keystone/results/results.json.

Correr (DESPUÉS de exp126):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp126_capacity_keystone.run --seeds 300
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle142_capacity_keystone
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle142_capacity_keystone')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp126_capacity_keystone', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="el R-VALOR (producto ctrl×rel, keystone 129) importa bajo DOS escaseces que INTERACTÚAN -- CAPACIDAD (K bajo) y DISOCIACIÓN (ctrl≠rel): la ventaja del producto sobre el mejor factor-solo es grande sólo cuando ambas escasean y decae por ambos ejes. PERO el decaimiento-en-K es parcialmente TRIVIAL (lo comparte la selección aleatoria: a K=D todo criterio captura todo), la forma de decaimiento es UNIVERSAL (lo regime-específico es adv(K=1) = el mis-ranking de un-factor de la disociación, 130), así que el aporte es una RECOMBINACIÓN de escasez (123-126) × disociación (130), no un mecanismo nuevo; y el orden anti>indep vale sólo para marginales GRADUADAS (con binarias invierte).", obtained=False,
                     claim=("El producto R-VALOR importa bajo capacidad×disociación conjuntas (decae por ambos ejes); es una "
                            "recombinación de escasez+disociación (forma de decaimiento universal, decaimiento parcialmente trivial), "
                            "válida para (b,w) graduados. (Principio organizador.)"))
S_C139 = Source(tier=5, ref="cognia_x/experiments/exp123_cyclic_substrate (CYCLE 139, K=1 load-bearing) + exp114 (CYCLE 130, disociación)", obtained=True,
                claim=("CYCLE 139 reveló que K=1 era load-bearing (el gap del keystone evaporaba a K≥2 en el sustrato cíclico). "
                       "CYCLE 130 mostró que la ventaja del producto escala con la DISOCIACIÓN ctrl-rel. H-V4-10n los UNIFICA: el "
                       "producto importa bajo capacidad×disociación; el K=1-load-bearing de 139 es el caso de capacidad mínima."))
S_VERIF = Source(tier=4, ref="verificación adversarial de 2 agentes (lentes tautología-novedad-trivialidad, robustez-sensibilidad; probes reales numpy)", obtained=True,
                 claim=("La verificación adversarial (12mo ciclo) CONFIRMÓ que el núcleo organizador es robusto en el régimen "
                        "GRADUADO (D/RHO/seeds/correlación-fina) PERO ACOTÓ: el decaimiento-en-K es parcialmente trivial (random "
                        "también decae a 0 en K=D), es una RECOMBINACIÓN (forma de decaimiento universal; lo regime-específico es "
                        "adv(K=1)=disociación de 130), K* es relativo (~0.7·D no absoluto), y el orden anti>indep INVIERTE bajo "
                        "marginal binaria (sólo vale para graduadas)."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp126 primero): " + results_path)

    auc = sm['auc_advantage']; kst = sm['kstar']; kstr = sm['kstar_rel']
    usm = sm['universal_shape_maxdiff']; rd = sm['rand_decay']; baa = sm['binary_auc_anti']; bai = sm['binary_auc_indep']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim126 = ("exp126 (propio, {n} seeds, numpy, post-verificación de 2 agentes): {V}. NÚCLEO (graduado): el producto R-VALOR "
                "importa bajo capacidad×disociación -- AUC ventaja anti={aa} > indep={ai} > corr={ac} (monótona/suave en ρ_bw); K* "
                "relativo ≈{kr}·D; explica el K=1-load-bearing de 139. RETRACTADO: decaimiento parcialmente trivial (random también "
                "decae, anti {rda}); RECOMBINACIÓN (forma universal max-diff {usm}; lo regime-específico es adv(K=1)=disociación 130); "
                "VALIDITY-LIMIT (binario invierte: AUC anti {baa} <= indep {bai}).").format(
                    n=data['args']['seeds'], V=status.upper(), aa=_f(auc['anti']), ai=_f(auc['indep']), ac=_f(auc['corr']),
                    kr=_f(kstr['anti']), rda=_f(rd['anti']), usm=_f(usm), baa=_f(baa), bai=_f(bai))
    S_EXP126 = Source(tier=5, ref="cognia_x/experiments/exp126_capacity_keystone", obtained=True, claim=claim126)
    for src in (S_PRINCIPLE, S_C139, S_VERIF, S_EXP126):
        ledger.add_source(src)
    notes.append("4 fuentes (S_PRINCIPLE tier2 el producto importa bajo capacidad×disociación, recombinación; S_C139 tier5 K=1-load-bearing 139 + disociación 130; S_VERIF tier4 verificación adversarial; S_EXP126 tier5 dato propio {}).".format(status.upper()))

    ev_for = [S_EXP126.ref, S_PRINCIPLE.ref]
    ev_against = [S_EXP126.ref, S_VERIF.ref]
    advtext = ("{V} (EJE DE CAPACIDAD del keystone -- núcleo organizador real + novedad/especificidad acotada por verificación "
               "adversarial de 2 agentes, 12mo ciclo): ¿cómo escala la ventaja del PRODUCTO R-VALOR (ctrl×rel) sobre los factores de "
               "un eje con la CAPACIDAD K? QUÉ SOBREVIVE (robusto en el régimen GRADUADO, verificado en D/RHO/seeds/correlación-fina): "
               "el R-VALOR importa bajo DOS escaseces que INTERACTÚAN -- la ventaja del producto es grande sólo a CAPACIDAD escasa (K "
               "bajo) Y factores DISOCIADOS (ctrl≠rel); AUC anti={aa} > indep={ai} > corr={ac} (monótona y SUAVE en ρ_bw); K* "
               "(capacidad a la que un factor basta) anti={ka}/indep={ki}/corr={kc} = RELATIVO a D (≈{kr}·D, no absoluto); EXPLICA el "
               "K=1-load-bearing de 139 (a K≥2 el gap evaporaba porque la capacidad alcanzaba para los modos competidores). QUÉ NO "
               "SOBREVIVE (retractado por la verificación de 2 agentes): (1) 'decae con K / se desvanece a K=D' es PARCIALMENTE "
               "TRIVIAL -- la (1−payoff) de la selección ALEATORIA también decae a ~0 en K=D (decaim anti {rda}): a K=D se eligen "
               "TODOS los modos -> payoff=1 por construcción para CUALQUIER criterio; el contenido no-trivial es adv(K=1) y la "
               "pendiente interior, no el endpoint. (2) RECOMBINACIÓN, no mecanismo nuevo: las curvas de ventaja anti/indep "
               "NORMALIZADAS por adv(K=1) son ~idénticas (max-diff {usm}) -> el eje-K aporta UNA forma universal de decaimiento; lo "
               "regime-específico es sólo el NIVEL adv(K=1) = el mis-ranking de un-factor de la DISOCIACIÓN (130). El aporte es la "
               "SÍNTESIS (escasez 123-126 × disociación 130 interactúan + explica 139), no un mecanismo nuevo. (3) VALIDITY-LIMIT: "
               "vale para (b,w) GRADUADOS (el régimen canónico del keystone 130) -- con (b,w) BINARIOS el orden anti>indep se "
               "INVIERTE (binario AUC anti {baa} <= indep {bai}). => MIXTA: la síntesis organizadora de los dos ejes de escasez es "
               "real y robusta en el régimen graduado, pero es una recombinación (no novel), el decaimiento-en-K es parcialmente "
               "trivial (lo comparte el azar), K* es relativo, y el orden se invierte bajo marginal binaria. APORTE: el cuadro "
               "unificado capacidad×disociación + la explicación del K=1-load-bearing de 139.").format(
                   V=status.upper(), aa=_f(auc['anti']), ai=_f(auc['indep']), ac=_f(auc['corr']), ka=kst['anti'], ki=kst['indep'],
                   kc=kst['corr'], kr=_f(kstr['anti']), rda=_f(rd['anti']), usm=_f(usm), baa=_f(baa), bai=_f(bai))

    hyp = Hypothesis(
        id="H-V4-10n",
        statement=("El R-VALOR (producto ctrl×rel, keystone 129) importa bajo DOS escaseces que INTERACTÚAN -- CAPACIDAD (K bajo) y "
                   "DISOCIACIÓN (ctrl≠rel): la ventaja del producto sobre el mejor factor-solo es grande sólo cuando ambas escasean "
                   "y decae por ambos ejes (AUC anti>indep>corr; K* relativo ≈0.7·D); explica el K=1-load-bearing de 139. ACOTADO: "
                   "el decaimiento-en-K es parcialmente trivial (random también decae a K=D), es una RECOMBINACIÓN (forma universal; "
                   "regime-específico = adv(K=1) = disociación 130), válido para (b,w) GRADUADOS (binarios invierten)."),
        prediction=("APOYADA si la ventaja del producto decae con K de forma NO-trivial Y novel Y robusta a la marginal. MIXTA si el "
                    "núcleo organizador (capacidad×disociación) es real pero el decaimiento es parcialmente trivial / es una "
                    "recombinación / válido sólo para graduadas. REFUTADA si el núcleo no se sostiene. (Pre-registrada; verificación "
                    "adversarial de 2 agentes: tautología-novedad / robustez.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp126_capacity_keystone")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-10n")
        notes.append("H-V4-10n marcada '{}': el producto R-VALOR importa bajo capacidad×disociación conjuntas (núcleo organizador real, graduado); pero el decaimiento-en-K es parcialmente trivial, es una recombinación (forma universal; regime-específico = adv(K=1)=disociación 130), y sólo vale para marginales graduadas. Explica el K=1-load-bearing de 139.".format(status))

    analogy = AnalogyRecord(
        problem=("Sabías que tu regla 'mirá lo que podés MOVER y que IMPORTA' (el producto) gana cuando esas dos cosas no "
                 "coinciden. ¿Y cuándo NO hace falta el producto -cuándo basta mirar una sola?"),
        everyday=("Basta una sola cuando tenés CAPACIDAD de sobra (podés atender muchas cosas a la vez -> agarrás las buenas igual "
                  "con cualquier criterio) O cuando 'lo que movés' y 'lo que importa' COINCIDEN (entonces da igual cuál mires). El "
                  "producto sólo paga cuando tenés que elegir POCAS (capacidad escasa) Y las dos cosas están desalineadas. Honestidad: "
                  "(a) que 'sobre capacidad cualquier criterio sirve' es medio obvio -hasta elegir al azar mejora si elegís casi "
                  "todo-; (b) esto no es un descubrimiento nuevo, es JUNTAR dos cosas que ya sabíamos (el valor importa bajo escasez; "
                  "el producto importa cuando control y relevancia se separan); (c) si las cosas son todo-o-nada (binario) en vez de "
                  "grados, la historia hasta se da vuelta."),
        solutions=["el producto R-VALOR importa sólo bajo DOS escaseces conjuntas: capacidad escasa (K bajo) Y disociación (ctrl≠rel)",
                   "el decaimiento con la capacidad es parcialmente TRIVIAL (hasta el azar mejora cuando elegís casi todo)",
                   "es una RECOMBINACIÓN de 'valor bajo escasez' (123-126) + 'disociación' (130): la forma de decaimiento es universal, lo específico es el nivel a K=1",
                   "vale para grados (b,w) continuos -el régimen del keystone 130-; con b,w binarios el orden se invierte"],
        principles=["el producto R-VALOR (ctrl×rel) importa bajo la INTERACCIÓN de capacidad escasa × disociación -- explica por qué K=1 era load-bearing en 139",
                    "un decaimiento 'con K' que lo comparte la selección aleatoria es parcialmente trivial: separar la parte específica (adv a K=1, pendiente interior) de la genérica (endpoint K=D forzado)",
                    "una forma de curva UNIVERSAL entre regímenes = recombinación, no mecanismo nuevo: el contenido vive en el nivel inicial (la disociación), no en la forma",
                    "META: 12mo ciclo seguido con verificación adversarial -- aquí acotó NOVEDAD (recombinación) + TRIVIALIDAD (random decae) + VALIDITY-LIMIT (binario invierte)"],
        adaptation=("El CYCLE 139 dejó como frontera 'el efecto de la CAPACIDAD K sobre el valor de decisión'. Este ciclo lo estudia "
                    "y obtiene un MIXTA honesto: el producto R-VALOR importa bajo la INTERACCIÓN de DOS escaseces (capacidad × "
                    "disociación) -- un cuadro organizador real y robusto en el régimen graduado, que EXPLICA el K=1-load-bearing de "
                    "139. PERO la verificación adversarial acotó la novedad/especificidad: el decaimiento-en-K es parcialmente "
                    "trivial (lo comparte el azar), es una RECOMBINACIÓN de escasez (123-126) + disociación (130) -no un mecanismo "
                    "nuevo: la forma de decaimiento es universal y lo regime-específico es sólo adv(K=1)=la disociación-, K* es "
                    "relativo (~0.7·D), y el orden anti>indep vale sólo para marginales graduadas (binarias invierten). APORTE: la "
                    "SÍNTESIS unificada + la explicación de 139. META-LECCIÓN: 12mo ciclo seguido con verificación adversarial. "
                    "Próximo: el resto de la frontera de 139 (aislar la relevancia bajo ciclos donde reach≠relevancia); SCALE."),
        measurement=("exp126 ({n} seeds): AUC ventaja anti={aa}/indep={ai}/corr={ac}; K* abs {ka}/{ki}/{kc} rel ≈{kr}·D; random "
                     "decae anti {rda} (parcialmente trivial); forma universal max-diff {usm} (recombinación); binario AUC anti {baa} "
                     "<= indep {bai} (invierte).").format(
                         n=data['args']['seeds'], aa=_f(auc['anti']), ai=_f(auc['indep']), ac=_f(auc['corr']), ka=kst['anti'],
                         ki=kst['indep'], kc=kst['corr'], kr=_f(kstr['anti']), rda=_f(rd['anti']), usm=_f(usm), baa=_f(baa),
                         bai=_f(bai)),
        iterations=1)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (el producto sólo paga bajo capacidad escasa Y disociación; el decaimiento es medio obvio -hasta el azar mejora-; es juntar dos cosas ya sabidas; con binario se da vuelta).")

    kl = ("REAL (exp126, {V} post-verificación adversarial de 2 agentes): el producto R-VALOR (ctrl×rel, 129) importa bajo la "
          "INTERACCIÓN de DOS escaseces -- CAPACIDAD (K bajo) y DISOCIACIÓN (ctrl≠rel); la ventaja decae por ambos ejes (AUC anti={aa} "
          "> indep={ai} > corr={ac}, monótona/suave en ρ_bw; K* relativo ≈{kr}·D); explica el K=1-load-bearing de 139. TECHO/ALCANCE: "
          "el decaimiento-en-K es parcialmente TRIVIAL (random también decae a 0 en K=D); es una RECOMBINACIÓN (forma de decaimiento "
          "universal, max-diff {usm}; lo regime-específico es adv(K=1)=disociación 130), no un mecanismo nuevo; vale para (b,w) "
          "GRADUADOS (binarios invierten el orden, AUC anti {baa} <= indep {bai}); numpy/toy, producto=oracle por construcción. "
          "Frontera: aislar la relevancia bajo ciclos (resto de 139); SCALE.").format(
              V=status.upper(), aa=_f(auc['anti']), ai=_f(auc['indep']), ac=_f(auc['corr']), kr=_f(kstr['anti']), usm=_f(usm),
              baa=_f(baa), bai=_f(bai))
    ceilings.add(CeilingRecord(
        subsystem="EJE DE CAPACIDAD del keystone R-VALOR (valor=ctrl×rel) — el producto importa bajo la INTERACCIÓN de capacidad escasa (K bajo) × disociación (ctrl≠rel); decae por ambos ejes; explica el K=1-load-bearing de 139. ACOTADO: el decaimiento-en-K es parcialmente trivial (random también decae a K=D), es una RECOMBINACIÓN (forma universal; regime-específico = adv(K=1) = disociación 130), válido sólo para (b,w) graduados (binarios invierten). Núcleo organizador robusto en el régimen graduado (D/RHO/seeds/correlación-fina)",
        known_limit=kl,
        blockers=[{"text": "TRIVIALIDAD PARCIAL + RECOMBINACIÓN (acotación central de la verificación): (a) 'decae con K / se desvanece a K=D' es parcialmente trivial -- la (1−payoff) de la selección ALEATORIA también decae a ~0 en K=D (a K=D se eligen TODOS los modos -> payoff=1 por construcción para cualquier criterio); el contenido no-trivial es adv(K=1) y la pendiente interior. (b) las curvas de ventaja anti/indep normalizadas por adv(K=1) son ~idénticas (max-diff {usm}) -> el eje-K aporta UNA forma universal; lo regime-específico es sólo adv(K=1) = el mis-ranking de un-factor de la disociación (130). El aporte es la SÍNTESIS (escasez 123-126 × disociación 130 interactúan), no un mecanismo nuevo".format(usm=_f(usm)), "kind": "diseno"},
        {"text": "VALIDITY-LIMIT + K* RELATIVO: el orden anti>indep vale sólo para (b,w) GRADUADOS (el régimen canónico del keystone 130); con (b,w) BINARIOS (estilo 129) el orden se INVIERTE (binario AUC anti {baa} <= indep {bai}) porque la controlabilidad b²/(b²+ρ) satura. El K* no es absoluto (9/8) sino RELATIVO a la capacidad (≈0.7·D); el K*(corr)=1 está pineado al piso porque corr no tiene ventaja (los factores ya coinciden)".format(baa=_f(baa), bai=_f(bai)), "kind": "diseno"},
        {"text": "ALCANCE: numpy/toy, sustrato keystone de 129/130 (modos independientes, costo de control cuadrático); el producto=valor verdadero=oracle por construcción (payoff_product=1.0; lo medido es el payoff de los factores-solos). NO cubre: sustrato acoplado (137)/no-lineal (135-136), relevancia DESCUBIERTA (134), el lazo real; el resto de la frontera de 139 (aislar la relevancia bajo ciclos donde reach≠relevancia) queda abierto; SCALE", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP126.ref, S_C139.ref, S_VERIF.ref]))
    notes.append("1 techo 'real': el producto R-VALOR importa bajo capacidad×disociación conjuntas (explica el K=1-load-bearing de 139); pero el decaimiento-en-K es parcialmente trivial, es una recombinación (forma universal), y vale sólo para marginales graduadas.")

    dstmt = ("North-Star R-VALOR (EJE DE CAPACIDAD del keystone; estudia la frontera 'efecto de K' de 139): {V}. El producto R-VALOR "
             "(ctrl×rel, 129) importa bajo la INTERACCIÓN de DOS escaseces -- CAPACIDAD (K bajo) y DISOCIACIÓN (ctrl≠rel); decae por "
             "ambos ejes (AUC anti={aa}>indep={ai}>corr={ac}; K* relativo ≈{kr}·D); EXPLICA el K=1-load-bearing de 139. PERO el "
             "decaimiento-en-K es parcialmente TRIVIAL (random también decae), es una RECOMBINACIÓN (forma universal; regime-"
             "específico=disociación 130), y vale sólo para (b,w) graduados (binarios invierten). Decisión: adoptar el cuadro "
             "organizador capacidad×disociación (explica 139) SIN venderlo como mecanismo novel. META-DECISIÓN: 12mo ciclo con "
             "verificación adversarial. Próximo: aislar la relevancia bajo ciclos (resto de 139); SCALE.").format(
                 V=status.upper(), aa=_f(auc['anti']), ai=_f(auc['indep']), ac=_f(auc['corr']), kr=_f(kstr['anti']))
    drat = ("exp126 (tier5, propio, {n} seeds, numpy, post-verificación de 2 agentes): el producto importa bajo capacidad×disociación "
            "(núcleo robusto en el régimen graduado, explica el K=1-load-bearing de 139) PERO el decaimiento-en-K es parcialmente "
            "trivial (random también decae), es una recombinación (forma universal, regime-específico=disociación 130), y vale sólo "
            "para graduadas (binario invierte). Convergente con el principio (tier2) y la verificación (tier4); unifica 139+130 "
            "(tier5). MIXTA: síntesis organizadora real pero recombinación/parcialmente-trivial/graduado-only.").format(
                n=data['args']['seeds'])
    dec = Decision(id="D-V4-104", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP126), _to_plain(S_C139), _to_plain(S_VERIF)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-104 ACEPTADA por el ledger (tier5 exp126 + tier5 exp123/C139+exp114/C130 + tier4 verificación adversarial).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-104:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle142_capacity_keystone',
                                description='CYCLE 142 (RESET v4, H-V4-10n MIXTA: el producto R-VALOR importa bajo capacidad×disociación -explica el K=1-load-bearing de 139- pero el decaimiento es parcialmente trivial, es una recombinación, y vale sólo para marginales graduadas; 12mo ciclo con verificación adversarial).')
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
    print("RESUMEN — CYCLE 142 (RESET v4): el producto R-VALOR importa bajo capacidad×disociación (explica el K=1-load-bearing de 139) — H-V4-10n " + (status.upper() if status else "?"))
    print("=" * 78)
    print("veredicto H-V4-10n:", status.upper() if status else "?")
    print("  NÚCLEO (graduado): el producto importa bajo la INTERACCIÓN de capacidad escasa (K bajo) × disociación (ctrl≠rel); decae por ambos ejes; explica el K=1-load-bearing de 139. ACOTADO: decaimiento-en-K parcialmente trivial (random también decae a K=D); RECOMBINACIÓN (forma universal; regime-específico=disociación 130), no mecanismo nuevo; vale sólo para (b,w) graduados (binarios invierten el orden).")
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
