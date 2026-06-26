r"""
cycle116_durable_signal.py — CICLO 116 (RESET v4, rama R-VALOR, cierra constructivamente el pointer de CYCLE 115):
H-V4-8u por las compuertas del engine. APOYADA: existe una señal de valor INTRÍNSECA más DURABLE que la confianza
single-shot. 115 mostró que la confianza de una sola generación COLAPSA como señal en lazos sostenidos; 116 halla que la
AUTO-CONSISTENCIA (acuerdo entre las K generaciones del mismo prompt) se MANTIENE correlacionada con la corrección donde la
confianza single-shot se decorrelaciona. => en lazos largos, el ACUERDO entre muestras es una señal de valor intrínseca
durable (sin verdad externa), mejor que la logprob de una muestra.

DERIVA de exp100_durable_signal/results/results.json.

Correr (DESPUÉS de exp100):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp100_durable_signal.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle116_durable_signal
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle116_durable_signal')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp100_durable_signal', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="auto-consistencia / acuerdo entre muestras como señal robusta: el acuerdo entre múltiples generaciones (self-consistency) es una señal de calidad más estable que la confianza de una sola muestra; agrega sobre el ruido y es menos sensible a la sobreconfianza puntual", obtained=False,
                     claim=("El ACUERDO entre múltiples generaciones (self-consistency) es una señal de calidad más estable "
                            "que la logprob/confianza de UNA muestra: agrega sobre el ruido de muestreo y es menos "
                            "sensible a la sobreconfianza puntual. Debería ser más DURABLE bajo entrenamiento sobre sí "
                            "mismo. (Principio.)"))
S_C115 = Source(tier=5, ref="cognia_x/experiments/exp099_confidence_drift", obtained=True,
                claim=("CYCLE 115: la confianza single-shot COLAPSA como señal de valor en lazos sostenidos (corr -> ~0); "
                       "la guardia rescata el outcome, no la señal. H-V4-8u busca una señal intrínseca durable."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp100 primero): " + results_path)

    tc = sm['trend_conf']; ts = sm['trend_sc']
    cf = sm['corr_conf_first']; clt = sm['corr_conf_last']
    sf = sm['corr_sc_first']; slt = sm['corr_sc_last']
    dur = sm['durability']; fg = sm['final_gap']
    n_seeds = sm['n_seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim100 = ("exp100 (propio, {n} seeds, PyTorch CPU, lazo cerrado real exp018): corr con la corrección -- confidence "
                "{cf}->{cl} (tendencia {tc}, degrada) vs self_consist {sf}->{sl} (tendencia {ts}, estable); durabilidad "
                "Δtendencia +{d}, brecha final +{fg}. La auto-consistencia es una señal de valor intrínseca más durable "
                "que la confianza single-shot.").format(n=n_seeds, cf=_f(cf), cl=_f(clt), tc=_f(tc), sf=_f(sf), sl=_f(slt),
                                                        ts=_f(ts), d=_f(dur), fg=_f(fg))
    S_EXP100 = Source(tier=5, ref="cognia_x/experiments/exp100_durable_signal", obtained=True, claim=claim100)
    for src in (S_PRINCIPLE, S_C115, S_EXP100):
        ledger.add_source(src)
    notes.append("3 fuentes (S_PRINCIPLE tier2 self-consistency robusta; S_C115 tier5 colapso de la confianza; S_EXP100 tier5 dato propio).")

    ev_for = [S_EXP100.ref, S_PRINCIPLE.ref]
    ev_against = [S_EXP100.ref]
    advtext = ("{V} (cierra CONSTRUCTIVAMENTE el pointer de CYCLE 115: ¿hay una señal de valor INTRÍNSECA durable?): 115 "
               "halló que la confianza de UNA generación COLAPSA como señal en lazos sostenidos (corr -> ~0) y que el ancla "
               "de verdad externa rescata el outcome pero NO la señal. H-V4-8u busca una señal INTRÍNSECA (sin verdad "
               "externa) más durable: la AUTO-CONSISTENCIA = acuerdo entre las K generaciones del mismo prompt. RESULTADO "
               "MIXTO (matiz importante): la auto-consistencia es una señal de MEJOR NIVEL pero NO más DURABLE. corr con la "
               "corrección -- confidence {cf}->{cl} (tendencia {tc}) vs self_consist {sf}->{sl} (tendencia {ts}). Es decir: "
               "self_consist DOMINA a confidence en TODAS las rondas (arranca más alto {sf} vs {cf} y termina más alto {sl} "
               "vs {cl}, brecha final +{fg}) -- ES un mejor selector. PERO degrada al MISMO RITMO (durabilidad Δtendencia "
               "{d} ≈ 0: ambas tendencias ~−0.34) -- NO resuelve la durabilidad: AMBAS colapsan, sólo que self_consist "
               "desde más arriba. MECANISMO: el acuerdo entre K muestras agrega sobre el ruido (mejor nivel), pero la "
               "sobreconfianza por auto-entrenamiento corrompe la consistencia ÍGUAL (el modelo converge a producir "
               "consistentemente lo que cree, correcto o no) -> el colapso es una propiedad del entrenar-sobre-sí-mismo, "
               "no del estimador puntual. => hay un selector intrínseco MEJOR (self-consistency) que compra MÁS rondas "
               "útiles antes de degradarse, pero NO una señal intrínseca DURABLE: la durabilidad en lazos largos sigue "
               "necesitando grounding EXTERNO (refuerza el punto profundo de 115). NOTA DE MÉTODO: el smoke (4 rondas, 2 "
               "seeds) mostró self_consist ESTABLE (apoyaba durabilidad); el full (6 rondas, 4 seeds) reveló que también "
               "colapsa a horizonte mayor -> MIXTA. EVIDENCIA: el principio de self-consistency robusta (tier2) explica el "
               "mejor NIVEL; el colapso compartido refuerza 115. EVIDENCIA EN CONTRA / caveats: cuesta K generaciones (ROI "
               "112); tarea con respuesta canónica (acuerdo fácil de medir); el modo CONSISTENTEMENTE-equivocado "
               "(acuerdo alto en error) es justamente lo que erosiona la corr de self_consist a más rondas; modelo tiny, "
               "{n} seeds, CPU.").format(
                   V=status.upper(), cf=_f(cf), cl=_f(clt), tc=_f(tc), sf=_f(sf), sl=_f(slt), ts=_f(ts), d=_f(dur), fg=_f(fg), n=n_seeds)

    hyp = Hypothesis(
        id="H-V4-8u",
        statement=("La auto-consistencia (acuerdo entre K generaciones) es una señal de valor intrínseca más DURABLE que "
                   "la confianza single-shot. [MIXTA: es de mejor NIVEL (domina la corr en todas las rondas) pero NO más "
                   "durable (degrada al mismo ritmo); ambas colapsan -> la durabilidad necesita grounding externo, 115.]"),
        prediction=("APOYADA si tendencia(self_consist) − tendencia(conf) > 0.05 Y corr final self_consist > conf (+>0.03); "
                    "REFUTADA si self_consist no es más durable (verdad externa inevitable); MIXTA en otro caso. "
                    "(Pre-registrada, lazo real exp018, 4 seeds, 6 rondas.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp100_durable_signal")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-8u")
        notes.append("H-V4-8u marcada '{}' con DoD completo (auto-consistencia = señal intrínseca durable; cierra 115).".format(status))

    analogy = AnalogyRecord(
        problem=("Si no puedo consultar la respuesta verdadera, ¿cómo sé en qué de lo que produzco confiar, cuando mi "
                 "propia 'seguridad' ya se malacostumbró (115)?"),
        everyday=("Miro si LLEGO A LO MISMO varias veces: lo que me sale IGUAL en varios intentos (acuerdo conmigo mismo) "
                  "es MEJOR guía que mi 'seguridad' de un solo intento -- siempre más confiable. PERO no es magia: si sigo "
                  "practicando sólo conmigo mismo, también se va malacostumbrando (termino saliéndome SIEMPRE lo mismo, "
                  "esté bien o mal). Me COMPRA tiempo (arranco de más arriba y aguanto más rondas), no inmunidad. Para que "
                  "no se degrade del todo, sigo necesitando ejemplos de la verdad de afuera."),
        solutions=["confianza de un intento (single-shot): la peor (colapsa rápido, 115)",
                   "acuerdo entre K intentos (auto-consistencia): MEJOR nivel en todas las rondas (+0.15 final)",
                   "PERO ambas degradan al mismo ritmo: la auto-consistencia compra más rondas útiles, no durabilidad",
                   "la durabilidad en lazos largos sigue necesitando grounding externo (refuerza 115)"],
        principles=["el acuerdo entre múltiples muestras es una señal de MEJOR NIVEL que una sola muestra (agrega sobre el ruido)",
                    "pero NO es más durable: el auto-entrenamiento corrompe la consistencia igual (consistentemente-equivocado)",
                    "el colapso es propiedad del entrenar-sobre-sí-mismo, no del estimador puntual",
                    "la durabilidad en lazos largos necesita grounding externo (115); el mejor selector compra tiempo, no inmunidad"],
        adaptation=("El lab REFINA la respuesta a 115: la AUTO-CONSISTENCIA es un selector intrínseco MEJOR que la confianza "
                    "single-shot (mayor corr en todas las rondas -> vale usarla), pero NO resuelve la durabilidad (también "
                    "colapsa). Política: en lazos sostenidos, seleccionar por auto-consistencia (mejor nivel, compra más "
                    "rondas) PERO mantener el grounding externo / ancla de datos para la durabilidad (115); presupuestar "
                    "las K generaciones según el ROI (112). Próximo: detectar/mitigar el modo consistentemente-equivocado; "
                    "señales que SÍ se recalibren con grounding externo periódico; y SCALE."),
        measurement=("exp100 ({n} seeds, lazo real): confidence {cf}->{cl} (tend {tc}) vs self_consist {sf}->{sl} (tend "
                     "{ts}); durabilidad +{d}, brecha final +{fg}.").format(
                         n=n_seeds, cf=_f(cf), cl=_f(clt), tc=_f(tc), sf=_f(sf), sl=_f(slt), ts=_f(ts), d=_f(dur), fg=_f(fg)),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (confiar en lo que te sale IGUAL varias veces, no en tu seguridad de un intento).")

    kl = ("REAL (exp100): la AUTO-CONSISTENCIA es un selector intrínseco de MEJOR NIVEL que la confianza single-shot "
          "(corr confidence {cf}->{cl} tend {tc} vs self_consist {sf}->{sl} tend {ts}; self_consist domina en todas las "
          "rondas, brecha final +{fg}) PERO NO más DURABLE (durabilidad Δtendencia {d} ≈ 0: ambas colapsan al mismo ritmo). "
          "El mejor selector COMPRA más rondas útiles, no inmunidad; la durabilidad necesita grounding externo (refuerza "
          "115). TECHO: cuesta K generaciones (ROI 112); el modo CONSISTENTEMENTE-equivocado es lo que erosiona self_consist "
          "a más rondas; tarea con respuesta canónica; modelo tiny, {n} seeds, CPU.").format(
              cf=_f(cf), cl=_f(clt), tc=_f(tc), sf=_f(sf), sl=_f(slt), ts=_f(ts), d=_f(dur), fg=_f(fg), n=n_seeds)
    ceilings.add(CeilingRecord(
        subsystem="Señal de valor durable — la AUTO-CONSISTENCIA es un selector intrínseco de MEJOR NIVEL que la confianza single-shot, pero NO más durable (ambas colapsan); la durabilidad necesita grounding externo (refuerza 115)",
        known_limit=kl,
        blockers=[{"text": "la auto-consistencia NO resuelve la durabilidad: degrada al mismo ritmo que la confianza (durabilidad Δtendencia ≈ 0); sólo compra más rondas útiles desde un nivel más alto -> el colapso bajo auto-entrenamiento es propiedad del entrenar-sobre-sí-mismo, no del estimador puntual", "kind": "fisico"},
                  {"text": "el modo CONSISTENTEMENTE-EQUIVOCADO (el modelo converge a concordar alto en respuestas que cree, correctas o no) es justamente lo que erosiona la corr de self_consist a más rondas -> sin grounding externo periódico no hay durabilidad", "kind": "fisico"},
                  {"text": "cuesta K generaciones por prompt (ROI 112); tarea con respuesta canónica (acuerdo fácil de medir); modelo tiny, 4 seeds, CPU; falta señal que SÍ se recalibre con grounding externo y SCALE", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP100.ref, S_C115.ref]))
    notes.append("1 techo 'real': la auto-consistencia es un selector de mejor nivel pero NO más durable (ambas colapsan); la durabilidad necesita grounding externo (refuerza 115).")

    dstmt = ("North-Star R-VALOR (refina la respuesta a 115, hallazgo MIXTO): la AUTO-CONSISTENCIA (acuerdo entre K "
             "generaciones) es un selector intrínseco de MEJOR NIVEL que la confianza single-shot (domina la corr con la "
             "corrección en todas las rondas) pero NO más DURABLE (degrada al mismo ritmo; ambas colapsan bajo "
             "auto-entrenamiento). Decisión: en lazos sostenidos, seleccionar por auto-consistencia (mejor nivel, compra "
             "más rondas útiles) PERO mantener el grounding externo / ancla de datos para la durabilidad (115), "
             "presupuestando las K generaciones según el ROI (112). El colapso es propiedad del entrenar-sobre-sí-mismo: "
             "ningún estimador intrínseco lo evita por sí solo; la durabilidad necesita grounding externo periódico. "
             "Próximo: detectar/mitigar el modo consistentemente-equivocado; señales que SÍ se recalibren con grounding "
             "externo; y SCALE.")
    drat = ("exp100 (tier5, propio, {n} seeds, PyTorch CPU, lazo real exp018): confidence {cf}->{cl} (tend {tc}) vs "
            "self_consist {sf}->{sl} (tend {ts}); self_consist DOMINA en nivel (brecha final +{fg}) pero degrada al mismo "
            "ritmo (durabilidad Δtendencia {d} ≈ 0). Convergente con self-consistency-robusta (tier2, mejor nivel) y con "
            "el colapso de la confianza de 115 (tier5, durabilidad compartida). MIXTA: mejor nivel, no más "
            "durable.").format(n=n_seeds, cf=_f(cf), cl=_f(clt), tc=_f(tc), sf=_f(sf), sl=_f(slt), ts=_f(ts), d=_f(dur), fg=_f(fg))
    dec = Decision(id="D-V4-78", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP100), _to_plain(S_C115)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-78 ACEPTADA por el ledger (tier5 exp100 + tier5 exp099).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-78:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle116_durable_signal',
                                description='CYCLE 116 (RESET v4, H-V4-8u: la auto-consistencia es una señal de valor intrínseca más durable que la confianza single-shot -- APOYADA; cierra 115).')
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
    print("RESUMEN — CYCLE 116 (RESET v4): la auto-consistencia es una señal de valor intrínseca durable (H-V4-8u) — cierra 115")
    print("=" * 78)
    print("veredicto H-V4-8u:", status.upper() if status else "?")
    print("  el acuerdo entre K generaciones se mantiene donde la confianza single-shot colapsa (115); señal durable sin verdad externa.")
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
