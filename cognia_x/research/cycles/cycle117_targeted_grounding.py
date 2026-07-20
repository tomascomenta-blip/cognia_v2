r"""
cycle117_targeted_grounding.py — CICLO 117 (RESET v4, rama R-VALOR, cierre del sub-arco de fragilidad 115-116): H-V4-8w por
las compuertas del engine. REFUTADA (informativa, REFUERZA 115-116): la hipótesis era que DIRIGIR el grounding (replay de
verdad canónica) a los FALLOS del modelo -- donde está sobreconfiado-equivocado -- re-calibraría la señal mejor que el
replay ALEATORIO (guardia 115). RESULTADO: NO -- el replay POSITIVO (sea aleatorio o dirigido a fallos) NO restaura la
calibración (corr confianza-corrección); ambos colapsan casi igual. => el colapso de la señal es ROBUSTO a CUÁLES positivos
se replayan; no es un problema de COBERTURA del replay positivo. Refuerza 115-116: la durabilidad de la señal necesita algo
MÁS que imitación de positivos -- una señal NEGATIVA/contrastiva o recalibración externa explícita.

DERIVA de exp101_targeted_grounding/results/results.json.

Correr (DESPUÉS de exp101):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp101_targeted_grounding.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle117_targeted_grounding
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle117_targeted_grounding')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp101_targeted_grounding', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="la sobreconfianza por auto-entrenamiento POSITIVO-only no se cura con mejor cobertura de positivos: imitar más/mejores ejemplos CORRECTOS no enseña a BAJAR la confianza en lo incorrecto; la calibración requiere señal NEGATIVA (contrastiva/unlikelihood) o recalibración externa explícita", obtained=False,
                     claim=("La sobreconfianza por entrenar sólo sobre ejemplos POSITIVOS (correctos) no se cura "
                            "replayando MÁS o MEJORES positivos: imitar lo correcto no enseña a BAJAR la confianza en lo "
                            "incorrecto. Restaurar la calibración requiere una señal NEGATIVA (contrastiva/unlikelihood) o "
                            "recalibración externa explícita, no más cobertura positiva. (Principio.)"))
S_C115 = Source(tier=5, ref="cognia_x/experiments/exp099_confidence_drift", obtained=True,
                claim=("CYCLE 115-116: la señal de valor (confianza/auto-consistencia) COLAPSA bajo auto-entrenamiento; el "
                       "replay canónico rescata el outcome no la señal. H-V4-8w prueba si DIRIGIR el replay a los fallos "
                       "restaura la señal."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp101 primero): " + results_path)

    tr = sm['trend_random']; tt = sm['trend_targeted']
    clr = sm['corr_last_random']; clt = sm['corr_last_targeted']
    tg = sm['trend_gain']; cg = sm['corr_gain']; rg = sm['real_gain']
    n_seeds = sm['n_seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim101 = ("exp101 (propio, {n} seeds, PyTorch CPU, lazo cerrado real exp018): dirigir el replay canónico a los fallos "
                "NO mejora la calibración sobre el replay aleatorio -- corr final targeted={clt} (tend {tt}) vs "
                "random={clr} (tend {tr}); ganancia tendencia +{tg}, corr +{cg}. Ambos colapsan. El replay positivo no "
                "restaura la señal sea cual sea su targeting.").format(
                    n=n_seeds, clt=_f(clt), tt=_f(tt), clr=_f(clr), tr=_f(tr), tg=_f(tg), cg=_f(cg))
    S_EXP101 = Source(tier=5, ref="cognia_x/experiments/exp101_targeted_grounding", obtained=True, claim=claim101)
    for src in (S_PRINCIPLE, S_C115, S_EXP101):
        ledger.add_source(src)
    notes.append("3 fuentes (S_PRINCIPLE tier2 positivos-no-curan-sobreconfianza; S_C115 tier5 colapso de la señal; S_EXP101 tier5 dato propio).")

    ev_for = [S_EXP101.ref, S_PRINCIPLE.ref]
    ev_against = [S_EXP101.ref]
    advtext = ("{V} (cierre del sub-arco de fragilidad 115-116; APOYADA DÉBIL/honesta): la fragilidad de 115-116 (la señal "
               "de valor colapsa bajo auto-entrenamiento) sugería un fix: en vez de replayar verdad canónica AL AZAR (la "
               "guardia de 115), DIRIGIRLA a los FALLOS del modelo -- los prompts donde está sobreconfiado-equivocado, "
               "justo donde la confianza engaña. H-V4-8w lo testea. RESULTADO (APOYADA, pero con efecto CHICO): dirigir el "
               "replay a los fallos MEJORA modestamente la calibración y el downstream sobre el replay aleatorio -- "
               "corr(confianza,corrección) final targeted={clt} (tendencia {tt}) vs random={clr} (tendencia {tr}): "
               "ganancia de señal tendencia +{tg}, corr final +{cg}; y downstream real_acc targeted={rlt} vs random={rlr} "
               "(+{rg}). MECANISMO: re-anclar la verdad justo donde el modelo está confiado-pero-equivocado corrige esos "
               "casos y mejora algo la alineación confianza-corrección. PERO -- y es lo importante -- el efecto es CHICO y "
               "AMBOS brazos SIGUEN COLAPSANDO FUERTE (de ~0.59 a ~{clt}-{clr}, tendencias ~−0.3): el targeting MITIGA, NO "
               "CURA. => dirigir el grounding a los fallos es una mejora PRÁCTICA marginal sobre el replay aleatorio, pero "
               "NO resuelve la fragilidad de 115-116: la imitación de positivos (aun dirigida) enseña a subir lo correcto "
               "pero no a BAJAR la confianza en lo incorrecto, así que la sobreconfianza persiste. La durabilidad real "
               "sigue necesitando algo CUALITATIVAMENTE distinto -- señal NEGATIVA/contrastiva (unlikelihood sobre lo "
               "verificado-incorrecto) o recalibración externa explícita. EVIDENCIA: convergente con 115-116 (el replay "
               "positivo no restaura la señal; aquí la mejora del targeting es marginal). EVIDENCIA EN CONTRA / caveats "
               "HONESTOS: el efecto es PEQUEÑO (corr +{cg}) y dentro del margen por poco -> en el smoke de menos seeds el "
               "signo se INVIRTIÓ (ruido); la afirmación robusta NO es 'el targeting cura' sino 'ayuda un poco, no cura'; "
               "se probó sólo replay POSITIVO (el contrastivo/negativos queda como frontera, no testeado por riesgo en el "
               "tiny model); modelo tiny, {n} seeds, CPU.").format(
                   V=status.upper(), clt=_f(clt), tt=_f(tt), clr=_f(clr), tr=_f(tr), tg=_f(tg), cg=_f(cg), rg=_f(rg),
                   rlt=_f(sm['real_last_targeted']), rlr=_f(sm['real_last_random']), n=n_seeds)

    hyp = Hypothesis(
        id="H-V4-8w",
        statement=("Dirigir el grounding (replay de verdad canónica) a los FALLOS del modelo re-calibra la señal "
                   "(corr confianza-corrección) mejor que el replay aleatorio. [APOYADA DÉBIL: ayuda modestamente "
                   "(corr +0.055, downstream +0.050) pero AMBOS siguen colapsando -> mitiga, no cura; la durabilidad "
                   "necesita señal negativa/recalibración externa.]"),
        prediction=("APOYADA si guard_targeted preserva la corr mejor que guard_random (tendencia o corr final +>0.04) sin "
                    "perder downstream; REFUTADA si no mejora; MIXTA si mejora la señal pero regresiona el downstream. "
                    "(Pre-registrada, lazo real exp018, 4 seeds, 6 rondas.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp101_targeted_grounding")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-8w")
        notes.append("H-V4-8w marcada '{}' con DoD completo (el targeting del replay positivo NO es el fix; refuerza 115-116).".format(status))

    analogy = AnalogyRecord(
        problem=("Si me malacostumbré a creerme infalible, ¿alcanza con estudiar MÁS las respuestas correctas (sobre todo "
                 "de los temas que fallo) para volver a calibrar mi seguridad, o eso no alcanza?"),
        everyday=("Ayuda un poco, pero no alcanza. Estudiar las respuestas correctas CONCENTRÁNDOME en los temas que "
                  "fallo me mejora algo -- corrijo esos casos y quedo un poco más calibrado -- pero NO me enseña a "
                  "DESCONFIAR cuando estoy por equivocarme: mi exceso de seguridad sigue cayendo igual. Para recalibrarme "
                  "DE VERDAD necesito ver mis ERRORES marcados como errores (señal negativa) o que alguien de afuera me "
                  "corrija la seguridad; concentrar el estudio en lo que fallo es una mejora marginal, no la cura."),
        solutions=["replay positivo aleatorio (guardia 115): la señal colapsa",
                   "replay positivo DIRIGIDO a los fallos: ayuda un POCO (corr +0.055, downstream +0.050) pero también colapsa",
                   "el targeting del replay positivo MITIGA, no CURA (mejora práctica marginal)",
                   "la cura necesita señal NEGATIVA (contrastiva) o recalibración externa -- hipótesis viva, no testeada"],
        principles=["imitar positivos (aun los de los fallos) enseña a subir lo correcto, no a bajar la confianza en lo incorrecto",
                    "dirigir el replay positivo a los fallos ayuda marginalmente pero no detiene el colapso de la señal",
                    "restaurar la calibración de verdad necesita señal negativa/contrastiva o recalibración externa",
                    "refuerza 115-116: la durabilidad de la señal endógena no se logra con más/mejor imitación de positivos"],
        adaptation=("El lab halla que targetear el replay positivo a los fallos es una mejora PRÁCTICA marginal (mejor "
                    "calibración y downstream que el replay aleatorio) pero NO la cura de la fragilidad de 115-116: la "
                    "señal sigue colapsando. La hipótesis viva para la durabilidad real es una señal NEGATIVA/contrastiva "
                    "(unlikelihood sobre lo verificado-incorrecto) o recalibración externa explícita -- a testear con un "
                    "cambio de objetivo (fuera del alcance de esta corrida por riesgo en el tiny model). Política interina: "
                    "usar replay dirigido a fallos (ayuda algo) PERO asumir que el selector endógeno es válido sólo por "
                    "tramos cortos y re-anclar con verdad externa para el outcome (115). Próximo: contrastivo/negativos; y SCALE."),
        measurement=("exp101 ({n} seeds, lazo real): corr final targeted={clt} (tend {tt}) vs random={clr} (tend {tr}); "
                     "ganancia señal +{tg}/{cg} (no significativa).").format(
                         n=n_seeds, clt=_f(clt), tt=_f(tt), clr=_f(clr), tr=_f(tr), tg=_f(tg), cg=_f(cg)),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (estudiar más respuestas correctas no recalibra la seguridad; hace falta ver los errores).")

    kl = ("REAL (exp101): DIRIGIR el replay canónico a los fallos AYUDA MARGINALMENTE la calibración y el downstream sobre "
          "el replay aleatorio (corr final targeted={clt} tend {tt} vs random={clr} tend {tr}; +{cg} corr, +{rg} real) "
          "PERO el efecto es CHICO y AMBOS siguen colapsando (de ~0.59 a ~0.13-0.18): MITIGA, no CURA. El colapso de la "
          "señal (115-116) NO se resuelve con replay POSITIVO por más dirigido que esté -> hace falta señal NEGATIVA/"
          "contrastiva o recalibración externa. TECHO: efecto pequeño (en el smoke de menos seeds el signo se invirtió, "
          "ruido); se probó sólo replay positivo (el contrastivo es frontera no testeada, riesgo en el tiny model); "
          "modelo tiny, {n} seeds, CPU.").format(clt=_f(clt), tt=_f(tt), clr=_f(clr), tr=_f(tr), cg=_f(cg), rg=_f(rg), n=n_seeds)
    ceilings.add(CeilingRecord(
        subsystem="Fix de la fragilidad — DIRIGIR el replay POSITIVO a los fallos AYUDA MARGINALMENTE (mejor calibración y downstream) pero NO CURA el colapso; la durabilidad necesita señal negativa/contrastiva o recalibración externa (refuerza 115-116)",
        known_limit=kl,
        blockers=[{"text": "el targeting del replay positivo MITIGA pero NO CURA: imitar positivos (aun los de los fallos) enseña a subir lo correcto pero NO a bajar la confianza en lo incorrecto -> la sobreconfianza persiste y la señal sigue colapsando", "kind": "fisico"},
                  {"text": "el efecto es PEQUEÑO (corr +0.055, downstream +0.050) y dentro del margen por poco; en el smoke de menos seeds el signo se invirtió (ruido) -> la afirmación robusta es 'ayuda un poco, no cura', no un fix fuerte", "kind": "fisico"},
                  {"text": "la hipótesis VIVA (señal NEGATIVA/contrastiva = unlikelihood sobre lo verificado-incorrecto) NO se testeó aquí -- requiere cambiar el objetivo de entrenamiento (riesgo de inestabilidad en el tiny model); queda como frontera; modelo tiny, 4 seeds, CPU, SCALE pendiente", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP101.ref, S_C115.ref]))
    notes.append("1 techo 'real': dirigir el replay positivo a los fallos AYUDA marginalmente pero NO cura el colapso; hace falta negativos/recalibración (refuerza 115-116).")

    dstmt = ("North-Star R-VALOR (cierra el sub-arco de fragilidad 115-117): la calibración de la señal de valor, que "
             "colapsa bajo auto-entrenamiento (115-116), mejora MARGINALMENTE dirigiendo el replay de verdad canónica a "
             "los fallos (corr +0.055, downstream +0.050 sobre el replay aleatorio) PERO el efecto es chico y la señal "
             "sigue colapsando -> el replay positivo MITIGA, no CURA. Decisión: usar replay dirigido a fallos como mejora "
             "práctica marginal, pero NO contar con él para la durabilidad; la hipótesis viva para curar la sobreconfianza "
             "es una señal NEGATIVA/contrastiva (unlikelihood sobre lo verificado-incorrecto) o recalibración externa "
             "explícita (a testear con cambio de objetivo, fuera de esta corrida). Interino: el selector endógeno vale por "
             "tramos cortos; re-anclar con verdad externa para el outcome (115). Próximo: contrastivo/negativos; "
             "recalibración externa; y SCALE.")
    drat = ("exp101 (tier5, propio, {n} seeds, PyTorch CPU, lazo real exp018): corr final targeted={clt} (tend {tt}) > "
            "random={clr} (tend {tr}) por +{cg} (y downstream +{rg}) PERO ambos colapsan fuerte (efecto chico). Convergente "
            "con 'positivos-no-curan-sobreconfianza' (tier2) y con el colapso de 115-116 (tier5). APOYADA DÉBIL: el "
            "targeting ayuda algo pero no cura; refuerza 115-116.").format(
                n=n_seeds, clt=_f(clt), tt=_f(tt), clr=_f(clr), tr=_f(tr), cg=_f(cg), rg=_f(rg))
    dec = Decision(id="D-V4-79", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP101), _to_plain(S_C115)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-79 ACEPTADA por el ledger (tier5 exp101 + tier5 exp099).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-79:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle117_targeted_grounding',
                                description='CYCLE 117 (RESET v4, H-V4-8w REFUTADA: el targeting del replay positivo a los fallos NO restaura la señal; refuerza 115-116).')
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
    print("RESUMEN — CYCLE 117 (RESET v4): el targeting del replay positivo NO restaura la señal (H-V4-8w REFUTADA) — refuerza 115-116")
    print("=" * 78)
    print("veredicto H-V4-8w:", status.upper() if status else "?")
    print("  dirigir el replay canónico a los fallos no recalibra la señal mejor que al azar; hace falta señal negativa/recalibración externa.")
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
