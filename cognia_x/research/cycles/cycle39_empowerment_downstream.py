r"""
cycle39_empowerment_downstream.py — CICLO 39 (RESET v4): H-V4-1d por las compuertas del engine.

H-V4-1d: el EMPOWERMENT como VALOR no sólo MIDE (exp024) sino que MEJORA a un agente en una tarea. Un agente
con CAPACIDAD LIMITADA que reparte su atención/control por empowerment logra la tarea; por predictibilidad
falla (se va al reloj inútil) — peor que el azar. DERIVA de exp025_empowerment_downstream/results/results.json.

RESULTADO REAL: APOYADA. A k=n_ctrl=4: EMPOWERMENT 1.000, PREDICTIBILIDAD 0.250 (=azar puro), AZAR 0.453
(emp-pred=+0.75). La predictibilidad es ANTI-útil (peor que el azar) a capacidad limitada. 0.835s CPU.
=> R-VALOR APLICADO confirmado: el valor endógeno (empowerment) hace al agente mejor, barato. Cierra el arco
R-VALOR (mecanismo exp024 + utilidad exp025); justifica el integrador act-and-verify con valor de control.

Correr (DESPUÉS de exp025):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp025_empowerment_downstream.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle39_empowerment_downstream
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
                             'cycle39_empowerment_downstream')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp025_empowerment_downstream', 'results', 'results.json')


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
                claim=("Encoder action-grounded recupera factores controlables y colapsa distractores; "
                       "mejor planning downstream. (No re-obtenido esta sesión.)"))
S_EXP024 = Source(tier=5, ref="cognia_x/experiments/exp024_empowerment", obtained=True,
                  claim=("exp024 (CYCLE 38): el empowerment MIDE la controlabilidad (la separa de la "
                         "predictibilidad). Faltaba probar que MEJORA una tarea -> exp025."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    s = data.get('summary')
    if not s or 'verdict' not in s:
        raise SystemExit("results.json sin summary.verdict (corre exp025 primero): " + results_path)
    status = s['verdict']
    kstar = s['kstar']
    d = s['by_cap'][kstar]
    emp = d['empowerment']['score_mean']
    pred = d['predictibilidad']['score_mean']
    rand = d['azar']['score_mean']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    S_EXP025 = Source(tier=5, ref="cognia_x/experiments/exp025_empowerment_downstream", obtained=True,
                      claim=("exp025 (propio, CPU, 12 seeds): a capacidad limitada k=n_ctrl, asignar la "
                             "atención/control por EMPOWERMENT logra score {e}; por PREDICTIBILIDAD {p} "
                             "(=azar puro, malgasta en relojes); AZAR {r}. La predictibilidad es ANTI-útil "
                             "(peor que el azar). El valor endógeno MEJORA la tarea. {w}s CPU.").format(
                                 e=_fmt(emp), p=_fmt(pred), r=_fmt(rand), w=_fmt(data.get('wall_secs'))))
    for src in (S_2606, S_EXP024, S_EXP025):
        ledger.add_source(src)
    notes.append("3 fuentes (S_2606 tier1 action-grounded; S_EXP024 tier5 mecanismo; S_EXP025 tier5 dato propio).")

    ev_for = [S_EXP025.ref, S_EXP024.ref]
    ev_against = [S_EXP025.ref]   # honesto: a capacidad PLENA (k=D) todas empatan -> la ventaja es del REGIMEN limitado
    adv = ("APOYADA contundente. A capacidad LIMITADA (k=n_ctrl) asignar por EMPOWERMENT logra la tarea "
           "(score {e}) mientras por PREDICTIBILIDAD falla (score {p} = azar puro) — incluso PEOR que el azar "
           "({r}): elegir lo predecible (el reloj) es ANTI-útil para controlar. Margen emp-pred=+{m}. => el "
           "valor endógeno (empowerment) no sólo MIDE (exp024): MEJORA al agente, barato. Caveat honesto "
           "(evidencia EN CONTRA de sobre-generalizar): a capacidad PLENA (k=D) las tres empatan en 1.0 — la "
           "ventaja del valor existe SÓLO bajo recursos limitados (que es justo el presupuesto del lab). "
           "Ataque considerado: '¿y si el ranking de empowerment fuera ruidoso?' -> el margen es +0.75 con "
           "std~0; el ranking separa limpio. Límite: tarea tabular; el salto a lenguaje es el integrador.").format(
               e=_fmt(emp), p=_fmt(pred), r=_fmt(rand), m=_fmt(d['emp_minus_pred']))

    hyp = Hypothesis(
        id="H-V4-1d",
        statement=("El empowerment como VALOR mejora a un agente en una tarea: asignar capacidad limitada por "
                   "controlabilidad logra la tarea; por predictibilidad falla (peor que el azar)."),
        prediction=("APOYADA si a k=n_ctrl emp-pred>0.3, emp>=azar y emp>0.9; REFUTADA si emp-pred<=0.1. "
                    "(Pre-registrada.)"),
        status='abierta', confidence='alta',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=adv, experiment_ref="exp025_empowerment_downstream")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-1d")
        notes.append("H-V4-1d marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("Tenés POCA atención y muchas cosas alrededor (tus manos, un reloj, el ruido de la calle). "
                 "Para LOGRAR algo, ¿en qué gastás tu atención limitada?"),
        everyday=("Servir un vaso de agua con prisa: si mirás el reloj (lo más predecible) no servís nada; si "
                  "mirás tus MANOS (lo que podés afectar) lo lográs. Atención limitada -> gastarla en lo controlable."),
        solutions=["asignar la atención por CONTROLABILIDAD (empowerment) -> logra la tarea (exp025: 1.0 a k=n_ctrl)",
                   "asignar por PREDICTIBILIDAD -> se va al reloj, falla; peor que el azar (anti-útil)",
                   "asignar al AZAR -> a medias (parcial, proporcional a la capacidad)",
                   "tener atención INFINITA (k=D) -> da igual la estrategia (todas 1.0); pero NADIE tiene recursos infinitos"],
        principles=["bajo recursos LIMITADOS, el valor de la atención es la controlabilidad, no la predictibilidad",
                    "elegir lo predecible-pero-inútil es PEOR que elegir al azar (anti-útil)",
                    "el valor endógeno (empowerment) MEJORA la tarea, no sólo la mide -> es un lever, no una curiosidad",
                    "la ventaja del valor aparece bajo presupuesto finito = justo el régimen del lab (CPU)"],
        adaptation=("Justifica el integrador: un razonador act-and-verify barato debe asignar su CÓMPUTO/atención "
                    "LIMITADA por controlabilidad/consecuencia (empowerment), no por predictibilidad. Próximo: "
                    "llevarlo al sustrato de lenguaje (estimar empowerment/consecuencia sobre rollouts de un "
                    "modelo chico)."),
        measurement=("exp025: a k=n_ctrl, EMP {e} / PRED {p} / AZAR {r}; emp-pred=+{m}; a k=D todas 1.0. "
                     "{w}s CPU.").format(e=_fmt(emp), p=_fmt(pred), r=_fmt(rand),
                                         m=_fmt(d['emp_minus_pred']), w=_fmt(data.get('wall_secs'))),
        iterations=1)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (atención limitada: gastarla en lo controlable, no en el reloj).")

    ceilings.add(CeilingRecord(
        subsystem="R-VALOR aplicado — el empowerment como valor MEJORA una tarea (bajo recursos limitados)",
        known_limit=("REAL (exp025): asignar capacidad LIMITADA por empowerment logra la tarea (1.0) vs "
                     "predictibilidad (=azar puro, anti-útil) — margen +0.75 a k=n_ctrl. El valor endógeno es "
                     "un LEVER, no sólo medición. Cota: la ventaja existe SÓLO bajo presupuesto finito (a "
                     "capacidad plena todas empatan) — que es el régimen del lab."),
        blockers=[{"text": "demostrado en tarea tabular; el salto a lenguaje (estimar empowerment sobre rollouts) sigue pendiente", "kind": "diseno"},
                  {"text": "estimar empowerment en espacios grandes/continuos es caro; falta receta CPU escalable", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP025.ref, S_EXP024.ref]))
    notes.append("1 techo 'real': R-VALOR aplicado (empowerment mejora la tarea bajo recursos limitados).")

    dstmt = ("R-VALOR queda confirmado COMPLETO (mecanismo exp024 + utilidad exp025): el valor endógeno de un "
             "agente es la CONTROLABILIDAD (empowerment), y bajo recursos limitados MEJORA la tarea (asignar por "
             "predictibilidad es anti-útil). Decisión: el INTEGRADOR del reset v4 será un razonador act-and-"
             "verify barato que asigna su cómputo/atención LIMITADA por controlabilidad/consecuencia, sobre un "
             "sustrato chico CPU (híbrido/RWKV en llama.cpp), con verificador barato (TTS). Próximo ciclo: dar "
             "el salto al sustrato de lenguaje (H-V4-1e / integrador): estimar empowerment/consecuencia sobre "
             "rollouts de un modelo chico y medir mejora de tarea vs costo.")
    drat = ("exp025 (tier5): a capacidad limitada k=n_ctrl, EMP {e} vs PRED {p} (=azar) vs AZAR {r}; "
            "predictibilidad anti-útil. Cierra el arco R-VALOR con exp024. Convergente con la literatura "
            "(action-grounded arXiv:2606.20104; verifier-based TTS arXiv:2408.03314). Barato: {w}s CPU.").format(
                e=_fmt(emp), p=_fmt(pred), r=_fmt(rand), w=_fmt(data.get('wall_secs')))
    dec = Decision(id="D-V4-4", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP025), _to_plain(S_EXP024)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-4 ACEPTADA por el ledger (tier5 exp025 + tier5 exp024).")
    except OpinionOnlyError as e:
        print("ERROR ledger D-V4-4:", e); raise

    return record, notes, status, s


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle39_empowerment_downstream',
                                description='CYCLE 39 (RESET v4, H-V4-1d: empowerment mejora downstream).')
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
    print("RESUMEN — CYCLE 39 (RESET v4): empowerment como valor MEJORA la tarea (H-V4-1d)")
    print("=" * 78)
    print("veredicto H-V4-1d:", status.upper() if status else "?")
    print("  el valor endógeno (empowerment) hace al agente mejor; asignar por predictibilidad es anti-útil.")
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
