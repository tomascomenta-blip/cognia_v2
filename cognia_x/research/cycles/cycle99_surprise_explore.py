r"""
cycle99_surprise_explore.py — CICLO 99 (RESET v4, rama R-VALOR/R-INTERVENCIÓN, CIERRA el sub-arco 97-99): H-V4-7l por las
compuertas del engine. APOYADA: la exploración SURPRISE-GATED (explorar sólo cuando la SORPRESA -- el combinador
sobre-predijo el valor de lo que eligió greedy -- indica cambio, reusando CYCLE 59) DOMINA al ε-fijo y es NO-REGRET, sin ε
fijo: AHORRA en estacionario (no malgasta explorando) y RESCATA en drift (detecta el cambio, explora). Cierra el caveat 'ε
fijo' de CYCLE 98; el análogo del selector no-regret de CYCLE 66/74 para la EXPLORACIÓN. Caveat: greedy es referencia
ROBUSTA (CYCLE 98 se auto-corrige bajo drift mild) -> el margen vs greedy es chico; hay un tradeoff de umbral de detección.

DERIVA de exp083_surprise_explore/results/results.json.

Correr (DESPUÉS de exp083):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp083_surprise_explore.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle99_surprise_explore
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle99_surprise_explore')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp083_surprise_explore', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="detección de cambio por sorpresa + exploración adaptativa: explorar gateado por una señal de cambio endógena (sorpresa) domina a un ε fijo (que paga exploración siempre); análogo a CYCLE 59 (olvido por sorpresa)", obtained=False,
                     claim=("Una exploración gateada por una señal de CAMBIO endógena (sorpresa = el modelo predijo algo "
                            "y observó otra cosa) explora sólo cuando hace falta, dominando a un ε FIJO que paga "
                            "exploración también en régimen estable. Es el análogo, para la EXPLORACIÓN, del olvido "
                            "adaptativo por sorpresa (CYCLE 59) y del selector no-regret (CYCLE 66/74). (Principio.)"))
S_EXP082 = Source(tier=5, ref="cognia_x/experiments/exp082_drift_exploration", obtained=True,
                  claim=("CYCLE 98 mostró que bajo drift + observación estrecha la exploración (ε FIJO) rescata al greedy "
                         "atrapado, PERO el ε fijo paga exploración también en estacionario (donde no hace falta). "
                         "H-V4-7l prueba la versión gateada por sorpresa."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp083 primero): " + results_path)

    dre = sm['drift_rescue']
    dve = sm['drift_vs_explore']
    ss = sm['stat_savings']
    svg = sm['stat_vs_greedy']
    sa = sm['surprise_avg']
    ga = sm['greedy_avg']
    ea = sm['explore_avg']
    nrm = sm['noregret_margin']
    g = sm['grid']
    st, dr = g['stationary'], g['drift']
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim083 = ("exp083 (propio, {n} seeds, numpy, reward action-gated): la exploración SURPRISE-GATED DOMINA al ε-fijo: "
                "AHORRA en estacionario (surprise={ss_} vs explore={es}, +{ss}) ≈ greedy={gs} ({svg}); RESCATA en drift "
                "(surprise={sd} >= explore={ed} ({dve}), > greedy={gd}, +{dre}). surprise_avg={sa} mejor (vs greedy {ga}/"
                "explore {ea}, margen {nrm}).").format(
                    n=n_seeds, ss_=_f(st['surprise_explore']), es=_f(st['explore']), ss=_f(ss), gs=_f(st['greedy']),
                    svg=_f(svg), sd=_f(dr['surprise_explore']), ed=_f(dr['explore']), dve=_f(dve), gd=_f(dr['greedy']),
                    dre=_f(dre), sa=_f(sa), ga=_f(ga), ea=_f(ea), nrm=_f(nrm))
    S_EXP083 = Source(tier=5, ref="cognia_x/experiments/exp083_surprise_explore", obtained=True, claim=claim083)
    for src in (S_PRINCIPLE, S_EXP082, S_EXP083):
        ledger.add_source(src)
    notes.append("3 fuentes (S_PRINCIPLE tier2 sorpresa/exploración adaptativa; S_EXP082 tier5 ε-fijo de CYCLE 98; S_EXP083 tier5 dato propio).")

    ev_for = [S_EXP083.ref]
    ev_against = [S_EXP083.ref, S_EXP082.ref, S_PRINCIPLE.ref]
    advtext = ("{V} (cierra el sub-arco 97-99): CYCLE 98 mostró que bajo drift + observación estrecha la exploración con ε "
               "FIJO rescata al greedy atrapado, pero el ε fijo paga exploración SIEMPRE (también en estacionario, donde "
               "no hace falta). H-V4-7l prueba la exploración SURPRISE-GATED: explorar (subir ε) sólo cuando la SORPRESA "
               "indica cambio -- el combinador SOBRE-PREDIJO el valor de lo que eligió greedy (pensó alto, observó bajo => "
               "la región se mudó), reusando la detección por sorpresa de CYCLE 59. MÉTRICA = reward action-gated (la "
               "calidad de lo SELECCIONADO; explorar tiene costo de oportunidad real). RESULTADO: la surprise-gated "
               "DOMINA al ε-fijo y es NO-REGRET. (1) AHORRA en ESTACIONARIO: surprise={ss_} vs explore-ε-fijo={es} "
               "(+{ss}: el ε-fijo malgasta ~{ss} de reward explorando cuando no hace falta) y ≈ greedy={gs} ({svg}). "
               "(2) RESCATA en DRIFT: surprise={sd} >= explore={ed} ({dve}) y > greedy={gd} (+{dre}). (3) Promediando, "
               "surprise_avg={sa} es la mejor (vs greedy {ga}/explore {ea}; supera al ε-fijo por {bea}). => exploración "
               "endógena gateada por SORPRESA, el análogo del selector no-regret de CYCLE 66/74 para la EXPLORACIÓN; "
               "cierra el caveat 'ε fijo' de CYCLE 98. EVIDENCIA EN CONTRA / caveats HONESTOS: el margen vs GREEDY es "
               "chico (greedy es ROBUSTO, CYCLE 98: se auto-corrige bajo drift mild; surprise_avg {sa} ≈ greedy_avg {ga}, "
               "margen {nrm}); hay un TRADEOFF de umbral de detección (un umbral más estricto baja el falso-positivo "
               "estacionario pero sub-detecta el drift, y viceversa) -> el cierre pleno sería calibrar el umbral o un "
               "selector de umbral (CYCLE 74); valor bump sintético, drift abrupto, k_obs=2, numpy/juguete. La clara "
               "victoria es sobre el ε-FIJO (la pregunta del ciclo: qué ESQUEMA de exploración).").format(
                   V=status.upper(), ss_=_f(st['surprise_explore']), es=_f(st['explore']), ss=_f(ss), gs=_f(st['greedy']),
                   svg=_f(svg), sd=_f(dr['surprise_explore']), ed=_f(dr['explore']), dve=_f(dve), gd=_f(dr['greedy']),
                   dre=_f(dre), sa=_f(sa), ga=_f(ga), ea=_f(ea), nrm=_f(nrm), bea=_f(round(sa - ea, 4)))

    hyp = Hypothesis(
        id="H-V4-7l",
        statement=("La exploración SURPRISE-GATED (explorar sólo cuando la sorpresa indica cambio) DOMINA al ε fijo y es "
                   "no-regret: ahorra en estacionario (no explora sin necesidad) y rescata en drift (detecta el cambio) -> "
                   "exploración endógena sin ε fijo (cierra el caveat de CYCLE 98)."),
        prediction=("APOYADA si surprise DOMINA al ε-fijo (ahorra >0.05 en estacionario, drift >= explore −0.03) Y es "
                    "no-regret (mejor o empatado en promedio) Y supera al ε-fijo en promedio (>0.05); REFUTADA si no domina "
                    "al ε-fijo; MIXTA si funciona pero el margen es chico. (Pre-registrada, numpy, 48 seeds, reward "
                    "action-gated.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp083_surprise_explore")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-7l")
        notes.append("H-V4-7l marcada '{}' con DoD completo (cierra el sub-arco 97-99).".format(status))

    analogy = AnalogyRecord(
        problem=("Las ofertas se mudan de barrio a veces. ¿Salgo a explorar SIEMPRE un poco (por si acaso) o sólo cuando "
                 "noto que mi barrio de siempre ya no rinde?"),
        everyday=("Sólo cuando noto que ya no rinde. Salir a explorar SIEMPRE me cuesta (gasto viajes en barrios al azar "
                  "aunque el mío siga bien). Mejor: me fijo si lo que esperaba encontrar SE CUMPLE; si un día mi barrio "
                  "de siempre está vacío (sorpresa: esperaba ofertas, no hay) -> salgo a explorar; si rinde como "
                  "esperaba, me quedo. Así no malgasto viajes cuando todo está estable y reacciono rápido cuando algo "
                  "cambia."),
        solutions=["explorar gateado por SORPRESA: ahorra cuando estable, reacciona cuando cambia (no-regret)",
                   "explorar siempre (ε fijo): reacciona pero malgasta viajes cuando está estable",
                   "no explorar nunca (greedy): barato cuando estable, se atrapa cuando cambia (mild: se auto-corrige)",
                   "el umbral de 'cuándo me sorprendí lo suficiente' es un tradeoff (sensibilidad vs falsos positivos)"],
        principles=["explorar gateado por sorpresa domina al ε fijo (explora sólo cuando la señal de cambio aparece)",
                    "la sorpresa = el modelo predijo y observó otra cosa (CYCLE 59) detecta el cambio sin aviso externo",
                    "greedy es robusto bajo drift mild (se auto-corrige, CYCLE 98) -> el margen vs greedy es chico",
                    "hay un tradeoff de umbral: sensibilidad al drift vs especificidad en estacionario"],
        adaptation=("El lab cierra el sub-arco 97-99: bajo no-estacionariedad, la asignación usa exploración SURPRISE-GATED "
                    "(explorar sólo al detectar cambio por sorpresa), que domina al ε fijo y es no-regret -- sin "
                    "hiperparámetro de exploración fijo. Es el análogo, para la EXPLORACIÓN, del olvido adaptativo por "
                    "sorpresa (CYCLE 59) y del selector no-regret (CYCLE 66/74). Próximo: calibrar/seleccionar el umbral "
                    "de sorpresa (CYCLE 74); integrar con el lazo cerrado real (93-96); objetivo VECTOR; y SCALE."),
        measurement=("exp083 ({n} seeds, reward action-gated): estacionario surprise={ss_} vs explore={es} (+{ss}) ≈ greedy="
                     "{gs}; drift surprise={sd} >= explore={ed}, > greedy (+{dre}); surprise_avg={sa} mejor (vs greedy {ga}/"
                     "explore {ea}).").format(n=n_seeds, ss_=_f(st['surprise_explore']), es=_f(st['explore']), ss=_f(ss),
                                              gs=_f(st['greedy']), sd=_f(dr['surprise_explore']), ed=_f(dr['explore']),
                                              dre=_f(dre), sa=_f(sa), ga=_f(ga), ea=_f(ea)),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (explorar sólo cuando el barrio de siempre deja de rendir).")

    kl = ("REAL (exp083): la exploración SURPRISE-GATED DOMINA al ε-fijo y es no-regret -- ahorra en estacionario "
          "(surprise={ss_} vs explore={es}, +{ss}) ≈ greedy; rescata en drift (surprise={sd} >= explore, > greedy +{dre}); "
          "surprise_avg={sa} mejor. Cierra el caveat 'ε fijo' de CYCLE 98. TECHO: margen vs greedy chico (greedy robusto, "
          "CYCLE 98); tradeoff de umbral de detección (sensibilidad-drift vs especificidad-estacionario); bump sintético, "
          "drift abrupto.").format(ss_=_f(st['surprise_explore']), es=_f(st['explore']), ss=_f(ss),
                                   sd=_f(dr['surprise_explore']), dre=_f(dre), sa=_f(sa))
    ceilings.add(CeilingRecord(
        subsystem="Exploración SURPRISE-GATED en la asignación — domina al ε fijo y es no-regret (cierra el caveat ε-fijo de CYCLE 98; análogo de CYCLE 59/74 para exploración)",
        known_limit=kl,
        blockers=[{"text": "el margen vs GREEDY es chico: greedy es robusto bajo drift mild (se auto-corrige, CYCLE 98); la clara victoria es sobre el ε-FIJO (el esquema de exploración), no sobre greedy", "kind": "diseno"},
                  {"text": "TRADEOFF de umbral de detección: estricto baja el falso-positivo estacionario pero sub-detecta el drift; laxo al revés -> el cierre pleno requiere calibrar/seleccionar el umbral (selector CYCLE 74)", "kind": "fisico"},
                  {"text": "valor bump sintético, drift ABRUPTO por fases, k_obs=2 fijo, numpy/juguete; falta integrar con el lazo cerrado real (93-96) y SCALE", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP083.ref, S_EXP082.ref]))
    notes.append("1 techo 'real': exploración surprise-gated domina al ε-fijo y es no-regret; cierra el sub-arco 97-99.")

    dstmt = ("North-Star R-VALOR/R-INTERVENCIÓN (cierra el sub-arco 97-99 con no-regret): bajo no-estacionariedad, la "
             "exploración SURPRISE-GATED (explorar sólo cuando la sorpresa -- el combinador sobre-predijo lo que eligió "
             "greedy -- indica cambio) DOMINA al ε fijo y es no-regret: ahorra en estacionario y rescata en drift, sin "
             "hiperparámetro de exploración fijo. Decisión: la política de asignación bajo drift usa exploración gateada "
             "por sorpresa (no ε fijo), el análogo del olvido por sorpresa (CYCLE 59) y del selector no-regret (CYCLE "
             "66/74) para la EXPLORACIÓN. Caveat: greedy es robusto (CYCLE 98), el margen vs greedy es chico; hay un "
             "tradeoff de umbral de detección. Próximo: calibrar/seleccionar el umbral; integrar con el lazo cerrado real; "
             "objetivo VECTOR; y SCALE.")
    drat = ("exp083 (tier5, propio, {n} seeds, numpy, reward action-gated): surprise DOMINA al ε-fijo (ahorra +{ss} "
            "estacionario, drift vs_explore {dve}) y es no-regret (surprise_avg {sa} vs greedy {ga}/explore {ea}, margen "
            "{nrm}). Convergente con detección por sorpresa/exploración adaptativa (tier2, análogo CYCLE 59) y con el "
            "ε-fijo de CYCLE 98 (tier5). APOYADA: surprise-gated es el esquema de exploración no-regret.").format(
                n=n_seeds, ss=_f(ss), dve=_f(dve), sa=_f(sa), ga=_f(ga), ea=_f(ea), nrm=_f(nrm))
    dec = Decision(id="D-V4-61", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP083), _to_plain(S_EXP082)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-61 ACEPTADA por el ledger (tier5 exp083 + tier5 exp082).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-61:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle99_surprise_explore',
                                description='CYCLE 99 (RESET v4, H-V4-7l: la exploración surprise-gated domina al ε-fijo y es no-regret -- cierra el sub-arco 97-99).')
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
    print("RESUMEN — CYCLE 99 (RESET v4): exploración SURPRISE-GATED domina al ε-fijo y es no-regret (H-V4-7l) — cierra 97-99")
    print("=" * 78)
    print("veredicto H-V4-7l:", status.upper() if status else "?")
    print("  explorar sólo al detectar cambio por sorpresa: ahorra en estacionario, rescata en drift. Análogo de CYCLE 59/74 para exploración.")
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
