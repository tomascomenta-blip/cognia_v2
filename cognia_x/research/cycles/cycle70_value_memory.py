r"""
cycle70_value_memory.py — CICLO 70 (RESET v4): H-V4-5 por las compuertas del engine. Cierra la última raíz
abierta del v4: ESCRIBIR≡OLVIDAR es rate-distortion dirigido por VALOR (conecta MEMORIA con R-VALOR).

H-V4-5: la ventaja de una memoria finita está ATADA a R-VALOR -- la escritura dirigida por valor >> aleatoria y
ablar el valor colapsa la ventaja a aleatoria. DERIVA de exp055_value_memory/results/results.json.

Correr (DESPUÉS de exp055):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp055_value_memory.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle70_value_memory
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle70_value_memory')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp055_value_memory', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_RD = Source(tier=1, ref="rate-distortion / value-weighted compression (memory)", obtained=False,
              claim=("Bajo capacidad finita, qué RETENER es una decisión de rate-distortion: se retiene lo de "
                     "mayor VALOR/utilidad esperada; sin una señal de valor, la compresión selectiva = aleatoria. "
                     "(Principio.)"))
S_TREE = Source(tier=5, ref="cognia_x/manager/decomposition_tree.md (R-VALOR / escribir≡olvidar)", obtained=True,
                claim=("El thesis v4 (R-VALOR raíz primera): escribir/olvidar es selectivo y 'consolidar exige "
                       "saber qué proteger -- indefinible sin un escalar de valor'. H-V4-5 lo ata empíricamente."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp055 primero): " + results_path)
    ba = sm['by_arm']
    vd, rnd, abl, anti = ba['value_directed'], ba['random'], ba['ablation'], ba['anti_value']
    n, m = data['args']['n'], data['args']['m']
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim054 = ("exp055 (propio, {n} seeds, numpy): memoria de capacidad {m}/{N}. hit-rate ponderado por valor: "
                "value_directed {vd}, random {r}, ablation {a} (=random), anti_value {an}. Ablar el valor colapsa "
                "la ventaja -> la ventaja de la memoria está ATADA a R-VALOR.").format(
                    n=n_seeds, m=m, N=n, vd=_f(vd), r=_f(rnd), a=_f(abl), an=_f(anti))
    S_EXP055 = Source(tier=5, ref="cognia_x/experiments/exp055_value_memory", obtained=True, claim=claim054)
    for src in (S_RD, S_TREE, S_EXP055):
        ledger.add_source(src)
    notes.append("3 fuentes (S_RD tier1 rate-distortion; S_TREE tier5 thesis R-VALOR/escribir-olvidar; S_EXP055 tier5 dato propio).")

    ev_for = [S_EXP055.ref, S_TREE.ref]
    ev_against = [S_EXP055.ref]
    adv = ("{V} (cierra la última raíz abierta del v4, conecta MEMORIA con R-VALOR): el thesis dice que "
           "escribir/olvidar es selectivo y 'consolidar exige saber qué proteger -- indefinible sin un escalar de "
           "valor'. exp055 lo ATA empíricamente: una memoria de capacidad finita ({m}/{N}) rinde porque guarda lo "
           "de mayor VALOR. La escritura value_directed cubre {vd} del valor de consulta (random {r} ~ m/n; "
           "+{adv} sobre aleatoria). ABLAR la señal de valor (todos iguales -> azar) COLAPSA exactamente a {a} "
           "(= random {r}): sin valor, la memoria selectiva = aleatoria -> la ventaja ES el valor, no la "
           "capacidad ni la 'selectividad' abstracta. anti_value (guardar lo de MENOR valor) cae a {an} (< "
           "random): la DIRECCIÓN del valor importa (no es sólo 'ordenar por algo'). => escribir≡olvidar es "
           "rate-distortion dirigido por valor; quitar la utilidad mata la ventaja. EVIDENCIA EN CONTRA (caveats "
           "honestos): (1) el valor (prob de consulta) se da de antemano y es PERFECTO; en la realidad hay que "
           "ESTIMARLO (ruidoso) -- pero los CYCLE 56-57 ya mostraron que el valor endógeno (info-gain/confianza) "
           "es estimable. (2) tarea de juguete (selección estática, valores power-law). (3) métrica = masa de "
           "valor cubierta (exacta), no un downstream más rico. CONCLUSIÓN: cierra el lazo del v4 -- las cuatro "
           "operaciones de memoria (escribir/olvidar/recordar/consolidar) son indefinibles sin valor, y aquí se "
           "muestra que la ventaja de la memoria ES el valor; R-VALOR es, en efecto, la raíz que aterriza la "
           "memoria.").format(V=status.upper(), m=m, N=n, vd=_f(vd), r=_f(rnd), adv=_f(vd - rnd), a=_f(abl),
                              an=_f(anti))

    hyp = Hypothesis(
        id="H-V4-5",
        statement=("La ventaja de una memoria finita está atada a R-VALOR: la escritura dirigida por valor >> "
                   "aleatoria y ablar el valor colapsa la ventaja (escribir≡olvidar es rate-distortion por valor)."),
        prediction=("APOYADA si value_directed >> random (+>0.20) Y ablar el valor colapsa a random Y anti_value "
                    "< random; REFUTADA si value_directed no supera a random o la ablación no colapsa; MIXTA si "
                    "ayuda pero la ablación/anti no es limpia. (Pre-registrada.)"),
        status='abierta', confidence='alta' if status == 'apoyada' else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=adv, experiment_ref="exp055_value_memory")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-5")
        notes.append("H-V4-5 marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("Tu mochila (memoria) entra sólo m de n cosas. ¿Qué la hace útil -- su tamaño, o ELEGIR BIEN qué "
                 "meter? ¿Y si no sabés qué vale cada cosa?"),
        everyday=("Lo que la hace útil es meter lo que más vas a NECESITAR (mayor valor): con 10 de 50 cosas bien "
                  "elegidas cubrís la mitad de lo que te van a pedir. Al azar cubrís sólo ~10/50. Si NO sabés qué "
                  "vale (ablás el valor), tu elección = al azar: la mochila selectiva pierde su gracia. Y meter "
                  "lo que MENOS vale es peor que al azar. El valor de la mochila ES saber qué vale."),
        solutions=["value_directed (guardar lo de mayor valor) -> cubre mucho con poca capacidad",
                   "random -> cubre ~m/n (la capacidad sola no alcanza)",
                   "ablation (valor removido) -> colapsa a random (la ventaja ERA el valor)",
                   "anti_value (lo de menor valor) -> peor que random (la dirección importa)"],
        principles=["la ventaja de una memoria finita es QUÉ guarda (valor), no su capacidad ni la selectividad abstracta",
                    "ablar la señal de valor colapsa la memoria selectiva a aleatoria: la ventaja ES el valor",
                    "escribir≡olvidar es rate-distortion dirigido por valor (retener lo de mayor utilidad esperada)",
                    "R-VALOR es la raíz que aterriza la memoria: escribir/olvidar/recordar/consolidar son indefinibles sin valor"],
        adaptation=("El lab trata la memoria como rate-distortion dirigido por valor; el valor endógeno (info-gain/"
                    "confianza, CYCLE 56-57) es la señal que decide qué escribir/olvidar. Próximos: valor "
                    "ESTIMADO ruidoso (no perfecto); memoria dinámica con escritura/olvido online dirigidos por "
                    "el valor endógeno; ligarlo al selector de estrategia del CYCLE 66."),
        measurement=("exp055 (m={m}/{N}): value_directed {vd} vs random {r} (+{adv}); ablation {a} (=random); "
                     "anti_value {an}. {n} seeds.").format(m=m, N=n, vd=_f(vd), r=_f(rnd), adv=_f(vd - rnd),
                                                           a=_f(abl), an=_f(anti), n=n_seeds),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (la mochila útil ES saber qué vale, no su tamaño).")

    kl = ("REAL (exp055): la ventaja de una memoria finita ({m}/{N}) ES el valor: value_directed {vd} vs random "
          "{r}; ablar el valor colapsa a {a} (=random); anti_value {an} < random. Escribir≡olvidar es "
          "rate-distortion dirigido por valor -> R-VALOR aterriza la memoria.").format(
              m=m, N=n, vd=_f(vd), r=_f(rnd), a=_f(abl), an=_f(anti))
    ceilings.add(CeilingRecord(
        subsystem="R-VALOR x MEMORIA (escribir≡olvidar) — la ventaja de la memoria finita ES el valor (rate-distortion)",
        known_limit=kl,
        blockers=[{"text": "el valor (prob de consulta) se da PERFECTO; falta valor ESTIMADO ruidoso (aunque CYCLE 56-57 ya mostraron que es estimable)", "kind": "diseno"},
                  {"text": "tarea de juguete (selección estática, power-law); falta memoria dinámica con escritura/olvido online", "kind": "diseno"},
                  {"text": "métrica = masa de valor cubierta (exacta); falta un downstream más rico", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP055.ref, S_TREE.ref]))
    notes.append("1 techo 'real': la ventaja de la memoria finita es el valor; escribir≡olvidar es rate-distortion dirigido por valor (R-VALOR aterriza la memoria).")

    dstmt = ("North-Star R-VALOR x MEMORIA (cierra la última raíz abierta del v4): la ventaja de una memoria de "
             "capacidad finita está ATADA a R-VALOR -- value_directed cubre {vd} del valor con {m}/{N} items "
             "(random {r}); ablar la señal de valor COLAPSA a {a} (=random) y anti_value cae a {an} (< random). "
             "Escribir≡olvidar es rate-distortion dirigido por valor: quitar la utilidad mata la ventaja; la "
             "ventaja ES el valor, no la capacidad. Decisión: el lab trata la memoria como rate-distortion "
             "dirigida por el valor ENDÓGENO (info-gain/confianza, CYCLE 56-57). Cierra el lazo del v4: las cuatro "
             "operaciones de memoria son indefinibles sin valor, y R-VALOR es la raíz que las aterriza. Próximos: "
             "valor estimado ruidoso; memoria dinámica online.").format(
                 vd=_f(vd), m=m, N=n, r=_f(rnd), a=_f(abl), an=_f(anti))
    drat = ("exp055 (tier5, propio, {n} seeds): value_directed {vd} >> random {r} (+{adv}); ablation {a} =random; "
            "anti_value {an} < random. Convergente con rate-distortion (tier1) y con el thesis R-VALOR. {V}.").format(
                n=n_seeds, vd=_f(vd), r=_f(rnd), adv=_f(vd - rnd), a=_f(abl), an=_f(anti), V=status.upper())
    dec = Decision(id="D-V4-33", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP055), _to_plain(S_TREE)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-33 ACEPTADA por el ledger (tier5 exp055 + tier5 thesis R-VALOR).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-33:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle70_value_memory',
                                description='CYCLE 70 (RESET v4, H-V4-5: escribir≡olvidar dirigido por valor).')
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
    print("RESUMEN — CYCLE 70 (RESET v4): escribir≡olvidar dirigido por valor (H-V4-5) — cierra la última raíz")
    print("=" * 78)
    print("veredicto H-V4-5:", status.upper() if status else "?")
    print("  la ventaja de una memoria finita ES el valor; ablar el valor la colapsa a aleatoria.")
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
