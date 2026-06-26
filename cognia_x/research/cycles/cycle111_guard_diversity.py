r"""
cycle111_guard_diversity.py — CICLO 111 (RESET v4, rama R-VALOR, intenta resolver el caveat de CYCLE 110): H-V4-8p por las
compuertas del engine. MIXTA (informativa): la GUARDIA de diversidad (CYCLE 94: dedup+replay) AYUDA a conf-alloc
(+guard_vs_plain: destraba su narrowing -- confirma que 94 transfiere a este lazo), PERO conf+guardia+alta-diversidad NO
alcanza a random_low (el ganador de 110). REFINAMIENTO: el FILTRO de confianza paga cuando el pool es RUIDOSO; cuando un
pool LIMPIO es barato (temp baja + base decente -> el generador emite mayormente correctos), RANDOM-from-clean es lo más
simple y MEJOR. El valor del filtro depende de la TASA BASE de calidad del pool.

DERIVA de exp095_guard_diversity/results/results.json.

Correr (DESPUÉS de exp095):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp095_guard_diversity.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle111_guard_diversity
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle111_guard_diversity')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp095_guard_diversity', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


S_PRINCIPLE = Source(tier=2, ref="el valor de un FILTRO de selección depende de la TASA BASE de calidad del pool: si los candidatos ya son mayormente buenos (pool limpio), el muestreo aleatorio basta; el filtro paga bajo pool RUIDOSO (tasa base baja). Sesgo de selección vs muestreo limpio", obtained=False,
                     claim=("El valor de un FILTRO de selección (elegir los mejores candidatos) depende de la TASA BASE de "
                            "calidad del pool. Si el pool ya es mayormente bueno (limpio), el muestreo ALEATORIO da una "
                            "muestra amplia y no-sesgada que basta o gana; el filtro paga cuando el pool es RUIDOSO (tasa "
                            "base baja). Un filtro siempre introduce SESGO de selección que cuesta diversidad. "
                            "(Principio.)"))
S_EXP094 = Source(tier=5, ref="cognia_x/experiments/exp094_gen_alloc_interaction", obtained=True,
                  claim=("CYCLE 110: interacción temp×alloc positiva (complementariedad), pero el mejor config absoluto fue "
                         "random_low (conf-alloc sola NARROWS, 93/94). H-V4-8p prueba si el filtro COMPLETO (conf + guardia "
                         "94) recupera el óptimo global."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp095 primero): " + results_path)

    gvp = sm['guard_vs_plain']
    gvr = sm['guard_vs_random']
    rl = _mean(sm['real_random_low']); ch = _mean(sm['real_conf_high']); cgh = _mean(sm['real_conf_guard_high'])
    csc = _mean(sm['conf_strong_corr_by_seed'])
    n_seeds = sm['n_seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim095 = ("exp095 ({n} seeds, PyTorch CPU, lazo cerrado real exp018): la guardia de diversidad (94) ayuda a conf "
                "(conf_guard_high={cgh} > conf_high={ch}, +{gvp}: destraba el narrowing) PERO no alcanza a random_low={rl} "
                "({gvr}). El filtro paga bajo pool ruidoso; con pool limpio barato, random-from-clean gana.").format(
                    n=n_seeds, cgh=_f(cgh), ch=_f(ch), gvp=_f(gvp), rl=_f(rl), gvr=_f(gvr))
    S_EXP095 = Source(tier=5, ref="cognia_x/experiments/exp095_guard_diversity", obtained=True, claim=claim095)
    for src in (S_PRINCIPLE, S_EXP094, S_EXP095):
        ledger.add_source(src)
    notes.append("3 fuentes (S_PRINCIPLE tier2 valor-del-filtro-depende-de-la-tasa-base; S_EXP094 tier5 caveat de 110; S_EXP095 tier5 dato propio).")

    ev_for = [S_EXP095.ref]
    ev_against = [S_EXP095.ref, S_EXP094.ref, S_PRINCIPLE.ref]
    advtext = ("{V} (intenta resolver el caveat de CYCLE 110 con la guardia de diversidad de 94): en 110 el mejor config "
               "absoluto fue random_low porque conf-alloc SOLA NARROWS (93/94). H-V4-8p prueba si el filtro COMPLETO "
               "(conf + GUARDIA: dedup de verificados + replay de verdad canónica, CYCLE 94) + alta diversidad del "
               "generador recupera el óptimo global venciendo a random_low. RESULTADO MIXTO: la GUARDIA AYUDA "
               "claramente -- conf_guard_high={cgh} > conf_high={ch} (+{gvp}: la guardia DESTRABA el narrowing de "
               "conf-alloc, confirmando que 94 transfiere a este lazo) -- PERO NO alcanza a random_low={rl} ({gvr}). => el "
               "filtro completo NO resuelve el caveat de 110 en este régimen: random_low (random-alloc sobre un pool de "
               "BAJA temperatura, mayormente CORRECTO) sigue siendo el mejor. REFINAMIENTO (la lección real): el valor del "
               "FILTRO de confianza depende de la TASA BASE de calidad del pool. Cuando el pool es RUIDOSO (alta temp, "
               "base débil) el filtro paga (separa lo bueno); pero cuando un pool LIMPIO es BARATO (baja temp + base "
               "decente -> el generador emite mayormente correctos), el muestreo ALEATORIO da una muestra amplia y "
               "no-sesgada que vence al filtro+guardia (que introduce sesgo de selección hacia lo confiado y pierde "
               "diversidad, y a alta temp paga el costo de filtrar la basura que ella misma generó). corr(conf,strong)="
               "{csc}. CONCILIACIÓN con 110: la INTERACCIÓN temp×alloc sigue siendo positiva (110), pero el ÓPTIMO GLOBAL "
               "en régimen de pool-limpio-barato es 'generá limpio (temp baja) y muestreá ancho (random)', no 'generá "
               "diverso (temp alta) y filtrá'. EVIDENCIA EN CONTRA / caveats: régimen tiny/sembrado donde la baja temp "
               "YA da un pool muy correcto (tasa base alta) -- a escala/tarea donde un pool limpio NO sea barato, el "
               "filtro debería ganar (no testeado); 2 niveles de temperatura; replay_frac fijo; {n} seeds, CPU.").format(
                   V=status.upper(), cgh=_f(cgh), ch=_f(ch), gvp=_f(gvp), rl=_f(rl), gvr=_f(gvr), csc=_f(csc), n=n_seeds)

    hyp = Hypothesis(
        id="H-V4-8p",
        statement=("El filtro COMPLETO (asignación por valor + guardia de diversidad 94) + alta diversidad del generador "
                   "es el óptimo global (vence a random_low de 110). [MIXTA: la guardia ayuda -destraba el narrowing- pero "
                   "no alcanza a random_low; el filtro paga bajo pool ruidoso, no cuando un pool limpio es barato.]"),
        prediction=("APOYADA si conf_guard_high > conf_high (+>0.03) Y >= random_low − 0.03; REFUTADA si la guardia no "
                    "ayuda; MIXTA si la guardia ayuda pero no alcanza a random_low. (Pre-registrada, lazo real exp018, 4 "
                    "seeds.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp095_guard_diversity")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-8p")
        notes.append("H-V4-8p marcada '{}' con DoD completo (la guardia ayuda pero el filtro no vence al pool-limpio-barato).".format(status))

    analogy = AnalogyRecord(
        problem=("Para juntar buenos ejemplos con qué practicar: ¿genero ideas muy variadas y las FILTRO con mi mejor "
                 "criterio (más una red de seguridad para no encasillarme), o genero ideas prolijas y agarro al azar?"),
        everyday=("Depende de qué tan prolijo me salga generar. Mi red de seguridad (no repetir + recordar lo básico) SÍ "
                  "me ayuda a no encasillarme cuando filtro. PERO si generando tranquilo (sin forzar variedad) ya me "
                  "salen casi todas bien, agarrar al azar de esa tanda PROLIJA me da más variedad limpia y me va MEJOR "
                  "que generar a lo loco y filtrar (filtrar me sesga hacia lo que ya me sale confiado, y encima tengo que "
                  "tirar la basura que generé de más). El filtro vale la pena cuando lo que genero es mayormente malo; si "
                  "lo barato es generar prolijo, mejor eso y agarrar ancho."),
        solutions=["pool limpio barato (temp baja) + random: el mejor en este régimen (muestra amplia, no-sesgada)",
                   "conf + guardia + alta diversidad: la guardia ayuda (destraba el narrowing) pero no alcanza al pool-limpio",
                   "el filtro de confianza paga cuando el pool es RUIDOSO (tasa base de calidad baja)",
                   "filtrar introduce sesgo de selección que cuesta diversidad; a alta temp, además, costo de filtrar basura"],
        principles=["el valor de un filtro de selección depende de la TASA BASE de calidad del pool",
                    "pool limpio (tasa base alta) -> el muestreo aleatorio basta/gana; pool ruidoso -> el filtro paga",
                    "la guardia de diversidad (94) ayuda al filtro (destraba el narrowing) pero no lo vuelve óptimo global aquí",
                    "concilia 110: la interacción temp×alloc es positiva, pero el óptimo global puede ser generar-limpio+muestrear-ancho"],
        adaptation=("El lab REFINA la política generación↔selección: no asumir que 'filtrar fuerte' es siempre lo mejor. "
                    "Si un pool LIMPIO es barato (el generador emite mayormente correctos a baja temperatura), conviene "
                    "generar prolijo y muestrear ANCHO (random) en vez de generar diverso y filtrar. El filtro de "
                    "confianza (aun con la guardia de diversidad 94, que sí ayuda) paga cuando el pool es RUIDOSO (tasa "
                    "base baja). Política: medir la tasa base de calidad del pool y elegir filtro-vs-random en función de "
                    "ella. Próximo: régimen donde un pool limpio NO sea barato (tarea dura / base débil) -> ¿el filtro "
                    "gana?; tasa base como señal de control; y SCALE."),
        measurement=("exp095 ({n} seeds, lazo real): conf_guard_high={cgh} > conf_high={ch} (+{gvp}) pero < random_low={rl} "
                     "({gvr}).").format(n=n_seeds, cgh=_f(cgh), ch=_f(ch), gvp=_f(gvp), rl=_f(rl), gvr=_f(gvr)),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (filtrar variado vs generar prolijo y agarrar al azar; depende de qué tan prolijo salga generar).")

    kl = ("REAL (exp095): la guardia de diversidad (94) AYUDA a conf-alloc (conf_guard_high={cgh} > conf_high={ch}, +{gvp}: "
          "destraba el narrowing) pero NO alcanza a random_low={rl} ({gvr}). El valor del FILTRO de confianza depende de la "
          "TASA BASE de calidad del pool: con pool limpio barato (baja temp + base decente) random-from-clean gana; el "
          "filtro paga bajo pool ruidoso. TECHO: no resuelve el caveat de 110 en este régimen; régimen tiny/sembrado con "
          "baja temp ya muy correcta; a escala/tarea donde un pool limpio NO sea barato el filtro debería ganar (no "
          "testeado); 2 niveles de temp, replay_frac fijo, {n} seeds, CPU.").format(
              cgh=_f(cgh), ch=_f(ch), gvp=_f(gvp), rl=_f(rl), gvr=_f(gvr), n=n_seeds)
    ceilings.add(CeilingRecord(
        subsystem="Generación↔selección — el valor del FILTRO de confianza depende de la TASA BASE de calidad del pool (la guardia 94 ayuda pero no vence al pool-limpio-barato); refina 110",
        known_limit=kl,
        blockers=[{"text": "régimen tiny/sembrado donde la baja temperatura YA da un pool mayormente correcto (tasa base alta) -> random-from-clean gana; a escala/tarea donde un pool limpio NO sea barato el filtro debería ganar (NO testeado)", "kind": "diseno"},
                  {"text": "la guardia de diversidad (94) ayuda al filtro (+narrowing destrabado) pero introduce/no elimina el sesgo de selección hacia lo confiado; el filtro siempre cuesta algo de diversidad vs muestreo limpio", "kind": "fisico"},
                  {"text": "2 niveles de temperatura, replay_frac fijo; 4 seeds, CPU; medir la tasa base como señal de control y SCALE pendientes", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP095.ref, S_EXP094.ref]))
    notes.append("1 techo 'real': el valor del filtro depende de la tasa base de calidad del pool (refina 110; la guardia ayuda pero no vence al pool-limpio-barato).")

    dstmt = ("North-Star R-VALOR (refina la política generación↔selección de 110): el valor de FILTRAR por valor depende "
             "de la TASA BASE de calidad del pool de candidatos. La guardia de diversidad (94) AYUDA al filtro de "
             "confianza (destraba su narrowing) pero NO lo vuelve óptimo global: cuando un pool LIMPIO es barato (baja "
             "temperatura del generador + base decente -> mayormente correctos), generar prolijo y muestrear ANCHO "
             "(random) vence a generar diverso y filtrar (que sesga hacia lo confiado y paga el costo de filtrar la "
             "basura de la alta temp). Decisión: elegir filtro-vs-muestreo-ancho según la tasa base de calidad del pool; "
             "el filtro de confianza se reserva para pools RUIDOSOS. Concilia con 110: la interacción temp×alloc es "
             "positiva, pero el óptimo global en pool-limpio-barato es generar-limpio+muestrear-ancho. Próximo: régimen "
             "de pool-no-limpio-barato; tasa base como señal de control; y SCALE.")
    drat = ("exp095 (tier5, propio, {n} seeds, PyTorch CPU, lazo real exp018): conf_guard_high={cgh} > conf_high={ch} "
            "(+{gvp}, la guardia ayuda) pero < random_low={rl} ({gvr}). Convergente con 'el valor del filtro depende de la "
            "tasa base' (tier2) y con el caveat de 110 (tier5). MIXTA: la guardia ayuda pero no resuelve el caveat; el "
            "filtro paga bajo pool ruidoso.").format(n=n_seeds, cgh=_f(cgh), ch=_f(ch), gvp=_f(gvp), rl=_f(rl), gvr=_f(gvr))
    dec = Decision(id="D-V4-73", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP095), _to_plain(S_EXP094)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-73 ACEPTADA por el ledger (tier5 exp095 + tier5 exp094).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-73:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle111_guard_diversity',
                                description='CYCLE 111 (RESET v4, H-V4-8p MIXTA: la guardia 94 ayuda al filtro pero no vence al pool-limpio-barato; el valor del filtro depende de la tasa base de calidad del pool).')
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
    print("RESUMEN — CYCLE 111 (RESET v4): la guardia (94) ayuda al filtro pero no vence al pool-limpio-barato (H-V4-8p MIXTA)")
    print("=" * 78)
    print("veredicto H-V4-8p:", status.upper() if status else "?")
    print("  el valor del filtro de confianza depende de la TASA BASE de calidad del pool: pool limpio barato -> random gana; pool ruidoso -> filtro paga.")
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
