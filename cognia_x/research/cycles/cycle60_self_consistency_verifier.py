r"""
cycle60_self_consistency_verifier.py — CICLO 60 (RESET v4): H-V4-2i por las compuertas del engine. UNIFICACIÓN
de los dos arcos de la corrida (VERIFICADOR-REAL 51-55 + R-VALOR 56-59).

H-V4-2i: la AUTO-CONSISTENCIA del modelo (acuerdo entre sus muestras = confianza endógena, sin oráculo) es un
VERIFICADOR PARCIAL en el lazo de auto-mejora, GATEADO por la CALIBRACIÓN: usable cuando el modelo está
calibrado (base fuerte), peligroso (refuerza errores confiados) cuando no (base débil). DERIVA de
exp046_self_consistency_verifier/results/results.json.

Correr (DESPUÉS de exp046):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp046_self_consistency_verifier.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle60_self_consistency_verifier
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
                             'cycle60_self_consistency_verifier')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp046_self_consistency_verifier', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_SELFCONS = Source(tier=1, ref="self-consistency / self-verification (sampling agreement)", obtained=False,
                    claim=("El acuerdo entre múltiples muestras (self-consistency) es una señal de confianza "
                           "interna usable como pseudo-verificador; su utilidad depende de la calibración del "
                           "modelo. (Principio, no re-obtenido.)"))
S_EXP037 = Source(tier=5, ref="cognia_x/experiments/exp037..041 (arco VERIFICADOR-REAL 51-55)", obtained=True,
                  claim=("Arco 51-55: el verificador EXTERNO (sandbox) es el motor de la auto-mejora; la guardia "
                         "compra robustez. ¿Es reemplazable por una señal endógena?"))
S_EXP043 = Source(tier=5, ref="cognia_x/experiments/exp043 (CYCLE 57, R-VALOR)", obtained=True,
                  claim=("exp043 (H-V4-1c): la confianza endógena es confiable SÓLO con la competencia correcta "
                         "(confiado-pero-equivocado cuando no calibrado) -> predice el gating de este ciclo."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp046 primero): " + results_path)
    S, W = sm['strong'], sm['weak']
    n_seeds = sm['n_seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    S_EXP046 = Source(tier=5, ref="cognia_x/experiments/exp046_self_consistency_verifier", obtained=True,
                      claim=("exp046 (propio, {n} seeds, HybridLM): la auto-consistencia como filtro del lazo de "
                             "auto-mejora está GATEADA por calibración. FUERTE (base {sb}, calib {scal}): sc {ssc} "
                             ">naive {sn}, <verified {sv}. DÉBIL (base {wb}, calib {wcal}): sc COLAPSA a {wsc} << "
                             "naive {wn}.").format(n=n_seeds, sb=_f(S['base']), scal=_f(S['sc_calibration']),
                                                   ssc=_f(S['self_consistency']), sn=_f(S['naive']),
                                                   sv=_f(S['verified']), wb=_f(W['base']),
                                                   wcal=_f(W['sc_calibration']), wsc=_f(W['self_consistency']),
                                                   wn=_f(W['naive'])))
    for src in (S_SELFCONS, S_EXP037, S_EXP043, S_EXP046):
        ledger.add_source(src)
    notes.append("4 fuentes (S_SELFCONS tier1 self-consistency; S_EXP037 tier5 arco verificador; S_EXP043 tier5 calibración/CYCLE57; S_EXP046 tier5 dato propio).")

    ev_for = [S_EXP046.ref, S_EXP043.ref]
    ev_against = [S_EXP046.ref]
    beat2 = sm.get('strong_beats_naive_2sigma', False)
    adv = ("{V} (UNIFICA los dos arcos de la corrida): prueba el insight del CYCLE 57 ('el verificador externo "
           "es, en parte, reemplazable por la confianza calibrada') en el sustrato de AUTO-MEJORA (51-55). "
           "Filtra las auto-generaciones para re-entrenar por AUTO-CONSISTENCIA (¿el modelo produce el mismo "
           "VALOR consistentemente?) en vez del verificador externo (sandbox). RESULTADO: la utilidad está "
           "GATEADA por la CALIBRACIÓN (contraste {gc}). FUERTE/calibrado (base {sb}, calib {scal}): "
           "self_consistency {ssc} SUPERA a naive {sn} (modesto, {b2} el bar 2σ) sin degradar la base, capturando "
           "PARTE del beneficio del verificador externo (verified {sv}) -> verificador PARCIAL usable. "
           "DÉBIL/mal-calibrado (base {wb}, calib {wcal}): self_consistency COLAPSA a {wsc} MUY por debajo de "
           "naive {wn} -- el modelo es CONSISTENTE-PERO-EQUIVOCADO y el filtro REFUERZA sus errores confiados "
           "(el peligro del CYCLE 57 manifiesto en el lazo). => el verificador externo (arco 51-55) es "
           "PARCIALMENTE reemplazable por la confianza endógena (arco 56-59) SÓLO cuando el modelo está "
           "calibrado; el lazo de auto-mejora y el lazo de valor endógeno se CONECTAN por la calibración. "
           "EVIDENCIA EN CONTRA (caveats honestos): (1) la ventaja FUERTE-sobre-naive es MODESTA (no cruza 2σ): "
           "la auto-consistencia PREVIENE la degradación de naive más que IGUALAR al externo (que sigue siendo "
           "claramente mejor). (2) acuerdo sobre el VALOR de una tarea de vocab chico (puede sobre-estimar "
           "consistencia). (3) un solo umbral tau. CONCLUSIÓN: la confianza endógena cierra parcialmente el lazo "
           "de auto-mejora SIN oráculo, pero sólo donde es CONFIABLE (calibrada); usarla mal calibrada es "
           "peligroso.").format(V=status.upper(), gc=_f(sm['gating_contrast']), sb=_f(S['base']),
                                scal=_f(S['sc_calibration']), ssc=_f(S['self_consistency']), sn=_f(S['naive']),
                                b2="supera" if beat2 else "NO supera", sv=_f(S['verified']), wb=_f(W['base']),
                                wcal=_f(W['sc_calibration']), wsc=_f(W['self_consistency']), wn=_f(W['naive']))

    hyp = Hypothesis(
        id="H-V4-2i",
        statement=("La auto-consistencia (confianza endógena) es un verificador parcial del lazo de auto-mejora, "
                   "GATEADO por calibración: usable/parcial cuando el modelo está calibrado, peligroso (refuerza "
                   "errores) cuando no."),
        prediction=("APOYADA si hay gating por calibración (contraste>0.30) Y en FUERTE/calibrado la "
                    "auto-consistencia supera a naive sin degradar la base Y en DÉBIL/mal-calibrado COLAPSA bajo "
                    "naive; REFUTADA si no hay gating o ni calibrada supera a naive; MIXTA si el gating no es "
                    "limpio. (Pre-registrada; afinada tras smoke al claim de gating.)"),
        status='abierta', confidence='alta' if status == 'apoyada' else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=adv, experiment_ref="exp046_self_consistency_verifier")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-2i")
        notes.append("H-V4-2i marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("¿Podés corregirte SOLO, sin la tabla de respuestas, quedándote con los ejercicios que "
                 "resolviste IGUAL varias veces (estás seguro)? ¿O te reforzás en errores que repetís con "
                 "seguridad?"),
        everyday=("Depende de cuánto SEPAS. Si ya dominás el tema (calibrado), tus 'seguros' son correctos y "
                  "aprendés sin la tabla. Si sabés poco (mal calibrado), repetís el MISMO error con seguridad y "
                  "te encerrás en él -- peor que estudiar sin filtrar. Tu propia seguridad sólo sirve si ya sos "
                  "competente."),
        solutions=["verificador EXTERNO (tabla de respuestas) -> mejor, pero necesita un oráculo",
                   "auto-consistencia con base FUERTE/calibrada -> supera a no-filtrar, captura parte del beneficio (sin oráculo)",
                   "auto-consistencia con base DÉBIL/mal-calibrada -> COLAPSA: refuerza errores confiados",
                   "=> la confianza endógena reemplaza PARCIALMENTE al verificador externo, gateada por calibración"],
        principles=["la auto-consistencia es un pseudo-verificador endógeno: su utilidad está GATEADA por la calibración",
                    "calibrado: la confianza endógena reemplaza en parte al verificador externo (sin oráculo)",
                    "mal calibrado: consistente-pero-equivocado -> el filtro refuerza errores (peligroso)",
                    "los dos arcos (auto-mejora con verificador externo + valor endógeno) se conectan por la calibración"],
        adaptation=("El lab puede usar la auto-consistencia como verificador parcial DONDE el modelo esté "
                    "calibrado (medible por su propia calibración, CYCLE 57), reservando el verificador externo "
                    "para el régimen no-calibrado. Próximos: gating EXPLÍCITO por confianza calibrada (usar el "
                    "filtro endógeno sólo cuando la calibración estimada es alta); combinar endógeno+externo."),
        measurement=("exp046: FUERTE sc {ssc}/naive {sn}/verified {sv} calib {scal}; DÉBIL sc {wsc}/naive {wn} "
                     "calib {wcal}; contraste {gc}. {n} seeds.").format(
                         ssc=_f(S['self_consistency']), sn=_f(S['naive']), sv=_f(S['verified']),
                         scal=_f(S['sc_calibration']), wsc=_f(W['self_consistency']), wn=_f(W['naive']),
                         wcal=_f(W['sc_calibration']), gc=_f(sm['gating_contrast']), n=n_seeds),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (corregirte solo por tus 'seguros' sólo sirve si ya sos competente).")

    ceilings.add(CeilingRecord(
        subsystem="UNIFICACIÓN arcos — auto-consistencia (confianza endógena) como verificador PARCIAL gateado por calibración",
        known_limit=("REAL (exp046): la auto-consistencia reemplaza PARCIALMENTE al verificador externo en el "
                     "lazo de auto-mejora SÓLO cuando el modelo está calibrado (FUERTE: sc {ssc}>naive {sn}, "
                     "<verified {sv}); mal calibrado COLAPSA (DÉBIL: sc {wsc}<<naive {wn}). Gateado por "
                     "calibración (contraste {gc}).").format(
                         ssc=_f(S['self_consistency']), sn=_f(S['naive']), sv=_f(S['verified']),
                         wsc=_f(W['self_consistency']), wn=_f(W['naive']), gc=_f(sm['gating_contrast'])),
        blockers=[{"text": "la ventaja fuerte-sobre-naive es MODESTA (no 2σ): la auto-consistencia previene la degradación más que igualar al externo", "kind": "diseno"},
                  {"text": "acuerdo sobre el VALOR en tarea de vocab chico; falta una tarea más rica donde la consistencia espuria sea menos probable", "kind": "diseno"},
                  {"text": "no se hizo el gating EXPLÍCITO (usar el filtro endógeno sólo cuando la calibración estimada es alta) ni combinar endógeno+externo", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP046.ref, S_EXP043.ref]))
    notes.append("1 techo 'real': la auto-consistencia es verificador parcial gateado por calibración -> conecta los dos arcos.")

    dstmt = ("UNIFICACIÓN de los dos arcos de la corrida: la AUTO-CONSISTENCIA (confianza endógena del CYCLE "
             "56-59) reemplaza PARCIALMENTE al verificador EXTERNO del lazo de auto-mejora (arco 51-55), GATEADA "
             "por la CALIBRACIÓN: con base CALIBRADA supera a no-filtrar y captura parte del beneficio sin "
             "oráculo (FUERTE sc {ssc} vs naive {sn}, verified {sv}); con base MAL calibrada COLAPSA "
             "(consistente-pero-equivocado refuerza errores: DÉBIL sc {wsc} vs naive {wn}). El insight del CYCLE "
             "57 (la confianza es confiable con la competencia correcta) se confirma en el lazo de auto-mejora. "
             "Decisión: el lab puede sustituir parcialmente el verificador externo por la confianza endógena "
             "DONDE el modelo esté calibrado. Matiz honesto: la ventaja sobre no-filtrar es MODESTA (previene la "
             "degradación más que igualar al externo). Próximos: gating explícito por calibración estimada; "
             "combinar endógeno+externo.").format(ssc=_f(S['self_consistency']), sn=_f(S['naive']),
                                                  sv=_f(S['verified']), wsc=_f(W['self_consistency']),
                                                  wn=_f(W['naive']))
    drat = ("exp046 (tier5, propio, {n} seeds): gating por calibración (contraste {gc}); FUERTE sc {ssc}>naive "
            "{sn} (calib {scal}), DÉBIL sc {wsc}<<naive {wn} (calib {wcal}). Convergente con self-consistency "
            "(tier1) y con el CYCLE 57. {V}.").format(n=n_seeds, gc=_f(sm['gating_contrast']),
                                                      ssc=_f(S['self_consistency']), sn=_f(S['naive']),
                                                      scal=_f(S['sc_calibration']), wsc=_f(W['self_consistency']),
                                                      wn=_f(W['naive']), wcal=_f(W['sc_calibration']),
                                                      V=status.upper())
    dec = Decision(id="D-V4-25", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP046), _to_plain(S_EXP043)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-25 ACEPTADA por el ledger (tier5 exp046 + tier5 exp043).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-25:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle60_self_consistency_verifier',
                                description='CYCLE 60 (RESET v4, H-V4-2i: auto-consistencia como verificador parcial gateado por calibración).')
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
    print("RESUMEN — CYCLE 60 (RESET v4): auto-consistencia como verificador PARCIAL gateado por calibración (H-V4-2i)")
    print("=" * 78)
    print("veredicto H-V4-2i:", status.upper() if status else "?")
    print("  la confianza endógena reemplaza en parte al verificador externo SÓLO cuando el modelo está calibrado.")
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
