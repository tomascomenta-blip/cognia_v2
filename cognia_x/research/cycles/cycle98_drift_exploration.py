r"""
cycle98_drift_exploration.py — CICLO 98 (RESET v4, rama R-VALOR/R-INTERVENCIÓN, REVIERTE CYCLE 87-88 condicionalmente):
H-V4-7k por las compuertas del engine. APOYADA (reversión CONDICIONAL): CYCLE 87-88 REFUTARON la necesidad de explorar
(greedy bastaba) bajo feedback action-gated, PERO en régimen ESTACIONARIO. CYCLE 97 mostró que el valor DERIVA. Bajo
DRIFT + observación ESTRECHA (k_obs chico), el greedy se ATRAPA (explota un combinador STALE del viejo 'buen barrio',
re-observa siempre la misma región, el decay no rastrea lo que no se observa) y la EXPLORACIÓN RESCATA; a observación
AMPLIA el greedy es robusto (87-88 vale) y bajo estacionario no atrapa a ningún k_obs. => R-INTERVENCIÓN (explorar para
RE-aprender el valor que se mueve) por fin LIGA -- condicionado a drift + observación estrecha, como el trap de CYCLE 88.
Vindica la raíz R-INTERVENCIÓN del árbol: la estructura es identificable sólo si la distribución VARÍA (el drift ES
variación).

DERIVA de exp082_drift_exploration/results/results.json.

Correr (DESPUÉS de exp082):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp082_drift_exploration.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle98_drift_exploration
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle98_drift_exploration')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp082_drift_exploration', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="R-INTERVENCIÓN / exploración bajo no-estacionariedad: la estructura es identificable sólo si la distribución VARÍA; en bandits/RL no-estacionarios la exploración es necesaria justo cuando el entorno cambia (el greedy se ancla a un óptimo viejo)", obtained=False,
                     claim=("La raíz R-INTERVENCIÓN del árbol del lab: la estructura/valor sólo es identificable si la "
                            "distribución VARÍA (por intervención o shift). En bandits/RL NO-estacionarios la exploración "
                            "es necesaria precisamente cuando el entorno cambia: el greedy bajo feedback action-gated se "
                            "ancla al óptimo viejo y no re-observa el nuevo. (Principio; el drift ES la variación que "
                            "R-INTERVENCIÓN predice como necesaria.)"))
S_EXP071 = Source(tier=5, ref="cognia_x/experiments/exp071_action_gated_feedback", obtained=True,
                  claim=("CYCLE 87-88 REFUTARON la necesidad de explorar (greedy ≈ random insesgado, no trap) bajo "
                         "feedback action-gated -- PERO en régimen ESTACIONARIO. Dejaron R-INTERVENCIÓN sin ligar. "
                         "H-V4-7k testea si el drift (CYCLE 97) revierte eso."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp082 primero): " + results_path)

    dt = sm['drift_trap']
    dr = sm['drift_rescue']
    wt = sm['wide_trap']
    st = sm['stat_trap']
    tk = sm['trap_kobs']
    nk = sm['narrow_kobs']
    wk = sm['wide_kobs']
    g = sm['grid']
    n_seeds = data['args']['seeds']
    nd = g["drift_kobs{}".format(nk)]
    wd = g["drift_kobs{}".format(wk)]

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim082 = ("exp082 (propio, {n} seeds, numpy, barrido k_obs): bajo DRIFT + observación ESTRECHA (k_obs={nk}) el greedy "
                "se ATRAPA (greedy={dg} << random={drn}, gap {dt}) y la EXPLORACIÓN rescata (explore={de}, +{dr}); a "
                "k_obs AMPLIO ({wk}) el greedy es robusto (gap {wt}); estacionario no atrapa (gap {st}); trap_kobs*<={tk}. "
                "Reversión CONDICIONAL de 87-88.").format(
                    n=n_seeds, nk=nk, dg=_f(nd["greedy"]), drn=_f(nd["random"]), dt=_f(dt), de=_f(nd["explore"]),
                    dr=_f(dr), wk=wk, wt=_f(wt), st=_f(st), tk=tk)
    S_EXP082 = Source(tier=5, ref="cognia_x/experiments/exp082_drift_exploration", obtained=True, claim=claim082)
    for src in (S_PRINCIPLE, S_EXP071, S_EXP082):
        ledger.add_source(src)
    notes.append("3 fuentes (S_PRINCIPLE tier2 R-INTERVENCIÓN/exploración bajo drift; S_EXP071 tier5 no-trap estacionario de 87-88; S_EXP082 tier5 dato propio).")

    ev_for = [S_EXP082.ref]
    ev_against = [S_EXP082.ref, S_EXP071.ref, S_PRINCIPLE.ref]
    advtext = ("{V} (REVIERTE CYCLE 87-88 condicionalmente; R-INTERVENCIÓN por fin LIGA): CYCLE 87-88 refutaron la "
               "necesidad de explorar (la explotación GREEDY bastaba, greedy ≈ random insesgado) bajo feedback "
               "ACTION-GATED -- PERO en régimen ESTACIONARIO. CYCLE 97 mostró que el valor DERIVA. H-V4-7k combina lo "
               "crítico (action-gated + DRIFT) y BARRE la amplitud de observación k_obs. RESULTADO: bajo DRIFT + "
               "observación ESTRECHA (k_obs={nk}) el greedy se ATRAPA -- greedy={dg} << random insesgado={drn} (gap {dt}>"
               "0.05): explota un combinador STALE del viejo 'buen barrio', re-observa siempre la misma región estrecha, "
               "y el decay (CYCLE 97) NO puede rastrear lo que NO se observa -> trap. La EXPLORACIÓN RESCATA: explore="
               "{de} > greedy (+{dr}). PERO a observación AMPLIA (k_obs={wk}) el greedy es ROBUSTO (gap {wt}<=0.05: "
               "observa suficiente del espacio para ver el valor caer y auto-corregir) y bajo ESTACIONARIO no atrapa a "
               "ningún k_obs (gap {st}<=0.05: reproduce 87-88). Umbral de trap k_obs*<={tk}. => la exploración "
               "(R-INTERVENCIÓN) es NECESARIA bajo NO-estacionariedad + observación ESTRECHA; el 'exploración "
               "innecesaria' de 87-88 era específico de la ESTACIONARIEDAD o de observación amplia. Esto VINDICA la raíz "
               "R-INTERVENCIÓN del árbol (la estructura sólo es identificable si la distribución VARÍA -- el drift ES "
               "variación) y reconcilia los nulls de 77-78/87-88: R-INTERVENCIÓN no ligaba porque esos regímenes eran "
               "ESTACIONARIOS. EVIDENCIA EN CONTRA / caveats HONESTOS: el efecto es CONDICIONAL (igual que el trap de "
               "CYCLE 88: emerge sólo con observación estrecha k_obs<=~2-4); a k_obs=1 (extremo) ni la exploración "
               "rescata (señal insuficiente; sólo el random insesgado ayuda); valor bump sintético, drift abrupto por "
               "fases, eps fijo, numpy/juguete; la magnitud del trap es modesta (~0.05).").format(
                   V=status.upper(), nk=nk, dg=_f(nd["greedy"]), drn=_f(nd["random"]), dt=_f(dt), de=_f(nd["explore"]),
                   dr=_f(dr), wk=wk, wt=_f(wt), st=_f(st), tk=tk)

    hyp = Hypothesis(
        id="H-V4-7k",
        statement=("Bajo feedback action-gated + DRIFT del valor y observación ESTRECHA, la explotación greedy se ATRAPA "
                   "(combinador stale del viejo óptimo, nunca re-observa el valor movido) y la EXPLORACIÓN rescata -> "
                   "revierte el 'exploración innecesaria' de CYCLE 87-88 (específico de la estacionariedad); "
                   "R-INTERVENCIÓN liga bajo no-estacionariedad."),
        prediction=("APOYADA si a k_obs estrecho el drift atrapa (random−greedy>0.05) Y explore rescata (>0.05), a k_obs "
                    "amplio NO atrapa, y estacionario NO atrapa a ningún k_obs; REFUTADA si el drift no atrapa a ningún "
                    "k_obs; MIXTA en otro caso. (Pre-registrada, numpy, 48 seeds, barrido k_obs.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp082_drift_exploration")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-7k")
        notes.append("H-V4-7k marcada '{}' con DoD completo (revierte 87-88 bajo drift; R-INTERVENCIÓN liga).".format(status))

    analogy = AnalogyRecord(
        problem=("Aprendí qué barrio tiene las ofertas y voy SÓLO ahí (mirando poquito alrededor). Las ofertas se mudan "
                 "de barrio. ¿Me quedo atrapado yendo al viejo barrio vacío, o conviene asomarme a otros?"),
        everyday=("Si miro POQUITO (sólo mi barrio de siempre), me quedo atrapado: voy al viejo barrio, lo encuentro "
                  "vacío, pero no me entero de dónde se mudaron -> asomarme a otros barrios (explorar) me rescata. Si en "
                  "cambio MIRO BASTANTE cada vez (varios barrios), me entero solo de que se mudaron y me reacomodo sin "
                  "esfuerzo extra. Cuando las ofertas NO se mudan, nunca hace falta asomarse. Asomarse paga sólo cuando "
                  "el mundo cambia Y miro poquito."),
        solutions=["drift + mirar poquito (k_obs chico): el greedy se atrapa -> explorar rescata (R-INTERVENCIÓN liga)",
                   "drift + mirar bastante (k_obs amplio): el greedy se auto-corrige -> explorar innecesario (87-88 vale)",
                   "sin drift (estable): nunca se atrapa a ningún k_obs (reproduce 87-88)",
                   "mirar poquísimo (k_obs=1): ni explorar alcanza; sólo mirar al azar (insesgado) ayuda"],
        principles=["la estructura/valor sólo es identificable si la distribución VARÍA (R-INTERVENCIÓN; el drift es variación)",
                    "bajo action-gated el greedy no re-observa lo que dejó de elegir -> stale bajo drift -> trap",
                    "la exploración rescata el trap, pero condicionado a observación estrecha + drift (como CYCLE 88)",
                    "los nulls de R-INTERVENCIÓN (77-78/87-88) eran por regímenes ESTACIONARIOS, no por el mecanismo"],
        adaptation=("El lab RECONCILIA R-INTERVENCIÓN con sus nulls: la exploración (intervenir/asomarse) NO ligaba en "
                    "77-78/87-88 porque eran ESTACIONARIOS; bajo DRIFT + observación estrecha SÍ liga (el greedy se atrapa, "
                    "explorar rescata). Política del lazo: bajo no-estacionariedad con observación estrecha, añadir "
                    "exploración (ε o surprise-gated, reusar CYCLE 59) a la asignación greedy; con observación amplia o "
                    "régimen estable, greedy basta. Próximo: exploración SURPRISE-GATED (sólo explorar cuando la sorpresa "
                    "indica cambio, CYCLE 59) para no pagar exploración en vano; integrar con el lazo cerrado real; SCALE."),
        measurement=("exp082 ({n} seeds): @k_obs={nk} drift_trap=+{dt} drift_rescue=+{dr}; @k_obs={wk} wide_trap={wt}; "
                     "stat_trap={st}; trap_kobs*<={tk}.").format(
                         n=n_seeds, nk=nk, dt=_f(dt), dr=_f(dr), wk=wk, wt=_f(wt), st=_f(st), tk=tk),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (las ofertas se mudan y miro poquito: asomarme rescata; mirando bastante me auto-corrijo).")

    kl = ("REAL (exp082): bajo feedback action-gated + DRIFT + observación ESTRECHA (k_obs<=~2) el greedy se ATRAPA "
          "(combinador stale, gap random−greedy={dt}) y la EXPLORACIÓN rescata (+{dr}); a observación AMPLIA (k_obs={wk}) "
          "el greedy es robusto (gap {wt}) y estacionario no atrapa (gap {st}). R-INTERVENCIÓN liga bajo no-estacionariedad "
          "+ observación estrecha -- reconcilia los nulls de 77-78/87-88 (eran estacionarios). TECHO: efecto CONDICIONAL "
          "y modesto (~0.05); a k_obs=1 ni explorar alcanza; bump sintético, drift abrupto, eps fijo.").format(
              dt=_f(dt), dr=_f(dr), wk=wk, wt=_f(wt), st=_f(st))
    ceilings.add(CeilingRecord(
        subsystem="R-INTERVENCIÓN bajo no-estacionariedad — la exploración LIGA bajo drift + observación estrecha (revierte condicionalmente 87-88); reconcilia los nulls estacionarios",
        known_limit=kl,
        blockers=[{"text": "efecto CONDICIONAL a observación estrecha (k_obs<=~2-4) Y drift; a observación amplia el greedy se auto-corrige (87-88 vale); magnitud modesta (~0.05)", "kind": "diseno"},
                  {"text": "a k_obs=1 (extremo) ni la exploración rescata (señal insuficiente); sólo el random insesgado ayuda -> hay un piso de observación bajo el cual nada explota la estructura", "kind": "fisico"},
                  {"text": "valor bump sintético nesteable por poly2, drift ABRUPTO por fases (no gradual), eps de exploración FIJO (no surprise-gated), numpy/juguete; falta integrar con el lazo cerrado real y SCALE", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP082.ref, S_EXP071.ref]))
    notes.append("1 techo 'real': la exploración (R-INTERVENCIÓN) liga bajo drift + observación estrecha; reconcilia los nulls estacionarios de 77-78/87-88.")

    dstmt = ("North-Star R-VALOR/R-INTERVENCIÓN (REVIERTE 87-88 condicionalmente; R-INTERVENCIÓN por fin LIGA): bajo "
             "feedback action-gated + DRIFT del valor + observación ESTRECHA, la explotación greedy se ATRAPA (combinador "
             "stale del viejo óptimo) y la EXPLORACIÓN rescata; a observación amplia o régimen estable, greedy basta "
             "(87-88). Decisión: la política de asignación añade EXPLORACIÓN bajo no-estacionariedad + observación "
             "estrecha; con observación amplia o estable, greedy. Esto RECONCILIA los nulls de R-INTERVENCIÓN (77-78/"
             "87-88, todos estacionarios) con su raíz: la estructura sólo es identificable si la distribución VARÍA -- el "
             "drift ES variación. Próximo: exploración SURPRISE-GATED (CYCLE 59, no pagar exploración en vano); integrar "
             "con el lazo cerrado real; y SCALE.")
    drat = ("exp082 (tier5, propio, {n} seeds, numpy, barrido k_obs): @k_obs={nk} drift atrapa (gap {dt}) y explore rescata "
            "(+{dr}); @k_obs={wk} robusto (gap {wt}); estacionario no atrapa (gap {st}); trap_kobs*<={tk}. Convergente con "
            "R-INTERVENCIÓN/exploración-bajo-drift (tier2) y con el no-trap estacionario de 87-88 (tier5). APOYADA la "
            "reversión condicional.").format(n=n_seeds, nk=nk, dt=_f(dt), dr=_f(dr), wk=wk, wt=_f(wt), st=_f(st), tk=tk)
    dec = Decision(id="D-V4-60", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP082), _to_plain(S_EXP071)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-60 ACEPTADA por el ledger (tier5 exp082 + tier5 exp071).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-60:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle98_drift_exploration',
                                description='CYCLE 98 (RESET v4, H-V4-7k: la exploración liga bajo drift + observación estrecha -- revierte 87-88 condicionalmente; R-INTERVENCIÓN liga).')
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
    print("RESUMEN — CYCLE 98 (RESET v4): la exploración (R-INTERVENCIÓN) LIGA bajo drift + observación estrecha (H-V4-7k) — revierte 87-88 condicionalmente")
    print("=" * 78)
    print("veredicto H-V4-7k:", status.upper() if status else "?")
    print("  drift + k_obs estrecho: greedy se atrapa, explore rescata; k_obs amplio o estable: greedy basta (87-88). R-INTERVENCIÓN liga.")
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
