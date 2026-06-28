r"""
cycle154_calibration_metric.py — CICLO 154 (RESET v4, FRONTERA REAL §4.2): H-V4-9n por las compuertas del engine. El test DECISIVO
que el 153 definió: su payoff downstream era RANK-ONLY (precision@top-m re-expresa el AUROC del 151). ¿La CALIBRACIÓN del residuo
genérico (ls_lo) paga, SEPARADA del ranking? Métricas SENSIBLES A MAGNITUDES (Brier, ECE=calibración pura, NET umbral-abstención
cost-weighted) vs AUROC rank-only, sobre el pool fijo escaso del 153.

VEREDICTO: <SE COMPLETA TRAS LA VERIFICACIÓN ADVERSARIAL — este script es verdict-driven; lee results.json>.

DERIVA de exp136_calibration_metric/results/results.json (lazo torch REAL, N=6).
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle154_calibration_metric')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp136_calibration_metric', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


VERIF_CLAIM = (
    "verificación adversarial (4 sondas + síntesis; recomendó REFUTADA-de-RELIABILITY, ece_valid=True, dissociation_clean=False, "
    "net_degenerate=True): 0 confirma + 3 ACOTA + 1 REFUTA. La CONCLUSIÓN de fondo (la reliability del ls_lo NO paga) es CORRECTA "
    "-el ECE, única métrica de reliability PURA threshold-free, es plano-a-PEOR en AMBOS pools y AMBOS lotes (indist −ECE −0.006 "
    "t=−1.28, ls_lo levemente PEOR; heldout +0.0004; el durable también)- y las métricas son VÁLIDAS (sanity: exp() monótona → "
    "AUROC realmente invariante; ECE/Brier responden a magnitud, sin bug de insensibilidad). PERO el framing 'todo se desvanece / "
    "disociación limpia' SOBRE-VENDE el negativo en 3 puntos load-bearing: (1) en INDIST −Brier (+0.007, t=2.21≥t_crit, CI excl 0) y "
    "NET(λ3) (+0.081, CI excl 0) NO se desvanecen -son positivos SUB-ROBUSTOS, fallan el gate sólo por 6/6/t- PERO por Brier="
    "reliability−resolution+uncertainty con ECE plano son RESOLUTION (discriminación que co-mueve con AUROC, corr~0.82) = RANKING "
    "re-expresado, NO reliability → APOYAN rank-only. (2) el NET heldout es DEGENERADO (0/72 celdas no-nulas: nadie cruza τ≥0.5 OOD, "
    "los p heldout comprimidos cerca del base-rate) → 'NET heldout +0.000' es CERO ESTRUCTURAL, NO evidencia; sacarlo de la cadena "
    "probatoria. (3) FRAGILIDAD A N=6: el label FLIPEA REFUTADA↔APOYADA por lote (seeds 3-5 SOLOS → APOYADA vía −Brier t=5.67 -un "
    "FALSO POSITIVO del gate, resolution-driven, no reliability-) o por un solo seed ~cero → 'cierra el arco' debe suavizarse a 'no "
    "se detecta reliability residual vía ECE; robustez limitada a 6 seeds, pendiente N≥12'. ACOTACIÓN extra: p=exp(mean_logprob) es la "
    "prob geométrica de GENERACIÓN (fluidez), no un modelo de P(correct) → 'calibración' aquí = si esa fluidez sigue la tasa empírica "
    "de corrección (afecta igual a los 3 brazos → la disociación se sostiene). REACCIÓN: anclé el veredicto en ECE (robust_ece), "
    "marqué net_degenerate, reframé Brier/NET como resolution=ranking. FRONTERA: réplica N≥12 con barra SIMÉTRICA (CI-excl-0 "
    "consistente, no 6/6-unanimidad asimétrica) + umbral EV-óptimo POR-BRAZO (no τ fijo compartido) para el test de magnitud justo.")


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp136 primero): " + results_path)

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    nb = finalize_narrative(status, sm)
    for src in nb['sources']:
        ledger.add_source(src)
    notes.append(nb['sources_note'])

    hyp = Hypothesis(id="H-V4-9n", statement=nb['hyp_statement'], prediction=nb['hyp_prediction'],
                     status='abierta', confidence=nb['confidence'], evidence_for=nb['ev_for'],
                     evidence_against=nb['ev_against'], adversarial_verdict=nb['advtext'],
                     experiment_ref="exp136_calibration_metric")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-9n")
        notes.append(nb['mark_note'])

    analogy = nb['analogy']
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append(nb['analogy_note'])

    ceilings.add(nb['ceiling'])
    notes.append(nb['ceiling_note'])

    try:
        ledger.record_decision(nb['decision'])
        notes.append(nb['decision_note'])
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-114:", ex); raise

    return record, notes, status, sm


def finalize_narrative(status, sm):
    """status='refutada' (REFUTADA-de-RELIABILITY): la reliability PURA (ECE) del residuo NO paga; el único payoff robusto es RANKING
    (AUROC) + RESOLUTION (Brier/NET indist sub-robusto = ranking re-expresado); NET heldout degenerado; ACOTADO N=6 batch-frágil."""
    pl = str(sm['prereg_lambda'])
    gei = sm['neg_ece_gap']['indist']['ls_lo']; geh = sm['neg_ece_gap']['heldout']['ls_lo']
    gah = sm['auroc_gap']['heldout']['ls_lo']; gai = sm['auroc_gap']['indist']['ls_lo']
    gbi = sm['neg_brier_gap']['indist']['ls_lo']; gni = sm['net_gap']['indist'][pl]['ls_lo']
    gd_ece = sm['neg_ece_gap']['indist']['durable']
    ndh = sm['net_degenerate']['heldout']

    S_PRINCIPLE = Source(tier=2, ref=(
        "en el lazo real desconfundido, la ventaja del residuo de calibración genérico (ls_lo) que sobrevivió al desconfound del 151 "
        "es RANKING (AUROC) + RESOLUTION, NO calibración-qua-RELIABILITY: sobre la única métrica de reliability PURA threshold-free "
        "(ECE) el ls_lo NO mejora (plano-a-peor) en ningún pool; las trazas magnitude-sensitive que sí existen (Brier/NET) se "
        "descomponen en resolution=ranking. La tesis 123 ('la calibración paga en la decisión') NO queda tocada por este residuo."), obtained=False,
        claim=("Métricas magnitude-sensitive separan calibración de ranking: la reliability PURA (ECE) del ls_lo no paga (indist {gei} "
               "t={geit}, ls_lo PEOR; heldout {geh}); el único payoff robusto es RANKING (heldout AUROC {gah} t={gaht}). Las trazas "
               "Brier/NET son resolution (ranking re-expresado). El payoff del 153 era ranking, no calibración. (Principio acotado.)").format(
                   gei=_f(gei['mean']), geit=_f(gei['tstat']), geh=_f(geh['mean']), gah=_f(gah['mean']), gaht=_f(gah['tstat'])))
    S_153 = Source(tier=5, ref="cognia_x/experiments/exp135 (CYCLE 153) — el positivo rank-only que este ciclo RESUELVE", obtained=True,
        claim=("El 153 halló un 1er positivo-leaning del residuo bajo escasez PERO la verificación lo marcó RANK-ONLY (precision@top-m "
               "re-expresa el AUROC). H-V4-9n lo RESUELVE con métricas magnitude-sensitive: confirma que la ventaja es RANKING "
               "(AUROC robusto) y NO calibración (ECE plano-a-peor) -> el payoff del 153 era ranking re-expresado."))
    S_151 = Source(tier=5, ref="cognia_x/experiments/exp133 (CYCLE 151) — el AUROC residual que aquí se re-localiza como RANKING puro", obtained=True,
        claim=("El residuo genérico que sobrevivió el desconfound del 151 (ventaja AUROC +0.018) es, por H-V4-9n, RANKING/discriminación "
               "PURA, no calibración: el único payoff robusto downstream es AUROC/resolution; la reliability (ECE) no paga. Cierra la "
               "interpretación: lo que sobrevive del lazo real es ranking, no una señal de valor más calibrada."))
    S_VERIF = Source(tier=4, ref="verificación adversarial (workflow, 4 sondas con probes reales sobre los datos crudos + síntesis)", obtained=True,
        claim=VERIF_CLAIM)
    claim136 = ("exp136 (propio, lazo torch REAL, N={n}, pool fijo escaso del 153 -desconfound del 151 preservado-, 2 pools): métricas "
                "SENSIBLES A MAGNITUDES (Brier, ECE=reliability PURA, NET umbral-abstención) vs AUROC rank-only. ECE ls_lo−naive indist "
                "{gei} (t={geit}, ls_lo PEOR), heldout {geh} (t={geht}) -> reliability NO paga. AUROC heldout {gah} (CI {gahci}, "
                "t={gaht}) -> RANKING robusto. Trazas sub-robustas indist (no reliability, resolution): −Brier {gbi} (t={gbit}), "
                "NET(λ{pl}) {gni} (t={gnit}). NET heldout DEGENERADO ({ndh}). robust_ece={re}, rank_only={ro}.").format(
                    n=sm['n'], gei=_f(gei['mean']), geit=_f(gei['tstat']), geh=_f(geh['mean']), geht=_f(geh['tstat']),
                    gah=_f(gah['mean']), gahci=gah['ci95'], gaht=_f(gah['tstat']), gbi=_f(gbi['mean']), gbit=_f(gbi['tstat']),
                    pl=sm['prereg_lambda'], gni=_f(gni['mean']), gnit=_f(gni['tstat']), ndh=ndh, re=sm['robust_ece'], ro=sm['rank_only'])
    S_EXP136 = Source(tier=5, ref="cognia_x/experiments/exp136_calibration_metric", obtained=True, claim=claim136)

    ev_for = [S_EXP136.ref, S_153.ref, S_151.ref, S_VERIF.ref]
    ev_against = [S_PRINCIPLE.ref]

    advtext = (
        "{V}-de-RELIABILITY (el test DECISIVO que el 153 definió; verificación adversarial de 4 sondas, recomendó REFUTADA-de-"
        "reliability, dissociation_clean=False, net_degenerate=True): el 153 halló un 1er positivo-leaning del residuo bajo escasez "
        "PERO la verificación cazó que precision@top-m es RANK-ONLY (re-expresa el AUROC del 151), NO testea calibración. exp136 "
        "aplica el test correcto: sobre el pool fijo escaso del 153, métricas SENSIBLES A MAGNITUDES (NO rank-invariantes) que SEPARAN "
        "reliability de ranking -- Brier, ECE (reliability PURA, threshold-free), NET umbral-abstención cost-weighted-, en paralelo "
        "al AUROC. QUÉ SE ESTABLECE: (a) LA RELIABILITY DEL RESIDUO NO PAGA -- el ECE (única reliability pura) del ls_lo es plano-a-"
        "PEOR en AMBOS pools (indist {gei}, t={geit}, ls_lo levemente PEOR; heldout {geh}; el durable también {gde}) -> NO hay mejora "
        "de calibración. (b) EL ÚNICO PAYOFF ROBUSTO ES RANKING -- heldout AUROC {gah} (CI {gahci}, t={gaht}, disociación limpia sólo "
        "aquí: AUROC robusto con ECE/Brier nulos). (c) ACOTACIÓN load-bearing (verificación): NO 'todo se desvanece' -- en INDIST "
        "−Brier {gbi} (t={gbit}) y NET(λ{pl}) {gni} (t={gnit}) SÍ son positivos SUB-ROBUSTOS (CI excl 0, fallan el gate por 6/6/t) "
        "PERO por Brier=reliability−resolution+uncertainty con ECE plano son RESOLUTION (discriminación que co-mueve con AUROC ~0.82) "
        "= RANKING re-expresado, NO reliability; el NET heldout es DEGENERADO (cero estructural, nadie cruza τ OOD), NO evidencia. "
        "(d) FRAGILIDAD A N=6: el label flipea REFUTADA↔APOYADA por lote (seeds 3-5 solos darían APOYADA vía −Brier/resolution, un "
        "FALSO POSITIVO del gate). RESULTADO HONESTO: la CALIBRACIÓN-qua-reliability del residuo genérico NO paga downstream; el único "
        "payoff robusto es RANKING/discriminación (ya capturado por el AUROC del 151). CIERRA el arco downstream '¿calibración o "
        "ranking?' (149-154) DEL LADO RANKING: lo que sobrevivió al desconfound del 151 es una señal de RANKING, NO una señal de valor "
        "más calibrada; la tesis 123 ('la calibración paga') NO queda tocada por este residuo en el lazo real desconfundido. ACOTACIÓN: "
        "N={n} SMOKE batch-frágil; p=exp(logprob)=fluidez de generación, no P(correct) -la disociación se sostiene (afecta igual a los "
        "3 brazos)-. FRONTERA: réplica N≥12 con barra SIMÉTRICA (CI-excl-0, no 6/6-unanimidad) + umbral EV-óptimo POR-BRAZO (no τ fijo "
        "compartido) para el test de magnitud definitivo.").format(
            V=status.upper(), gei=_f(gei['mean']), geit=_f(gei['tstat']), geh=_f(geh['mean']), gde=_f(gd_ece['mean']),
            gah=_f(gah['mean']), gahci=gah['ci95'], gaht=_f(gah['tstat']), gbi=_f(gbi['mean']), gbit=_f(gbi['tstat']),
            pl=sm['prereg_lambda'], gni=_f(gni['mean']), gnit=_f(gni['tstat']), n=sm['n'])

    hyp_statement = ("¿La CALIBRACIÓN-qua-RELIABILITY del residuo genérico (ls_lo, único superviviente del desconfound del 151) PAGA "
                     "downstream, SEPARADA del ranking? (métricas sensibles a magnitudes -Brier, ECE reliability pura, NET umbral-"
                     "abstención- vs AUROC rank-only, sobre el pool fijo escaso del 153). RESULTADO: REFUTADA-de-RELIABILITY -- el ECE "
                     "(reliability pura) del ls_lo NO paga (plano-a-peor en ambos pools: indist {gei} t={geit}; heldout {geh}); el único "
                     "payoff robusto es RANKING (heldout AUROC {gah} t={gaht}); las trazas Brier/NET indist son RESOLUTION (ranking "
                     "re-expresado), el NET heldout degenerado. El payoff del 153 era ranking, no calibración. Alcance: lazo torch real "
                     "CPU, N={n} smoke batch-frágil.").format(
                         gei=_f(gei['mean']), geit=_f(gei['tstat']), geh=_f(geh['mean']), gah=_f(gah['mean']), gaht=_f(gah['tstat']), n=sm['n'])
    hyp_prediction = ("APOYADA-reliability si el ls_lo tiene ventaja ROBUSTA en ECE (reliability PURA) en un pool. REFUTADA si el ECE "
                      "no paga mientras el ranking (AUROC) sí (la ventaja es ranking/resolution). MIXTA si parcial. (Compuerta anclada "
                      "en ECE -reliability pura threshold-free-, NO en Brier/NET -que mezclan resolution-; verificación adversarial.)")

    mark_note = ("H-V4-9n marcada 'refutada' (REFUTADA-de-RELIABILITY): la reliability PURA (ECE) del residuo NO paga -plano-a-peor en "
                 "ambos pools/lotes-; el único payoff robusto es RANKING (heldout AUROC {gah} t={gaht}) + RESOLUTION (Brier/NET indist "
                 "sub-robusto = ranking re-expresado). NET heldout degenerado (no-evidencia). Cierra el arco downstream del lado "
                 "RANKING. ACOTADO: N=6 smoke batch-frágil, pendiente N≥12.").format(gah=_f(gah['mean']), gaht=_f(gah['tstat']))

    analogy = AnalogyRecord(
        problem=("El 153 vio que la pizca de criterio del residuo parecía servir para decidir bajo escasez, pero la forma de medir "
                 "sólo miraba el ORDEN (ranking), no qué tan seguro estaba el modelo. ¿Esa pizca es 'estar mejor calibrado' (la "
                 "seguridad coincide con acertar) o sólo 'ordenar mejor'?"),
        everyday=("Sólo ordenar mejor; estar-bien-calibrado NO. Medimos directamente si la SEGURIDAD del modelo coincide con cuánto "
                  "acierta (eso es calibración pura, no mira el orden). El método genérico (ls_lo) NO quedó mejor calibrado -de hecho "
                  "un pelín peor- en ningún examen. Lo único en lo que gana firme es ORDENANDO (ranking), que ya sabíamos del 151. "
                  "Algunas medidas intermedias parecían darle ventaja, pero al descomponerlas resultó que esa ventaja era otra vez "
                  "ORDEN disfrazado, no seguridad-bien-puesta. Y una de las pruebas (la de poner un umbral) ni siquiera funcionó en el "
                  "examen difícil porque nadie llegaba al umbral. Conclusión: lo que sobrevive del lazo real es 'ordena mejor', NO "
                  "'está mejor calibrado' -> la idea de que 'la buena calibración paga en la decisión' no la toca este residuo. (Ojo: "
                  "es un examen chico -6 alumnos- y frágil: con medio examen distinto el veredicto se daría vuelta; falta repetir más grande.)"),
        solutions=["ECE (reliability pura, threshold-free) ls_lo−naive indist {gei} (t={geit}, ls_lo PEOR) y heldout {geh}: NO mejor calibrado en ningún pool".format(gei=_f(gei['mean']), geit=_f(gei['tstat']), geh=_f(geh['mean'])),
                   "único payoff ROBUSTO: heldout AUROC {gah} (t={gaht}) -ranking-, con ECE/Brier nulos -> disociación limpia: ranking sí, calibración no".format(gah=_f(gah['mean']), gaht=_f(gah['tstat'])),
                   "trazas indist −Brier {gbi} (t={gbit}) / NET {gni}: NO se desvanecen pero son RESOLUTION (co-mueven con AUROC ~0.82) = ranking re-expresado".format(gbi=_f(gbi['mean']), gbit=_f(gbi['tstat']), gni=_f(gni['mean'])),
                   "NET heldout DEGENERADO (nadie cruza τ OOD) -> cero estructural, no-evidencia; el negativo se ancla en ECE, no en NET",
                   "FRAGILIDAD N=6: el label flipea por lote (seeds 3-5 darían APOYADA vía Brier/resolution, falso positivo del gate)"],
        principles=["separar CALIBRACIÓN (reliability: ¿la confianza coincide con la tasa de acierto?) de RANKING (resolution: ¿ordena "
                    "bien?) exige una métrica threshold-free de reliability (ECE); Brier y las decisiones-a-umbral MEZCLAN resolution "
                    "-> no aíslan calibración",
                    "un payoff downstream medido con una métrica rank-invariante (precision@top-m, AUROC) NO puede distinguir "
                    "calibración de ranking; el 153 lo confundió, el 154 lo separa",
                    "un umbral FIJO compartido sobre una confianza de escala desplazada DEGENERA OOD (nadie cruza) -> no informa; el "
                    "test de magnitud justo necesita un umbral EV-óptimo por-brazo",
                    "META: una REFUTADA que CIERRA un arco (el residuo es ranking, no calibración) es progreso -resuelve el limbo del "
                    "153- PERO a N=6 smoke batch-frágil es 'no se detecta', no 'demostrado imposible'; pendiente N≥12"],
        adaptation=("FRONTERA REAL §4.2 (el test decisivo del 153). El 153 dejó la pregunta calibración-vs-ranking abierta (su métrica "
                    "era rank-only). exp136 la separa con métricas magnitude-sensitive: la reliability del residuo NO paga; lo que "
                    "sobrevive es ranking. CIERRA el arco downstream del lado ranking. PRÓXIMO: réplica N≥12 con barra simétrica + "
                    "umbral EV-óptimo por-brazo; o PIVOTE a otra frontera (régimen base-acc alta, transferencia, SCALE)."),
        measurement=("exp136 (lazo torch real, N={n}, pool escaso): ECE ls_lo−naive indist {gei} (t={geit}), heldout {geh} (t={geht}); "
                     "AUROC heldout {gah} (CI {gahci}, t={gaht}); −Brier indist {gbi} (t={gbit}); NET(λ{pl}) indist {gni} (t={gnit}); "
                     "NET heldout degenerado={ndh}.").format(
                         n=sm['n'], gei=_f(gei['mean']), geit=_f(gei['tstat']), geh=_f(geh['mean']), geht=_f(geh['tstat']),
                         gah=_f(gah['mean']), gahci=gah['ci95'], gaht=_f(gah['tstat']), gbi=_f(gbi['mean']), gbit=_f(gbi['tstat']),
                         pl=sm['prereg_lambda'], gni=_f(gni['mean']), gnit=_f(gni['tstat']), ndh=ndh),
        iterations=4)
    analogy_note = ("Analogía 7 etapas registrada (lo que sobrevive del lazo real es 'ordena mejor' -ranking-, NO 'está mejor "
                    "calibrado' -reliability-; la tesis 'la calibración paga' no la toca este residuo; N=6 frágil, pendiente N≥12).")

    kl = ("REAL (exp136, REFUTADA-de-RELIABILITY + verificación adversarial): la reliability PURA (ECE) del residuo genérico NO paga "
          "downstream -plano-a-peor en ambos pools/lotes-; el único payoff robusto es RANKING (heldout AUROC {gah} t={gaht}) + "
          "RESOLUTION (Brier/NET indist sub-robusto = ranking re-expresado); NET heldout degenerado. Cierra el arco downstream del "
          "lado RANKING: lo que sobrevivió al desconfound del 151 es ranking, no calibración -> la tesis 123 no la toca este residuo. "
          "TECHO/ALCANCE: N={n} smoke BATCH-FRÁGIL (el label flipea por lote); p=fluidez no P(correct). NO cubre: réplica N≥12 con "
          "barra simétrica + umbral EV-óptimo por-brazo (el test de magnitud definitivo).").format(gah=_f(gah['mean']), gaht=_f(gah['tstat']), n=sm['n'])
    ceiling = CeilingRecord(
        subsystem=("Test DECISIVO del 153: ¿la CALIBRACIÓN-qua-reliability del residuo paga downstream, separada del ranking? (métricas "
                   "magnitude-sensitive Brier/ECE/NET vs AUROC). RESULTADO: REFUTADA-de-RELIABILITY -- el ECE (reliability pura) no "
                   "paga; el único payoff robusto es RANKING; cierra el arco downstream del lado ranking. ACOTADO N=6 batch-frágil"),
        known_limit=kl,
        blockers=[{"text": ("RELIABILITY NO PAGA, RANKING SÍ: el ECE (única reliability pura) del ls_lo es plano-a-peor en ambos pools "
                            "(indist {gei} t={geit}); el único payoff robusto es heldout AUROC {gah} (t={gaht}). Las trazas Brier/NET "
                            "indist (CI excl 0) son RESOLUTION = ranking re-expresado (co-mueven con AUROC ~0.82), no reliability.").format(
                                gei=_f(gei['mean']), geit=_f(gei['tstat']), gah=_f(gah['mean']), gaht=_f(gah['tstat'])), "kind": "diseno"},
                  {"text": ("FRAGILIDAD/ACOTACIÓN: N={n} SMOKE; el label flipea REFUTADA↔APOYADA por lote (seeds 3-5 solos → APOYADA vía "
                            "−Brier/resolution, falso positivo del gate). NET heldout DEGENERADO (nadie cruza τ OOD). 'Cierra el arco' "
                            "= 'no se detecta reliability residual vía ECE', no 'demostrado imposible'.").format(n=sm['n']), "kind": "fisico"},
                  {"text": ("FRONTERA: réplica N≥12 con barra SIMÉTRICA (CI-excl-0 consistente, no 6/6-unanimidad asimétrica) + un "
                            "umbral EV-óptimo POR-BRAZO en holdout (no τ fijo compartido, que degenera OOD) para el test de magnitud "
                            "definitivo. O PIVOTE: régimen base-acc alta; transferencia; SCALE (la inversión robusta del durable y el "
                            "ranking del residuo SÍ son firmes)."), "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP136.ref, S_153.ref, S_VERIF.ref])
    ceiling_note = ("1 techo 'real': la calibración-qua-reliability del residuo NO paga downstream (ECE plano-a-peor); el único payoff "
                    "robusto es RANKING. Cierra el arco downstream del lado ranking. ACOTADO N=6 batch-frágil, pendiente N≥12.")

    dstmt = ("North-Star R-VALOR (FRONTERA REAL §4.2 -- el test DECISIVO del 153): {V}. ¿La CALIBRACIÓN-qua-reliability del residuo "
             "genérico PAGA downstream, separada del ranking? exp136 (métricas magnitude-sensitive Brier/ECE/NET vs AUROC, pool escaso "
             "del 153): REFUTADA-de-RELIABILITY -- el ECE (reliability PURA) del ls_lo no paga (plano-a-peor en ambos pools: indist "
             "{gei}, heldout {geh}); el único payoff ROBUSTO es RANKING (heldout AUROC {gah} t={gaht}); las trazas Brier/NET indist son "
             "RESOLUTION (ranking re-expresado), el NET heldout degenerado. Verificación adversarial (recomendó REFUTADA-de-reliability, "
             "net_degenerate=True). Decisión: ADOPTAR que (1) la reliability del residuo NO paga downstream, (2) lo que sobrevivió al "
             "desconfound del 151 es una señal de RANKING/discriminación, NO una señal de valor más calibrada -> la tesis 123 ('la "
             "calibración paga') NO queda tocada por este residuo en el lazo real desconfundido, (3) CIERRA el arco downstream "
             "'calibración o ranking?' del lado RANKING. ACOTADO: N=6 smoke batch-frágil. Próximo: réplica N≥12 + umbral EV-óptimo "
             "por-brazo; o pivote (base-acc alta / transferencia / SCALE).").format(
                 V=status.upper(), gei=_f(gei['mean']), geh=_f(geh['mean']), gah=_f(gah['mean']), gaht=_f(gah['tstat']))
    drat = ("exp136 (tier5, propio, lazo torch real, N={n}, post-verificación adversarial que recomendó REFUTADA-de-reliability): el "
            "ECE (reliability PURA threshold-free) del ls_lo no paga (plano-a-peor en ambos pools/lotes); el único payoff robusto es "
            "RANKING (heldout AUROC {gah} t={gaht}); las trazas Brier/NET indist (CI excl 0) son resolution=ranking re-expresado; NET "
            "heldout degenerado. Convergente con el principio (tier2), el 153/151 (tier5) y la verificación (tier4). REFUTADA-de-"
            "reliability: cierra el arco downstream del lado ranking; ACOTADO N=6 batch-frágil.").format(
                n=sm['n'], gah=_f(gah['mean']), gaht=_f(gah['tstat']))
    decision = Decision(id="D-V4-114", statement=dstmt, rationale=drat,
                        sources=[_to_plain(S_EXP136), _to_plain(S_153), _to_plain(S_VERIF)], important=True)

    return {
        "sources": [S_PRINCIPLE, S_153, S_151, S_VERIF, S_EXP136],
        "sources_note": ("5 fuentes (S_PRINCIPLE tier2 el residuo es ranking no reliability; S_153 tier5 el positivo rank-only que se "
                         "resuelve; S_151 tier5 el AUROC residual re-localizado como ranking puro; S_VERIF tier4 verificación recomendó "
                         "REFUTADA-de-reliability; S_EXP136 tier5 dato propio REFUTADA-de-reliability)."),
        "hyp_statement": hyp_statement, "hyp_prediction": hyp_prediction, "confidence": "media",
        "ev_for": ev_for, "ev_against": ev_against, "advtext": advtext, "mark_note": mark_note,
        "analogy": analogy, "analogy_note": analogy_note, "ceiling": ceiling, "ceiling_note": ceiling_note,
        "decision": decision, "decision_note": "D-V4-114 ACEPTADA por el ledger (tier5 exp136 + tier5 153/151 + tier4 verificación adversarial)."}


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle154_calibration_metric',
                                description='CYCLE 154 (RESET v4, H-V4-9n: ¿la CALIBRACIÓN del residuo paga separada del ranking?).')
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
    print("RESUMEN — CYCLE 154 (RESET v4): ¿la CALIBRACIÓN del residuo paga separada del ranking? — H-V4-9n " + (status.upper() if status else "?"))
    print("=" * 78)
    print("veredicto H-V4-9n:", status.upper() if status else "?")
    for n_ in notes:
        print("  CHECK ", n_)
    print("")
    for name in ('sources', 'hypotheses', 'analogies', 'ceilings', 'decisions'):
        print("  {:<12}: {}".format(name, count_lines(record.store_path(name))))
    print("  verify_no_loss =", "OK" if res['ok'] else "FAIL")
    print("=" * 78)
    return 0 if res['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
