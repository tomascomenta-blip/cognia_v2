r"""
cycle50_diversity_guard.py — CICLO 50 (RESET v4): H-V4-2c por las compuertas del engine.

H-V4-2c: ¿una GUARDIA de diversidad simple (dedup de verificados + REPLAY de datos semilla de la verdad)
previene el narrowing del lazo iterado (caveat de CYCLE 49) y/o sube el techo del bootstrapping? DERIVA de
exp036_diversity_guard/results/results.json.

RESULTADO REAL: APOYADA (3 seeds, R=6). PLANO step por ronda [0.300,0.442,0.475,0.536,0.425,0.547,0.642]
(trepa pero ERRÁTICO: cae a 0.425 en r4; cobertura ESTANCADA ~180; diversidad 0.036->0.019). GUARDED
[0.300,0.531,0.525,0.586,0.656,0.697,0.692] (trepa SUAVE y MÁS ALTO; cobertura CRECIENTE 175->202; sin costo
de precisión: 0.692 >= 0.642). => la narrowing del CYCLE 49 era REAL (el plano se estanca/erratiza y su
cobertura no crece) y una guardia BARATA (dedup+replay) la arregla: lazo más estable, techo más alto y
cobertura del espacio de problemas creciente. (La diversidad-de-respuestas colapsa para ambos por el vocab
chico de la suma -> la COBERTURA de prompts es la señal buena.) Confirma que el lazo de auto-mejora es
controlable con un guardián barato.

Correr (DESPUÉS de exp036):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp036_diversity_guard.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle50_diversity_guard
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
                             'cycle50_diversity_guard')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp036_diversity_guard', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _fmt(x):
    return "{:.3f}".format(x) if isinstance(x, (int, float)) else str(x)


def _seq(xs, fmt="%.3f"):
    return "[" + " ".join(fmt % x for x in xs) + "]"


S_REPLAY = Source(tier=1, ref="experience-replay/anti-collapse", obtained=False,
                  claim=("Mezclar datos originales (replay) y deduplicar evita el colapso de distribución al "
                         "auto-entrenar (anti model-collapse). (Principio, no re-obtenido esta sesión.)"))
S_C11 = Source(tier=5, ref="cognia_x/learn (CYCLE 11)", obtained=True,
               claim=("CYCLE 11: el anti-colapso es un eje del lab; verify-before-learn previene el colapso."))
S_EXP035 = Source(tier=5, ref="cognia_x/experiments/exp035_iterated_star", obtained=True,
                  claim=("exp035 (CYCLE 49): el lazo iterado es estable pero la diversidad declina monótona "
                         "(narrowing temprano) -> caveat a resolver con una guardia."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    v = data.get('verdict')
    st = data.get('stats')
    if not v or not st:
        raise SystemExit("results.json sin verdict/stats (corre exp036 primero): " + results_path)
    status = v.lower()
    sp, sg = st['step_plain'], st['step_guarded']
    cp, cg = st['cov_plain'], st['cov_guarded']
    R = len(sp) - 1
    n_seeds = st['n_seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    S_EXP036 = Source(tier=5, ref="cognia_x/experiments/exp036_diversity_guard", obtained=True,
                      claim=("exp036 (propio, {n} seeds, R={R}, modelo HybridLM): una guardia barata (dedup de "
                             "verificados + replay de datos semilla) hace el lazo iterado más ESTABLE y de techo "
                             "MÁS ALTO: paso final plano {fp} -> guarded {fg}; cobertura final plano {kp} -> "
                             "guarded {kg} (creciente). El plano trepa ERRÁTICO y su cobertura se estanca.").format(
                                 n=n_seeds, R=R, fp=_fmt(sp[R]), fg=_fmt(sg[R]), kp=int(cp[R]), kg=int(cg[R])))
    for src in (S_REPLAY, S_C11, S_EXP035, S_EXP036):
        ledger.add_source(src)
    notes.append("4 fuentes (S_REPLAY tier1; S_C11 tier5 anti-colapso; S_EXP035 tier5 caveat narrowing; S_EXP036 tier5 dato propio).")

    ev_for = [S_EXP036.ref, S_EXP035.ref]
    ev_against = [S_EXP036.ref]      # honesto: la diversidad-de-respuestas colapsa para AMBOS (vocab chico)
    adv = ("APOYADA: la narrowing del CYCLE 49 era REAL y una GUARDIA BARATA la arregla. PLANO: el paso trepa "
           "pero ERRÁTICO {sp} (cae a 0.425 en r4) y su COBERTURA de prompts se ESTANCA {cp} (~180). GUARDED "
           "(dedup de verificados + replay de datos semilla de la VERDAD): trepa SUAVE y MÁS ALTO {sg} (techo "
           "{fg} vs {fp}), con COBERTURA CRECIENTE {cg} (de {k1} a {kg}) y SIN costo de precisión. MECANISMO: el "
           "plano entrena con verificados CON FRECUENCIA -> se machaca en los correctos fáciles/frecuentes "
           "(overfit, se estanca); el dedup quita esa frecuencia y el replay reinyecta señal de la verdad -> el "
           "lazo sigue cubriendo MÁS del espacio de problemas y trepa más. EVIDENCIA EN CONTRA (caveat honesto): "
           "la métrica diversidad-de-respuestas colapsa para AMBOS (acotada por el vocab chico de la suma, ~39 "
           "valores) -> la señal válida de narrowing es la COBERTURA de prompts (no la diversidad de answers). "
           "Ataques: (1) '¿el replay es sólo más datos buenos?' -> el replay es CHICO (replay_n) y de la verdad; "
           "el efecto grande viene también del DEDUP (quitar la frecuencia de lo auto-generado). (2) '¿el plano "
           "colapsa de verdad?' -> no colapsa a 0, pero se estanca/erratiza y NO cubre más; la guardia sí. "
           "CONCLUSIÓN: el lazo de auto-mejora es CONTROLABLE con un guardián barato -> motor de auto-mejora "
           "sostenible y de techo más alto.").format(
               sp=_seq(sp), cp=_seq(cp, "%.0f"), sg=_seq(sg), cg=_seq(cg, "%.0f"), fg=_fmt(sg[R]), fp=_fmt(sp[R]),
               k1=int(cg[1]), kg=int(cg[R]))

    hyp = Hypothesis(
        id="H-V4-2c",
        statement=("Una guardia de diversidad (dedup de verificados + replay de datos semilla) previene el "
                   "narrowing del lazo iterado y sube su techo, sin sacrificar precisión."),
        prediction=("APOYADA si la guardia mantiene MÁS cobertura/diversidad que el plano al final Y su precisión "
                    "final >= la del plano; REFUTADA si no mejora la cobertura o hunde la precisión; MIXTA si el "
                    "plano no narrowing (guardia innecesaria). (Pre-registrada.)"),
        status='abierta', confidence='alta',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=adv, experiment_ref="exp036_diversity_guard")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-2c")
        notes.append("H-V4-2c marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("Repasás repitiendo SÓLO tus ejercicios bien resueltos y terminás machacando los mismos pocos "
                 "(perdés variedad y te estancás). ¿Cómo seguís mejorando sin encerrarte?"),
        everyday=("Dos arreglos baratos: (1) NO repetir el mismo ejercicio 50 veces porque salió bien (DEDUP); "
                  "(2) intercalar ejercicios del LIBRO original (REPLAY de la verdad). Con eso seguís cubriendo "
                  "casos nuevos y trepás más alto, en vez de pulir tres cuentas fáciles."),
        solutions=["lazo PLANO (entrenar con todos los verificados con frecuencia) -> se estanca/erratiza, cobertura plana",
                   "DEDUP (cada verificado único una vez) -> quita el sesgo de frecuencia hacia lo fácil",
                   "REPLAY (datos semilla de la verdad) -> reinyecta señal y cobertura",
                   "DEDUP+REPLAY juntos -> trepa suave y más alto (0.692 vs 0.642), cobertura creciente (202 vs 185)"],
        principles=["entrenar con auto-salidas CON FRECUENCIA sesga hacia lo fácil/frecuente -> estancamiento",
                    "deduplicar + replay de la verdad sostiene la cobertura del espacio y sube el techo del bootstrapping",
                    "la señal válida de narrowing es la COBERTURA de problemas, no la diversidad de answers (acotada por el vocab)",
                    "el lazo de auto-mejora es CONTROLABLE con un guardián barato (no requiere un modelo más grande)"],
        adaptation=("El lazo de auto-mejora del lab incorpora una guardia barata por defecto (dedup + replay de "
                    "la verdad). Próximos: medir el TECHO real con más rondas/base más fuerte, una métrica de "
                    "diversidad no acotada por el vocab, y el verificador real-chequeable (código→sandbox) para "
                    "tareas más ricas."),
        measurement=("exp036: paso final plano {fp} -> guarded {fg}; cobertura final {kp} -> {kg}; plano "
                     "errático {sp}. {n} seeds.").format(fp=_fmt(sp[R]), fg=_fmt(sg[R]), kp=int(cp[R]),
                                                         kg=int(cg[R]), sp=_seq(sp), n=n_seeds),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (dedup + replay de la verdad: seguir cubriendo casos nuevos en vez de pulir tres cuentas fáciles).")

    ceilings.add(CeilingRecord(
        subsystem="SUSTRATO — guardia de diversidad (dedup+replay) en el lazo iterado: más estable y techo más alto",
        known_limit=("REAL (exp036): la narrowing del lazo iterado (CYCLE 49) es real (el plano se estanca/"
                     "erratiza, cobertura plana ~{kp}) y una guardia barata (dedup+replay) la arregla: techo más "
                     "alto ({fp}->{fg}), cobertura creciente (->{kg}), sin costo de precisión.").format(
                         kp=int(cp[R]), fp=_fmt(sp[R]), fg=_fmt(sg[R]), kg=int(cg[R])),
        blockers=[{"text": "no se midió el TECHO real (cuántas rondas hasta plateau con la guardia); falta correr más rondas/base más fuerte", "kind": "diseno"},
                  {"text": "la métrica diversidad-de-respuestas está acotada por el vocab chico de la suma; falta una métrica de diversidad para tareas ricas", "kind": "diseno"},
                  {"text": "tarea aritmética con oráculo exacto; falta verificador real-chequeable (código→sandbox) y razonamiento no-aritmético", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP036.ref, S_EXP035.ref]))
    notes.append("1 techo 'real': la guardia barata (dedup+replay) arregla el narrowing y sube el techo del bootstrapping.")

    dstmt = ("El lazo de auto-mejora del integrador queda CONTROLADO con un guardián barato: dedup de los "
             "verificados + replay de datos semilla de la verdad evita el narrowing (que el CYCLE 49 detectó) y "
             "SUBE el techo del bootstrapping (paso final {fp}->{fg}, cobertura creciente) sin costo de precisión, "
             "sin un modelo más grande. Decisión: el lazo de auto-mejora del lab usa dedup+replay por defecto. "
             "Cierra el sub-arco de auto-mejora (48 una ronda + 49 iterado estable + 50 guardia controla el "
             "narrowing). Próximos: medir el TECHO real (más rondas), métrica de diversidad no acotada por el "
             "vocab, y verificador real-chequeable (código→sandbox) para tareas más ricas que la aritmética.")
    drat = ("exp036 (tier5, propio, {n} seeds, R={R}): guarded > plano en techo ({fg} vs {fp}) y cobertura "
            "({kg} vs {kp}), sin costo de precisión; el plano se estanca/erratiza. Convergente con replay/"
            "anti-colapso y con CYCLE 11. APOYADA.").format(n=n_seeds, R=R, fg=_fmt(sg[R]), fp=_fmt(sp[R]),
                                                            kg=int(cg[R]), kp=int(cp[R]))
    dec = Decision(id="D-V4-15", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP036), _to_plain(S_EXP035)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-15 ACEPTADA por el ledger (tier5 exp036 + tier5 exp035).")
    except OpinionOnlyError as e:
        print("ERROR ledger D-V4-15:", e); raise

    return record, notes, status, st


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle50_diversity_guard',
                                description='CYCLE 50 (RESET v4, H-V4-2c: guardia de diversidad en el lazo iterado).')
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
    print("RESUMEN — CYCLE 50 (RESET v4): guardia de diversidad (dedup+replay) en el lazo iterado (H-V4-2c)")
    print("=" * 78)
    print("veredicto H-V4-2c:", status.upper() if status else "?")
    print("  dedup+replay frena el narrowing y sube el techo del bootstrapping, sin costo de precisión.")
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
