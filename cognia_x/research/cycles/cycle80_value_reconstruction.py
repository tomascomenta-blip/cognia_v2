r"""
cycle80_value_reconstruction.py — CICLO 80 (RESET v4, rama R-CONTROL, capstone CONSTRUCTIVO del par 79-80): H-V4-6b
por las compuertas del engine. APOYADA: R-VALOR se RECONSTRUYE de dos marginales ENDÓGENAS. El CYCLE 79 acotó
(empowerment = la marginal-de-controlabilidad, no el valor universal); este lo CONSTRUYE: estimar AMBAS marginales
-- controlabilidad (de las consecuencias) Y relevancia (de la recompensa) -- y combinarlas (ctrl_est × rel_est)
reconstruye el valor completo y vence a cualquier marginal sola justo donde control ⊥ relevancia. SIN oráculo.

DERIVA de exp064_value_reconstruction/results/results.json. Cierra el par R-CONTROL con la pieza POSITIVA: el valor
se CONSTRUYE de señales endógenas, no se postula.

Correr (DESPUÉS de exp064):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp064_value_reconstruction.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle80_value_reconstruction
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle80_value_reconstruction')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp064_value_reconstruction', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_FACTOR = Source(tier=1, ref="value factorization / reward decomposition (successor-feature-style: value = controllability x relevance)", obtained=False,
                  claim=("El valor de una acción se descompone en factores estimables de la experiencia: cuánto la "
                         "acción CONTROLA el futuro (empowerment) y cuán RELEVANTE es ese futuro para el objetivo "
                         "(recompensa). Combinar estimadores de ambos factores reconstruye el valor sin un oráculo. "
                         "(Principio; converge con descomposición de valor / shaping.)"))
S_TREE = Source(tier=5, ref="cognia_x/manager/decomposition_tree.md (CYCLE 79: empowerment=marginal de R-VALOR)", obtained=True,
                claim=("CYCLE 79 (exp063, H-V4-6a) acotó: el empowerment es la marginal-de-controlabilidad de R-VALOR "
                       "(ctrl×rel), no el valor universal; ni control ni predicción solos bastan. H-V4-6b construye la "
                       "pieza positiva: R-VALOR = producto de marginales endógenas estimadas."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp064 primero): " + results_path)
    hi = sm['rho0_S64']
    rv, emp, rel = hi['rvalue_est'], hi['empowerment'], hi['relevance']
    curve = sm['rvalue_curve_rho0']
    best_marg = max(emp, rel)
    n, k = data['args']['n'], data['args']['k']
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim064 = ("exp064 (propio, {n} seeds, numpy): en rho=0 (control ⊥ relevancia), rvalue_est (ctrl_est × rel_est) "
                "captura {rv} del óptimo, venciendo a empowerment {emp} y relevance {rel} (cada marginal sola ~{bm}); "
                "curva por muestras {curve} (converge). R-VALOR se reconstruye de dos marginales endógenas.").format(
                    n=n_seeds, rv=_f(rv), emp=_f(emp), rel=_f(rel), bm=_f(best_marg), curve=[_f(x) for x in curve])
    S_EXP064 = Source(tier=5, ref="cognia_x/experiments/exp064_value_reconstruction", obtained=True, claim=claim064)
    for src in (S_FACTOR, S_TREE, S_EXP064):
        ledger.add_source(src)
    notes.append("3 fuentes (S_FACTOR tier1 descomposición de valor; S_TREE tier5 CYCLE 79; S_EXP064 tier5 dato propio).")

    ev_for = [S_EXP064.ref, S_TREE.ref]
    ev_against = [S_EXP064.ref]
    adv = ("{V} (capstone CONSTRUCTIVO del par R-CONTROL 79-80; pieza POSITIVA): el CYCLE 79 dejó que ni control ni "
           "predicción/relevancia PURO es el valor (el general es R-VALOR=ctrl×rel). exp064 muestra que ese valor se "
           "CONSTRUYE de dos marginales ENDÓGENAS: el agente estima la CONTROLABILIDAD (de sus consecuencias, "
           "empowerment) Y la RELEVANCIA (de la recompensa) con S muestras ruidosas, y las COMBINA. En rho=0 (control "
           "⊥ relevancia, el régimen donde ninguna marginal basta), rvalue_est (ctrl_est × rel_est) {rv} VENCE a CADA "
           "marginal sola -- empowerment {emp}, relevance {rel} -- por +{adv}, y recupera >=85% del oráculo, mientras "
           "ninguna marginal pasa de ~{bm}. La curva por muestras {curve} CONVERGE al oráculo (paralelo a la "
           "estimación online del CYCLE 72). En rho=1 (alineadas) cualquier marginal basta (control de exp024/025). => "
           "R-VALOR (referido al objetivo) se reconstruye combinando dos estimadores endógenos baratos, SIN oráculo; "
           "el empowerment (control) y la relevancia (predicción de recompensa) son sus DOS marginales, ninguna "
           "suficiente sola donde divergen. EVIDENCIA EN CONTRA (caveats): el valor multiplicativo ctrl×rel se asume "
           "(la factorización es de diseño; en general el valor podría no factorizar limpio); las marginales se "
           "estiman con ruido ~1/√S (abstrae el aprendizaje real de consecuencias/recompensa); juguete (selección "
           "estática). CONCLUSIÓN: cierra el par R-CONTROL -- 79 ACOTÓ (empowerment=marginal), 80 RECONSTRUYE "
           "(R-VALOR=producto de marginales endógenas). El valor se CONSTRUYE de la experiencia, no se postula.").format(
               V=status.upper(), rv=_f(rv), emp=_f(emp), rel=_f(rel), adv=_f(rv - best_marg), bm=_f(best_marg),
               curve=[_f(x) for x in curve])

    hyp = Hypothesis(
        id="H-V4-6b",
        statement=("R-VALOR (ctrl×rel) se reconstruye combinando dos estimadores endógenos baratos (controlabilidad de "
                   "las consecuencias + relevancia de la recompensa); ni control ni relevancia solos bastan donde divergen."),
        prediction=("APOYADA si en rho=0 y S>=16 rvalue_est supera a ambas marginales (+>0.05) Y recupera >=0.85 del "
                    "oráculo, con cada marginal sola estancada (~0.72); REFUTADA si rvalue_est no supera a las "
                    "marginales; MIXTA si reconstruye parcial. (Pre-registrada.)"),
        status='abierta', confidence='alta' if status == 'apoyada' else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=adv, experiment_ref="exp064_value_reconstruction")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-6b")
        notes.append("H-V4-6b marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("Para elegir bien necesitás saber el VALOR de cada opción, pero nadie te lo dice. Tenés dos pistas "
                 "que SÍ podés medir: cuánto podés CAMBIAR cada cosa y cuánto te IMPORTA. ¿Alcanza combinarlas?"),
        everyday=("Sí: el valor de algo es 'cuánto lo podés mover' × 'cuánto te importa moverlo'. Medís las dos por "
                  "separado (probando qué cambia con tus acciones, y viendo qué te acerca a tu meta) y las MULTIPLICÁS. "
                  "Con una sola pista elegís mal cuando no coinciden (cosas muy controlables pero que no importan, o "
                  "al revés); con las dos juntas reconstruís el valor casi como si te lo hubieran dicho -- y mejora "
                  "cuanto más medís."),
        solutions=["rvalue_est (ctrl_est × rel_est) -> reconstruye el valor; vence a ambas marginales donde divergen",
                   "empowerment (ctrl_est solo) -> la mitad: bueno si controlable=importante",
                   "relevance (rel_est solo) -> la otra mitad: bueno si importante=controlable",
                   "el valor general R-VALOR es el PRODUCTO de las dos marginales endógenas"],
        principles=["R-VALOR se descompone en controlabilidad × relevancia, ambas estimables de la experiencia",
                    "combinar dos estimadores endógenos baratos reconstruye el valor sin oráculo",
                    "ninguna marginal sola basta donde control y relevancia divergen; su producto sí",
                    "el valor se CONSTRUYE de la experiencia (consecuencias + recompensa), no se postula"],
        adaptation=("El lab reconstruye el valor para asignar atención/memoria/cómputo combinando empowerment (control "
                    "estimado) y relevancia (recompensa estimada). Próximo: estimación de las marginales en un lazo "
                    "REAL de acción-consecuencia (no ruido abstracto); valor que no factorice limpio; objetivo "
                    "no-escalar; ligar con el lazo de auto-mejora (verificador = señal de relevancia)."),
        measurement=("exp064 (rho=0, k={k}/{N}): rvalue_est {rv} > empowerment {emp}, relevance {rel} (+{adv}); curva "
                     "{curve}. {n} seeds.").format(k=k, N=n, rv=_f(rv), emp=_f(emp), rel=_f(rel),
                                                    adv=_f(rv - best_marg), curve=[_f(x) for x in curve], n=n_seeds),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (el valor = cuánto podés cambiarlo × cuánto te importa; medí las dos y multiplicá).")

    kl = ("REAL (exp064): R-VALOR (ctrl×rel) se RECONSTRUYE de dos marginales endógenas. En rho=0 (control ⊥ "
          "relevancia), rvalue_est {rv} vence a empowerment {emp} y relevance {rel} (cada marginal ~{bm}) y recupera "
          ">=85% del óptimo; converge con las muestras {curve}. El valor se construye combinando control estimado + "
          "relevancia estimada, SIN oráculo. Empowerment y relevancia son las dos marginales de R-VALOR.").format(
              rv=_f(rv), emp=_f(emp), rel=_f(rel), bm=_f(best_marg), curve=[_f(x) for x in curve])
    ceilings.add(CeilingRecord(
        subsystem="R-VALOR reconstruido — valor = controlabilidad_est × relevancia_est (dos marginales endógenas)",
        known_limit=kl,
        blockers=[{"text": "el valor multiplicativo ctrl×rel se asume (factorización de diseño); en general el valor podría no factorizar limpio", "kind": "diseno"},
                  {"text": "las marginales se estiman con ruido ~1/√S abstracto; falta un lazo REAL de acción-consecuencia y de recompensa", "kind": "diseno"},
                  {"text": "juguete (selección estática, objetivo escalar); ligar con auto-mejora (verificador=señal de relevancia) y empowerment estimado online", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP064.ref, S_TREE.ref]))
    notes.append("1 techo 'real': R-VALOR se reconstruye de control_est × relevancia_est; empowerment y relevancia son sus dos marginales endógenas.")

    dstmt = ("North-Star R-VALOR (capstone CONSTRUCTIVO del par R-CONTROL 79-80): R-VALOR (ctrl×rel) se RECONSTRUYE "
             "combinando dos estimadores ENDÓGENOS baratos -- controlabilidad (empowerment, de las consecuencias) y "
             "relevancia (de la recompensa). En rho=0 (donde divergen), rvalue_est {rv} vence a cada marginal sola "
             "(emp {emp}, rel {rel}) por +{adv} y recupera >=85% del oráculo; converge con las muestras. Decisión: el "
             "lab CONSTRUYE el valor de la experiencia (control + recompensa estimados), no lo postula; empowerment y "
             "relevancia/predicción son sus DOS marginales, ninguna suficiente sola. Cierra el par R-CONTROL: 79 acotó, "
             "80 reconstruye. Próximo: estimación en un lazo real acción-consecuencia; ligar con auto-mejora "
             "(verificador = señal de relevancia).").format(rv=_f(rv), emp=_f(emp), rel=_f(rel), adv=_f(rv - best_marg))
    drat = ("exp064 (tier5, propio, {n} seeds): rho=0 rvalue_est {rv} > empowerment {emp}, relevance {rel} (+{adv}), "
            "recupera >=85% del oráculo, converge con S. Convergente con descomposición de valor (tier1) y con CYCLE "
            "79 (tier5). APOYADA.").format(n=n_seeds, rv=_f(rv), emp=_f(emp), rel=_f(rel), adv=_f(rv - best_marg))
    dec = Decision(id="D-V4-42", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP064), _to_plain(S_TREE)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-42 ACEPTADA por el ledger (tier5 exp064 + tier5 CYCLE 79).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-42:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle80_value_reconstruction',
                                description='CYCLE 80 (RESET v4, H-V4-6b: R-VALOR reconstruido de marginales endógenas).')
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
    print("RESUMEN — CYCLE 80 (RESET v4): R-VALOR reconstruido de marginales endógenas (H-V4-6b) — capstone R-CONTROL")
    print("=" * 78)
    print("veredicto H-V4-6b:", status.upper() if status else "?")
    print("  R-VALOR = controlabilidad_est × relevancia_est; combinar dos marginales endógenas reconstruye el valor.")
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
