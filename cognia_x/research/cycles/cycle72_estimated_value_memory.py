r"""
cycle72_estimated_value_memory.py — CICLO 72 (RESET v4): H-V4-5b por las compuertas del engine. ABRE el arco
"R-VALOR bajo realismo": la ventaja de la memoria dirigida por valor SOBREVIVE con valor ESTIMADO ONLINE (sin
oráculo) y supera a una heurística value-free (recencia/LRU).

H-V4-5b ataca el caveat #1 del techo de CYCLE 70 (exp055/H-V4-5): allí el valor de consulta se daba PERFECTO y la
selección era ESTÁTICA. Aquí el agente NO conoce el valor: lo estima de su propia experiencia (frecuencia
observada = LFU) en una memoria ONLINE, y aun así recupera ~99% de la ventaja del oráculo y vence a LRU.
DERIVA de exp056_estimated_value_memory/results/results.json.

Correr (DESPUÉS de exp056):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp056_estimated_value_memory.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle72_estimated_value_memory
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle72_estimated_value_memory')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp056_estimated_value_memory', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_LFU = Source(tier=1, ref="LFU optimality under stationary popularity / rate-distortion (online caching)", obtained=False,
               claim=("Bajo popularidad ESTACIONARIA, retener los items de mayor frecuencia observada (LFU) "
                      "converge a la política óptima de capacidad finita; la frecuencia empírica es un estimador "
                      "consistente del valor de consulta. (Principio; converge con rate-distortion dirigido por valor.)"))
S_TREE = Source(tier=5, ref="cognia_x/manager/decomposition_tree.md (techo CYCLE 70: falta valor ESTIMADO + memoria online)", obtained=True,
                claim=("El techo 'real' de CYCLE 70 (H-V4-5) registró como blocker: 'el valor se da PERFECTO; "
                       "falta valor ESTIMADO ruidoso' y 'falta memoria dinámica con escritura/olvido online'. "
                       "H-V4-5b ataca ese blocker -> abre el arco R-VALOR bajo realismo."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp056 primero): " + results_path)
    ba = sm['by_arm']
    oracle, est, rec, rnd, anti = (ba['oracle'], ba['estimated'], ba['recency'], ba['random'], ba['anti_value'])
    frac = sm['fraction_recovered']
    n, m, T = data['args']['n'], data['args']['m'], data['args']['T']
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim056 = ("exp056 (propio, {n} seeds, numpy, stream T={T}): memoria online {m}/{N}. hit-rate ventana final: "
                "oracle {o}, estimated(LFU) {e} (recupera {p}% de la ventaja del oráculo), recency(LRU) {r}, "
                "random {rn}, anti_value {a}. El valor ESTIMADO de la frecuencia recupera ~la ventaja del oráculo "
                "sin saber el valor verdadero.").format(
                    n=n_seeds, T=T, m=m, N=n, o=_f(oracle), e=_f(est), p=int(round(frac * 100)), r=_f(rec),
                    rn=_f(rnd), a=_f(anti))
    S_EXP056 = Source(tier=5, ref="cognia_x/experiments/exp056_estimated_value_memory", obtained=True, claim=claim056)
    for src in (S_LFU, S_TREE, S_EXP056):
        ledger.add_source(src)
    notes.append("3 fuentes (S_LFU tier1 LFU/rate-distortion; S_TREE tier5 techo CYCLE 70; S_EXP056 tier5 dato propio).")

    ev_for = [S_EXP056.ref, S_TREE.ref]
    ev_against = [S_EXP056.ref]
    adv = ("{V} (abre el arco R-VALOR bajo realismo; ataca el caveat #1 de CYCLE 70): H-V4-5 cerró 'la ventaja de "
           "la memoria ES el valor' PERO con valor PERFECTO y selección estática. exp056 quita esa muleta: el "
           "agente NO conoce el valor y lo ESTIMA online de la frecuencia observada (LFU = valor endógeno). "
           "Resultado: estimated {e} recupera {p}% de la ventaja del oráculo ({o}) sobre random ({rn}); +{adv} "
           "sobre aleatoria; y le gana a recency ({r}, LRU value-free) por +{vr}: estimar el VALOR por frecuencia "
           "vence a una memoria sin valor (aísla que es el VALOR, no la mera 'memoria reciente'). anti_value {a} < "
           "random: la DIRECCIÓN del valor estimado importa. La curva cumulativa muestra al estimador CONVERGER al "
           "oráculo. EVIDENCIA EN CONTRA (caveats honestos): (1) régimen ESTACIONARIO -- bajo popularidad fija, "
           "LFU≈óptimo es un resultado clásico; la frontera es la NO-estacionariedad, donde la frecuencia de TODA "
           "la historia es un valor SESGADO y hace falta olvido dirigido por sorpresa (eso YA lo estudió el lab en "
           "CYCLE 58-66: el TIPO de olvido se elige del régimen). (2) sigue siendo juguete (Pareto, n=50). (3) el "
           "valor estimado aquí es FRECUENCIA pura; CYCLE 56-57 mostraron valores endógenos más ricos "
           "(info-gain/confianza). CONCLUSIÓN: la tesis R-VALOR×memoria NO depende del oráculo de valor -- un "
           "estimador endógeno barato (frecuencia) recupera la ventaja en estacionario; queda como hija atar el "
           "estimador a la no-estacionariedad (combinar con el olvido de CYCLE 59/66).").format(
               V=status.upper(), e=_f(est), p=int(round(frac * 100)), o=_f(oracle), rn=_f(rnd), adv=_f(est - rnd),
               r=_f(rec), vr=_f(est - rec), a=_f(anti))

    hyp = Hypothesis(
        id="H-V4-5b",
        statement=("La ventaja de la memoria dirigida por valor SOBREVIVE con valor ESTIMADO online (frecuencia "
                   "observada = valor endógeno, sin oráculo) y supera a una heurística value-free (recencia/LRU)."),
        prediction=("APOYADA si estimated recupera >=70% de la ventaja del oráculo Y estimated >> random (+>0.15) "
                    "Y estimated > recency (+>0.03); REFUTADA si estimated no supera a random o estimated<=recency; "
                    "MIXTA si ayuda pero recupera poco o no le gana limpio a recency. (Pre-registrada.)"),
        status='abierta', confidence='alta' if status == 'apoyada' else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=adv, experiment_ref="exp056_estimated_value_memory")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-5b")
        notes.append("H-V4-5b marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("Tu mochila (memoria) entra sólo m de n cosas y NO te dicen qué vale cada una. ¿Podés elegir bien "
                 "igual, sólo mirando qué te piden seguido? ¿O necesitás que alguien te diga el valor?"),
        everyday=("Sí: si guardás lo que más te PIDEN (lo que ves pasar seguido = frecuencia), terminás llenando la "
                  "mochila casi igual que si supieras el valor exacto -- recuperás ~99% de la ventaja sin oráculo. "
                  "Guardar 'lo último que te pidieron' (recencia) es peor: un pedido raro te hace tirar algo "
                  "popular. Y guardar lo que MENOS te piden es lo peor de todo. Aprender el valor de la propia "
                  "experiencia alcanza... mientras lo que se pide no CAMBIE (si cambia, hay que olvidar)."),
        solutions=["estimated/LFU (guardar lo más frecuente observado) -> recupera ~99% del oráculo SIN saber el valor",
                   "oracle (top-m por valor verdadero) -> cota superior (te dan el valor)",
                   "recency/LRU (lo más reciente) -> value-free: peor que estimar el valor por frecuencia",
                   "anti_value (lo menos frecuente) -> peor que random (la dirección del valor estimado importa)"],
        principles=["el valor de consulta es ESTIMABLE online de la propia experiencia (frecuencia) sin oráculo",
                    "un estimador endógeno barato recupera ~la ventaja del valor perfecto en régimen estacionario",
                    "estimar el VALOR (frecuencia) vence a una memoria value-free (recencia): la ventaja es el valor, no la memoria",
                    "el estimador de frecuencia hereda el límite de la no-estacionariedad: ahí hace falta olvido (CYCLE 58-66)"],
        adaptation=("El lab puede dirigir la memoria por un valor ENDÓGENO estimado (frecuencia/uso) en vez de un "
                    "oráculo. Próxima hija: atar el estimador a la NO-estacionariedad combinándolo con el olvido "
                    "dirigido por sorpresa (CYCLE 59) y el selector de estrategia (CYCLE 66) -- frecuencia con "
                    "ventana/decay adaptativo; y subir de frecuencia pura a info-gain/confianza (CYCLE 56-57)."),
        measurement=("exp056 (m={m}/{N}, T={T}): estimated {e} (recupera {p}%) vs oracle {o}; vs recency {r} "
                     "(+{vr}); vs random {rn} (+{adv}); anti {a}. {n} seeds.").format(
                         m=m, N=n, T=T, e=_f(est), p=int(round(frac * 100)), o=_f(oracle), r=_f(rec),
                         vr=_f(est - rec), rn=_f(rnd), adv=_f(est - rnd), a=_f(anti), n=n_seeds),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (estimar el valor por frecuencia ≈ saber el valor; recencia es peor).")

    kl = ("REAL (exp056): la ventaja de una memoria finita ({m}/{N}) por valor SOBREVIVE al estimar el valor online "
          "de la frecuencia (LFU): estimated {e} recupera {p}% de la ventaja del oráculo ({o}) sobre random ({rn}) "
          "y vence a recency value-free ({r}). El valor de consulta es estimable endógenamente -> R-VALOR×memoria "
          "no necesita oráculo de valor en régimen estacionario.").format(
              m=m, N=n, e=_f(est), p=int(round(frac * 100)), o=_f(oracle), rn=_f(rnd), r=_f(rec))
    ceilings.add(CeilingRecord(
        subsystem="R-VALOR x MEMORIA bajo realismo — valor ESTIMADO online (frecuencia) recupera la ventaja del oráculo",
        known_limit=kl,
        blockers=[{"text": "régimen ESTACIONARIO: bajo popularidad fija LFU≈óptimo es clásico; la frontera es la NO-estacionariedad (frecuencia de toda la historia = valor sesgado -> hace falta olvido, CYCLE 58-66)", "kind": "diseno"},
                  {"text": "el estimador es FRECUENCIA pura; falta subir a valores endógenos más ricos (info-gain/confianza, CYCLE 56-57)", "kind": "diseno"},
                  {"text": "tarea de juguete (Pareto, n=50, consultas IID); falta un downstream con consultas correlacionadas/estructura", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP056.ref, S_TREE.ref]))
    notes.append("1 techo 'real': el valor de consulta es estimable online (frecuencia) y recupera la ventaja del oráculo en estacionario.")

    dstmt = ("North-Star R-VALOR bajo realismo (abre el arco; ataca el caveat #1 de CYCLE 70): la ventaja de una "
             "memoria de capacidad finita por valor NO depende de un oráculo -- estimated(LFU) recupera {p}% de la "
             "ventaja del oráculo ({o}) sobre random ({rn}) estimando el valor online de la frecuencia observada, y "
             "vence a recency value-free ({r}) por +{vr}. anti_value {a} < random (la dirección importa). Decisión: "
             "el lab dirige la memoria por un valor ENDÓGENO ESTIMADO (frecuencia/uso) y NO por un oráculo de valor. "
             "Próxima hija: atar el estimador a la no-estacionariedad (combinar con el olvido dirigido por sorpresa "
             "de CYCLE 59 y el selector de estrategia de CYCLE 66).").format(
                 p=int(round(frac * 100)), o=_f(oracle), rn=_f(rnd), r=_f(rec), vr=_f(est - rec), a=_f(anti))
    drat = ("exp056 (tier5, propio, {n} seeds, T={T}): estimated {e} recupera {p}% del oráculo {o}; +{adv} sobre "
            "random {rn}; +{vr} sobre recency {r}; anti {a} < random. Convergente con LFU/rate-distortion (tier1) y "
            "con el techo de CYCLE 70 (tier5). {V}.").format(
                n=n_seeds, T=T, e=_f(est), p=int(round(frac * 100)), o=_f(oracle), adv=_f(est - rnd), rn=_f(rnd),
                vr=_f(est - rec), r=_f(rec), a=_f(anti), V=status.upper())
    dec = Decision(id="D-V4-34", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP056), _to_plain(S_TREE)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-34 ACEPTADA por el ledger (tier5 exp056 + tier5 techo CYCLE 70).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-34:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle72_estimated_value_memory',
                                description='CYCLE 72 (RESET v4, H-V4-5b: memoria por valor ESTIMADO online).')
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
    print("RESUMEN — CYCLE 72 (RESET v4): memoria por valor ESTIMADO online (H-V4-5b) — abre R-VALOR bajo realismo")
    print("=" * 78)
    print("veredicto H-V4-5b:", status.upper() if status else "?")
    print("  la ventaja de la memoria por valor SOBREVIVE al estimar el valor online (frecuencia), sin oráculo.")
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
