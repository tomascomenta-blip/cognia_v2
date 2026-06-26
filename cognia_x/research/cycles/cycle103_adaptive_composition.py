r"""
cycle103_adaptive_composition.py — CICLO 103 (RESET v4, rama R-VALOR, ablación/composición del sub-arco 97-99): H-V4-8h
por las compuertas del engine. MIXTA (composición PARCIAL, califica honestamente 98-99): bajo drift + action-gated, la
ABLACIÓN 2×2 (decay sí/no × surprise-explore sí/no) con métrica de REWARD action-gated revela que el OLVIDO (decay) es la
pieza DOMINANTE -- decay_only ≈ full_adaptive, ambos >> naive -- mientras la EXPLORACIÓN surprise-gated añade ~0 SOBRE el
decay (y sola, sin decay, apenas ayuda). => bajo esta métrica, una vez que el combinador OLVIDA bien, la exploración es
casi redundante (su costo de oportunidad inmediato no se paga); CALIFICA el rescate de 98-99 (que se medía sobre el
ranking del pool, sin costo de explorar) como metric/régimen-condicional. La composición NO es aditiva-trivial: decay
carga el peso.

DERIVA de exp087_adaptive_composition/results/results.json.

Correr (DESPUÉS de exp087):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp087_adaptive_composition.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle103_adaptive_composition
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle103_adaptive_composition')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp087_adaptive_composition', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="ablación de componentes / sustituibilidad: dos mecanismos que abordan el mismo problema (no-estacionariedad) pueden ser SUSTITUTOS -- si uno (olvido) ya adapta, el otro (exploración) aporta poco; la 'necesidad' de un componente es relativa a los demás presentes", obtained=False,
                     claim=("En un sistema con varios mecanismos para el mismo fin (adaptarse a la no-estacionariedad), "
                            "los componentes pueden ser SUSTITUTOS: si el OLVIDO (decay) ya rastrea el cambio, la "
                            "EXPLORACIÓN aporta poco encima (y bajo una métrica con costo de oportunidad, su costo no se "
                            "paga). La 'necesidad' de un componente es RELATIVA a los demás presentes; la ablación lo "
                            "revela. (Principio.)"))
S_EXP083 = Source(tier=5, ref="cognia_x/experiments/exp083_surprise_explore", obtained=True,
                  claim=("CYCLE 98-99 mostraron PIEZA por PIEZA que bajo drift la exploración rescata (98) y la "
                         "surprise-gated domina al ε-fijo (99). H-V4-8h hace la ABLACIÓN conjunta para ver si las piezas "
                         "COMPONEN o si una subsume a la otra."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp087 primero): " + results_path)

    fvn = sm['full_vs_naive']
    fvd = sm['full_vs_decay']
    fve = sm['full_vs_explore']
    og = sm['oracle_gap']
    cell = sm['cell']
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim087 = ("exp087 (propio, {n} seeds, numpy, ablación 2×2, reward action-gated): full_adaptive={fa} ≈ decay_only="
                "{do} (ambos >> naive={nv}, +{fvn}); explore_only={eo} apenas supera al naive; la EXPLORACIÓN añade ~0 "
                "sobre decay (full_vs_decay {fvd}), el OLVIDO es la pieza dominante (full_vs_explore +{fve}). Composición "
                "PARCIAL: decay carga el peso.").format(
                    n=n_seeds, fa=_f(cell['full_adaptive']), do=_f(cell['decay_only']), nv=_f(cell['naive']), fvn=_f(fvn),
                    eo=_f(cell['explore_only']), fvd=_f(fvd), fve=_f(fve))
    S_EXP087 = Source(tier=5, ref="cognia_x/experiments/exp087_adaptive_composition", obtained=True, claim=claim087)
    for src in (S_PRINCIPLE, S_EXP083, S_EXP087):
        ledger.add_source(src)
    notes.append("3 fuentes (S_PRINCIPLE tier2 ablación/sustituibilidad; S_EXP083 tier5 piezas 98-99; S_EXP087 tier5 dato propio).")

    ev_for = [S_EXP087.ref]
    ev_against = [S_EXP087.ref, S_EXP083.ref, S_PRINCIPLE.ref]
    advtext = ("{V} (ablación/composición del sub-arco 97-99; califica honestamente 98-99): 97 mostró que bajo drift el "
               "combinador debe OLVIDAR (decay), y 98-99 que la EXPLORACIÓN gateada por sorpresa rescata/domina. H-V4-8h "
               "junta las dos piezas y hace la ABLACIÓN 2×2 (decay × surprise-explore) bajo drift + action-gated, con "
               "MÉTRICA de REWARD action-gated (perf_of de lo SELECCIONADO; explorar tiene costo de oportunidad). "
               "RESULTADO: el OLVIDO (decay) es la pieza DOMINANTE -- decay_only={do} ≈ full_adaptive={fa}, ambos >> "
               "naive (full-history+greedy)={nv} (+{fvn}, ≈ la mejora total) -- mientras la EXPLORACIÓN añade ~0 SOBRE el "
               "decay (full_adaptive − decay_only = {fvd}) y SOLA (explore_only={eo}) apenas supera al naive. => bajo "
               "esta métrica, una vez que el combinador OLVIDA bien, la exploración es casi REDUNDANTE: las dos piezas "
               "son SUSTITUTOS (no complementos) para adaptarse al drift; el decay ya re-aprende el valor movido y el "
               "greedy sobre el combinador adaptado lo explota, sin pagar el costo de explorar. ESTO CALIFICA 98-99: el "
               "rescate por exploración se midió sobre el RANKING del pool (sin costo de explorar) y/o sin decay; con "
               "decay + reward action-gated, la exploración no paga. La composición NO es aditiva-trivial: decay carga el "
               "peso. EVIDENCIA EN CONTRA / matiz: NO es REFUTADA -- full_adaptive SÍ es el mejor (decay necesario, +{fve} "
               "sobre explore-solo) y supera al naive; es MIXTA porque la pieza EXPLORE no aporta en composición bajo esta "
               "métrica (no es que la exploración nunca sirva -- sirve sin decay o bajo otra métrica, 98-99 -- sino que "
               "decay la subsume aquí). Caveats: 1 régimen (drift+action-gated k_obs=2), métrica reward, decay/eps fijos, "
               "bump sintético, numpy/juguete; el oracle gap es grande ({og}: la adaptación es parcial bajo drift "
               "abrupto).").format(
                   V=status.upper(), do=_f(cell['decay_only']), fa=_f(cell['full_adaptive']), nv=_f(cell['naive']),
                   fvn=_f(fvn), fvd=_f(fvd), eo=_f(cell['explore_only']), fve=_f(fve), og=_f(og))

    hyp = Hypothesis(
        id="H-V4-8h",
        statement=("Las piezas de no-estacionariedad (olvido por decay + exploración surprise-gated) COMPONEN y cada una "
                   "es NECESARIA: el asignador full-adaptive supera al naive y ablar cada pieza lo degrada."),
        prediction=("APOYADA si full_adaptive es el mejor (> naive +0.05) Y ablar CADA pieza lo degrada (>+0.015 cada una); "
                    "REFUTADA si full ≈ naive (ninguna pieza ayuda); MIXTA si full > naive pero una pieza no aporta sobre "
                    "la otra (composición parcial / sustituibilidad). (Pre-registrada, numpy, 48 seeds, reward "
                    "action-gated.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp087_adaptive_composition")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-8h")
        notes.append("H-V4-8h marcada '{}' con DoD completo (ablación: decay dominante, explore redundante-dado-decay).".format(status))

    analogy = AnalogyRecord(
        problem=("Para no perderme cuando las ofertas se mudan de barrio tengo dos hábitos: (a) descartar mi info vieja "
                 "(olvidar) y (b) asomarme a otros barrios (explorar). ¿Necesito los DOS, o uno ya alcanza?"),
        everyday=("Con OLVIDAR ya alcanza casi todo: si descarto lo viejo, mi mapa se actualiza solo con lo que voy viendo "
                  "y voy al barrio bueno de ahora. Asomarme a otros barrios encima cuesta viajes y, una vez que olvido "
                  "bien, no me agrega casi nada. (Asomarse SÍ sirve si NO olvido, o si no me cuesta asomarme -- pero "
                  "teniendo el olvido y con viajes costosos, es redundante.) Los dos hábitos son SUSTITUTOS para este "
                  "problema, no complementos."),
        solutions=["olvidar (decay): la pieza que carga el peso -- re-aprende el valor movido sola",
                   "explorar (surprise-gated): redundante una vez que olvido bien (y con costo de oportunidad)",
                   "explorar SIN olvidar: apenas ayuda (el mapa viejo contamina)",
                   "ambos: igual que sólo olvidar (la exploración no agrega en composición)"],
        principles=["dos mecanismos para el mismo fin pueden ser SUSTITUTOS, no complementos (ablación lo revela)",
                    "el OLVIDO (decay) es la pieza dominante para adaptarse al drift bajo reward action-gated",
                    "la exploración es redundante una vez que el combinador olvida bien (su costo no se paga)",
                    "la 'necesidad' de un componente es RELATIVA a los demás presentes (califica 98-99)"],
        adaptation=("El lab CALIFICA el sub-arco 97-99: para adaptarse a la no-estacionariedad, el OLVIDO (decay) es la "
                    "pieza de 1ra clase; la exploración surprise-gated es un sustituto que aporta poco una vez que se "
                    "olvida bien (bajo reward action-gated). Política: priorizar el olvido (decay/selector de tasa CYCLE "
                    "74) en la asignación no-estacionaria; añadir exploración sólo si no se puede olvidar (combinador "
                    "fijo) o si explorar es barato. Honestidad: la ablación mostró sustituibilidad, no complementariedad. "
                    "Próximo: regímenes donde olvidar NO baste (cambio que requiera re-muestrear activamente); integrar "
                    "en el lazo cerrado real; y SCALE."),
        measurement=("exp087 ({n} seeds, reward action-gated): full_adaptive={fa} ≈ decay_only={do} >> naive={nv} (+{fvn}); "
                     "explore añade {fvd} sobre decay; decay aporta +{fve} sobre explore-solo; oracle gap {og}.").format(
                         n=n_seeds, fa=_f(cell['full_adaptive']), do=_f(cell['decay_only']), nv=_f(cell['naive']),
                         fvn=_f(fvn), fvd=_f(fvd), fve=_f(fve), og=_f(og)),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (olvidar vs asomarse: sustitutos; olvidar carga el peso).")

    kl = ("REAL (exp087): ablación 2×2 bajo drift + action-gated (reward action-gated): el OLVIDO (decay) es la pieza "
          "DOMINANTE (decay_only={do} ≈ full_adaptive={fa} >> naive={nv}); la EXPLORACIÓN surprise-gated añade ~0 sobre "
          "decay ({fvd}) -- las dos piezas son SUSTITUTOS, no complementos, para adaptarse al drift. Califica 98-99 (el "
          "rescate por exploración era metric/régimen-condicional). TECHO: 1 régimen, métrica reward, decay/eps fijos, "
          "oracle gap grande ({og}: adaptación parcial bajo drift abrupto).").format(
              do=_f(cell['decay_only']), fa=_f(cell['full_adaptive']), nv=_f(cell['naive']), fvd=_f(fvd), og=_f(og))
    ceilings.add(CeilingRecord(
        subsystem="No-estacionariedad en la asignación — ablación: el OLVIDO (decay) es la pieza dominante; la exploración surprise-gated es un SUSTITUTO redundante una vez que se olvida bien (califica 98-99)",
        known_limit=kl,
        blockers=[{"text": "resultado bajo MÉTRICA de reward action-gated (explorar tiene costo de oportunidad); bajo la métrica de ranking-de-pool (CYCLE 98) la exploración sí ayudaba -> la conclusión es métrica-dependiente", "kind": "diseno"},
                  {"text": "1 régimen (drift+action-gated, k_obs=2, drift abrupto por fases); en regímenes donde olvidar NO baste (p.ej. cambio que exige re-muestrear activamente una región nunca observada) la exploración podría volverse necesaria; no testeado", "kind": "diseno"},
                  {"text": "decay y eps fijos, bump sintético, numpy/juguete; oracle gap grande (adaptación parcial); no integrado con el lazo cerrado real ni SCALE", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP087.ref, S_EXP083.ref]))
    notes.append("1 techo 'real': el olvido es la pieza dominante; la exploración es sustituto redundante dado decay (métrica-dependiente).")

    dstmt = ("North-Star R-VALOR (ablación del sub-arco 97-99): bajo no-estacionariedad + action-gated (reward "
             "action-gated), el OLVIDO (decay) es la pieza de 1ra clase para adaptarse al drift; la EXPLORACIÓN "
             "surprise-gated es un SUSTITUTO que aporta poco una vez que se olvida bien (su costo de oportunidad no se "
             "paga). Decisión: priorizar el olvido (decay / selector de tasa CYCLE 74) en la asignación no-estacionaria; "
             "añadir exploración sólo si no se puede olvidar (combinador fijo) o si explorar es barato (otra métrica). "
             "HONESTIDAD: la ablación mostró SUSTITUIBILIDAD (no complementariedad), calificando 98-99 (cuyo rescate por "
             "exploración era metric/régimen-condicional). Próximo: regímenes donde olvidar no baste (re-muestreo activo "
             "necesario); integrar en el lazo cerrado real; y SCALE.")
    drat = ("exp087 (tier5, propio, {n} seeds, numpy, ablación 2×2): full_adaptive={fa} ≈ decay_only={do} >> naive={nv} "
            "(+{fvn}); explore añade {fvd} sobre decay (redundante); decay aporta +{fve} sobre explore-solo (dominante). "
            "Convergente con ablación/sustituibilidad (tier2) y con las piezas de 98-99 (tier5). MIXTA: composición "
            "parcial, decay carga el peso.").format(n=n_seeds, fa=_f(cell['full_adaptive']), do=_f(cell['decay_only']),
                                                    nv=_f(cell['naive']), fvn=_f(fvn), fvd=_f(fvd), fve=_f(fve))
    dec = Decision(id="D-V4-65", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP087), _to_plain(S_EXP083)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-65 ACEPTADA por el ledger (tier5 exp087 + tier5 exp083).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-65:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle103_adaptive_composition',
                                description='CYCLE 103 (RESET v4, H-V4-8h: ablación -- el olvido es la pieza dominante, la exploración es sustituto redundante dado decay -- MIXTA; califica 98-99).')
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
    print("RESUMEN — CYCLE 103 (RESET v4): ablación -- el OLVIDO es la pieza dominante; la exploración es sustituto redundante (H-V4-8h)")
    print("=" * 78)
    print("veredicto H-V4-8h:", status.upper() if status else "?")
    print("  decay_only ≈ full_adaptive >> naive; explore añade ~0 sobre decay. Piezas SUSTITUTAS, no complementos (califica 98-99).")
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
