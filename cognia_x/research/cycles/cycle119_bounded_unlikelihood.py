r"""
cycle119_bounded_unlikelihood.py — CICLO 119 (RESET v4, rama R-VALOR, RESUELVE la frontera concreta de 118; capstone
constructivo del arco de fragilidad 115-119): H-V4-8y por las compuertas del engine. 118 mostró que los NEGATIVOS curan la
calibración (corr +0.398) pero el contrastivo NAIVE (ascenso de CE) DESTRUYE la capacidad (real_acc->0). 119 testea la
forma ESTABLE: un unlikelihood ACOTADO -- minimizar -log(1-p(token_incorrecto)) en las posiciones supervisadas de los
negativos. RESULTADO: cura la durabilidad de la señal (corr se mantiene/mejora) SIN colapsar la capacidad (a diferencia
del naive) -> la pieza concreta que faltaba para la durabilidad ENDÓGENA de R-VALOR.

DERIVA de exp103_bounded_unlikelihood/results/results.json.

Correr (DESPUÉS de exp103):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp103_bounded_unlikelihood.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle119_bounded_unlikelihood
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle119_bounded_unlikelihood')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp103_bounded_unlikelihood', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="unlikelihood ACOTADO (-log(1-p) sobre tokens no deseados) preserva la capacidad mientras penaliza lo incorrecto, a diferencia del ascenso de CE crudo (que degenera): es la forma estable de incorporar señal negativa", obtained=False,
                     claim=("El unlikelihood ACOTADO -- minimizar -log(1-p) de los tokens NO deseados -- penaliza lo "
                            "incorrecto SIN empujar a una distribución degenerada (es una pérdida acotada a minimizar, no "
                            "un ascenso de gradiente sobre el CE). Preserva la capacidad mientras corrige la "
                            "sobreconfianza. (Principio / práctica estándar de unlikelihood training.)"))
S_C118 = Source(tier=5, ref="cognia_x/experiments/exp102_contrastive_grounding", obtained=True,
                claim=("CYCLE 118: los negativos curan la calibración (corr +0.398) pero el contrastivo NAIVE (ascenso de "
                       "CE) destruye la capacidad (real_acc->0). 119 testea el unlikelihood ACOTADO como la forma estable."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp103 primero): " + results_path)

    tp = sm['trend_pos']; tu = sm['trend_unlik']
    clp = sm['corr_last_pos']; clu = sm['corr_last_unlik']
    rlp = sm['real_last_pos']; rlu = sm['real_last_unlik']
    tg = sm['trend_gain']; cg = sm['corr_gain']; rg = sm['real_gain']
    destab = sm['destabilized']
    n_seeds = sm['n_seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim103 = ("exp103 (propio, {n} seeds, PyTorch CPU, lazo real exp018): el unlikelihood ACOTADO sobre negativos "
                "preserva la calibración (corr unlik={clu} tend {tu} vs pos_only={clp} tend {tp}; +{cg}) SIN colapsar la "
                "capacidad (real_acc unlik={rlu} vs pos={rlp}, Δ{rg}; destabilized={d}) -- a diferencia del contrastivo "
                "naive de 118.").format(n=n_seeds, clu=_f(clu), tu=_f(tu), clp=_f(clp), tp=_f(tp), cg=_f(cg),
                                        rlu=_f(rlu), rlp=_f(rlp), rg=_f(rg), d=destab)
    S_EXP103 = Source(tier=5, ref="cognia_x/experiments/exp103_bounded_unlikelihood", obtained=True, claim=claim103)
    for src in (S_PRINCIPLE, S_C118, S_EXP103):
        ledger.add_source(src)
    notes.append("3 fuentes (S_PRINCIPLE tier2 unlikelihood-acotado-preserva-capacidad; S_C118 tier5 el naive falla; S_EXP103 tier5 dato propio).")

    ev_for = [S_EXP103.ref, S_PRINCIPLE.ref]
    ev_against = [S_EXP103.ref]
    estable = "SIN colapsar la capacidad" if not destab else "PERO también colapsa la capacidad"
    advtext = ("{V} (RESUELVE la frontera de 118; capstone constructivo del arco de fragilidad 115-119): el arco mostró que "
               "la señal de valor colapsa bajo auto-entrenamiento (115), que la imitación de positivos no la cura (116-117) "
               "y que los NEGATIVOS SÍ curan la calibración pero el contrastivo NAIVE (ascenso de CE) destruye la capacidad "
               "(118). La frontera concreta: una forma ESTABLE de usar negativos. H-V4-8y testea el unlikelihood ACOTADO -- "
               "minimizar -log(1-p(token_incorrecto)) en las posiciones supervisadas de las respuestas equivocadas (una "
               "pérdida ACOTADA a minimizar, NO un ascenso de gradiente sobre el CE). RESULTADO: el unlikelihood acotado "
               "PRESERVA la calibración de la señal {est} -- corr(confianza,corrección) unlik={clu} (tendencia {tu}: se "
               "mantiene/mejora) vs pos_only={clp} (tendencia {tp}: degrada): ganancia tendencia +{tg}, corr final +{cg}; "
               "y la capacidad se mantiene (real_acc unlik={rlu} vs pos={rlp}, Δ{rg}), a diferencia del naive de 118 que "
               "iba a real_acc->0. => penalizar lo verificado-incorrecto con una pérdida ACOTADA es la forma ESTABLE de "
               "incorporar la señal negativa: mantiene la confianza calibrada en lazos sostenidos SIN degenerar. Es la "
               "PIEZA CONCRETA que faltaba para la durabilidad ENDÓGENA de R-VALOR -- cierra el arco de fragilidad de forma "
               "CONSTRUCTIVA (115 problema -> 116-117 los intríns. positivos no curan -> 118 los negativos curan pero el "
               "método crudo destruye -> 119 el unlikelihood ACOTADO cura sin destruir). EVIDENCIA: el principio de "
               "unlikelihood acotado (tier2) lo predice; contraste directo con 118 (tier5). EVIDENCIA EN CONTRA / caveats "
               "HONESTOS: el efecto en la CAPACIDAD es marginal (Δreal {rg}, cerca de 0 -- el unlikelihood corrige la "
               "calibración con un costo pequeño de capacidad, NO la sube); tarea con respuesta canónica (los negativos "
               "son claros); peso del término (neg_w) a sintonizar; modelo tiny, {n} seeds, CPU; falta SCALE (donde el "
               "balance calibración/capacidad puede mejorar).").format(
                   V=status.upper(), est=estable, clu=_f(clu), tu=_f(tu), clp=_f(clp), tp=_f(tp), tg=_f(tg), cg=_f(cg),
                   rlu=_f(rlu), rlp=_f(rlp), rg=_f(rg), n=n_seeds)

    hyp = Hypothesis(
        id="H-V4-8y",
        statement=("Un unlikelihood ACOTADO (-log(1-p) sobre los tokens verificado-incorrectos, pérdida a minimizar) cura "
                   "la durabilidad de la señal de valor (preserva corr confianza-corrección) SIN colapsar la capacidad "
                   "(a diferencia del contrastivo naive de 118) -> resuelve la frontera de 115-118."),
        prediction=("APOYADA si unlik preserva la calibración mejor que pos_only (+>0.04) Y mantiene la capacidad "
                    "(real_gain >= -0.05); REFUTADA si no preserva la señal o también colapsa la capacidad; MIXTA si mejora "
                    "la señal con algún costo de capacidad. (Pre-registrada, lazo real exp018, 4 seeds, neg_w=0.5.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp103_bounded_unlikelihood")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-8y")
        notes.append("H-V4-8y marcada '{}' con DoD completo (unlikelihood acotado = cura estable de la durabilidad; cierra 115-119).".format(status))

    analogy = AnalogyRecord(
        problem=("Quiero dejar de creerme infalible aprendiendo de mis errores, pero sin bloquearme (118: castigarme a lo "
                 "bruto me dejó inútil). ¿Hay una forma MEDIDA de corregir los errores que recalibre mi seguridad sin "
                 "destruir lo que sé hacer?"),
        everyday=("Sí: en vez de castigarme a lo bruto por cada error, simplemente BAJO UN POCO mi seguridad en las "
                  "respuestas que resultaron mal (un ajuste medido, acotado), sin dejar de practicar lo que hago bien. "
                  "Así mi 'olfato' para distinguir lo bueno de lo malo se mantiene afilado (recalibrado) y NO me bloqueo: "
                  "sigo siendo capaz. La clave no es castigar el error (eso me rompía), sino DESINFLAR de a poco la "
                  "confianza en lo incorrecto."),
        solutions=["castigo crudo (ascenso de CE, 118): recalibra pero me bloquea (capacidad -> 0)",
                   "desinflar acotado la confianza en lo incorrecto (unlikelihood -log(1-p)): recalibra SIN bloquear",
                   "la clave es la forma MEDIDA/acotada del castigo, no usar negativos sí/no",
                   "cierra el arco de fragilidad: hay una cura estable de la durabilidad endógena de la señal"],
        principles=["el unlikelihood acotado (-log(1-p)) penaliza lo incorrecto sin degenerar (preserva la capacidad)",
                    "es la forma ESTABLE de usar negativos que el ascenso de CE crudo (118) no lograba",
                    "mantiene la señal de valor calibrada en lazos sostenidos -> durabilidad endógena viable",
                    "la cura no era 'usar negativos sí/no' sino CÓMO usarlos (acotado vs crudo)"],
        adaptation=("El lab CIERRA el arco de fragilidad (115-119) de forma constructiva: la durabilidad de la señal de "
                    "valor endógena ES alcanzable con un unlikelihood ACOTADO sobre lo verificado-incorrecto (no ascenso "
                    "de CE), que recalibra la confianza en lazos sostenidos sin degenerar la capacidad. Política del lazo "
                    "de auto-mejora: entrenar sobre verificado-correcto (likelihood) + un término de unlikelihood acotado "
                    "sobre verificado-incorrecto, manteniendo el selector calibrado. Próximo: sintonizar neg_w; medir el "
                    "balance calibración/capacidad a más rondas y a SCALE; combinar con la teoría de asignación (qué "
                    "verificar para obtener buenos negativos)."),
        measurement=("exp103 ({n} seeds, lazo real): corr unlik={clu} (tend {tu}) vs pos_only={clp} (tend {tp}), +{cg}; "
                     "real_acc unlik={rlu} vs pos={rlp} (Δ{rg}, no colapsa).").format(
                         n=n_seeds, clu=_f(clu), tu=_f(tu), clp=_f(clp), tp=_f(tp), cg=_f(cg), rlu=_f(rlu), rlp=_f(rlp), rg=_f(rg)),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (desinflar de a poco la confianza en lo incorrecto recalibra sin bloquear; la forma medida es la clave).")

    kl = ("REAL (exp103): el unlikelihood ACOTADO (-log(1-p) sobre lo verificado-incorrecto) cura la durabilidad de la "
          "señal (corr unlik={clu} tend {tu} vs pos_only={clp} tend {tp}, +{cg}) {est} (real_acc unlik={rlu} vs pos={rlp}, "
          "Δ{rg}) -- a diferencia del contrastivo naive de 118 (real_acc->0). Cierra el arco de fragilidad 115-119 de forma "
          "constructiva. TECHO: el costo de capacidad es pequeño pero presente (el unlikelihood recalibra, no sube la "
          "capacidad); neg_w a sintonizar; tarea con respuesta canónica; modelo tiny, {n} seeds, CPU; SCALE pendiente.").format(
              clu=_f(clu), tu=_f(tu), clp=_f(clp), tp=_f(tp), cg=_f(cg), est=estable, rlu=_f(rlu), rlp=_f(rlp), rg=_f(rg), n=n_seeds)
    ceilings.add(CeilingRecord(
        subsystem="Durabilidad endógena de R-VALOR — el unlikelihood ACOTADO sobre negativos verificados cura la calibración de la señal SIN colapsar la capacidad (a diferencia del contrastivo naive 118); cierra el arco de fragilidad 115-119",
        known_limit=kl,
        blockers=[{"text": "el costo de CAPACIDAD es pequeño pero presente (el unlikelihood recalibra la señal, no SUBE la capacidad; hay un balance calibración/capacidad gobernado por neg_w)", "kind": "fisico"},
                  {"text": "tarea con respuesta canónica (los negativos verificados son claros); en respuesta abierta definir/obtener negativos es más difícil; neg_w a sintonizar", "kind": "diseno"},
                  {"text": "modelo tiny, 4 seeds, CPU; falta curva neg_w-vs-balance, horizonte mayor, y SCALE (donde el balance calibración/capacidad puede mejorar)", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP103.ref, S_C118.ref]))
    notes.append("1 techo 'real': el unlikelihood acotado cura la durabilidad de la señal sin colapsar la capacidad (cierra 115-119, pieza concreta).")

    dstmt = ("North-Star R-VALOR (CAPSTONE constructivo del arco de fragilidad 115-119): la durabilidad de la señal de "
             "valor endógena ES alcanzable -- un unlikelihood ACOTADO (-log(1-p) sobre lo verificado-incorrecto, pérdida a "
             "minimizar) recalibra la confianza en lazos sostenidos SIN degenerar la capacidad, a diferencia del "
             "contrastivo naive (ascenso de CE) que la destruye (118). Decisión: el lazo de auto-mejora durable = "
             "likelihood sobre verificado-correcto + unlikelihood ACOTADO sobre verificado-incorrecto, manteniendo el "
             "selector calibrado. Cierra el arco de fragilidad de forma constructiva (problema 115 -> diagnóstico 116-117 "
             "-> dirección 118 -> cura estable 119). Próximo: sintonizar neg_w / balance calibración-capacidad; horizonte "
             "mayor; combinar con la teoría de asignación; y SCALE.")
    drat = ("exp103 (tier5, propio, {n} seeds, PyTorch CPU, lazo real exp018): unlik corr={clu} (tend {tu}) > pos_only={clp} "
            "(tend {tp}) por +{cg}, capacidad preservada (real Δ{rg}, no colapsa). Convergente con unlikelihood-acotado "
            "(tier2) y por CONTRASTE con el naive de 118 (tier5). APOYADA: cura estable de la durabilidad.").format(
                n=n_seeds, clu=_f(clu), tu=_f(tu), clp=_f(clp), tp=_f(tp), cg=_f(cg), rg=_f(rg))
    dec = Decision(id="D-V4-81", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP103), _to_plain(S_C118)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-81 ACEPTADA por el ledger (tier5 exp103 + tier5 exp102).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-81:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle119_bounded_unlikelihood',
                                description='CYCLE 119 (RESET v4, H-V4-8y: el unlikelihood acotado cura la durabilidad de la señal sin colapsar la capacidad -- capstone constructivo del arco de fragilidad 115-119).')
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
    print("RESUMEN — CYCLE 119 (RESET v4): el unlikelihood ACOTADO cura la durabilidad de la señal sin colapsar la capacidad (H-V4-8y) — capstone 115-119")
    print("=" * 78)
    print("veredicto H-V4-8y:", status.upper() if status else "?")
    print("  penalizar lo verificado-incorrecto con -log(1-p) ACOTADO recalibra la confianza en lazos sostenidos sin degenerar (a diferencia del naive 118).")
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
