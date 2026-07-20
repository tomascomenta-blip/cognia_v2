r"""
cycle73_nonstationary_value_memory.py — CICLO 73 (RESET v4, arco "R-VALOR bajo realismo"): H-V4-5c por las
compuertas del engine. El estimador de valor (frecuencia) debe OLVIDAR para rastrear valor NO-estacionario: ata
R-VALOR (el estimador endógeno del CYCLE 72) con el arco de OLVIDO (CYCLE 58-66).

H-V4-5c ataca el caveat de CYCLE 72 (exp056/H-V4-5b APOYADA sólo en ESTACIONARIO). Bajo cambio de popularidad,
la frecuencia-de-toda-la-historia (lfu_full, ganadora del 72) DEGRADA cayendo hacia random; una frecuencia con
DECAY (valor estimado + olvido) recupera la ventaja del oráculo y vence a una memoria value-free (LRU).
DERIVA de exp057_nonstationary_value_memory/results/results.json.

Correr (DESPUÉS de exp057):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp057_nonstationary_value_memory.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle73_nonstationary_value_memory
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle73_nonstationary_value_memory')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp057_nonstationary_value_memory', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_FORGET = Source(tier=1, ref="non-stationary tracking / exponential-decay (sliding-window) frequency estimation", obtained=False,
                  claim=("Para estimar una estadística que CAMBIA en el tiempo, el estimador debe DESCONTAR el "
                         "pasado (decay/ventana): el promedio de toda la historia es sesgado bajo no-estacionariedad. "
                         "Hay un tradeoff estabilidad-plasticidad: descontar acelera el seguimiento pero sube la "
                         "varianza. (Principio; converge con stability-plasticity y constant-step-size tracking.)"))
S_TREE = Source(tier=5, ref="cognia_x/manager/decomposition_tree.md (caveat CYCLE 72 + arco olvido CYCLE 58-66)", obtained=True,
                claim=("El techo de CYCLE 72 (H-V4-5b) registró: 'régimen ESTACIONARIO; la frontera es la "
                       "NO-estacionariedad, donde la frecuencia de toda la historia es valor SESGADO -> hace falta "
                       "olvido (CYCLE 58-66)'. H-V4-5c lo ataca: el estimador de valor con decay rastrea el cambio."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp057 primero): " + results_path)
    st, ns = sm['stationary'], sm['nonstationary']
    o_n, full_n, dec_n, rec_n, rnd_n = (ns['oracle_current'], ns['lfu_full'], ns['lfu_decay'], ns['recency'], ns['random'])
    full_s, dec_s = st['lfu_full'], st['lfu_decay']
    frac = sm['fraction_recovered_ns']
    n, m = data['args']['n'], data['args']['m']
    decay = data['args']['decay']
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim057 = ("exp057 (propio, {n} seeds, numpy, decay={d}): memoria online no-estacionaria (popularidad re-permuta "
                "cada fase). NO-ESTAC hit-rate: oracle {on}, lfu_full {fn} (degrada de {fs} en estac.), lfu_decay {dn} "
                "(recupera {p}% del oráculo), recency {rc}, random {rn}. ESTAC: full {fs} >= decay {ds} (olvidar "
                "cuesta sin cambio). El estimador de valor con DECAY rastrea valor no-estacionario; full se confunde.").format(
                    n=n_seeds, d=decay, on=_f(o_n), fn=_f(full_n), fs=_f(full_s), dn=_f(dec_n), p=int(round(frac * 100)),
                    rc=_f(rec_n), rn=_f(rnd_n), ds=_f(dec_s))
    S_EXP057 = Source(tier=5, ref="cognia_x/experiments/exp057_nonstationary_value_memory", obtained=True, claim=claim057)
    for src in (S_FORGET, S_TREE, S_EXP057):
        ledger.add_source(src)
    notes.append("3 fuentes (S_FORGET tier1 decay/tracking; S_TREE tier5 caveat CYCLE 72 + arco olvido; S_EXP057 tier5 dato propio).")

    ev_for = [S_EXP057.ref, S_TREE.ref]
    ev_against = [S_EXP057.ref]
    adv = ("{V} (hija del CYCLE 72; ata R-VALOR-estimador con el arco de OLVIDO): el CYCLE 72 cerró que el valor es "
           "estimable de la frecuencia, pero sólo en ESTACIONARIO. exp057 quita esa muleta haciendo CAMBIAR la "
           "popularidad (re-permuta item->valor cada fase, régimen recurrente cf. CYCLE 63). Resultado: lfu_full (no "
           "olvida) DEGRADA de {fs} (estac.) a {fn}, cayendo hacia random ({rn}) porque promedia épocas viejas con la "
           "actual; lfu_decay (frecuencia que OLVIDA, ventana ~{win:.0f}) recupera {p}% de la ventaja del oráculo "
           "({on}) -> {dn}, +{df} sobre full y +{dr} sobre recency value-free ({rc}). En ESTACIONARIO el control es "
           "clave: full {fs} >= decay {ds} -> olvidar tiene un COSTO cuando NO hay cambio (tradeoff estabilidad-"
           "plasticidad real, NO dominación de decay). CROSSOVER limpio: full gana sin cambio, decay gana con cambio. "
           "EVIDENCIA EN CONTRA (caveats honestos): (1) el decay es FIJO (0.97); el óptimo depende de la tasa de "
           "cambio -- un decay adaptativo/meta lo elegiría (CYCLE 64/66 ya lo hicieron para el olvido de memoria; "
           "queda como hija). (2) bajo no-estacionariedad FUERTE la recency value-free (LRU) queda competitiva "
           "(decay sólo +{dr}) -- el valor estimado tiene poco tiempo para acumularse; honesto, no se infló. (3) "
           "cambio ABRUPTO recurrente (no deriva gradual); juguete (Pareto, n=50). CONCLUSIÓN: el estimador de valor "
           "endógeno (frecuencia) DEBE olvidar para servir bajo no-estacionariedad -> R-VALOR (qué vale) y OLVIDO "
           "(cuándo dejó de valer) son la MISMA señal vista en dos tiempos; unifica CYCLE 72 con el arco 58-66.").format(
               V=status.upper(), fs=_f(full_s), fn=_f(full_n), rn=_f(rnd_n), win=1.0 / (1.0 - decay),
               p=int(round(frac * 100)), on=_f(o_n), dn=_f(dec_n), df=_f(dec_n - full_n), dr=_f(dec_n - rec_n),
               rc=_f(rec_n), ds=_f(dec_s))

    hyp = Hypothesis(
        id="H-V4-5c",
        statement=("El estimador de valor por frecuencia DEBE olvidar (decay) para rastrear valor NO-estacionario: "
                   "lfu_full degrada bajo cambio de popularidad y lfu_decay recupera la ventaja (ata R-VALOR con olvido)."),
        prediction=("APOYADA si en no-estac. lfu_decay supera a lfu_full (+>0.05) Y recupera >=55% de la ventaja del "
                    "oráculo Y > recency (+>0.03), con el control de que en estac. lfu_full>=lfu_decay (olvidar "
                    "cuesta); REFUTADA si decay no supera a full o decay<=recency; MIXTA si ayuda parcial. (Pre-registrada.)"),
        status='abierta', confidence='alta' if status == 'apoyada' else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=adv, experiment_ref="exp057_nonstationary_value_memory")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-5c")
        notes.append("H-V4-5c marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("Aprendiste qué le gusta a tu cliente contando lo que pide. Pero sus gustos CAMBIAN con las "
                 "temporadas. ¿Te sirve el conteo de SIEMPRE, o tenés que olvidar lo viejo?"),
        everyday=("El conteo de SIEMPRE (toda la historia) te confunde: mezcla la temporada pasada con esta, y "
                  "terminás surtiendo lo que ya no piden -- tu acierto cae hacia el del que no sabe nada. Si "
                  "DESCONTÁS lo viejo (mirás sólo lo reciente) seguís sus gustos actuales y aciertas casi como si los "
                  "supieras. Pero ojo: si los gustos NO cambian, olvidar te hace tirar datos útiles y aciertas un "
                  "poco menos. Olvidar es necesario cuando el mundo cambia, y un costo cuando no."),
        solutions=["lfu_decay (frecuencia que olvida) -> rastrea la popularidad actual; gana cuando hay cambio",
                   "lfu_full (frecuencia de toda la historia) -> promedia épocas; gana sin cambio, se confunde con cambio",
                   "recency/LRU (value-free) -> olvida pero sin estimar valor; competitiva sólo si el cambio es fuerte",
                   "oracle_current (sabe el valor actual) -> cota superior en ambos regímenes"],
        principles=["el estimador de valor endógeno DEBE olvidar (decay) para rastrear valor no-estacionario",
                    "crossover: no-olvidar gana sin cambio; olvidar gana con cambio (tradeoff estabilidad-plasticidad)",
                    "R-VALOR (qué vale) y OLVIDO (cuándo dejó de valer) son la misma señal en dos tiempos -> unifica CYCLE 72 con 58-66",
                    "olvidar tiene un costo cuando no hay cambio: el decay no domina, hay que elegirlo del régimen (meta-olvido, CYCLE 64/66)"],
        adaptation=("El lab estima el valor para la memoria con frecuencia DESCONTADA (decay), no acumulada, cuando "
                    "el mundo puede cambiar. Próxima hija: decay ADAPTATIVO -- elegir la tasa de olvido de la propia "
                    "sorpresa/tasa de cambio (reusar el meta-olvido de CYCLE 64 y el selector de estrategia de CYCLE "
                    "66 sobre el estimador de valor), para no pagar el costo del olvido cuando no hay cambio."),
        measurement=("exp057 (decay={d}): NO-ESTAC decay {dn} (recupera {p}%) > full {fn} (+{df}) > recency {rc}; "
                     "ESTAC full {fs} >= decay {ds}. {n} seeds.").format(
                         d=decay, dn=_f(dec_n), p=int(round(frac * 100)), fn=_f(full_n), df=_f(dec_n - full_n),
                         rc=_f(rec_n), fs=_f(full_s), ds=_f(dec_s), n=n_seeds),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (el conteo de siempre confunde si los gustos cambian; hay que olvidar).")

    kl = ("REAL (exp057): bajo no-estacionariedad el estimador de valor por frecuencia DEBE olvidar -- lfu_decay {dn} "
          "recupera {p}% de la ventaja del oráculo ({on}) y vence a lfu_full {fn} (+{df}) y a recency value-free {rc}; "
          "en estacionario full {fs} >= decay {ds} (olvidar cuesta). R-VALOR (estimador) se ata al OLVIDO (CYCLE 58-66): "
          "qué vale y cuándo dejó de valer son la misma señal en dos tiempos.").format(
              dn=_f(dec_n), p=int(round(frac * 100)), on=_f(o_n), fn=_f(full_n), df=_f(dec_n - full_n),
              rc=_f(rec_n), fs=_f(full_s), ds=_f(dec_s))
    ceilings.add(CeilingRecord(
        subsystem="R-VALOR x OLVIDO — el estimador de valor (frecuencia) debe DESCONTAR para rastrear valor no-estacionario",
        known_limit=kl,
        blockers=[{"text": "el decay es FIJO (0.97); el óptimo depende de la tasa de cambio -> falta decay ADAPTATIVO/meta (reusar CYCLE 64/66 sobre el estimador de valor)", "kind": "diseno"},
                  {"text": "bajo cambio FUERTE la recency value-free (LRU) queda competitiva (decay +0.05): el valor estimado tiene poco tiempo de acumularse", "kind": "diseno"},
                  {"text": "cambio ABRUPTO recurrente (no deriva gradual); juguete (Pareto, n=50, consultas IID dentro de fase)", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP057.ref, S_TREE.ref]))
    notes.append("1 techo 'real': el estimador de valor debe olvidar (decay) para rastrear valor no-estacionario; crossover full/decay.")

    dstmt = ("North-Star R-VALOR bajo realismo (hija del CYCLE 72; ata el estimador de valor con el OLVIDO): bajo "
             "no-estacionariedad el valor endógeno por frecuencia DEBE descontar el pasado. lfu_decay recupera {p}% "
             "de la ventaja del oráculo ({on}) y vence a lfu_full {fn} (+{df}, que cae de {fs} hacia random {rn}) y a "
             "recency value-free {rc}; en estacionario full {fs} >= decay {ds} (olvidar cuesta -> tradeoff real). "
             "Decisión: el lab estima el valor para la memoria con frecuencia DESCONTADA (decay) cuando el mundo "
             "cambia. R-VALOR (qué vale) y OLVIDO (cuándo dejó de valer) son la misma señal en dos tiempos -> unifica "
             "CYCLE 72 con el arco 58-66. Próxima hija: decay ADAPTATIVO (meta-olvido del estimador).").format(
                 p=int(round(frac * 100)), on=_f(o_n), fn=_f(full_n), df=_f(dec_n - full_n), fs=_f(full_s),
                 rn=_f(rnd_n), rc=_f(rec_n), ds=_f(dec_s))
    drat = ("exp057 (tier5, propio, {n} seeds, decay={d}): NO-ESTAC decay {dn} recupera {p}% del oráculo {on}, +{df} "
            "sobre full {fn}, +{dr} sobre recency {rc}; ESTAC full {fs} >= decay {ds}. Convergente con decay/tracking "
            "(tier1) y con el caveat de CYCLE 72 (tier5). {V}.").format(
                n=n_seeds, d=decay, dn=_f(dec_n), p=int(round(frac * 100)), on=_f(o_n), df=_f(dec_n - full_n),
                fn=_f(full_n), dr=_f(dec_n - rec_n), rc=_f(rec_n), fs=_f(full_s), ds=_f(dec_s), V=status.upper())
    dec = Decision(id="D-V4-35", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP057), _to_plain(S_TREE)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-35 ACEPTADA por el ledger (tier5 exp057 + tier5 caveat CYCLE 72).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-35:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle73_nonstationary_value_memory',
                                description='CYCLE 73 (RESET v4, H-V4-5c: estimador de valor con olvido bajo no-estacionariedad).')
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
    print("RESUMEN — CYCLE 73 (RESET v4): estimador de valor con OLVIDO bajo no-estacionariedad (H-V4-5c)")
    print("=" * 78)
    print("veredicto H-V4-5c:", status.upper() if status else "?")
    print("  el estimador de valor por frecuencia DEBE olvidar (decay) para rastrear valor no-estacionario.")
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
