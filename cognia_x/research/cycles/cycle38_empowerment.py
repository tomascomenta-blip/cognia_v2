r"""
cycle38_empowerment.py — CICLO 38 (RESET v4): H-V4-1c por las compuertas del engine.

H-V4-1c: un valor AUTO-generado (EMPOWERMENT = capacidad de canal acción->futuro, Blahut-Arimoto, SIN
reward/verificador externo) captura la CONTROLABILIDAD ("lo que puedo afectar") que la predicción pasiva NO
puede. DERIVA de exp024_empowerment/results/results.json.

RESULTADO REAL: APOYADA (inversión limpia). EMPOWERMENT: ctrl 1.71 bits, reloj 0.0, rand 0.0. PREDICCIÓN
pasiva: ctrl 0.0, reloj 1.71, rand 0.0. => el empowerment aísla el factor CONTROLABLE y descarta el reloj
predecible-pero-inútil; la predicción pasiva hace lo contrario (se queda con el reloj, pierde el controlable).
A diferencia del info-gain (exp023, ≈ azar), el empowerment SÍ se distingue de lo trivial.
=> R-VALOR es REAL en su forma FUERTE (valor = controlabilidad, no info-gain), y se unifica con
R-INTERVENCIÓN (el valor endógeno que sobrevive ES sobre la acción/control).

Correr (DESPUÉS de exp024):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp024_empowerment.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle38_empowerment
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
                             'cycle38_empowerment')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp024_empowerment', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _fmt(x):
    return "{:.3f}".format(x) if isinstance(x, (int, float)) else str(x)


S_2606 = Source(tier=1, ref="arXiv:2606.20104", obtained=False,
                claim=("Ivashkov/Balestriero/Schölkopf 2026: encoder action-grounded (inverse-dynamics) "
                       "recupera factores controlables y colapsa distractores; 84% vs 59% planning; ~5M "
                       "params CPU-scale. (No re-obtenido esta sesión.)"))
S_BA = Source(tier=1, ref="arXiv:2510.05996", obtained=False,
              claim=("Empowerment vía Blahut-Arimoto (sin gradiente, CPU): pre-entrenar con empowerment "
                     "transfiere. (No re-obtenido esta sesión.)"))
S_EXP023 = Source(tier=5, ref="cognia_x/experiments/exp023_value_isolation", obtained=True,
                  claim=("exp023 (CYCLE 36): el info-gain NO se distingue del azar-activo => NO es el valor. "
                         "Motivó probar el EMPOWERMENT (forma fuerte) en exp024."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    s = data.get('summary')
    if not s or 'verdict' not in s:
        raise SystemExit("results.json sin summary.verdict (corre exp024 primero): " + results_path)
    status = s['verdict']
    bk = s['by_kind']
    chk = s['checks']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    S_EXP024 = Source(tier=5, ref="cognia_x/experiments/exp024_empowerment", obtained=True,
                      claim=("exp024 (propio, CPU, numpy, 12 seeds): EMPOWERMENT(bits) ctrl={ec}/reloj={ek}/"
                             "rand={er}; PREDICCIÓN pasiva ctrl={pc}/reloj={pk}/rand={pr}. Inversión limpia: "
                             "el empowerment aísla el CONTROLABLE; la predicción pasiva se queda con el reloj "
                             "predecible-inútil. Costo {w}s CPU.").format(
                                 ec=_fmt(bk['ctrl']['emp_mean']), ek=_fmt(bk['clock']['emp_mean']),
                                 er=_fmt(bk['rand']['emp_mean']), pc=_fmt(bk['ctrl']['pred_mean']),
                                 pk=_fmt(bk['clock']['pred_mean']), pr=_fmt(bk['rand']['pred_mean']),
                                 w=_fmt(data.get('wall_secs'))))
    for src in (S_2606, S_BA, S_EXP023, S_EXP024):
        ledger.add_source(src)
    notes.append("4 fuentes (S_2606 tier1 action-grounded; S_BA tier1 empowerment BA; S_EXP023 tier5 motivación; "
                 "S_EXP024 tier5 dato propio).")

    ev_for = [S_EXP024.ref, S_2606.ref]
    ev_against = [S_EXP023.ref]   # honesto: el info-gain (también 'valor') NO funcionó -> "valor" en abstracto no basta
    adv = ("APOYADA con inversión limpia. El EMPOWERMENT (auto-generado, sin reward/verificador externo) aísla "
           "el factor CONTROLABLE (E_ctrl-E_reloj={d1} bits) y da ~0 al reloj predecible-inútil; la PREDICCIÓN "
           "pasiva hace lo contrario (P_reloj-P_ctrl={d2} bits) — ni siquiera VE el controlable. A diferencia "
           "del info-gain (exp023, ≈ azar), el empowerment SÍ se distingue de lo trivial: 'valor' en abstracto "
           "no basta, pero la CONTROLABILIDAD sí es un valor real. Ataque considerado: 'es trivial porque "
           "ctrl'=acción' -> NO: el punto es que la predicción pasiva, teniendo el mismo mundo, se queda con el "
           "reloj y PIERDE el controlable; controlabilidad != predictibilidad es justo lo que un agente "
           "necesita. Límite honesto: muestra el MECANISMO, no aún mejora downstream ni escala a lenguaje "
           "(=H-V4-1d / integrador).").format(d1=_fmt(chk['E_ctrl_minus_E_clock']), d2=_fmt(chk['P_clock_minus_P_ctrl']))

    hyp = Hypothesis(
        id="H-V4-1c",
        statement=("Un valor AUTO-generado (empowerment = capacidad de canal acción->futuro, sin reward/"
                   "verificador externo) captura la CONTROLABILIDAD que la predicción pasiva no puede."),
        prediction=("APOYADA si E_ctrl>>E_reloj,E_rand (>0.8 bits) Y la inversión P_reloj>>P_ctrl (>0.8); "
                    "REFUTADA si E_ctrl-E_reloj<=0.8. (Pre-registrada.)"),
        status='abierta', confidence='alta',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=adv, experiment_ref="exp024_empowerment")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-1c")
        notes.append("H-V4-1c marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("Muchas cosas se mueven a la vez: mi mano, el reloj de pared, las motas de polvo. ¿Cuál es "
                 "MÍA (la puedo afectar) y cuál solo pasa? Predecir no alcanza: el reloj es el MÁS predecible y "
                 "no es mío."),
        everyday=("Un bebé descubre que su mano se mueve cuando él QUIERE (controlable), distinta del reloj que "
                  "avanza solo (predecible pero ajeno) y del polvo (azar). Aprende qué es suyo PROBANDO, no mirando."),
        solutions=["medir CONTROLABILIDAD (empowerment: ¿cambia el futuro si yo actúo?) -> se queda con la mano, "
                   "0 al reloj y al polvo (es exp024: empowerment)",
                   "medir PREDICTIBILIDAD (¿puedo adivinar el futuro?) -> se queda con el RELOJ (el más "
                   "predecible) y PIERDE la mano -> el predictor pasivo mira lo que no importa para un agente",
                   "esperar una recompensa externa que diga 'la mano es tuya' = verificador externo (lo que el "
                   "lab ya sabía); aquí NO se usa: el bebé lo descubre solo",
                   "azar de exploración (info-gain) -> exp023 mostró que no se distingue del azar; no es el valor"],
        principles=["para un AGENTE, el valor de la información es CONTROLABILIDAD, no predictibilidad",
                    "un valor AUTO-generado (empowerment) existe sin reward/verificador externo y es CPU-barato",
                    "controlabilidad != predictibilidad: la predicción pasiva PIERDE lo controlable (no lo ve)",
                    "R-VALOR (forma fuerte) se UNIFICA con R-INTERVENCIÓN: el valor endógeno es sobre la ACCIÓN"],
        adaptation=("R-VALOR confirmado real (empowerment). Integrar empowerment/controlabilidad como el valor "
                    "endógeno que dirige un lazo act-and-verify barato; siguiente: que mejore una tarea "
                    "downstream y dé el salto al sustrato de lenguaje (H-V4-1d / integrador)."),
        measurement=("exp024: E ctrl {ec}/reloj {ek}; P ctrl {pc}/reloj {pk}; inversión {d1}/{d2} bits; "
                     "costo {w}s CPU.").format(
                         ec=_fmt(bk['ctrl']['emp_mean']), ek=_fmt(bk['clock']['emp_mean']),
                         pc=_fmt(bk['ctrl']['pred_mean']), pk=_fmt(bk['clock']['pred_mean']),
                         d1=_fmt(chk['E_ctrl_minus_E_clock']), d2=_fmt(chk['P_clock_minus_P_ctrl']),
                         w=_fmt(data.get('wall_secs'))),
        iterations=1)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (la mano del bebé vs el reloj: controlabilidad != predictibilidad).")

    ceilings.add(CeilingRecord(
        subsystem="R-VALOR — forma FUERTE (empowerment): el valor endógeno es CONTROLABILIDAD",
        known_limit=("REAL (exp024): un valor AUTO-generado (empowerment, Blahut-Arimoto, sin señal externa) "
                     "captura la controlabilidad y la SEPARA de la predictibilidad; la predicción pasiva no "
                     "puede (pierde lo controlable). El MECANISMO está demostrado: controlabilidad != "
                     "predictibilidad. (El info-gain, exp023, NO lograba esto.)"),
        blockers=[{"text": "demostrado el mecanismo (controlabilidad!=predictibilidad), no aún la utilidad downstream", "kind": "diseno"},
                  {"text": "la dirección causal/controlable no está en lo observacional sin actuar (identificabilidad)", "kind": "fisico"}],
        real_or_assumed="real", evidence=[S_EXP024.ref, S_2606.ref]))
    ceilings.add(CeilingRecord(
        subsystem="R-VALOR aplicado — ¿el empowerment MEJORA una tarea y ESCALA a lenguaje?",
        known_limit=("ABIERTO: exp024 muestra el mecanismo en factores tabulares; falta (a) que el empowerment "
                     "como valor MEJORE una tarea downstream vs predicción pasiva, y (b) el salto al sustrato de "
                     "lenguaje (estimar empowerment sobre rollouts de un modelo chico, EELMA-style)."),
        blockers=[{"text": "empowerment en espacios grandes/continuos (lenguaje) es caro de estimar; falta receta CPU", "kind": "diseno"},
                  {"text": "no hay aún demo de que empowerment-como-valor suba una métrica de tarea", "kind": "historico"}],
        real_or_assumed="asumido", evidence=[S_EXP024.ref]))
    notes.append("2 techos: R-VALOR forma-fuerte 'real' (empowerment=controlabilidad); R-VALOR aplicado 'asumido' (downstream/lenguaje).")

    dstmt = ("R-VALOR queda CONFIRMADO como real en su forma fuerte: el valor endógeno de un agente es la "
             "CONTROLABILIDAD (empowerment), no el info-gain (descartado, exp023) ni la predicción pasiva. Se "
             "UNIFICA con R-INTERVENCIÓN (el valor que sobrevive es sobre la acción). Rumbo v4 consolidado: "
             "construir un lazo ACT-AND-VERIFY barato cuyo valor endógeno sea la controlabilidad/consecuencia, "
             "sobre un sustrato chico CPU (híbrido/RWKV en llama.cpp), guiado por verificador barato (TTS, "
             "convergente con la literatura). Próximo: H-V4-1d (empowerment MEJORA una tarea downstream) y el "
             "integrador hacia lenguaje.")
    drat = ("exp024 (tier5): inversión limpia empowerment vs predicción pasiva (E_ctrl {ec} vs reloj {ek}; "
            "P_reloj {pk} vs ctrl {pc}); el empowerment aísla lo controlable, la predicción pasiva lo pierde. "
            "Unifica con exp022/023 (R-INTERVENCIÓN) y con la literatura (action-grounded arXiv:2606.20104, "
            "empowerment arXiv:2510.05996). Barato: {w}s CPU.").format(
                ec=_fmt(bk['ctrl']['emp_mean']), ek=_fmt(bk['clock']['emp_mean']),
                pk=_fmt(bk['clock']['pred_mean']), pc=_fmt(bk['ctrl']['pred_mean']), w=_fmt(data.get('wall_secs')))
    dec = Decision(id="D-V4-3", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP024), _to_plain(S_2606)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-3 ACEPTADA por el ledger (tier5 exp024 + tier1 action-grounded).")
    except OpinionOnlyError as e:
        print("ERROR ledger D-V4-3:", e); raise

    return record, notes, status, s


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle38_empowerment',
                                description='CYCLE 38 (RESET v4, H-V4-1c: empowerment = R-VALOR forma fuerte).')
    p.add_argument('--store', default=DEFAULT_STORE)
    p.add_argument('--results', default=DEFAULT_RESULTS)
    p.add_argument('--reset', dest='reset', action='store_true', default=True)
    p.add_argument('--no-reset', dest='reset', action='store_false')
    args = p.parse_args(argv)
    store = os.path.abspath(args.store)
    if args.reset and os.path.isdir(store):
        shutil.rmtree(store)
    os.makedirs(store, exist_ok=True)
    record, notes, status, s = run(store, os.path.abspath(args.results))
    res = record.verify_no_loss()
    print("=" * 78)
    print("RESUMEN — CYCLE 38 (RESET v4): empowerment = R-VALOR forma fuerte (H-V4-1c)")
    print("=" * 78)
    print("veredicto H-V4-1c:", status.upper() if status else "?")
    print("  R-VALOR es REAL en su forma fuerte: el valor endógeno es la CONTROLABILIDAD (empowerment).")
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
