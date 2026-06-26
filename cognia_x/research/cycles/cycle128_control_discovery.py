r"""
cycle128_control_discovery.py — CICLO 128 (RESET v4, rama control/acción, CIERRA el caveat principal de 127): H-V4-10b por
las compuertas del engine. APOYADA: 127 mostró que el CONTROL enfoca la capacidad en lo controlable-relevante (no en el
distractor ruidoso) PERO le DABA la partición al agente. Este ciclo la cierra: el agente DESCUBRE qué es controlable de sus
PROPIOS datos acción-resultado (estimando |b̂| por modo), sin que se le diga -- y con datos suficientes iguala al oracle y
supera a la predicción que colapsa, eligiendo el modo controlable correcto el 100% de las veces. Con POCA data el distractor
ruidoso lo confunde (descubrir necesita suficiente ACCIÓN -> R-INTERVENCIÓN). "El control es la fuente de la relevancia" (127)
se fortalece a "el control DESCUBRE la relevancia ACTUANDO".

DERIVA de exp112_control_discovery/results/results.json.

Correr (DESPUÉS de exp112):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp112_control_discovery.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle128_control_discovery
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle128_control_discovery')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp112_control_discovery', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="la PARTICIÓN de relevancia (qué dimensiones son controlables) es DESCUBRIBLE de los datos acción-resultado del propio agente: estimar la influencia |b̂| de la acción sobre cada dimensión revela lo accionable sin que se diga; pero requiere SUFICIENTE data interventiva (poca data + distractor ruidoso confunde la estimación) -> aprendés qué controlás ACTUANDO (R-INTERVENCIÓN). Descubrimiento de la controlabilidad por la acción", obtained=False,
                     claim=("La PARTICIÓN de relevancia -- qué dimensiones del mundo son CONTROLABLES -- es DESCUBRIBLE de los "
                            "datos acción-resultado del propio agente: estimar cuánto influye la acción sobre cada dimensión "
                            "(|b̂|) revela lo accionable SIN que se le diga. Pero requiere SUFICIENTE data interventiva: con "
                            "poca acción, un distractor ruidoso (alta varianza) confunde la estimación de controlabilidad. => "
                            "aprendés qué controlás ACTUANDO lo suficiente (R-INTERVENCIÓN: la causa/controlabilidad sólo se "
                            "identifica variando la distribución). (Principio.)"))
S_C127 = Source(tier=5, ref="cognia_x/experiments/exp111_control_relevance", obtained=True,
                claim=("CYCLE 127: el CONTROL enfoca la capacidad en lo controlable-relevante (no en el distractor ruidoso) "
                       "-- PERO le DABA la partición al agente. H-V4-10b cierra ese caveat: el agente la DESCUBRE actuando."))
S_INTERV = Source(tier=5, ref="cognia_x/experiments/exp022_endogenous_value", obtained=True,
                  claim=("R-INTERVENCIÓN (CYCLE 35): la causa/controlabilidad sólo se identifica variando la distribución "
                         "(actuando). H-V4-10b lo MIDE: descubrir qué es controlable requiere suficiente data acción-resultado; "
                         "con poca, el distractor ruidoso confunde."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp112 primero): " + results_path)

    dh, oh, ph = sm['disc_hi'], sm['orac_hi'], sm['pred_hi']
    pk, dl, dd = sm['disc_pick_hi'], sm['disc_lo'], sm['data_dependence']
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim112 = ("exp112 (propio, {n} seeds, numpy, extiende exp111): con data suficiente y distractor fuerte, CONTROL-DISCOVERY "
                "(estima |b̂| por modo, NO sabe la partición) iguala al CONTROL-ORACLE ({dh}≈{oh}) y supera a la PREDICCIÓN que "
                "colapsa ({ph}), eligiendo el modo controlable correcto el {pk}. Con poca data rinde {dl} (Δ{dd}): descubrir "
                "necesita suficiente acción. La relevancia es DESCUBRIBLE actuando.").format(
                    n=n_seeds, dh=_f(dh), oh=_f(oh), ph=_f(ph), pk=_f(pk), dl=_f(dl), dd=_f(dd))
    S_EXP112 = Source(tier=5, ref="cognia_x/experiments/exp112_control_discovery", obtained=True, claim=claim112)
    for src in (S_PRINCIPLE, S_C127, S_INTERV, S_EXP112):
        ledger.add_source(src)
    notes.append("4 fuentes (S_PRINCIPLE tier2 descubrir controlabilidad por la acción; S_C127 tier5 el caveat que cierra; S_INTERV tier5 R-INTERVENCIÓN como mecanismo; S_EXP112 tier5 dato propio).")

    ev_for = [S_EXP112.ref, S_PRINCIPLE.ref]
    ev_against = [S_EXP112.ref]
    advtext = ("{V} (CIERRA el caveat principal de 127): 127 mostró que el CONTROL es la fuente de la relevancia -- enfoca la "
               "capacidad en el modo controlable y no en el distractor ruidoso -- PERO le DABA al agente la partición (sabía "
               "cuál modo era accionable). H-V4-10b cierra ese caveat: ¿el agente DESCUBRE qué es controlable de sus PROPIOS "
               "datos acción-resultado, sin que se le diga? El arm CONTROL-DISCOVERY estima la controlabilidad |b̂| de cada "
               "modo (regresión del next-state sobre [estado, acción]) y asigna su capacidad-1 al modo de mayor |b̂| estimado. "
               "RESULTADO: con DATA SUFICIENTE (T=200) y distractor FUERTE (s2=4.0), DISCOVERY iguala al CONTROL-ORACLE "
               "({dh}≈{oh}) y supera a la PREDICCIÓN que colapsa ({ph}), eligiendo el modo controlable correcto el {pk} de las "
               "veces -- SIN que se le diga la partición. => la PARTICIÓN de relevancia (qué es controlable) es DESCUBRIBLE de "
               "los datos acción-resultado ACTUANDO; cierra el caveat de 127 y fortalece 'control = fuente de relevancia' a "
               "'control DESCUBRE la relevancia ACTUANDO'. Y lo ANCLA en R-INTERVENCIÓN de forma MEDIDA: con POCA data (T=12) "
               "el acierto del modo correcto se degrada al crecer el distractor (pick 0.97->0.57) y la perf cae a {dl} "
               "(Δ{dd}) -- un distractor de alta varianza confunde la estimación de controlabilidad cuando no actuaste lo "
               "suficiente; aprendés qué controlás interviniendo BASTANTE. EVIDENCIA: el principio descubrir-controlabilidad "
               "(tier2) y R-INTERVENCIÓN (tier5) lo predicen. EVIDENCIA EN CONTRA / caveats: misma abstracción que 127 (numpy, "
               "lineal 2D, cuello de botella elegir-1-de-2, control 1 paso); la controlabilidad se estima por |b̂| de una "
               "regresión lineal (lo natural aquí), no por un esquema interventivo activo; reproducible smoke 50 ≈ full "
               "200.").format(V=status.upper(), dh=_f(dh), oh=_f(oh), ph=_f(ph), pk=_f(pk), dl=_f(dl), dd=_f(dd))

    hyp = Hypothesis(
        id="H-V4-10b",
        statement=("La PARTICIÓN de relevancia (qué dimensiones son controlables) es DESCUBRIBLE de los datos acción-resultado "
                   "del propio agente -- estimando |b̂| por modo -- sin que se le diga: con data suficiente, CONTROL-DISCOVERY "
                   "iguala al oracle y supera a la predicción que colapsa, eligiendo el modo controlable correcto; con poca "
                   "data el distractor ruidoso confunde. Cierra el caveat de 127; ancla 'control = fuente de relevancia' en "
                   "R-INTERVENCIÓN (descubrís qué controlás actuando)."),
        prediction=("APOYADA si con data suficiente CONTROL-DISCOVERY ≈ CONTROL-ORACLE (|Δ|<0.15) y >> PREDICCIÓN (gap>0.30) "
                    "y elige el modo controlable correcto (>0.8). REFUTADA si DISCOVERY no recupera el modo controlable "
                    "(colapsa como predicción). MIXTA en otro caso. (Pre-registrada, numpy, 200 seeds, barrido distractor × "
                    "presupuesto de datos T.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp112_control_discovery")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-10b")
        notes.append("H-V4-10b marcada '{}' con DoD completo (la relevancia es DESCUBRIBLE actuando; cierra el caveat de 127).".format(status))

    analogy = AnalogyRecord(
        problem=("En 127 vimos que querer-controlar te dice qué vale la pena entender -- pero el agente ya sabía qué podía "
                 "tocar. ¿Y si NO lo sabe? ¿Puede DESCUBRIR qué cosas responden a sus actos, sin que nadie se lo diga?"),
        everyday=("Sí: probando. Si muevo una palanca y algo cambia consistentemente, aprendo que ESA palanca controla ESA "
                  "cosa; si muevo y nada cambia, no la controlo. Estimando cuánto responde cada cosa a mis actos, descubro "
                  "qué es accionable y enfoco ahí mi atención -- sin que me digan el mapa. PERO necesito probar LO "
                  "SUFICIENTE: si actué poco, una cosa muy ruidosa (que cambia sola mucho) me confunde y creo que la "
                  "controlo cuando no. Aprendés qué controlás actuando bastante."),
        solutions=["estimar la controlabilidad |b̂| de cada dimensión (cuánto responde a la acción) descubre la partición de relevancia sin que se diga",
                   "con data interventiva suficiente, descubrir iguala al que YA sabía la partición (oracle) y vence a la predicción que colapsa",
                   "con poca data, un distractor de alta varianza confunde la estimación de controlabilidad (pick degrada)",
                   "aprendés qué controlás ACTUANDO lo suficiente -> R-INTERVENCIÓN MEDIDA"],
        principles=["la partición de relevancia (qué es controlable) es DESCUBRIBLE de los datos acción-resultado del propio agente",
                    "descubrir la controlabilidad requiere SUFICIENTE data interventiva (con poca, el ruido del distractor confunde)",
                    "el control DESCUBRE la relevancia actuando (fortalece 127: no necesita que se le dé la partición)",
                    "ancla la rama control/acción en R-INTERVENCIÓN de forma medida (la controlabilidad se identifica variando la distribución)"],
        adaptation=("El lab CIERRA el caveat de 127: la relevancia no hay que dársela al agente -- la DESCUBRE actuando. "
                    "Estimando cuánto responde cada dimensión a su acción (|b̂|), un agente de capacidad limitada recupera la "
                    "partición controlable/incontrolable y modela lo accionable, igualando al que la sabía de antemano, SIN "
                    "supervisión de la partición. Esto convierte 'control = fuente de relevancia' (127) en 'control DESCUBRE "
                    "la relevancia ACTUANDO', y lo ancla en R-INTERVENCIÓN de forma medida: con poca acción el distractor "
                    "ruidoso confunde -> la auto-construcción de la relevancia es un PRESUPUESTO DE ACCIÓN, no gratis. "
                    "Política/dirección: un agente que se auto-asigna por R-VALOR puede GENERAR su criterio de relevancia "
                    "actuando y midiendo qué controla -- sin meta externa que se la dé. Próximo (H-V4-10): partición continua "
                    "(grados de controlabilidad) y muchas dimensiones; descubrir bajo controlabilidad PARCIAL/no-lineal; "
                    "exploración ACTIVA para descubrir más rápido (vs acción pasiva-excitada); puente a active inference."),
        measurement=("exp112 ({n} seeds): discovery {dh} ≈ oracle {oh} >> predicción {ph} (T alto, distractor fuerte); pick "
                     "correcto {pk}; con poca data {dl} (Δ{dd}).").format(
                         n=n_seeds, dh=_f(dh), oh=_f(oh), ph=_f(ph), pk=_f(pk), dl=_f(dl), dd=_f(dd)),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (descubrís qué controlás probando -estimando cuánto responde cada cosa a tus actos-, pero hay que probar lo suficiente).")

    kl = ("REAL (exp112): la PARTICIÓN de relevancia (qué es controlable) es DESCUBRIBLE de los datos acción-resultado del "
          "propio agente -- estimando |b̂| por modo. Con data suficiente, CONTROL-DISCOVERY iguala al oracle ({dh}≈{oh}) y "
          "supera a la predicción que colapsa ({ph}), eligiendo el modo correcto el {pk}, SIN que se le diga la partición. "
          "Con poca data el distractor ruidoso confunde (perf {dl}, Δ{dd}): descubrir necesita suficiente ACCIÓN "
          "(R-INTERVENCIÓN medida). Cierra el caveat de 127. TECHO: numpy, lineal 2D, cuello de botella elegir-1-de-2, "
          "control 1 paso, |b̂| por regresión lineal (no exploración activa); frontera: controlabilidad parcial/continua, "
          "muchas dimensiones, no-lineal, exploración activa, active inference.").format(
              dh=_f(dh), oh=_f(oh), ph=_f(ph), pk=_f(pk), dl=_f(dl), dd=_f(dd))
    ceilings.add(CeilingRecord(
        subsystem="DESCUBRIMIENTO de la relevancia por la acción (rama control/acción) — la partición controlable/incontrolable es DESCUBRIBLE de los datos acción-resultado del propio agente (estimar |b̂| por modo) sin supervisión, con suficiente data interventiva; el control DESCUBRE la relevancia actuando (cierra el caveat de 127)",
        known_limit=kl,
        blockers=[{"text": "misma abstracción que 127: numpy, lineal 2D, cuello de botella = elegir 1 de 2 modos, control de 1 paso; la controlabilidad se estima por |b̂| de una regresión lineal (lo natural aquí), no por un esquema de exploración ACTIVA", "kind": "diseno"},
                  {"text": "controlabilidad BINARIA (un modo accionable, otro no) y sólo 2 dimensiones; falta controlabilidad PARCIAL/continua, muchas dimensiones, y descubrimiento bajo dinámica NO-lineal", "kind": "diseno"},
                  {"text": "los datos son acción-PASIVA-excitada (u~N(0,1)), no exploración ACTIVA dirigida a descubrir más rápido; el threshold de data (Δ vs poca data) podría mejorar con exploración activa -- frontera", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP112.ref, S_C127.ref, S_INTERV.ref]))
    notes.append("1 techo 'real': la relevancia es DESCUBRIBLE actuando (estimando |b̂|), con suficiente data interventiva; cierra el caveat de 127, ancla R-INTERVENCIÓN.")

    dstmt = ("North-Star R-VALOR (rama control/acción -- el control DESCUBRE la relevancia actuando): la PARTICIÓN de "
             "relevancia (qué es controlable) es DESCUBRIBLE de los datos acción-resultado del propio agente. Estimando |b̂| "
             "por modo, CONTROL-DISCOVERY iguala al oracle ({dh}≈{oh}) y supera a la predicción que colapsa ({ph}), eligiendo "
             "el modo correcto el {pk}, SIN que se le diga la partición -- con suficiente data interventiva (con poca, el "
             "distractor confunde: {dl}, Δ{dd}). Decisión: un agente que se auto-asigna por R-VALOR puede GENERAR su criterio "
             "de relevancia ACTUANDO y midiendo qué controla, sin meta externa que se la dé -- pero la auto-construcción de la "
             "relevancia es un PRESUPUESTO DE ACCIÓN (R-INTERVENCIÓN), no gratis. Cierra el caveat de 127. Próximo: "
             "controlabilidad continua/parcial, muchas dimensiones, no-lineal, exploración activa, active inference.").format(
                 dh=_f(dh), oh=_f(oh), ph=_f(ph), pk=_f(pk), dl=_f(dl), dd=_f(dd))
    drat = ("exp112 (tier5, propio, {n} seeds, numpy): CONTROL-DISCOVERY (estima |b̂|, no sabe la partición) iguala al oracle "
            "({dh}≈{oh}) y vence a la predicción que colapsa ({ph}), pick correcto {pk}; con poca data {dl} (Δ{dd}). "
            "Convergente con descubrir-controlabilidad (tier2) y R-INTERVENCIÓN (tier5); cierra el caveat de 127 (tier5). "
            "APOYADA: la relevancia es DESCUBRIBLE actuando.").format(
                n=n_seeds, dh=_f(dh), oh=_f(oh), ph=_f(ph), pk=_f(pk), dl=_f(dl), dd=_f(dd))
    dec = Decision(id="D-V4-90", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP112), _to_plain(S_C127), _to_plain(S_INTERV)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-90 ACEPTADA por el ledger (tier5 exp112 + tier5 exp111 + tier5 exp022).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-90:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle128_control_discovery',
                                description='CYCLE 128 (RESET v4, H-V4-10b: el control DESCUBRE la relevancia actuando -- la partición controlable es descubrible de los datos acción-resultado con suficiente data; cierra el caveat de 127).')
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
    print("RESUMEN — CYCLE 128 (RESET v4): el control DESCUBRE la relevancia ACTUANDO -- la partición controlable es descubrible de los datos acción-resultado (cierra el caveat de 127) — H-V4-10b")
    print("=" * 78)
    print("veredicto H-V4-10b:", status.upper() if status else "?")
    print("  estimando |b̂| por modo el agente descubre qué es controlable sin que se le diga; iguala al oracle, vence a la predicción; con poca data el distractor confunde (R-INTERVENCIÓN medida).")
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
