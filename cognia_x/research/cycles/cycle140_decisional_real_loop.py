r"""
cycle140_decisional_real_loop.py — CICLO 140 (RESET v4, rama R-VALOR, SALIR DEL ORÁCULO): H-V4-9g por las compuertas del engine.
La auditoría de la teoría (post-139) marcó el hueco #1: TODO el payoff decisional del R-VALOR se demostró en numpy SINTÉTICO con
oráculo (exp107/123, +0.904 bajo escasez con ρ IMPUESTO); el único intento previo en el LAZO TORCH REAL (exp106/122) dio REFUTADA
por saturación. Este ciclo intenta aterrizarlo: reusa el lazo cerrado REAL (HybridLM genera 'N=a*b' -> verificador REAL sandbox ->
confianza ENDÓGENA -> self-train con/sin cura de unlikelihood 119) y mide si la calibración del durable paga en la decisión real.

VEREDICTO: MIXTA (post-verificación adversarial de 4 agentes; 10mo ciclo seguido). El experimento AUTO-DOCUMENTA el veredicto.

QUÉ SOBREVIVE (limpio): (a) la DECISIÓN es genuinamente ENDÓGENA (ranking por la confianza del modelo; el oráculo sólo MIDE) y el
verificador es REAL (sandbox aritmético) -- el paso fuera del ρ-sintético es real en ese sentido estrecho; (b) hay una ventaja de
RANKING base-rate-INVARIANTE del durable (AUROC > naive, signo-consistente sobre seeds): un efecto de calibración real, MODESTO.

QUÉ NO SOBREVIVE (retractado/acotado por la verificación de 4 agentes -- el experimento lo AUTO-DOCUMENTA):
  (1) CONFOUND DE BASE-RATE: el titular de la 1ra versión (payoff precision@m) estaba CONFUNDIDO -- los dos brazos son modelos
      distintos que generan pools con distinto #correctas; precision@m es base-rate-SENSIBLE. La 1ra versión ni siquiera logueaba
      el #correctas del naive. Corregido aquí con AUROC (invariante) + lift + base-rate de AMBOS brazos.
  (2) NO SIGNIFICATIVO a N=4 (underpowered): el t-test pareado no cruza el umbral; el sign-test tope con 4 seeds es p=0.125.
  (3) MECANISMO FALSO: NO hay 'pico recall-crítico en f=1' (el gap del payoff es máximo en f≈0.5, zona trivial, monótono-
      decreciente); el gate 'decision_driven' (se anula a f=4) era VACUO (4·#correctas>pool -> a f=4 se somete todo).
  (4) TRADE-OFF GENERACIÓN/RANKING: el unlikelihood (cura 119) suprime la generación -> el durable genera MENOS correctas; 'decide
      mejor' se acota con 'genera menos para decidir'.
  (5) FRAMING: 'sale del oráculo' es ACOTADO (el verificador supervisa el self-train, etiqueta y normaliza la métrica; sólo el
      ranking es endógeno); 'transfiere' es un ECO ATENUADO vs exp107 (no la escasez q=0.08; ~44% correctas = abundancia).

APORTE NETO honesto: (i) el paso metodológico REAL (decisión endógena + verificador real) y una ventaja de ranking base-rate-
invariante (AUROC) modesta del durable; (ii) la LECCIÓN: medir payoff decisional en un lazo de auto-entrenamiento EXIGE controlar
el base-rate (AUROC/lift, no precision@m) y N suficiente. MIXTA EXITOSA: la verificación cazó un CONFOUND + mecanismo falso +
framing sobre-vendido antes del ledger.

DERIVA de exp124_decisional_real_loop/results/results.json.

Correr (DESPUÉS de exp124):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp124_decisional_real_loop.run --seeds 0,1,2,3
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle140_decisional_real_loop
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle140_decisional_real_loop')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp124_decisional_real_loop', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="medir el payoff DECISIONAL de una señal de valor ENDÓGENA en un LAZO de auto-entrenamiento REAL exige controlar el BASE-RATE: dos brazos que difieren en su entrenamiento (p.ej. con/sin unlikelihood) generan pools con distinto #correctas, y las métricas de decisión base-rate-SENSIBLES (precision@m) confunden 'mejor calibración' con 'genera menos/más'. La métrica correcta es base-rate-INVARIANTE (AUROC del ranking confianza-vs-correcto) o base-rate-controlada (lift sobre azar). Bajo esas métricas la ventaja de calibración del brazo durable (cura 119) es REAL pero MODESTA, y el unlikelihood induce un TRADE-OFF generación/ranking.", obtained=False,
                     claim=("El payoff decisional del R-VALOR medido en un lazo real es CONFUNDIBLE con el base-rate; con métricas "
                            "base-rate-invariantes (AUROC) la ventaja del durable es real pero modesta y underpowered, con un "
                            "trade-off generación/ranking del unlikelihood. (Principio metodológico.)"))
S_PRIOR = Source(tier=5, ref="cognia_x/experiments/exp107_decisional_scarcity (CYCLE 123) + exp106_decisional_payoff (CYCLE 122)", obtained=True,
                 claim=("CYCLE 123 (exp107, numpy SINTÉTICO, ρ impuesto): la calibración paga +0.904 bajo escasez. CYCLE 122 "
                        "(exp106, lazo torch REAL): REFUTADA por saturación de la decisión. H-V4-9g intenta aterrizar el payoff en "
                        "el lazo real: el paso (decisión endógena + verificador real) es real, pero la atribución a calibración "
                        "está confundida con el base-rate y es underpowered -> MIXTA."))
S_VERIF = Source(tier=4, ref="verificación adversarial de 4 agentes (lentes confound/mecanismo, tautología/leakage, robustez-seed, fairness-framing; probes reales sobre exp124 y su log)", obtained=True,
                 claim=("La verificación adversarial (4 agentes, 10mo ciclo) CONFIRMÓ que la decisión es endógena y el verificador "
                        "real (no leakage/tautología) PERO CAZÓ: un CONFOUND DE BASE-RATE (los brazos generan distinto #correctas; "
                        "la 1ra versión no logueaba el #correctas del naive -> el titular precision@m era irrecuperable); que NO es "
                        "significativo a N=4; que el mecanismo 'pico en f=1' es FALSO (pico en f≈0.5 trivial, gap monótono-"
                        "decreciente; el gate decision_driven era vacuo); y que 'sale del oráculo'/'transfiere' estaban sobre-"
                        "vendidos. El experimento se reescribió con AUROC/lift/base-rate-de-ambos-brazos -> MIXTA honesta."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp124 primero): " + results_path)

    au = sm['auroc_gap_stats']; lf = sm['lift_f1_gap_stats']; br = sm['baserate_gap_stats']
    aun, aud = sm['auroc_naive'], sm['auroc_durable']
    ncd, ncn, npool = sm['mean_ncorrect_durable'], sm['mean_ncorrect_naive'], sm['mean_npool']
    cgap = sm['corr_gap']
    n_seeds = data['args']['seeds'] if isinstance(data['args'].get('seeds'), int) else len(str(data['args'].get('seeds', '')).split(','))

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim124 = ("exp124 (propio, {n} seeds, PyTorch CPU, lazo cerrado REAL, post-verificación de 4 agentes): {V}. SALIR DEL "
                "ORÁCULO -- reusa el lazo real (HybridLM genera 'N=a*b' -> verificador REAL sandbox -> confianza ENDÓGENA -> self-"
                "train con/sin cura 119). SOBREVIVE: la decisión es endógena (ranking por confianza, el oráculo sólo mide) y el "
                "verificador es real; ventaja de RANKING base-rate-INVARIANTE del durable AUROC {aud} vs naive {aun} (gap medio "
                "+{aum}, {aup}/{ann} seeds pos, mediana +{aumed}, jackknife-min +{aujk}, t={aut}, signif={ausig}). RETRACTADO: el "
                "titular precision@m estaba CONFUNDIDO con el base-rate (durable {ncd} vs naive {ncn} correctas, gap {brm}); no "
                "significativo a N={n}; el mecanismo 'pico f=1' es falso; 'sale del oráculo'/'transfiere' sobre-vendidos. Trade-off "
                "generación/ranking del unlikelihood.").format(
                    n=n_seeds, V=status.upper(), aud=_f(aud), aun=_f(aun), aum=_f(au['mean']), aup=au['n_positive'],
                    ann=au['n'], aumed=_f(au['median']), aujk=_f(au['jackknife_min']), aut=au['tstat'], ausig=au['significant'],
                    ncd=_f(ncd), ncn=_f(ncn), brm=_f(br['mean']))
    S_EXP124 = Source(tier=5, ref="cognia_x/experiments/exp124_decisional_real_loop", obtained=True, claim=claim124)
    for src in (S_PRINCIPLE, S_PRIOR, S_VERIF, S_EXP124):
        ledger.add_source(src)
    notes.append("4 fuentes (S_PRINCIPLE tier2 medir payoff decisional en lazo real exige controlar el base-rate; S_PRIOR tier5 exp107 sintético / exp106 REFUTADA; S_VERIF tier4 verificación adversarial -confound+mecanismo falso+framing-; S_EXP124 tier5 dato propio {}).".format(status.upper()))

    ev_for = [S_EXP124.ref, S_PRINCIPLE.ref]
    ev_against = [S_EXP124.ref, S_VERIF.ref]
    advtext = ("{V} (SALIR DEL ORÁCULO: intento de aterrizar el payoff decisional del R-VALOR fuera del numpy sintético; "
               "caracterización honesta tras verificación adversarial de 4 agentes, 10mo ciclo): ¿la calibración endógena del "
               "brazo durable PAGA en la decisión real del lazo torch (HybridLM genera 'N=a*b' -> verificador REAL sandbox -> "
               "confianza ENDÓGENA -> self-train; durable agrega unlikelihood=cura 119)? QUÉ SOBREVIVE (EVIDENCIA A FAVOR, limpio): "
               "(a) la DECISIÓN de submission es genuinamente ENDÓGENA -- el top-m se elige por la CONFIANZA del modelo (mean-"
               "logprob), el oráculo (verificador real) sólo MIDE el payoff; sin leakage/tautología (confirmado por la "
               "verificación). (b) hay una ventaja de RANKING base-rate-INVARIANTE del durable: AUROC(confianza,correcto) {aud} vs "
               "naive {aun}, gap medio +{aum}, {aup}/{ann} seeds POSITIVOS (mediana +{aumed}, jackknife-min +{aujk}) -- un efecto "
               "de calibración REAL (el unlikelihood mantiene la confianza más honesta), MODESTO. EVIDENCIA EN CONTRA (retractado "
               "por la verificación de 4 agentes -- el experimento lo AUTO-DOCUMENTA): (1) el TITULAR previo (payoff precision@m a "
               "f=1) estaba CONFUNDIDO con el BASE-RATE: el durable y el naive son modelos DISTINTOS que generan pools con distinto "
               "#correctas (durable {ncd} vs naive {ncn}, gap {brm}); precision@m es base-rate-SENSIBLE, y un Δbase-rate plausible "
               "con CERO diferencia de calibración reproduce el titular. La 1ra versión NI SIQUIERA logueaba el #correctas del "
               "naive -> el confound era irrecuperable; corregido con AUROC+lift+base-rate de AMBOS brazos. (2) NO SIGNIFICATIVO a "
               "N={n} (underpowered): el t-test pareado no cruza el umbral (t={aut}); con 4 seeds el sign-test tope es p=0.125 -- "
               "la significancia se REPORTA pero no habilita APOYADA. (3) el MECANISMO afirmado ('pico recall-crítico en f=1') es "
               "FALSO: el gap del payoff es MÁXIMO en f≈0.5 (zona que el propio grid llama trivial) y monótono-decreciente; el gate "
               "'decision_driven' (se anula a f=4) era VACUO (4·#correctas>pool -> a f=4 se somete todo por construcción). (4) "
               "TRADE-OFF generación/ranking: el unlikelihood SUPRIME la generación (el durable genera MENOS correctas) -> 'el "
               "calibrado decide mejor' se acota con 'genera menos para decidir'. (5) FRAMING: 'sale del oráculo' es ACOTADO -- "
               "sólo el RANKING es endógeno; el verificador supervisa el self-train, etiqueta las generaciones y NORMALIZA la "
               "métrica; 'transfiere' es un ECO MUY ATENUADO vs exp107 (+0.904 random-vs-best, escasez q=0.08) -- acá entre dos "
               "señales ya-positivas a ~44% correctas (abundancia); el régimen f≈1 se eligió POST-HOC. => RESULTADO HONESTO: el "
               "paso fuera del ρ-sintético es REAL (decisión endógena + verificador real) y hay una ventaja de ranking base-rate-"
               "invariante MODESTA del durable, pero NO significativa a N=4 y con confound de base-rate + trade-off de generación; "
               "el 'payoff decisional' limpio NO está establecido en el lazo real. APORTE NETO: la LECCIÓN METODOLÓGICA (controlar "
               "base-rate con AUROC/lift + N suficiente). MIXTA EXITOSA: la verificación cazó un CONFOUND + mecanismo falso + "
               "framing sobre-vendido antes del ledger (10mo ciclo seguido).").format(
                   V=status.upper(), aud=_f(aud), aun=_f(aun), aum=_f(au['mean']), aup=au['n_positive'], ann=au['n'],
                   aumed=_f(au['median']), aujk=_f(au['jackknife_min']), aut=au['tstat'], n=n_seeds, ncd=_f(ncd),
                   ncn=_f(ncn), brm=_f(br['mean']))

    hyp = Hypothesis(
        id="H-V4-9g",
        statement=("¿El payoff DECISIONAL del R-VALOR (la calibración endógena paga en la decisión) ATERRIZA en un LAZO CERRADO "
                   "REAL (HybridLM genera -> verificador REAL sandbox -> confianza ENDÓGENA -> self-train con/sin cura 119), fuera "
                   "del numpy sintético de exp107? La decisión es endógena (ranking por confianza) y el verificador real; la "
                   "atribución a calibración debe controlarse por BASE-RATE (los brazos generan distinto #correctas). Alcance: "
                   "sustrato chico, tarea aritmética, N=4, CPU."),
        prediction=("APOYADA si hay una ventaja de ranking base-rate-INVARIANTE (AUROC) del durable, significativa (N>=8) y sin "
                    "trade-off de generación. REFUTADA si no hay ventaja de ranking (el payoff aparente era confound de base-rate). "
                    "MIXTA si la ventaja es real pero modesta/underpowered/con trade-off de generación. (Pre-registrada; "
                    "verificación adversarial de 4 agentes: confound/tautología/robustez/framing.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp124_decisional_real_loop")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-9g")
        notes.append("H-V4-9g marcada '{}': la decisión es endógena + verificador real (paso real fuera del ρ-sintético) y hay una ventaja de ranking base-rate-invariante (AUROC) MODESTA del durable, pero confundida con el base-rate, underpowered a N=4, con trade-off de generación, y framing sobre-vendido. Lección metodológica: controlar base-rate (AUROC/lift) + N suficiente.".format(status))

    analogy = AnalogyRecord(
        problem=("Querés mostrar que un modelo que se entrena solo y mantiene su 'olfato' honesto elige mejores respuestas para "
                 "mandar a corregir. Lo medís contando 'qué fracción de las que mandó eran buenas'. ¿Esa cuenta prueba que el "
                 "olfato ayuda?"),
        everyday=("Casi te traiciona. Si el modelo 'calibrado' resulta que GENERA muchas menos respuestas buenas que el otro (la "
                  "cura que le afila el olfato también le seca la creatividad), entonces 'qué fracción de las que mandó eran "
                  "buenas' sube por una razón tramposa: tenía menos para elegir y las pocas buenas saltaban a la vista -- no "
                  "porque su olfato sea mejor. La medición original ni siquiera anotó cuántas buenas generaba el otro, así que el "
                  "número era irrecuperable. La cuenta JUSTA es '¿ordena las buenas arriba de las malas?' (independiente de cuántas "
                  "haya): ahí el calibrado SÍ gana, pero POCO, y con sólo 4 corridas no alcanza para estar seguro. Moraleja: para "
                  "decir que el olfato paga hay que medir el ORDEN (no la fracción), anotar cuánto genera cada uno, y correr "
                  "suficientes veces."),
        solutions=["medir el payoff decisional en un lazo de auto-entrenamiento EXIGE controlar el base-rate: usar AUROC (ranking, invariante) o lift, no precision@m (sensible al base-rate)",
                   "loguear el #correctas de AMBOS brazos -- si no, el confound es irrecuperable (la 1ra versión sólo logueaba el durable)",
                   "el unlikelihood (cura 119) induce un TRADE-OFF generación/ranking: afila el olfato pero seca la generación -> 'decide mejor' se acota con 'genera menos'",
                   "con N=4 seeds NO se puede reclamar significancia (sign-test tope p=0.125): la ventaja AUROC es real en signo pero underpowered"],
        principles=["medir payoff decisional en un lazo de auto-entrenamiento REAL exige controlar el base-rate (AUROC/lift) y N suficiente; precision@m confunde calibración con cantidad-generada",
                    "un CONFOUND es irrecuperable si no se loguea la variable confusora de AMBOS brazos -> instrumentar el confound ANTES, no después",
                    "una intervención de entrenamiento (unlikelihood) puede mejorar UN eje (ranking) y dañar OTRO (generación) -> medir ambos, el 'win' de un eje no es un win neto",
                    "META: 10mo ciclo seguido en que la verificación adversarial corrige overclaims (aquí: confound de base-rate + mecanismo falso + framing sobre-vendido) antes del ledger"],
        adaptation=("La auditoría (post-139) marcó como hueco #1 que TODO el payoff decisional del R-VALOR vivía en numpy-con-"
                    "oráculo. Este ciclo da el PRIMER intento afuera: reusa el lazo cerrado REAL (modelo genera, verificador real, "
                    "confianza endógena, self-train) y mide si la calibración del durable paga. RESULTADO MIXTO honesto: el PASO es "
                    "real (la decisión es endógena -ranking por confianza- y el verificador es real, no leakage) y hay una ventaja "
                    "de RANKING base-rate-INVARIANTE (AUROC) MODESTA del durable. PERO la verificación adversarial de 4 agentes "
                    "cazó que el titular previo (payoff precision@m) estaba CONFUNDIDO con el base-rate (los brazos generan distinto "
                    "#correctas; la 1ra versión no logueaba el del naive), que NO es significativo a N=4, que el mecanismo 'pico en "
                    "f=1' es falso, que hay un trade-off generación/ranking del unlikelihood, y que 'sale del oráculo'/'transfiere' "
                    "estaban sobre-vendidos. APORTE NETO: el paso metodológico real + la LECCIÓN (controlar base-rate con AUROC/"
                    "lift, loguear el confound de ambos brazos, N suficiente). META-LECCIÓN: 10mo ciclo seguido en que la "
                    "verificación adversarial corrige overclaims antes del ledger -- aquí un CONFOUND de base-rate (el modo de "
                    "fallo de un lazo real con dos generadores distintos). Próximo: re-correr con N>=8 + base-rate emparejado o "
                    "ranking-AUC como métrica primaria; SCALE; verificador de dominio más rico."),
        measurement=("exp124 ({n} seeds, lazo torch REAL): AUROC durable {aud} vs naive {aun} (gap +{aum}, {aup}/{ann} seeds, "
                     "mediana +{aumed}, t={aut}, signif={ausig}); lift@f1 gap +{lm}; CONFOUND base-rate durable {ncd} vs naive "
                     "{ncn}/{np} correctas (gap {brm}); corr-AUC gap +{cg}.").format(
                         n=n_seeds, aud=_f(aud), aun=_f(aun), aum=_f(au['mean']), aup=au['n_positive'], ann=au['n'],
                         aumed=_f(au['median']), aut=au['tstat'], ausig=au['significant'], lm=_f(lf['mean']),
                         ncd=_f(ncd), ncn=_f(ncn), np=_f(npool), brm=_f(br['mean']), cg=_f(cgap)),
        iterations=1)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (medir 'fracción de buenas' confunde calibración con cantidad-generada; la cuenta justa es el ORDEN -AUROC-, y con 4 corridas no alcanza).")

    kl = ("REAL (exp124, {V} post-verificación adversarial de 4 agentes): primer intento de aterrizar el payoff decisional del "
          "R-VALOR fuera del numpy-con-oráculo, en un lazo cerrado REAL (HybridLM + verificador sandbox + confianza endógena + "
          "self-train con/sin cura 119). SOBREVIVE: la decisión es endógena (ranking por confianza, el oráculo sólo mide) y el "
          "verificador real; ventaja de RANKING base-rate-INVARIANTE del durable (AUROC {aud} vs {aun}, gap +{aum}, {aup}/{ann} "
          "seeds), MODESTA. NO ESTABLECIDO (retractado): el payoff precision@m estaba CONFUNDIDO con el base-rate (durable {ncd} vs "
          "naive {ncn} correctas); no significativo a N={n}; mecanismo 'pico f=1' falso; trade-off generación/ranking; framing "
          "'sale del oráculo'/'transfiere' sobre-vendido. TECHO/ALCANCE: el oráculo (verificador) supervisa el lazo entero y "
          "normaliza la métrica -- sólo el RANKING es endógeno; sustrato CHICO (HybridLM ~200k), tarea aritmética acotada, N=4 "
          "underpowered, CPU. LECCIÓN: medir payoff decisional en un lazo de auto-entrenamiento exige controlar el base-rate "
          "(AUROC/lift) y N suficiente. Frontera: re-correr con N>=8 + base-rate emparejado; SCALE; verificador de dominio rico; "
          "lazo de acción-consecuencia SECUENCIAL.").format(
              V=status.upper(), aud=_f(aud), aun=_f(aun), aum=_f(au['mean']), aup=au['n_positive'], ann=au['n'],
              ncd=_f(ncd), ncn=_f(ncn), n=n_seeds)
    ceilings.add(CeilingRecord(
        subsystem="PAYOFF DECISIONAL del R-VALOR en un LAZO CERRADO REAL (primer intento fuera del numpy-con-oráculo, hueco #1 de la auditoría post-139) — MIXTA. SOBREVIVE: la decisión es ENDÓGENA (ranking por confianza del modelo; el oráculo sólo mide) + verificador REAL (sandbox aritmético); ventaja de RANKING base-rate-INVARIANTE del durable (AUROC, signo-consistente), MODESTA. NO ESTABLECIDO: el titular precision@m estaba CONFUNDIDO con el base-rate (brazos con distinto #correctas; la 1ra versión no logueaba el del naive), no significativo a N=4, mecanismo 'pico f=1' falso, trade-off generación/ranking del unlikelihood, framing sobre-vendido. Corregido con AUROC/lift/base-rate de ambos brazos. Alcance: sustrato chico, tarea aritmética, N=4, oráculo supervisa el lazo",
        known_limit=kl,
        blockers=[{"text": "CONFOUND DE BASE-RATE (el modo de fallo central, cazado por la verificación): el durable y el naive son modelos DISTINTOS que generan pools con distinto #correctas (durable {ncd} vs naive {ncn}); el payoff precision@m es base-rate-SENSIBLE, así que un Δbase-rate con CERO diferencia de calibración reproduce el 'gap' aparente. La 1ra versión NI SIQUIERA logueaba el #correctas del naive -> irrecuperable. Corregido aquí con AUROC (ranking, base-rate-INVARIANTE) + lift + base-rate de AMBOS brazos. Lo NO-confundido/load-bearing: la ventaja de RANKING AUROC del durable (gap +{aum}, {aup}/{ann} seeds positivos)".format(ncd=_f(ncd), ncn=_f(ncn), aum=_f(au['mean']), aup=au['n_positive'], ann=au['n']), "kind": "diseno"},
                  {"text": "UNDERPOWERED + TRADE-OFF + MECANISMO FALSO: (a) con N={n} seeds NO se puede reclamar significancia (t={aut}; sign-test tope p=0.125) -- la ventaja AUROC es real en SIGNO pero no en magnitud robusta; (b) el unlikelihood (cura 119) induce un TRADE-OFF generación/ranking (el durable genera menos correctas) -> 'decide mejor' se acota con 'genera menos'; (c) el mecanismo 'pico recall-crítico f=1' es FALSO -- el gap del payoff es máximo en f≈0.5 (trivial) y monótono-decreciente; el gate 'decision_driven' (se anula a f=4) era VACUO (4·#correctas>pool)".format(n=n_seeds, aut=au['tstat']), "kind": "diseno"},
                  {"text": "FRAMING + ALCANCE: 'sale del oráculo' es ACOTADO -- el verificador (oráculo) supervisa el self-train, etiqueta las generaciones y NORMALIZA la métrica; SÓLO el ranking de submission es endógeno. 'transfiere' es un ECO ATENUADO vs exp107 (+0.904 random-vs-best, escasez q=0.08; acá entre dos señales ya-positivas a ~44% correctas = abundancia). El régimen f≈1 se eligió POST-HOC. ALCANCE: sustrato CHICO (HybridLM ~200k), tarea ARITMÉTICA acotada ('N=a*b'), lazo STaR (no MDP secuencial), N=4, CPU. NO cubre: SCALE, verificador de dominio rico, lazo secuencial, lenguaje natural, N>=8", "kind": "fisico"}],
        real_or_assumed="real", evidence=[S_EXP124.ref, S_PRIOR.ref, S_VERIF.ref]))
    notes.append("1 techo 'real': primer intento de payoff decisional fuera del oráculo (decisión endógena + verificador real); ventaja de ranking AUROC modesta del durable PERO confundida con base-rate, underpowered a N=4, con trade-off de generación. Lección: controlar base-rate (AUROC/lift) + N.")

    dstmt = ("North-Star R-VALOR (SALIR DEL ORÁCULO: primer intento de aterrizar el payoff decisional fuera del numpy sintético, "
             "hueco #1 de la auditoría post-139): {V}. SOBREVIVE -- la DECISIÓN es endógena (ranking por confianza; el oráculo sólo "
             "mide) + verificador REAL; ventaja de RANKING base-rate-INVARIANTE del durable (AUROC {aud} vs {aun}, gap +{aum}, "
             "{aup}/{ann} seeds), MODESTA. NO ESTABLECIDO (retractado por verificación de 4 agentes): el titular precision@m estaba "
             "CONFUNDIDO con el base-rate (durable {ncd} vs naive {ncn} correctas); no significativo a N={n}; mecanismo 'pico f=1' "
             "falso; trade-off generación/ranking; framing sobre-vendido. Decisión: NO declarar el payoff decisional 'aterrizado' "
             "en el lazo real -- adoptar la LECCIÓN METODOLÓGICA (controlar base-rate con AUROC/lift, loguear el confound de ambos "
             "brazos, N>=8) y el paso real (decisión endógena + verificador real). META-DECISIÓN: 10mo ciclo con verificación "
             "adversarial (confound + mecanismo falso + framing). Próximo: re-correr con N>=8 + base-rate emparejado; SCALE.").format(
                 V=status.upper(), aud=_f(aud), aun=_f(aun), aum=_f(au['mean']), aup=au['n_positive'], ann=au['n'],
                 ncd=_f(ncd), ncn=_f(ncn), n=n_seeds)
    drat = ("exp124 (tier5, propio, {n} seeds, PyTorch CPU, lazo cerrado REAL, post-verificación de 4 agentes): la decisión es "
            "endógena + verificador real (paso real fuera del ρ-sintético) y hay una ventaja de ranking base-rate-invariante "
            "(AUROC) modesta del durable, PERO el titular precision@m estaba confundido con el base-rate, no es significativo a "
            "N=4, el mecanismo 'pico f=1' es falso, hay trade-off generación/ranking, y el framing estaba sobre-vendido. "
            "Convergente con el principio metodológico (tier2) y la verificación (tier4); contextualizado por exp106/exp107 "
            "(tier5). MIXTA: paso real + ventaja modesta + lección metodológica; el payoff decisional limpio NO se establece en el "
            "lazo real con N=4.").format(n=n_seeds)
    dec = Decision(id="D-V4-102", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP124), _to_plain(S_PRIOR), _to_plain(S_VERIF)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-102 ACEPTADA por el ledger (tier5 exp124 + tier5 exp107/exp106 + tier4 verificación adversarial).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-102:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle140_decisional_real_loop',
                                description='CYCLE 140 (RESET v4, H-V4-9g MIXTA: SALIR DEL ORÁCULO -- la decisión es endógena + verificador real y hay una ventaja de ranking AUROC modesta del durable, pero confundida con el base-rate, underpowered a N=4, con trade-off de generación; 10mo ciclo con verificación adversarial).')
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
    print("RESUMEN — CYCLE 140 (RESET v4): SALIR DEL ORÁCULO (primer intento, lazo torch real) — H-V4-9g " + (status.upper() if status else "?"))
    print("=" * 78)
    print("veredicto H-V4-9g:", status.upper() if status else "?")
    print("  SOBREVIVE: la decisión es ENDÓGENA (ranking por confianza; el oráculo sólo mide) + verificador REAL; ventaja de RANKING base-rate-INVARIANTE (AUROC) MODESTA del durable. NO ESTABLECIDO: el titular precision@m estaba CONFUNDIDO con el base-rate (la 1ra versión no logueaba el #correctas del naive); no significativo a N=4; mecanismo 'pico f=1' falso; trade-off generación/ranking; framing 'sale del oráculo'/'transfiere' sobre-vendido. Lección: controlar base-rate (AUROC/lift) + N suficiente.")
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
