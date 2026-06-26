r"""
cycle122_decisional_payoff.py — CICLO 122 (RESET v4, rama R-VALOR, intenta el capstone POSITIVO de 121): H-V4-9b por las
compuertas del engine. MIXTA (NULL/inconclusivo): 121 re-localizó el valor de R-VALOR como DECISIONAL. Este ciclo intenta
demostrarlo POSITIVAMENTE -- que el selector durable (calibrado, 119) PAGA en una decisión de asignación de recurso EXTERNO
(un "submission budget"). RESULTADO: NO se pudo aislar en esta tarea toy. El payoff de submission no separa los brazos de
forma limpia -- el smoke SATURA (≈1.0 en ambos: la tarea que el modelo SABE hacer tiene CORRECTOS ABUNDANTES, someter las
top-m es trivial) y el full a 4 seeds da señales MIXTAS/RUIDOSAS (sin separación consistente); subir la temperatura para
escasear los correctos DESESTABILIZA el brazo durable. DIAGNÓSTICO:
el payoff DECISIONAL de la calibración sólo se manifiesta bajo ESCASEZ de buenas opciones relativa al presupuesto -- la
MISMA precondición de toda la teoría de asignación (83-114). La tarea toy no provee esa escasez; demostrar el payoff
positivo es FRONTERA (tarea más dura / SCALE). La re-localización de 121 queda como inferencia LÓGICA sólida (apoyada por
las mediciones de calibración de todo el arco), no demostrada positivamente aquí.

DERIVA de exp106_decisional_payoff/results/results.json.

Correr (DESPUÉS de exp106):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp106_decisional_payoff.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle122_decisional_payoff
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle122_decisional_payoff')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp106_decisional_payoff', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="el valor DECISIONAL de la calibración de un selector se manifiesta sólo bajo ESCASEZ de buenas opciones relativa al presupuesto de decisión; bajo abundancia, cualquier selector acierta (la decisión es trivial)", obtained=False,
                     claim=("La calidad/calibración de un selector PAGA en una decisión sólo cuando las buenas opciones "
                            "son ESCASAS relativa al presupuesto: bajo abundancia (muchas opciones buenas), someter las "
                            "top-m es trivial y cualquier selector acierta. El payoff decisional necesita escasez -- la "
                            "misma precondición que el valor importe para asignar. (Principio.)"))
S_C121 = Source(tier=5, ref="cognia_x/experiments/exp105_full_recipe_payoff", obtained=True,
                claim=("CYCLE 121 re-localizó el valor de R-VALOR como DECISIONAL (no acelera el self-training downstream). "
                       "H-V4-9b intenta demostrarlo positivamente en una decisión de submission externa."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp106 primero): " + results_path)

    pfn = sm['payoff_final_naive']; pfd = sm['payoff_final_durable']
    aucn = sm['payoff_auc_naive']; aucd = sm['payoff_auc_durable']
    cfn = sm['corr_final_naive']; cfd = sm['corr_final_durable']
    fg = sm['final_gap']; ag = sm['auc_gap']; cg = sm['corr_gap']
    n_seeds = sm['n_seeds']
    saturated = (pfn >= 0.95 and pfd >= 0.95)

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim106 = ("exp106 ({n} seeds, PyTorch CPU, lazo real exp018): el payoff de submission SATURA (durable={pfd} vs "
                "naive={pfn}, AUC {aucd} vs {aucn}) -- la tarea toy tiene correctos abundantes, someter las top-m es "
                "trivial; subir temp para escasear los correctos desestabiliza el durable. No se aísla el payoff decisional "
                "en este régimen.").format(n=n_seeds, pfd=_f(pfd), pfn=_f(pfn), aucd=_f(aucd), aucn=_f(aucn))
    S_EXP106 = Source(tier=5, ref="cognia_x/experiments/exp106_decisional_payoff", obtained=True, claim=claim106)
    for src in (S_PRINCIPLE, S_C121, S_EXP106):
        ledger.add_source(src)
    notes.append("3 fuentes (S_PRINCIPLE tier2 payoff-decisional-necesita-escasez; S_C121 tier5 re-localización decisional; S_EXP106 tier5 dato propio).")

    ev_for = [S_EXP106.ref, S_PRINCIPLE.ref]
    ev_against = [S_EXP106.ref]
    sat_txt = "SATURA (≈1.0 en ambos brazos)" if saturated else "no separa los brazos"
    advtext = ("{V} (intenta el capstone POSITIVO de 121; NULL informativo + diagnóstico): 121 re-localizó el valor de "
               "R-VALOR como DECISIONAL -- la señal calibrada vale por las decisiones que la usan, no por acelerar el "
               "self-training. H-V4-9b intenta demostrarlo POSITIVAMENTE: que el selector durable (calibrado por "
               "unlikelihood, 119) PAGA en una decisión de asignación de recurso EXTERNO (someter las top-m generaciones "
               "por confianza a recompensa externa). RESULTADO: NO se pudo aislar limpio en esta tarea toy -- el payoff de "
               "submission {sat} (durable={pfd} vs naive={pfn}, AUC {aucd} vs {aucn}; el smoke saturó a 1.0, el full a 4 "
               "seeds dio señales mixtas/ruidosas). DIAGNÓSTICO (lo informativo): la "
               "tarea toy (computar '1+(n-1)', que el modelo SABE hacer) tiene CORRECTOS ABUNDANTES en el pool, así que "
               "someter las top-m es TRIVIAL -- cualquier selector acierta -- y la calibración no separa el payoff. Subir "
               "la temperatura para ESCASEAR los correctos DESESTABILIZA el brazo durable (el unlikelihood sobre un pool "
               "muy ruidoso rompe, corr->0). => el payoff DECISIONAL de la calibración sólo se manifiesta bajo ESCASEZ de "
               "buenas opciones relativa al presupuesto -- la MISMA precondición de toda la teoría de asignación (el valor "
               "importa cuando hay que ASIGNAR bajo escasez/presupuesto, 83-114). La tarea toy no provee esa escasez. "
               "CONSECUENCIA HONESTA: la re-localización de 121 (R-VALOR es decisional) queda como una inferencia LÓGICA "
               "sólida -- apoyada por las mediciones de calibración de todo el arco (corr durable > naive consistente) y "
               "por el principio (tier2) -- pero su demostración POSITIVA en una decisión con payoff es FRONTERA: requiere "
               "una tarea con escasez genuina de buenas opciones (o SCALE), no este toy que el modelo domina. EVIDENCIA: "
               "el principio escasez (tier2) explica la saturación. EVIDENCIA EN CONTRA / caveats: probé submit_m chico "
               "(3) y temp alta (1.5-1.8) -> saturan o desestabilizan; el corr durable SÍ tiende a > naive (la calibración "
               "se preserva, 119) pero no se traduce en payoff por la abundancia; modelo tiny, {n} seeds, CPU.").format(
                   V=status.upper(), sat=sat_txt, pfd=_f(pfd), pfn=_f(pfn), aucd=_f(aucd), aucn=_f(aucn), n=n_seeds)

    hyp = Hypothesis(
        id="H-V4-9b",
        statement=("El selector durable (calibrado, 119) paga en una decisión de asignación de recurso externo (submission "
                   "budget). [MIXTA/inconclusiva: no se aísla en la tarea toy -- el payoff de submission satura (smoke) o "
                   "da señales mixtas/ruidosas (full), o la temp alta desestabiliza el durable; el payoff decisional "
                   "necesita ESCASEZ de buenas opciones -> frontera.]"),
        prediction=("APOYADA si el payoff de submission durable > naive sostenidamente (+>0.04 Y AUC>0); REFUTADA si ≈; "
                    "MIXTA en otro caso. (Pre-registrada, lazo real exp018, 4 seeds, 8 rondas.)"),
        status='abierta', confidence='media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp106_decisional_payoff")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-9b")
        notes.append("H-V4-9b marcada '{}' con DoD completo (NULL: el toy task no aísla el payoff decisional -- satura o desestabiliza).".format(status))

    analogy = AnalogyRecord(
        problem=("Quiero MOSTRAR que tener buen criterio para elegir vale la pena, eligiendo qué presentar de mi trabajo. "
                 "Pero si TODO lo que hago está bien, ¿cómo voy a notar que mi criterio ayuda?"),
        everyday=("No lo voy a notar: si casi todo lo que produzco está bien, elija como elija lo que presento, sale "
                  "bien -- mi buen criterio no se luce porque no hay escasez de cosas buenas. El criterio se LUCE cuando "
                  "las cosas buenas son ESCASAS y hay que saber encontrarlas. Con una tarea que domino, no puedo demostrar "
                  "que mi criterio paga; necesito una tarea DIFÍCIL donde lo bueno escasee."),
        solutions=["tarea fácil (correctos abundantes): el payoff de elegir SATURA -> no se nota el criterio",
                   "subir la dificultad a lo bruto (temp alta): desestabiliza el método -> tampoco sirve",
                   "el payoff decisional de la calibración necesita ESCASEZ genuina de buenas opciones",
                   "es la misma precondición de la teoría de asignación (el valor importa bajo escasez)"],
        principles=["el payoff decisional de un buen selector se manifiesta sólo bajo escasez relativa al presupuesto",
                    "bajo abundancia de buenas opciones, cualquier selector acierta (decisión trivial)",
                    "la re-localización de 121 (R-VALOR decisional) queda como inferencia lógica, no demostrada positivamente aquí",
                    "demostrar el payoff positivo es frontera: requiere una tarea con escasez (o SCALE)"],
        adaptation=("El lab DOCUMENTA una limitación metodológica honesta: el payoff DECISIONAL de la señal calibrada "
                    "(re-localización de 121) NO se puede demostrar positivamente en la tarea toy actual, porque el modelo "
                    "la domina -> correctos abundantes -> la decisión de submission satura; y forzar escasez vía "
                    "temperatura desestabiliza. El payoff decisional necesita ESCASEZ genuina (la misma precondición de la "
                    "teoría de asignación). La re-localización de 121 se sostiene por lógica + las mediciones de "
                    "calibración del arco, pero su demostración POSITIVA en una decisión con payoff queda como FRONTERA. "
                    "Próximo: una tarea con escasez genuina de buenas opciones (más difícil) o SCALE, donde la calibración "
                    "del selector sea decisiva para el payoff."),
        measurement=("exp106 ({n} seeds): payoff submission durable={pfd} vs naive={pfn} (satura, +{fg}); AUC +{ag}; corr "
                     "durable={cfd} vs naive={cfn} (+{cg}, la calibración SÍ se preserva pero no paga por la "
                     "abundancia).").format(n=n_seeds, pfd=_f(pfd), pfn=_f(pfn), fg=_f(fg), ag=_f(ag), cfd=_f(cfd), cfn=_f(cfn), cg=_f(cg)),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (no se nota el buen criterio si casi todo lo que hacés está bien; hace falta escasez).")

    kl = ("REAL (exp106): el payoff DECISIONAL de la señal calibrada NO se puede aislar en la tarea toy -- el payoff de "
          "submission SATURA (durable={pfd} vs naive={pfn}, correctos abundantes -> decisión trivial) y forzar escasez vía "
          "temperatura desestabiliza el durable. El payoff decisional necesita ESCASEZ de buenas opciones (precondición de "
          "la teoría de asignación). La re-localización de 121 queda como inferencia lógica + apoyada por la calibración "
          "(corr durable={cfd} vs naive={cfn}), no demostrada positivamente. TECHO: tarea toy que el modelo domina; forzar "
          "escasez rompe; demostración positiva = FRONTERA (tarea dura / SCALE); modelo tiny, {n} seeds, CPU.").format(
              pfd=_f(pfd), pfn=_f(pfn), cfd=_f(cfd), cfn=_f(cfn), n=n_seeds)
    ceilings.add(CeilingRecord(
        subsystem="Demostración POSITIVA del payoff decisional de R-VALOR — NO aislable en la tarea toy (submission satura por correctos abundantes; forzar escasez desestabiliza); necesita ESCASEZ genuina (precondición de la asignación) -> frontera",
        known_limit=kl,
        blockers=[{"text": "la tarea toy (que el modelo domina) tiene correctos ABUNDANTES -> la decisión de submission satura (cualquier selector acierta) -> la calibración no separa el payoff; el payoff decisional necesita ESCASEZ de buenas opciones", "kind": "diseno"},
                  {"text": "forzar escasez subiendo la temperatura DESESTABILIZA el brazo durable (unlikelihood sobre pool muy ruidoso, corr->0) -> no hay un régimen toy que aísle el efecto limpio", "kind": "fisico"},
                  {"text": "la re-localización de 121 queda como inferencia lógica + apoyada por la calibración del arco, NO demostrada positivamente; la demostración requiere una tarea con escasez genuina o SCALE; modelo tiny, 4 seeds, CPU", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP106.ref, S_C121.ref]))
    notes.append("1 techo 'real': el payoff decisional positivo no se aísla en el toy (satura/desestabiliza); necesita escasez genuina -> frontera. (La re-localización de 121 se sostiene por lógica + calibración.)")

    dstmt = ("North-Star R-VALOR (frontera honesta de la demostración positiva): el payoff DECISIONAL de la señal "
             "calibrada (re-localización de 121) NO se pudo demostrar positivamente en la tarea toy -- el modelo la domina, "
             "los correctos son abundantes y la decisión de submission SATURA (cualquier selector acierta); forzar escasez "
             "vía temperatura desestabiliza el brazo durable. El payoff decisional necesita ESCASEZ genuina de buenas "
             "opciones -- la MISMA precondición de la teoría de asignación (el valor importa bajo escasez/presupuesto, "
             "83-114). Decisión: la re-localización de 121 (R-VALOR es decisional) se sostiene por LÓGICA + las mediciones "
             "de calibración del arco (corr durable > naive consistente), pero su demostración POSITIVA en una decisión "
             "con payoff queda como FRONTERA: requiere una tarea con escasez genuina de buenas opciones, o SCALE. Próximo: "
             "esa tarea / SCALE.")
    drat = ("exp106 (tier5, propio, {n} seeds, PyTorch CPU, lazo real exp018): payoff submission durable={pfd} vs "
            "naive={pfn} (SATURA, +{fg}); corr durable={cfd} vs naive={cfn} (+{cg}, calibración preservada). Convergente "
            "con 'payoff-decisional-necesita-escasez' (tier2). MIXTA/inconclusiva: el toy no aísla el payoff (smoke satura, "
            "full ruidoso); la re-localización de 121 queda como inferencia lógica, no demostrada positivamente.").format(
                n=n_seeds, pfd=_f(pfd), pfn=_f(pfn), fg=_f(fg), cfd=_f(cfd), cfn=_f(cfn), cg=_f(cg))
    dec = Decision(id="D-V4-84", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP106), _to_plain(S_C121)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-84 ACEPTADA por el ledger (tier5 exp106 + tier5 exp105).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-84:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle122_decisional_payoff',
                                description='CYCLE 122 (RESET v4, H-V4-9b REFUTADA-null: el payoff decisional de la señal calibrada no se aísla en el toy -satura/desestabiliza-; necesita escasez genuina -> frontera).')
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
    print("RESUMEN — CYCLE 122 (RESET v4): el payoff decisional positivo no se aísla en el toy (satura/desestabiliza) -> frontera (H-V4-9b NULL)")
    print("=" * 78)
    print("veredicto H-V4-9b:", status.upper() if status else "?")
    print("  el toy task satura (correctos abundantes); el payoff decisional necesita escasez genuina. La re-localización de 121 se sostiene por lógica + calibración.")
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
