r"""
cycle36_value_isolation.py — CICLO 36 (RESET v4): H-V4-1b por las compuertas del engine.

H-V4-1b: ¿el VALOR endógeno (info-gain) está AISLADO de la "intervención activa per se"? En un régimen
DURO (D=40, clúster=8, ruido 0.25) donde el azar NO cubre por fuerza bruta, ¿info-gain > azar-activo?

DERIVA de exp023_value_isolation/results/results.json. RESULTADO REAL: MIXTA, inclinada a refutar el
valor-como-info-gain. Los márgenes B-C oscilan alrededor de 0 (media +0.004; único pico K=16 +0.099 dentro
del ruido std~0.18 y contradicho en K=32). Lo ROBUSTO es ACTUAR>>observar (C-A=+0.07..+0.36; A plano).
=> el lever demostrado es la INTERVENCIÓN, NO el valor info-gain diseñado. R-INTERVENCIÓN reforzada (real);
R-VALOR sigue 'asumido' y se reorienta: info-gain NO es buen proxy del valor; el siguiente intento debe ser
un valor AUTO-generado (homeostasis/empowerment) o pivotar a EXPLOTAR R-INTERVENCIÓN (act-and-verify, que el
lab ya apoya: exp016-018 H-LEARN-1).

Correr (DESPUÉS de exp023):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp023_value_isolation.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle36_value_isolation
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
                             'cycle36_value_isolation')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp023_value_isolation', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _fmt(x):
    return "{:.3f}".format(x) if isinstance(x, (int, float)) else str(x)


S_BALD = Source(tier=1, ref="arXiv:1112.5745 (Houlsby et al. 2011, BALD)", obtained=False,
                claim=("Active learning bayesiano por information-gain. Hipótesis: debería superar al "
                       "muestreo aleatorio. (No re-obtenido esta sesión.)"))
S_EXP022 = Source(tier=5, ref="cognia_x/experiments/exp022_endogenous_value", obtained=True,
                  claim=("exp022 (CYCLE 35): demostró R-INTERVENCIÓN (activo>>pasivo, muro informacional) "
                         "pero NO aisló el valor (azar-activo alcanzaba a info-gain). Generó H-V4-1b."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    s = data.get('summary')
    if not s or 'verdict' not in s:
        raise SystemExit("results.json sin summary.verdict (corre exp023 primero): " + results_path)
    status = s['verdict']
    vi = s['value_isolation']
    Kmax = str(max(s['budgets']))
    A_max = s['by_budget'][Kmax]['A_pasivo']['interv_mean']
    B_max = s['by_budget'][Kmax]['B_infogain']['interv_mean']
    C_max = s['by_budget'][Kmax]['C_aleatorio']['interv_mean']
    cost = s.get('cost', {})

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    S_EXP023 = Source(tier=5, ref="cognia_x/experiments/exp023_value_isolation", obtained=True,
                      claim=("exp023 (propio, CPU, 24 seeds, régimen DURO D=40/clúster=8/ruido=0.25): el "
                             "info-gain NO supera de forma robusta al azar-activo (margen B-C medio "
                             "{mm}, máx {mx} en un solo presupuesto dentro del ruido). Lo robusto: "
                             "ACTUAR>>observar (A pasivo ~{a}; activos ->{b}/{c}). Costo: {n} modelos "
                             "causales en {w}s CPU.").format(
                                 mm=_fmt(vi['mean_margin']), mx=_fmt(vi['max_margin']), a=_fmt(A_max),
                                 b=_fmt(B_max), c=_fmt(C_max), n=cost.get('total_agent_runs'),
                                 w=cost.get('wall_secs_all_agent_runs')))
    for src in (S_BALD, S_EXP022, S_EXP023):
        ledger.add_source(src)
    notes.append("3 fuentes (S_BALD tier1 info-gain hipótesis; S_EXP022 tier5 padre; S_EXP023 tier5 dato propio).")

    ev_for = [S_EXP023.ref]      # un pico aislado (K=16) + ambos activos >> pasivo
    ev_against = [S_EXP023.ref, S_EXP022.ref]   # margen medio ~0, oscila, no robusto -> valor NO aislado
    adv = ("MIXTA (inclinada a REFUTAR el valor-como-info-gain). Honrando el pre-registro (margen máx "
           "{mx}>0.05 evita 'refutada'), pero la lectura honesta: el info-gain NO le gana de forma ROBUSTA "
           "al azar-activo ni en régimen duro — el margen B-C oscila alrededor de 0 (media {mm}); el único "
           "pico (K=16) está dentro del ruido (std~0.18) y se contradice en K=32. Lo que SÍ aguanta (otra "
           "vez) es ACTUAR>>observar (C-A=+0.07..+0.36; A plano). => El lever demostrado es la INTERVENCIÓN, "
           "NO el valor info-gain DISEÑADO. Ataque considerado: 'el régimen no era bastante duro' -> el azar "
           "tarda más (no satura hasta K=64-128) y aun así info-gain no separa. Reorientación: el valor "
           "endógeno, si existe, NO es info-gain; probar valor AUTO-generado, o pivotar a explotar "
           "R-INTERVENCIÓN (act-and-verify, ya apoyado por exp016-018).").format(
               mx=_fmt(vi['max_margin']), mm=_fmt(vi['mean_margin']))

    hyp = Hypothesis(
        id="H-V4-1b",
        statement=("El VALOR endógeno (info-gain) está AISLADO de la intervención activa per se: en un "
                   "régimen donde el azar no cubre por fuerza bruta, info-gain supera al azar-activo."),
        prediction=("APOYADA si B-C>0.08 en presupuestos chico/medio y prom>0.05; REFUTADA si margen máx "
                    "<=0.05; MIXTA si parcial. (Pre-registrada antes de correr.)"),
        status='abierta', confidence='media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=adv, experiment_ref="exp023_value_isolation")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-1b")
        notes.append("H-V4-1b marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("Hay MUCHAS cosas que podrían encender la luz y poco tiempo para probar. ¿Conviene un método "
                 "astuto de búsqueda (preguntar lo que más duda) o da igual probar al azar — mientras PRUEBES?"),
        everyday=("Dos electricistas con pocos minutos buscan cuál de 8 cables idénticos prende la luz. Uno "
                  "usa un método (prueba el que más dudaría); el otro toca cables al azar. Ambos TOCAN (no solo "
                  "miran). Medimos quién acierta más rápido."),
        solutions=["el que solo MIRA no descubre nunca (suben todos juntos) = muro informacional (A pasivo)",
                   "el que toca AL AZAR descubre, y con suficientes intentos llega igual de lejos (C)",
                   "el que usa MÉTODO astuto debería ganar cuando hay muchos cables y poco tiempo... pero medido "
                   "NO gana de forma robusta al azar (B≈C) -> la astucia del orden no es el lever",
                   "lo que separa al que descubre del que no es simplemente TOCAR (intervenir), no el orden"],
        principles=["el lever robusto es INTERVENIR/ACTUAR, no la inteligencia del criterio de exploración",
                    "un valor de exploración DISEÑADO (info-gain) no supera al azar => si hay un valor que "
                    "importa, no es éste; habría que buscar uno AUTO-generado o cambiar de pregunta",
                    "barato: actuar y aprender de la consecuencia ya rompe el muro; no hace falta un planificador caro",
                    "convergencia con el lab: act-and-verify (exp016-018) es la encarnación de 'intervenir' que ya funcionó"],
        adaptation=("Pivote: explotar R-INTERVENCIÓN (act-and-verify barato) como motor de inteligencia, en vez "
                    "de seguir buscando un valor de exploración astuto. R-VALOR endógeno se redefine como pregunta "
                    "abierta de valor AUTO-generado, NO info-gain."),
        measurement=("exp023: B-C medio {mm} (no robusto); C-A hasta +0.36; A plano ~{a}; costo {n} modelos en "
                     "{w}s CPU (~{p}s c/u).").format(
                         mm=_fmt(vi['mean_margin']), a=_fmt(A_max), n=cost.get('total_agent_runs'),
                         w=cost.get('wall_secs_all_agent_runs'), p=_fmt(cost.get('mean_secs_per_agent_run'))),
        iterations=1)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (8 cables: método astuto vs azar; lo que importa es TOCAR).")

    ceilings.add(CeilingRecord(
        subsystem="R-VALOR — el info-gain DISEÑADO NO es el lever (reorientar a valor auto-generado)",
        known_limit=("REFINADO (exp023): un valor de exploración DISEÑADO (information-gain) NO supera de forma "
                     "robusta al azar-activo ni en régimen duro (margen medio ~0). Por tanto 'valor endógeno = "
                     "info-gain' queda DESCARTADO como lever. R-VALOR sigue ABIERTO sólo en su forma fuerte: un "
                     "valor AUTO-generado (homeostasis/autopoiesis/empowerment) que no sea reducible a una meta "
                     "de exploración diseñada ni a 'actuar al azar'."),
        blockers=[{"text": "info-gain (objetivo diseñado) no se distingue del azar-activo: refutado como lever", "kind": "diseno"},
                  {"text": "un valor AUTO-generado no fue probado; sin un mecanismo concreto es no-falsable todavía", "kind": "diseno"}],
        real_or_assumed="asumido", evidence=[S_EXP023.ref, S_EXP022.ref]))
    ceilings.add(CeilingRecord(
        subsystem="R-INTERVENCIÓN — reforzada: ACTUAR es el lever robusto (no el criterio de exploración)",
        known_limit=("REAL (exp022 + exp023, replicado): bajo intervención el agente PASIVO queda plano por más "
                     "presupuesto; cualquier política que INTERVIENE (incluso al azar) identifica la causa. El "
                     "lever es ACTUAR/intervenir, no la astucia del muestreo. Cota: límite informacional "
                     "(la causa no está en lo observacional)."),
        blockers=[{"text": "la dirección causal no está en datos observacionales (identificabilidad)", "kind": "fisico"},
                  {"text": "sin acción no hay señal que rompa la simetría causa-espuria", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP023.ref, S_EXP022.ref]))
    notes.append("2 techos: R-VALOR 'asumido' refinado (info-gain descartado como lever); R-INTERVENCIÓN 'real' reforzada.")

    dstmt = ("PIVOTE de método dentro del reset v4: dejar de buscar un VALOR de exploración astuto (info-gain "
             "descartado, exp023) y EXPLOTAR R-INTERVENCIÓN como motor de inteligencia barato: act-and-verify "
             "(el agente ACTÚA y aprende de la CONSECUENCIA), que el lab YA apoya (exp016-018, H-LEARN-1). "
             "R-VALOR queda como pregunta abierta sólo en su forma fuerte (valor AUTO-generado). Próximo: "
             "H-V4-2 (formalizar identificabilidad sin cuerpo) y empezar a conectar R-INTERVENCIÓN con el "
             "sustrato de lenguaje (un razonador barato act-and-verify sobre el híbrido CPU).")
    drat = ("exp023 (tier5): info-gain NO supera al azar-activo (margen medio {mm}); robusto: ACTUAR>>observar "
            "(C-A hasta +0.36, A plano ~{a}). Barato: {n} modelos causales en {w}s CPU. Coherente con exp022 y "
            "con exp016-018 (verificador-que-ejecuta = intervención).").format(
                mm=_fmt(vi['mean_margin']), a=_fmt(A_max), n=cost.get('total_agent_runs'),
                w=cost.get('wall_secs_all_agent_runs'))
    dec = Decision(id="D-V4-2", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP023), _to_plain(S_EXP022)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-2 ACEPTADA por el ledger (tier5 exp023 + tier5 exp022).")
    except OpinionOnlyError as e:
        print("ERROR ledger D-V4-2:", e); raise

    return record, notes, status, s


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle36_value_isolation',
                                description='CYCLE 36 (RESET v4, H-V4-1b: aislamiento del valor info-gain).')
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
    print("RESUMEN — CYCLE 36 (RESET v4): aislamiento del valor info-gain (H-V4-1b)")
    print("=" * 78)
    print("veredicto H-V4-1b:", status.upper() if status else "?")
    print("  el lever robusto es ACTUAR/intervenir; el valor info-gain DISEÑADO no se distingue del azar.")
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
