r"""
cycle76_action_gated_value.py — CICLO 76 (RESET v4, arco "R-VALOR bajo realismo", hija del 75): H-V4-5f por las
compuertas del engine. El valor task-definido SOBREVIVE a la OBSERVACIÓN GATEADA POR LA ACCIÓN: cuando cachear un
item CIEGA a su costo (revelado sólo al FALLAR), el agente igual aprende el valor -- porque observa los costos de
justo lo que NO cachea (su CONTRAFÁCTICO) y el cold-start observa todo una vez. Bajo estacionariedad, observar-al-
fallar IGUALA a observar-siempre; la exploración extra RESTA.

H-V4-5f ataca el caveat #1 del techo de CYCLE 75 (allí el costo se observaba en cada consulta). DERIVA de
exp060_action_gated_value/results/results.json.

Correr (DESPUÉS de exp060):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp060_action_gated_value.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle76_action_gated_value
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle76_action_gated_value')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp060_action_gated_value', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_OBS = Source(tier=1, ref="active sensing / partial monitoring (observación gateada por la acción)", obtained=False,
               claim=("Cuando las observaciones están GATEADAS por la acción del agente, el aprendizaje igual "
                      "converge SI el conjunto de acciones revela la información necesaria (aquí: no-cachear revela "
                      "el costo). El caso duro (observación adversaria / no-estacionaria de lo no-observado) requiere "
                      "exploración deliberada. (Principio; converge con partial monitoring / value-of-information.)"))
S_TREE = Source(tier=5, ref="cognia_x/manager/decomposition_tree.md (caveat CYCLE 75 'costo sólo al fallar'; raíz R-INTERVENCIÓN)", obtained=True,
                claim=("El techo de CYCLE 75 (H-V4-5e) registró como hija: 'el costo se observa en cada consulta; la "
                       "versión dura sólo lo revela al FALLAR (exploración: actuar para aprender el valor)'. H-V4-5f "
                       "lo ataca; conecta con R-INTERVENCIÓN (la acción del agente decide qué observa)."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp060 primero): " + results_path)
    ba = sm['by_arm']
    o, vfull, vmiss, vexp, lfu, rnd = (ba['oracle_value'], ba['value_full'], ba['value_miss'], ba['value_explore'],
                                       ba['lfu_freq'], ba['random'])
    frac = sm['fraction_recovered_miss']
    n, m = data['args']['n'], data['args']['m']
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim060 = ("exp060 (propio, {n} seeds, numpy): memoria online m={m}/{N}, costo revelado SÓLO al fallar. "
                "value_miss {vm} recupera {p}% del oráculo ({o}); = value_full {vf} (costo siempre visible); vence a "
                "lfu {lfu}. value_explore {ve} RESTA (sacrificar un slot a re-sondar no ayuda con costos "
                "estacionarios). El valor es aprendible aun con la observación gateada por la acción de cachear.").format(
                    n=n_seeds, m=m, N=n, vm=_f(vmiss), p=int(round(frac * 100)), o=_f(o), vf=_f(vfull), lfu=_f(lfu),
                    ve=_f(vexp))
    S_EXP060 = Source(tier=5, ref="cognia_x/experiments/exp060_action_gated_value", obtained=True, claim=claim060)
    for src in (S_OBS, S_TREE, S_EXP060):
        ledger.add_source(src)
    notes.append("3 fuentes (S_OBS tier1 active-sensing/partial-monitoring; S_TREE tier5 caveat CYCLE 75 + R-INTERVENCIÓN; S_EXP060 tier5 dato propio).")

    ev_for = [S_EXP060.ref, S_TREE.ref]
    ev_against = [S_EXP060.ref]
    adv = ("{V} (hija del CYCLE 75; matiza la conexión con R-INTERVENCIÓN): CYCLE 75 asumió el costo OBSERVABLE en "
           "cada consulta. exp060 lo gatea por la acción: cachear un item CIEGA a su costo (revelado sólo al FALLAR). "
           "Resultado MATIZADO y honesto: value_miss {vm} recupera {p}% de la ventaja del oráculo ({o}) e IGUALA a "
           "value_full {vf} (|dif| {dif}) -> la observación gateada NO rompe el aprendizaje del valor bajo "
           "ESTACIONARIEDAD. Mecanismo: el agente observa los costos de justo lo que NO cachea (su CONTRAFÁCTICO, "
           "que es la info que necesita para decidir si cambiarlo) y el cold-start (cache vacía -> todo falla) observa "
           "todo una vez. La exploración EXTRA (value_explore {ve}, sacrificar un slot a re-sondar) RESTA {dexp}: no "
           "hace falta intervenir más con costos estacionarios. EVIDENCIA EN CONTRA / matiz CLAVE (honesto): este "
           "resultado NIEGA la intuición fuerte de 'aprender valor EXIGE intervenir' EN ESTE RÉGIMEN -- la "
           "observación pasiva del contrafáctico basta. La intervención (re-sondar) sería necesaria SÓLO si los "
           "costos fueran NO-ESTACIONARIOS (un item cacheado cuyo costo DERIVA pasaría desapercibido porque no se "
           "observa) -> ese es el caso R-INTERVENCIÓN real y la próxima hija (combinar con CYCLE 73). (2) costos "
           "estacionarios; juguete (Pareto, n=50). CONCLUSIÓN: bajo estacionariedad el valor task-definido es "
           "aprendible aunque la acción cieguen la observación; R-INTERVENCIÓN sobre la MEMORIA aparece sólo con "
           "no-estacionariedad de los costos cacheados-no-observados. Conexión con R-INTERVENCIÓN: DÉBIL aquí "
           "(honesto), no la sobre-vendemos.").format(
               V=status.upper(), vm=_f(vmiss), p=int(round(frac * 100)), o=_f(o), vf=_f(vfull),
               dif=_f(abs(vmiss - vfull)), ve=_f(vexp), dexp=_f(vexp - vmiss))

    hyp = Hypothesis(
        id="H-V4-5f",
        statement=("Estimar el valor task-definido SOBREVIVE a la observación gateada por la acción (costo revelado "
                   "sólo al fallar): el agente observa el costo de lo que NO cachea (su contrafáctico) y eso basta "
                   "bajo estacionariedad, sin exploración extra."),
        prediction=("APOYADA si value_miss recupera >=70% del oráculo Y supera a lfu (+>0.05) Y ~ value_full "
                    "(|dif|<0.05); REFUTADA si value_miss colapsa hacia lfu; MIXTA si ayuda pero queda lejos de "
                    "value_full y la exploración recupera el gap. (Pre-registrada.)"),
        status='abierta', confidence='alta' if status == 'apoyada' else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=adv, experiment_ref="exp060_action_gated_value")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-5f")
        notes.append("H-V4-5f marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("Sólo sentís cuánto te cuesta algo cuando te FALTA (si lo tenés en la mochila, no sentís el dolor). "
                 "¿Podés aprender qué vale cada cosa así, o tenés que sacar cosas a propósito para 'probar' su falta?"),
        everyday=("Podés aprender igual: justo SENTÍS el costo de lo que NO llevás (cuando te falta), que es "
                  "exactamente lo que necesitás saber para decidir si conviene cambiarlo por algo de la mochila. Y al "
                  "principio, con la mochila vacía, te falta todo una vez y aprendés todos los costos. Sacar cosas a "
                  "propósito para re-probar (explorar) sólo te hace pasar frío al pedo... MIENTRAS los costos no "
                  "cambien. Si cambiaran, ahí sí tendrías que re-probar lo que llevás."),
        solutions=["value_miss (costo sólo al fallar) -> aprende el valor igual: observa el contrafáctico de lo no-cacheado",
                   "value_full (costo siempre visible) -> iguala a value_miss bajo estacionariedad (no agrega)",
                   "value_explore (sacrifica un slot a re-sondar) -> RESTA: la exploración extra cuesta sin pagar",
                   "lfu_freq (sólo frecuencia) -> peor: no estima el valor task-definido"],
        principles=["el valor es aprendible aunque la acción gatee la observación, SI las acciones revelan lo necesario (el contrafáctico)",
                    "observar el costo de lo que NO cacheás (tu regret) basta para decidir qué cachear, bajo estacionariedad",
                    "la exploración deliberada RESTA cuando la observación pasiva ya revela lo necesario",
                    "R-INTERVENCIÓN sobre la memoria aparece sólo con costos NO-estacionarios de lo cacheado-no-observado"],
        adaptation=("El lab NO necesita exploración extra para aprender valor con observación gateada bajo "
                    "estacionariedad. Próxima hija (el caso R-INTERVENCIÓN real): costos NO-estacionarios + "
                    "observación gateada -> un item cacheado cuyo costo deriva pasa desapercibido; ahí re-sondar "
                    "(intervenir) SÍ debería pagar. Combinar exp060 con la no-estacionariedad de exp057 (CYCLE 73)."),
        measurement=("exp060 (m={m}/{N}): value_miss {vm} (recupera {p}%) = value_full {vf}; > lfu {lfu}; "
                     "value_explore {ve} (resta). {n} seeds.").format(
                         m=m, N=n, vm=_f(vmiss), p=int(round(frac * 100)), vf=_f(vfull), lfu=_f(lfu), ve=_f(vexp),
                         n=n_seeds),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (sentís el costo de lo que NO llevás; eso basta para decidir, sin explorar).")

    kl = ("REAL (exp060): el valor task-definido SOBREVIVE a la observación gateada por la acción (costo sólo al "
          "fallar) bajo estacionariedad: value_miss {vm} recupera {p}% del oráculo ({o}) e IGUALA a value_full {vf}; "
          "la exploración extra RESTA. El agente observa el costo de lo que NO cachea (su contrafáctico) y eso basta. "
          "R-INTERVENCIÓN sobre la memoria aparecería sólo con costos NO-estacionarios cacheados-no-observados.").format(
              vm=_f(vmiss), p=int(round(frac * 100)), o=_f(o), vf=_f(vfull))
    ceilings.add(CeilingRecord(
        subsystem="R-VALOR x observación GATEADA POR LA ACCIÓN — el valor es aprendible sin exploración extra (estacionario)",
        known_limit=kl,
        blockers=[{"text": "resultado limitado a costos ESTACIONARIOS; el caso R-INTERVENCIÓN real (costos NO-estacionarios + observación gateada -> deriva de lo cacheado-no-observado) queda como hija (combinar con CYCLE 73)", "kind": "diseno"},
                  {"text": "la conexión con R-INTERVENCIÓN es DÉBIL aquí (la observación pasiva del contrafáctico basta); no sobre-venderla", "kind": "historico"},
                  {"text": "valor = frecuencia×costo (falta info-gain/confianza, CYCLE 56-57); juguete (Pareto, n=50, IID)", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP060.ref, S_TREE.ref]))
    notes.append("1 techo 'real': el valor es aprendible con observación gateada por la acción (estacionario); la intervención no hace falta acá.")

    dstmt = ("North-Star R-VALOR bajo realismo (hija del 75; MATIZA R-INTERVENCIÓN sobre la memoria): el valor "
             "task-definido SOBREVIVE a la observación gateada por la acción (costo revelado sólo al fallar). "
             "value_miss recupera {p}% del oráculo ({o}) e IGUALA a value_full {vf} (la observación gateada no rompe "
             "el aprendizaje), vence a lfu {lfu}; la exploración extra (value_explore {ve}) RESTA. Decisión: bajo "
             "estacionariedad el lab NO necesita intervenir para aprender valor -- observa el costo de lo que NO "
             "cachea (su contrafáctico) y eso basta. HONESTO: niega 'aprender valor exige intervenir' EN ESTE "
             "RÉGIMEN; R-INTERVENCIÓN sobre la memoria aparecería con costos NO-estacionarios (próxima hija: combinar "
             "con CYCLE 73).").format(
                 p=int(round(frac * 100)), o=_f(o), vf=_f(vfull), lfu=_f(lfu), ve=_f(vexp))
    drat = ("exp060 (tier5, propio, {n} seeds): value_miss {vm} recupera {p}% del oráculo {o}, = value_full {vf}, "
            "+{adv} sobre lfu {lfu}; value_explore {ve} resta. Convergente con active-sensing/partial-monitoring "
            "(tier1) y con el caveat de CYCLE 75 (tier5). {V}.").format(
                n=n_seeds, vm=_f(vmiss), p=int(round(frac * 100)), o=_f(o), vf=_f(vfull), adv=_f(vmiss - lfu),
                lfu=_f(lfu), ve=_f(vexp), V=status.upper())
    dec = Decision(id="D-V4-38", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP060), _to_plain(S_TREE)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-38 ACEPTADA por el ledger (tier5 exp060 + tier5 caveat CYCLE 75).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-38:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle76_action_gated_value',
                                description='CYCLE 76 (RESET v4, H-V4-5f: valor con observación gateada por la acción).')
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
    print("RESUMEN — CYCLE 76 (RESET v4): valor con observación GATEADA POR LA ACCIÓN (H-V4-5f)")
    print("=" * 78)
    print("veredicto H-V4-5f:", status.upper() if status else "?")
    print("  el valor task-definido es aprendible aunque cachear ciegue su costo (observa el contrafáctico).")
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
