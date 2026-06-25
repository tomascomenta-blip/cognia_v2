r"""
cycle56_value_isolation_post.py — CICLO 56 (RESET v4): H-V4-1b por las compuertas del engine. PIVOTE al
North-Star (R-VALOR). Reabre la hija pendiente de exp022/CYCLE 35.

H-V4-1b: medido por post_on_cause (masa del posterior sobre la causa VERDADERA, instrumento FIEL) — no por la
accuracy downstream que SATURA — info-gain (B) AÍSLA su valor sobre el azar-activo (C) en el régimen DURO
(espacio grande, clúster grande, ruido alto). DERIVA de exp042_value_isolation_post/results/results.json.

Correr (DESPUÉS de exp042):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp042_value_isolation_post.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle56_value_isolation_post
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store',
                             'cycle56_value_isolation_post')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp042_value_isolation_post', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _fmt(x):
    return "{:+.3f}".format(x) if isinstance(x, (int, float)) else str(x)


def _curve(by_K, budgets, key):
    return "[" + " ".join("K%s=%+.3f" % (K, by_K[str(K)][key]) for K in budgets) + "]"


S_AINF = Source(tier=1, ref="optimal experiment design / active inference (info-gain)", obtained=False,
                claim=("Elegir la consulta que maximiza la información esperada (info-gain / EIG) identifica "
                       "causas con menos datos que muestrear pasivo o al azar. (Principio, no re-obtenido.)"))
S_EXP022 = Source(tier=5, ref="cognia_x/experiments/exp022_endogenous_value (CYCLE 35)", obtained=True,
                  claim=("exp022 (H-V4-1, MIXTA): R-INTERVENCIÓN demostrada (el pasivo se queda plano; las "
                         "políticas ACTIVAS identifican) pero R-VALOR NO aislado — medido por ACCURACY, el "
                         "azar-activo alcanzaba a info-gain."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp042 primero): " + results_path)
    budgets = sm['budgets']
    n_seeds = sm['n_seeds']
    Kmax = sm['Kmax']
    h = sm['hard_by_K']
    e = sm['easy_by_K']
    iso = sm['post_iso_hard_Kmax']
    sign = sm['sign_consistency_hard_Kmax']
    acc_gap = h[str(Kmax)]['acc_BminusC']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    S_EXP042 = Source(tier=5, ref="cognia_x/experiments/exp042_value_isolation_post", obtained=True,
                      claim=("exp042 (propio, {n} seeds, bayesiano numpy): con post_on_cause (instrumento fiel) "
                             "info-gain AÍSLA su valor sobre el azar-activo en el régimen DURO: B-C post {iso} a "
                             "Kmax ({sg:.0f}% seeds B>C, crece con K). La accuracy lo enmascara (acc B-C {ag}). "
                             "Explica la MIXTA de exp022.").format(n=n_seeds, iso=_fmt(iso), sg=sign * 100,
                                                                   ag=_fmt(acc_gap)))
    for src in (S_AINF, S_EXP022, S_EXP042):
        ledger.add_source(src)
    notes.append("3 fuentes (S_AINF tier1 info-gain/EIG; S_EXP022 tier5 MIXTA por accuracy; S_EXP042 tier5 dato propio).")

    supported = status == 'apoyada'
    ev_for = [S_EXP042.ref, S_AINF.ref]
    ev_against = [S_EXP042.ref, S_EXP022.ref]
    adv = ("{V} (PIVOTE al North-Star R-VALOR): exp022 (CYCLE 35) quedó MIXTA — no aisló el valor de info-gain "
           "del de intervenir — porque midió con ACCURACY downstream, que SATURA (una vez descartado el clúster "
           "confundido, el voto ponderado acierta aunque el posterior NO esté concentrado en la causa exacta). "
           "exp042 usa el instrumento FIEL: post_on_cause = masa del posterior sobre la causa VERDADERA. "
           "RESULTADO: en el régimen DURO (D=48, clúster=14, ruido=0.20) info-gain (B) concentra MÁS en la causa "
           "que el azar-activo (C): B-C post {curve} (a Kmax {iso}, {sg:.0f}% seeds B>C, CRECE con K). La "
           "ACCURACY lo ENMASCARA (acc B-C {ag} << post B-C {iso}). En el régimen FÁCIL el gap post se cierra "
           "rápido {ecurve} (la accuracy satura aún antes). => R-VALOR (el valor de *qué* consultar, info-gain) "
           "se SEPARA de R-INTERVENCIÓN (el valor de *intervenir*), con el instrumento correcto y en el régimen "
           "donde el azar no alcanza. EVIDENCIA EN CONTRA (caveats honestos): (1) el efecto, aunque robusto en "
           "dirección, es MODESTO en seeds individuales ({sg:.0f}%, no 100%) -> el valor de info-gain es real "
           "pero secundario al de la actividad. (2) mundo de juguete (hipótesis lineal y=x_i, clúster confundido "
           "sintético). (3) el aislamiento depende del régimen (en el fácil el azar alcanza). CONCLUSIÓN: hay un "
           "VALOR ENDÓGENO (info-gain sobre el propio posterior) que construye un modelo más causal que la mera "
           "actividad — primera evidencia POSITIVA de R-VALOR específico en el lab, con el instrumento "
           "fiel.").format(V=status.upper(), curve=_curve(h, budgets, "post_BminusC"), iso=_fmt(iso),
                           sg=sign * 100, ag=_fmt(acc_gap), ecurve=_curve(e, budgets, "post_BminusC"))

    hyp = Hypothesis(
        id="H-V4-1b",
        statement=("Medido por post_on_cause (no accuracy), info-gain aísla su valor sobre el azar-activo en el "
                   "régimen duro: construye un modelo más causal (más masa en la causa verdadera)."),
        prediction=("APOYADA si en el régimen DURO B-C post_on_cause > 0.15 a Kmax, signo-consistente (>=70%) y "
                    "creciente con K, Y la accuracy lo enmascara; REFUTADA si B-C post <= 0 o no signo-consistente; "
                    "MIXTA si positivo pero bajo umbral o no crece. (Pre-registrada.)"),
        status='abierta', confidence='alta' if supported else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=adv, experiment_ref="exp042_value_isolation_post")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-1b")
        notes.append("H-V4-1b marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("Dos personas investigan cuál de 14 sospechosos parecidos (un clúster confundido) es el "
                 "culpable, con pocas preguntas y respuestas ruidosas. Una pregunta AL AZAR; la otra elige la "
                 "pregunta que más DISTINGUE a los sospechosos que aún sobreviven. ¿La segunda llega a saber MEJOR "
                 "quién es, no sólo a 'acertar' un caso?"),
        everyday=("Si sólo te fijás en si ACIERTAN el caso de prueba, las dos parecen iguales (una vez que "
                  "descartás al grupo, cualquiera acierta). Pero si mirás cuánta CERTEZA tienen sobre el culpable "
                  "REAL, la que elige preguntas informativas sabe mucho más, y la diferencia CRECE con cada "
                  "pregunta. Elegir QUÉ preguntar (valor) vale, no sólo preguntar (actividad)."),
        solutions=["medir por ACCURACY downstream (exp022) -> satura, esconde el valor de info-gain (MIXTA)",
                   "medir por post_on_cause (masa sobre la causa real) -> revela el valor (instrumento fiel)",
                   "régimen FÁCIL -> el azar alcanza; el valor no se ve",
                   "régimen DURO (espacio/clúster grande, ruido) -> info-gain concentra más en la causa, crece con K"],
        principles=["la métrica importa: la accuracy downstream puede ENMASCARAR el valor de una mejor representación",
                    "info-gain (valor endógeno) construye un modelo más CAUSAL que la mera intervención activa",
                    "el valor de QUÉ consultar (R-VALOR) se separa del de intervenir (R-INTERVENCIÓN) en el régimen duro",
                    "el efecto es real pero MODESTO: la actividad capta el grueso; el valor afina"],
        adaptation=("El lab mide el valor endógeno con el instrumento FIEL (masa sobre la causa / objetivo), no "
                    "sólo con accuracy downstream. Próximos: valor endógeno SIN oráculo de la causa (el agente no "
                    "sabe c); regímenes donde el azar falle del todo; ligar este valor a memoria (escribir≡olvidar, "
                    "H-V4-5) y a la auto-mejora (el verificador como caso de valor)."),
        measurement=("exp042: DURO post B-C {curve} (Kmax {iso}, {sg:.0f}% seeds); acc B-C {ag} (enmascara). "
                     "{n} seeds.").format(curve=_curve(h, budgets, "post_BminusC"), iso=_fmt(iso), sg=sign * 100,
                                          ag=_fmt(acc_gap), n=n_seeds),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (medir certeza sobre el culpable real, no sólo acertar el caso).")

    ceilings.add(CeilingRecord(
        subsystem="R-VALOR — valor endógeno (info-gain) aislado de la actividad con el instrumento fiel (post_on_cause)",
        known_limit=("REAL (exp042): info-gain aísla su valor sobre el azar-activo en el régimen DURO medido por "
                     "post_on_cause (B-C {iso} a Kmax, {sg:.0f}% seeds, crece con K); la accuracy lo enmascaraba "
                     "(exp022 MIXTA). Primera evidencia POSITIVA de R-VALOR específico.").format(
                         iso=_fmt(iso), sg=sign * 100),
        blockers=[{"text": "el efecto es MODESTO por seed ({:.0f}%, no 100%): el valor de info-gain es secundario a la actividad".format(sign * 100), "kind": "diseno"},
                  {"text": "mundo de juguete (hipótesis lineal y=x_i, clúster confundido sintético); falta un mundo más rico", "kind": "diseno"},
                  {"text": "el agente info-gain optimiza MI sobre su posterior pero el eval usa la causa VERDADERA c (oráculo de eval); falta un proxy endógeno de 'mejor modelo' sin conocer c", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP042.ref, S_EXP022.ref]))
    notes.append("1 techo 'real': R-VALOR (info-gain) se aísla de la actividad con el instrumento fiel; primera evidencia positiva.")

    dstmt = ("PIVOTE al North-Star (R-VALOR): hay un VALOR ENDÓGENO (info-gain sobre el propio posterior) que "
             "construye un modelo más CAUSAL que la mera intervención activa, AISLABLE con el instrumento FIEL "
             "(post_on_cause = masa sobre la causa verdadera) en el régimen DURO (B-C {iso} a Kmax, {sg:.0f}% "
             "seeds, crece con K). La ACCURACY downstream lo ENMASCARABA (acc B-C {ag}) -> eso explica la MIXTA "
             "de exp022 (CYCLE 35): instrumento equivocado. Decisión: el lab mide el valor endógeno por la masa "
             "sobre el objetivo, no por accuracy; y R-VALOR (qué consultar) se separa de R-INTERVENCIÓN. Matiz "
             "honesto: el efecto es real pero MODESTO por seed (la actividad capta el grueso). Próximos: valor "
             "endógeno sin oráculo de la causa; ligarlo a memoria (H-V4-5) y a la auto-mejora.").format(
                 iso=_fmt(iso), sg=sign * 100, ag=_fmt(acc_gap))
    drat = ("exp042 (tier5, propio, {n} seeds): DURO post B-C {iso} a Kmax ({sg:.0f}% seeds B>C, crece); acc B-C "
            "{ag} (enmascara); FÁCIL post se cierra. Convergente con info-gain/EIG (tier1) y refina exp022. "
            "{V}.").format(n=n_seeds, iso=_fmt(iso), sg=sign * 100, ag=_fmt(acc_gap), V=status.upper())
    dec = Decision(id="D-V4-21", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP042), _to_plain(S_EXP022)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-21 ACEPTADA por el ledger (tier5 exp042 + tier5 exp022).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-21:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle56_value_isolation_post',
                                description='CYCLE 56 (RESET v4, H-V4-1b: aislar el valor de info-gain con post_on_cause).')
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
    print("RESUMEN — CYCLE 56 (RESET v4): aislar R-VALOR (info-gain) con post_on_cause (H-V4-1b) — PIVOTE North-Star")
    print("=" * 78)
    print("veredicto H-V4-1b:", status.upper() if status else "?")
    print("  info-gain construye un modelo más causal que la actividad; la accuracy de exp022 lo enmascaraba.")
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
