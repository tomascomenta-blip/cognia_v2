r"""
cycle120_durable_payoff.py — CICLO 120 (RESET v4, rama R-VALOR, PAYOFF END-TO-END del selector durable): H-V4-8z por las
compuertas del engine. Pregunta: ¿el selector durable (unlikelihood acotado, 119) PAGA end-to-end -- sostiene la
auto-mejora del downstream bajo presupuesto AJUSTADO y SIN ancla de replay externa, donde el naive (selector que colapsa)
desperdicia el presupuesto? RESULTADO (informativo): el selector durable mantiene la calibración (corr alta) Y encuentra
MÁS correctos (yield) PERO el downstream NO mejora -- porque SIN el ancla de replay, el COSTO DE CAPACIDAD del unlikelihood
(que en 119 el ancla compensaba) NO se compensa y arrastra el downstream. CONCLUSIÓN: la durabilidad del lazo necesita
AMBAS piezas -- el ANCLA de replay (capacidad, 115) Y el unlikelihood (calibración, 119); ninguna sola basta.

DERIVA de exp104_durable_payoff/results/results.json.

Correr (DESPUÉS de exp104):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp104_durable_payoff.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle120_durable_payoff
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle120_durable_payoff')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp104_durable_payoff', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="calibración y capacidad son ejes SEPARADOS con mecanismos separados: el unlikelihood mejora la calibración pero tiene un costo de capacidad que necesita compensarse con grounding/datos (ancla); ninguno solo basta para un lazo de auto-mejora sostenido", obtained=False,
                     claim=("Calibración (qué tan bien la confianza rankea la corrección) y CAPACIDAD (qué tan bien el "
                            "modelo genera lo correcto) son ejes SEPARADOS. El unlikelihood mejora la calibración pero "
                            "tiene un costo de capacidad; un ANCLA de datos (replay de verdad) sostiene la capacidad. Un "
                            "lazo de auto-mejora durable necesita AMBOS mecanismos; ninguno solo basta. (Principio.)"))
S_C119 = Source(tier=5, ref="cognia_x/experiments/exp103_bounded_unlikelihood", obtained=True,
                claim=("CYCLE 119: el unlikelihood acotado preserva la calibración SIN costo de capacidad CUANDO hay ancla "
                       "de replay (ambos arms la tenían). 120 testea el unlikelihood SIN ancla bajo presupuesto ajustado."))
S_C115 = Source(tier=5, ref="cognia_x/experiments/exp099_confidence_drift", obtained=True,
                claim=("CYCLE 115: el ancla de replay rescata el DOWNSTREAM (capacidad) pero no la señal. 120 confirma su "
                       "rol: sin ancla, el unlikelihood no alcanza para el downstream."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp104 primero): " + results_path)

    rfn = sm['real_final_naive']; rfd = sm['real_final_durable']
    aucn = sm['real_auc_naive']; aucd = sm['real_auc_durable']
    yn = sm['yield_naive']; yd = sm['yield_durable']
    cfn = sm['corr_final_naive']; cfd = sm['corr_final_durable']
    fg = sm['final_gap']; ag = sm['auc_gap']; yg = sm['yield_gap']
    n_seeds = sm['n_seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim104 = ("exp104 ({n} seeds, PyTorch CPU, lazo real exp018, presupuesto ajustado SIN replay): el selector durable "
                "mantiene la calibración (corr final {cfd} vs naive {cfn}) y encuentra más correctos (yield {yd} vs {yn}, "
                "+{yg}) PERO el downstream NO mejora (real_acc final {rfd} vs {rfn}, +{fg}; AUC {aucd} vs {aucn}, +{ag}): "
                "sin ancla, el costo de capacidad del unlikelihood arrastra el downstream. Calibración y capacidad son "
                "ejes separados.").format(n=n_seeds, cfd=_f(cfd), cfn=_f(cfn), yd=_f(yd), yn=_f(yn), yg=_f(yg),
                                          rfd=_f(rfd), rfn=_f(rfn), fg=_f(fg), aucd=_f(aucd), aucn=_f(aucn), ag=_f(ag))
    S_EXP104 = Source(tier=5, ref="cognia_x/experiments/exp104_durable_payoff", obtained=True, claim=claim104)
    for src in (S_PRINCIPLE, S_C119, S_C115, S_EXP104):
        ledger.add_source(src)
    notes.append("4 fuentes (S_PRINCIPLE tier2 calibración/capacidad ejes separados; S_C119 tier5 unlikelihood-con-ancla; S_C115 tier5 ancla=capacidad; S_EXP104 tier5 dato propio).")

    ev_for = [S_EXP104.ref, S_PRINCIPLE.ref]
    ev_against = [S_EXP104.ref]
    advtext = ("{V} (PAYOFF end-to-end del selector durable; resultado INFORMATIVO que completa el arco): tras curar la "
               "calibración (119), la pregunta práctica: ¿el selector durable SOSTIENE la auto-mejora bajo presupuesto "
               "AJUSTADO y SIN ancla de replay, donde el naive (selector que colapsa) desperdicia el presupuesto? "
               "RESULTADO: el selector durable hace DOS cosas bien -- mantiene la calibración (corr final {cfd} vs naive "
               "{cfn}, confirmando 119) y encuentra MÁS correctos bajo el presupuesto ajustado (yield {yd} vs {yn}, +{yg}) "
               "-- PERO el downstream NO mejora (real_acc final {rfd} vs {rfn}, +{fg}; AUC {aucd} vs {aucn}, +{ag}). "
               "MECANISMO: en 119 ambos arms tenían el ANCLA de replay, que compensaba el costo de capacidad del "
               "unlikelihood; AQUÍ, SIN ancla, ese costo de capacidad NO se compensa y arrastra el downstream pese a la "
               "mejor calibración y yield. CONCLUSIÓN (completa el arco): CALIBRACIÓN y CAPACIDAD son ejes SEPARADOS con "
               "mecanismos separados -- el unlikelihood ACOTADO cura la CALIBRACIÓN (119) y el ANCLA de replay sostiene la "
               "CAPACIDAD (115); un lazo de auto-mejora durable necesita AMBOS, ninguno solo basta. La receta durable "
               "completa = likelihood(verificado-correcto) + replay-ancla(verdad canónica) + unlikelihood-acotado("
               "verificado-incorrecto). EVIDENCIA: el principio calibración-vs-capacidad (tier2) lo predice; convergente "
               "con 119 (la cura necesitaba el ancla presente) y 115 (el ancla = capacidad). EVIDENCIA EN CONTRA / "
               "caveats: el diseño quitó el ancla A PROPÓSITO para aislar el selector -> es un test del selector SOLO, no "
               "de la receta completa (que SÍ funciona, 119); presupuesto muy ajustado; modelo tiny, {n} seeds, CPU. La "
               "afirmación robusta: el selector durable mejora calibración+yield pero necesita el ancla para el "
               "downstream.").format(V=status.upper(), cfd=_f(cfd), cfn=_f(cfn), yd=_f(yd), yn=_f(yn), yg=_f(yg),
                                     rfd=_f(rfd), rfn=_f(rfn), fg=_f(fg), aucd=_f(aucd), aucn=_f(aucn), ag=_f(ag), n=n_seeds)

    hyp = Hypothesis(
        id="H-V4-8z",
        statement=("El selector durable (unlikelihood acotado, 119) paga end-to-end sosteniendo la auto-mejora bajo "
                   "presupuesto ajustado SIN ancla. [Resultado: mejora calibración+yield pero NO el downstream sin ancla "
                   "-> calibración y capacidad son ejes separados; la receta durable necesita ancla + unlikelihood.]"),
        prediction=("APOYADA si real_acc final durable > naive (+>0.04) Y AUC gap > 0; REFUTADA si no sostiene mejor; MIXTA "
                    "en otro caso. (Pre-registrada, lazo real exp018, 4 seeds, 8 rondas, presupuesto ajustado sin replay.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp104_durable_payoff")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-8z")
        notes.append("H-V4-8z marcada '{}' con DoD completo (el selector durable solo no basta: calibración y capacidad son ejes separados).".format(status))

    analogy = AnalogyRecord(
        problem=("Recalibré mi seguridad (ya sé cuándo dudar) y con eso ELIJO mejor en qué practicar con poco tiempo. "
                 "Pero, ¿alcanza con eso para mejorar de verdad, o me falta algo?"),
        everyday=("No alcanza solo. Tener buen criterio para elegir (y elegir más cosas buenas) ayuda, pero si al mismo "
                  "tiempo el método con que me recalibro me MERMA un poco la capacidad y NO tengo ejemplos sólidos de la "
                  "verdad para apoyarme, no termino mejorando. Necesito las DOS cosas: el buen criterio (calibración) Y un "
                  "ancla de ejemplos verdaderos (capacidad). Son cosas distintas y cada una necesita su mecanismo."),
        solutions=["selector durable solo (calibración + más yield) SIN ancla: no mejora el downstream",
                   "el unlikelihood cura la calibración (119) pero tiene un costo de capacidad",
                   "el ancla de replay sostiene la capacidad (115); ninguno solo basta",
                   "receta durable completa = likelihood(correcto) + replay-ancla + unlikelihood-acotado(incorrecto)"],
        principles=["calibración y capacidad son ejes SEPARADOS con mecanismos separados",
                    "el unlikelihood cura la calibración pero merma la capacidad -> necesita compensación (ancla)",
                    "el selector durable mejora calibración+yield pero no el downstream sin ancla",
                    "un lazo de auto-mejora durable necesita AMBOS: ancla (capacidad) + unlikelihood (calibración)"],
        adaptation=("El lab COMPLETA la receta del lazo de auto-mejora durable: no basta el selector calibrado (119) ni el "
                    "ancla sola (115) -- se necesitan AMBOS. Calibración (unlikelihood acotado) y capacidad (replay-ancla "
                    "de verdad) son ejes separados con mecanismos separados. Receta: likelihood(verificado-correcto) + "
                    "replay-ancla(verdad canónica) + unlikelihood-acotado(verificado-incorrecto). Próximo: sintonizar el "
                    "balance de los tres términos; horizontes largos; y SCALE."),
        measurement=("exp104 ({n} seeds): durable corr {cfd} vs naive {cfn}, yield {yd} vs {yn} (+{yg}) PERO real_acc final "
                     "{rfd} vs {rfn} (+{fg}), AUC +{ag} -> sin ancla no paga el downstream.").format(
                         n=n_seeds, cfd=_f(cfd), cfn=_f(cfn), yd=_f(yd), yn=_f(yn), yg=_f(yg), rfd=_f(rfd), rfn=_f(rfn), fg=_f(fg), ag=_f(ag)),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (buen criterio + ancla de ejemplos verdaderos: las dos cosas, no una sola).")

    kl = ("REAL (exp104): el selector durable (unlikelihood, 119) mejora calibración (corr {cfd} vs {cfn}) y yield ({yd} vs "
          "{yn}) PERO no el downstream SIN ancla (real_acc final {rfd} vs {rfn}, +{fg}; AUC +{ag}): sin replay, el costo de "
          "capacidad del unlikelihood arrastra el downstream. Calibración y capacidad son ejes SEPARADOS; la receta durable "
          "necesita AMBOS (ancla + unlikelihood). TECHO: el diseño quitó el ancla a propósito (test del selector solo, no "
          "de la receta completa de 119 que SÍ funciona); presupuesto muy ajustado; modelo tiny, {n} seeds, CPU.").format(
              cfd=_f(cfd), cfn=_f(cfn), yd=_f(yd), yn=_f(yn), rfd=_f(rfd), rfn=_f(rfn), fg=_f(fg), ag=_f(ag), n=n_seeds)
    ceilings.add(CeilingRecord(
        subsystem="Lazo de auto-mejora durable — calibración (unlikelihood, 119) y capacidad (replay-ancla, 115) son ejes SEPARADOS; el selector durable solo (sin ancla) mejora calibración+yield pero no el downstream -> se necesitan AMBOS",
        known_limit=kl,
        blockers=[{"text": "el unlikelihood cura la calibración pero tiene un costo de capacidad que SIN ancla no se compensa -> el selector durable solo no paga el downstream; calibración y capacidad son ejes separados", "kind": "fisico"},
                  {"text": "el diseño quitó el ancla A PROPÓSITO para aislar el selector; la receta COMPLETA (likelihood + replay-ancla + unlikelihood, como 119) SÍ funciona -- esto NO la refuta, la complementa", "kind": "diseno"},
                  {"text": "presupuesto muy ajustado, modelo tiny, 4 seeds, CPU; falta sintonizar el balance de los tres términos, horizontes largos y SCALE", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP104.ref, S_C119.ref, S_C115.ref]))
    notes.append("1 techo 'real': calibración y capacidad son ejes separados; la receta durable necesita ancla (capacidad) + unlikelihood (calibración), ninguno solo basta.")

    dstmt = ("North-Star R-VALOR (completa la receta del lazo durable): el selector durable (unlikelihood acotado, 119) "
             "mejora la calibración y el yield bajo presupuesto ajustado PERO no sostiene el downstream SIN un ancla de "
             "datos -- porque el costo de capacidad del unlikelihood necesita compensarse. CALIBRACIÓN y CAPACIDAD son "
             "ejes SEPARADOS con mecanismos separados. Decisión: la receta del lazo de auto-mejora durable necesita los "
             "TRES términos -- likelihood(verificado-correcto) + replay-ancla(verdad canónica, capacidad/115) + "
             "unlikelihood-acotado(verificado-incorrecto, calibración/119); ninguna pieza sola basta. Próximo: balance de "
             "los tres términos; horizontes largos; y SCALE.")
    drat = ("exp104 (tier5, propio, {n} seeds, PyTorch CPU, lazo real exp018, sin replay): durable mejora calibración (corr "
            "{cfd} vs {cfn}) y yield (+{yg}) pero no el downstream (real_acc final +{fg}, AUC +{ag}). Convergente con "
            "calibración-vs-capacidad-ejes-separados (tier2), con 119 (cura con ancla) y 115 (ancla=capacidad). El selector "
            "durable solo no basta: se necesitan ancla + unlikelihood.").format(
                n=n_seeds, cfd=_f(cfd), cfn=_f(cfn), yg=_f(yg), fg=_f(fg), ag=_f(ag))
    dec = Decision(id="D-V4-82", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP104), _to_plain(S_C119), _to_plain(S_C115)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-82 ACEPTADA por el ledger (tier5 exp104 + tier5 exp103 + tier5 exp099).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-82:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle120_durable_payoff',
                                description='CYCLE 120 (RESET v4, H-V4-8z: el selector durable solo no basta -- calibración y capacidad son ejes separados; la receta durable necesita ancla + unlikelihood).')
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
    print("RESUMEN — CYCLE 120 (RESET v4): calibración y capacidad son ejes separados; la receta durable necesita ancla + unlikelihood (H-V4-8z)")
    print("=" * 78)
    print("veredicto H-V4-8z:", status.upper() if status else "?")
    print("  el selector durable solo (sin ancla) mejora calibración+yield pero no el downstream; se necesitan AMBOS mecanismos.")
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
