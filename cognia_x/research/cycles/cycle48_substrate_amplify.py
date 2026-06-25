r"""
cycle48_substrate_amplify.py — CICLO 48 (RESET v4): H-V4-2 por las compuertas del engine. CAPSTONE del arco
v4 (cierra el lazo verify->sustrato->razonamiento).

H-V4-2: el lazo act-and-verify no sólo asigna cómputo (40-47) — genera DATOS verificados que MEJORAN el
sustrato barato (auto-mejora STaR por la señal de CORRECCIÓN, no el volumen), y esa mejora del paso se
AMPLIFICA en cadenas largas (p^K). El sustrato es el lever dominante del multi-paso, y el lazo lo entrega.
DERIVA de exp034_substrate_amplify/results/results.json.

RESULTADO REAL: APOYADA (4 seeds, modelo propio HybridLM).
  - PASO (suma held-out): base 0.317 -> VERIFIED 0.419 (+0.102) vs CONTROL 0.258 (Δvs_ctl=+0.160). Verified
    supera al base Y al control -> la SEÑAL DE CORRECCIÓN, no el volumen (el control entrenando con salidas sin
    verificar incluso EMPEORA el base).
  - AMPLIFICACIÓN (cadena greedy, sin orquestación, aísla el sustrato): ratio VERIFIED/BASE crece monótono con
    K: K1 1.32× -> K2 1.93× -> K3 2.71×. Curva K->BASE/VERIFIED: K1 0.438/0.578 | K2 0.183/0.353 | K3 0.080/0.217.
  => una mejora MODESTA del paso (+0.10) rinde una mejora COMPUESTA en multi-paso (2.71× a K=3). El sustrato es
     el lever dominante que el sub-arco 44-47 señalaba, y el lazo verify->reentrenar lo entrega gratis de las
     propias salidas correctas del modelo. CIERRA el arco v4: R-VALOR/R-INTERVENCIÓN (act+verify) -> mejor
     sustrato -> razonamiento amplificado.

Correr (DESPUÉS de exp034):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp034_substrate_amplify.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle48_substrate_amplify
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
                             'cycle48_substrate_amplify')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp034_substrate_amplify', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _fmt(x):
    return "{:.3f}".format(x) if isinstance(x, (int, float)) else str(x)


S_STAR = Source(tier=1, ref="arXiv:2203.14465", obtained=False,
                claim=("STaR (Zelikman 2022): reentrenar con las propias salidas VERIFICADO-correctas mejora el "
                       "razonamiento (bootstrapping por rejection sampling). (Principio, no re-obtenido.)"))
S_EXP016 = Source(tier=5, ref="cognia_x/experiments/exp016_verified_bootstrap", obtained=True,
                  claim=("exp016 (CYCLE 29, H-LEARN-1): la auto-mejora verificada funciona y la SEÑAL DE "
                         "CORRECCIÓN (no el volumen) es el motor (control random_matched lo aísla)."))
S_EXP033 = Source(tier=5, ref="cognia_x/experiments/exp033_backtrack_retry", obtained=True,
                  claim=("exp033/CYCLE 47: los 4 mecanismos de orquestación multi-paso (44-47) convergen al "
                         "cuello de botella de la PRECISIÓN POR PASO -> el lever es el SUSTRATO."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    v = data.get('verdict')
    st = data.get('stats')
    if not v or not st:
        raise SystemExit("results.json sin verdict/stats (corre exp034 primero): " + results_path)
    status = v.lower()
    step = st['step']
    curve = st['curve']
    Ks = [str(x) for x in data.get('Ks', [])]
    Kmax = str(st['Kmax'])
    r_lo, r_hi = st['ratio_lo'], st['ratio_hi']
    n_seeds = st['n_seeds']
    d_base = step['verified'] - step['base']
    d_ctl = step['verified'] - step['control']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    S_EXP034 = Source(tier=5, ref="cognia_x/experiments/exp034_substrate_amplify", obtained=True,
                      claim=("exp034 (propio, {n} seeds, modelo HybridLM): auto-mejora VERIFICADA sube el paso "
                             "base {sb}->{sv} (+{db}) vs control {sc} (la corrección, no el volumen; el control "
                             "empeora el base), y la mejora se AMPLIFICA en cadena: ratio verified/base K1 {rl}× "
                             "-> K{km} {rh}×.").format(n=n_seeds, sb=_fmt(step['base']), sv=_fmt(step['verified']),
                                                       db=_fmt(d_base), sc=_fmt(step['control']), rl=_fmt(r_lo),
                                                       km=st['Kmax'], rh=_fmt(r_hi)))
    for src in (S_STAR, S_EXP016, S_EXP033, S_EXP034):
        ledger.add_source(src)
    notes.append("4 fuentes (S_STAR tier1; S_EXP016 tier5 STaR verificado; S_EXP033 tier5 cuello de botella; S_EXP034 tier5 dato propio).")

    ev_for = [S_EXP034.ref, S_EXP016.ref]
    ev_against = [S_EXP034.ref]      # honesto: a K>=4 la cadena greedy es ~0 (piso de medición); base débil
    adv = ("APOYADA, capstone del arco v4. (a) AUTO-MEJORA POR CORRECCIÓN: entrenar con las propias salidas "
           "VERIFICADO-correctas sube la precisión por paso del base {sb}->{sv} (+{db}) y supera al CONTROL "
           "{sc} (+{dc}) — que entrena con el MISMO volumen de salidas SIN verificar y hasta EMPEORA el base. "
           "Es la señal de CORRECCIÓN, no el volumen (control decisivo, replica exp016 en este sustrato). (b) "
           "AMPLIFICACIÓN: en cadena greedy (sin orquestación -> aísla el sustrato) el ratio verified/base CRECE "
           "monótono con la longitud: {rl}× (K1) -> {rh}× (K{km}); una mejora MODESTA del paso (+0.10) rinde "
           "una mejora COMPUESTA en multi-paso. Esto cierra el arco: el sub-arco 44-47 mostró que la "
           "orquestación de cómputo topa con la precisión por paso; aquí el lazo act-and-verify MEJORA esa "
           "precisión por paso desde las propias salidas correctas, y el efecto se amplifica en lo largo. "
           "Ataques considerados: (1) '¿es sólo más datos?' -> NO: el control (mismo N, sin verificar) empeora "
           "-> es la corrección. (2) '¿la amplificación es artefacto de medir cerca de 0?' -> se midió a Ks "
           "cortos (1,2,3) con accuracy de cadena medible (>=0.08); a K>=4 la greedy cae a ~0 (piso, declarado). "
           "EVIDENCIA EN CONTRA (honesta): el base es débil y la cadena larga (K>=4) no es medible greedy; la "
           "amplificación está demostrada a K<=3 (donde el ratio ya llega a {rh}×).").format(
               sb=_fmt(step['base']), sv=_fmt(step['verified']), db=_fmt(d_base), sc=_fmt(step['control']),
               dc=_fmt(d_ctl), rl=_fmt(r_lo), rh=_fmt(r_hi), km=st['Kmax'])

    hyp = Hypothesis(
        id="H-V4-2",
        statement=("El lazo act-and-verify mejora el sustrato barato (precisión por paso) desde sus propias "
                   "salidas VERIFICADO-correctas (señal de corrección, no volumen), y esa mejora se AMPLIFICA en "
                   "razonamiento multi-paso (p^K)."),
        prediction=("APOYADA si verified > base y > control en el paso (>=0.03) Y el ratio verified/base en "
                    "cadena a Kmax > a K=1; REFUTADA si no supera al base/control o no amplifica. (Pre-registrada.)"),
        status='abierta', confidence='alta',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=adv, experiment_ref="exp034_substrate_amplify")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-2")
        notes.append("H-V4-2 marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("¿Conviene gastar el esfuerzo en ORQUESTAR mejor (cómo uso lo que tengo) o en MEJORAR EL "
                 "LADRILLO (qué tan bien hago cada paso simple)?"),
        everyday=("Si mejorás un poco tu precisión en CADA cuenta simple (50%->65%), tu chance de clavar una "
                  "cuenta larga de un tirón salta MUCHO más que ese poco (compuesto: 0.5^6 vs 0.65^6 ≈ 4.7×). Y "
                  "el truco es gratis: practicás con TUS PROPIAS cuentas que SALIERON BIEN (verificadas) — no "
                  "con cualquiera (entrenar con las que salieron mal te empeora)."),
        solutions=["mejorar el SUSTRATO (precisión por paso) con auto-salidas VERIFICADAS -> +0.10 paso, 2.71× cadena a K=3",
                   "entrenar con auto-salidas SIN verificar (control) -> EMPEORA el base (no es volumen, es corrección)",
                   "sólo ORQUESTAR (40-47) -> topa con la precisión por paso (rinde cada vez menos)",
                   "la mejora del paso se AMPLIFICA en lo largo (p^K) -> el sustrato es el lever dominante del multi-paso"],
        principles=["la señal de CORRECCIÓN (verificar) entrena un sustrato mejor; el volumen sin verificar no (empeora)",
                    "una mejora modesta del paso rinde compuesta en multi-paso (p^K) -> el sustrato domina sobre la orquestación",
                    "el lazo act-and-verify es DOBLE: asigna cómputo en test (40-47) Y genera datos para mejorar el sustrato (48)",
                    "cierra el arco v4: actuar+verificar (R-INTERVENCIÓN) con valor de control (R-VALOR) -> mejor sustrato -> razonamiento"],
        adaptation=("El integrador del lab es un LAZO DE AUTO-MEJORA: razonar con act-and-verify, quedarse con "
                    "los pasos verificados, reentrenar el sustrato, repetir. Próximos: iterar el lazo varias "
                    "rondas (¿hasta dónde sube?), verificador REAL-chequeable (código→sandbox) para tareas más "
                    "ricas que la suma, y cadenas de razonamiento de verdad (no sólo aritmética)."),
        measurement=("exp034: paso base {sb}->verified {sv} (+{db}) vs control {sc}; ratio cadena {rl}×(K1)->"
                     "{rh}×(K{km}). {n} seeds.").format(sb=_fmt(step['base']), sv=_fmt(step['verified']),
                                                        db=_fmt(d_base), sc=_fmt(step['control']), rl=_fmt(r_lo),
                                                        rh=_fmt(r_hi), km=st['Kmax'], n=n_seeds),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (mejorar el ladrillo barato rinde compuesto; practicar con las propias cuentas bien hechas).")

    ceilings.add(CeilingRecord(
        subsystem="SUSTRATO — auto-mejora verificada del paso y su AMPLIFICACIÓN en multi-paso (cierra el arco v4)",
        known_limit=("REAL (exp034): el lazo act-and-verify mejora la precisión por paso del sustrato desde sus "
                     "auto-salidas VERIFICADAS (+{db} sobre base, por la corrección no el volumen), y la mejora "
                     "se AMPLIFICA en cadena (ratio {rl}×->{rh}× de K1 a K{km}). El sustrato es el lever "
                     "dominante del multi-paso.").format(db=_fmt(d_base), rl=_fmt(r_lo), rh=_fmt(r_hi), km=st['Kmax']),
        blockers=[{"text": "base débil (CPU) -> cadena greedy a K>=4 cae a ~0 (piso de medición); la amplificación se demostró a K<=3", "kind": "fisico"},
                  {"text": "una sola ronda de STaR; falta iterar el lazo (¿hasta dónde sube la precisión por paso?) y verificar saturación", "kind": "diseno"},
                  {"text": "tarea aritmética con oráculo exacto; falta verificador real-chequeable (código→sandbox) y razonamiento no-aritmético", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP034.ref, S_EXP016.ref]))
    notes.append("1 techo 'real': auto-mejora verificada del paso + amplificación multi-paso (el sustrato es el lever dominante).")

    dstmt = ("CIERRE DEL ARCO v4: el integrador del lab es un LAZO DE AUTO-MEJORA, no sólo orquestación. El lazo "
             "act-and-verify (1) asigna cómputo en test-time guiado por controlabilidad y la fiabilidad del "
             "verificador (40-43), (2) lo extiende a multi-paso con verificación de proceso + presupuesto "
             "adaptativo + abstención + backtracking (44-47), y (3) genera datos VERIFICADOS que mejoran la "
             "precisión por paso del sustrato barato (48), mejora que se AMPLIFICA en razonamiento multi-paso "
             "(p^K). Unifica R-INTERVENCIÓN (actuar+verificar) y R-VALOR (valor de controlabilidad) en un "
             "sistema CPU-first sobre el modelo propio del lab. Próximos: iterar el lazo de auto-mejora varias "
             "rondas, verificador real-chequeable (código→sandbox) para tareas más ricas, y razonamiento "
             "no-aritmético — el camino hacia 'algo que habla y razona, barato'.")
    drat = ("exp034 (tier5, propio, {n} seeds): paso base {sb}->verified {sv} (+{db}, señal de corrección: "
            "control {sc} empeora); amplificación cadena {rl}×->{rh}× de K1 a K{km}. Convergente con STaR "
            "(Zelikman 2022) y con exp016. Cierra el arco v4 (orquestación 40-47 + sustrato 48).").format(
                n=n_seeds, sb=_fmt(step['base']), sv=_fmt(step['verified']), db=_fmt(d_base),
                sc=_fmt(step['control']), rl=_fmt(r_lo), rh=_fmt(r_hi), km=st['Kmax'])
    dec = Decision(id="D-V4-13", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP034), _to_plain(S_EXP016)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-13 ACEPTADA por el ledger (tier5 exp034 + tier5 exp016).")
    except OpinionOnlyError as e:
        print("ERROR ledger D-V4-13:", e); raise

    return record, notes, status, st


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle48_substrate_amplify',
                                description='CYCLE 48 (RESET v4, H-V4-2: sustrato — auto-mejora verificada + amplificación).')
    p.add_argument('--store', default=DEFAULT_STORE)
    p.add_argument('--results', default=DEFAULT_RESULTS)
    p.add_argument('--reset', dest='reset', action='store_true', default=True)
    p.add_argument('--no-reset', dest='reset', action='store_false')
    args = p.parse_args(argv)
    store = os.path.abspath(args.store)
    if args.reset and os.path.isdir(store):
        shutil.rmtree(store)
    os.makedirs(store, exist_ok=True)
    record, notes, status, st = run(store, os.path.abspath(args.results))
    res = record.verify_no_loss()
    print("=" * 78)
    print("RESUMEN — CYCLE 48 (RESET v4): SUSTRATO — auto-mejora verificada + amplificación (H-V4-2)")
    print("=" * 78)
    print("veredicto H-V4-2:", status.upper() if status else "?")
    print("  el lazo verify->reentrenar mejora el paso (corrección, no volumen) y la mejora se amplifica en multi-paso.")
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
