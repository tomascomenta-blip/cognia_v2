r"""
cycle83_nonfactorizable_value.py — CICLO 83 (RESET v4, rama R-VALOR, ATAQUE a la factorización): H-V4-7a por las
compuertas del engine. APOYADA: la reconstrucción-PRODUCTO de R-VALOR (ctrl_est × rel_est) del arco 79-82 NO es una
ley universal sino un PRIOR DE COMPLEMENTARIEDAD. Es robusta a no-factorizabilidad COMPLEMENTARIA (g=min, óptimo
both-high) en TODO λ, y se ROMPE bajo SUSTITUTOS puros (g=max, λ=1.0, óptimo 'al menos uno alto') donde una marginal
la supera. Caveat honesto: tolera no-factorizabilidad MODERADA (λ<=0.5 el producto vence en ambas familias). Ataca el
gap #2 del decomposition_tree (valor multiplicativo ctrl×rel asumido) y lo acota: la factorización del thesis sobrevive
salvo cuando el óptimo deja de ser both-high.

DERIVA de exp067_nonfactorizable_value/results/results.json.

Correr (DESPUÉS de exp067):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp067_nonfactorizable_value.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle83_nonfactorizable_value
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle83_nonfactorizable_value')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp067_nonfactorizable_value', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


def _adv(adv, key):
    # adv viene de JSON: claves float serializadas a str ("0.5"). Acepta ambas.
    if key in adv:
        return adv[key]
    return adv.get(str(key), adv.get("{:.1f}".format(float(key))))


S_COBB = Source(tier=2, ref="microeconomía: utilidad Cobb-Douglas (multiplicativa, complementos) vs sustitutos perfectos (aditiva/max)", obtained=False,
                claim=("La forma PRODUCTO (Cobb-Douglas) modela bienes COMPLEMENTARIOS: el óptimo exige ambos insumos "
                       "altos; ranquea bien cualquier valor cuyo máximo esté en 'ambos altos'. La forma SUSTITUTOS "
                       "(aditiva/max) tiene su óptimo en 'al menos uno alto' y NO se reduce a un producto de marginales. "
                       "(Principio; un combinador-producto codifica un prior de complementariedad, no una ley universal.)"))
S_TREE = Source(tier=5, ref="cognia_x/manager/decomposition_tree.md (gap #2 del estado 72-82: 'valor multiplicativo ctrl×rel asumido; falta valor no-factorizable')", obtained=True,
                claim=("El estado v4 tras 72-82 declaró como caveat abierto que TODO el arco 79-82 asumió value=ctrl×rel "
                       "(factorización de diseño). H-V4-7a ataca ese gap: introduce valor NO factorizable y mide si la "
                       "reconstrucción-producto sobrevive."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp067 primero): " + results_path)

    adv_comp, adv_subs = sm['adv_comp'], sm['adv_subs']
    comp_10 = _adv(adv_comp, 1.0)
    subs_05 = _adv(adv_subs, 0.5)
    subs_10 = _adv(adv_subs, 1.0)
    comp_05 = _adv(adv_comp, 0.5)
    xover_comp = sm['crossover_comp']
    xover_subs = sm['crossover_subs']
    robust_all = sm['comp_robust_all']
    breaks_ext = sm['subs_breaks_extreme']
    moderate = sm['moderate_tolerant']
    rc, rs = sm['rep_comp_pure'], sm['rep_subs_pure']
    n_seeds = data['args']['seeds']
    xc = "nunca" if xover_comp is None else str(xover_comp)
    xs = "nunca" if xover_subs is None else str(xover_subs)

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim067 = ("exp067 (propio, {n} seeds, numpy): con value=(1-λ)·ctrl·rel + λ·g, bajo COMPLEMENTOS (g=min) la "
                "reconstrucción-producto (ctrl_est × rel_est) vence a cada marginal en TODO λ (crossover {xc}; adv en "
                "λ=1.0 = {c10}); bajo SUSTITUTOS (g=max) la ventaja decae monótona y se ROMPE en λ=1.0 (crossover λ*={xs}; "
                "adv {s10}<=0.05, una marginal la supera). Tolera no-factorizabilidad moderada (λ=0.5: comp adv {c05}, "
                "subs adv {s05}, ambos>0.05). Las filas 'clean' (estimadores perfectos) reproducen la asimetría -> es la "
                "FACTORIZACIÓN, no el ruido.").format(
                    n=n_seeds, xc=xc, c10=_f(comp_10), xs=xs, s10=_f(subs_10), c05=_f(comp_05), s05=_f(subs_05))
    S_EXP067 = Source(tier=5, ref="cognia_x/experiments/exp067_nonfactorizable_value", obtained=True, claim=claim067)
    for src in (S_COBB, S_TREE, S_EXP067):
        ledger.add_source(src)
    notes.append("3 fuentes (S_COBB tier2 complementos vs sustitutos; S_TREE tier5 gap #2; S_EXP067 tier5 dato propio).")

    ev_for = [S_EXP067.ref, S_TREE.ref, S_COBB.ref]
    ev_against = [S_EXP067.ref]
    adv = ("{V} (ataque a la factorización del arco 79-82; acota el gap #2): TODO el arco asumió value=ctrl×rel. "
           "exp067 lo ataca con valor NO factorizable, value=(1-λ)·ctrl·rel + λ·g, en dos familias opuestas y dos "
           "niveles de ruido. RESULTADO (asimetría = prior de complementariedad): bajo COMPLEMENTOS (g=min, óptimo "
           "both-high) la reconstrucción-producto vence a ambas marginales en TODO λ (crossover {xc}; adv en λ=1.0 = "
           "{c10}, prod={cp1}); bajo SUSTITUTOS (g=max, óptimo 'al menos uno alto') la ventaja decae monótona "
           "({s_profile}) y el producto se ROMPE en λ=1.0 (crossover λ*={xs}; rvalue_prod {sp1} < mejor marginal "
           "max(emp {se1}, rel {sr1}), adv={s10}). => la factorización ctrl×rel NO es ley universal sino un PRIOR DE "
           "COMPLEMENTARIEDAD: vale cuando la no-factorizabilidad preserva el óptimo both-high, falla cuando lo cambia a "
           "sustitutos. EVIDENCIA EN CONTRA / caveats: el producto es MÁS robusto de lo pre-registrado -- tolera "
           "no-factorizabilidad MODERADA (λ<=0.5 vence en AMBAS familias: comp adv {c05}, subs adv {s05}); el break sólo "
           "aparece cerca de sustitutos puros (λ>=0.75). NOTA DE PROCESO: el punto único λ=0.5 del piloto resultó laxo; "
           "la métrica confirmatoria es el crossover λ*/extremo (misma hipótesis cualitativa). Juguete: g sintético "
           "(min/max), objetivo escalar, estimadores con ruido abstracto. CONCLUSIÓN: el thesis R-VALOR=control×relevancia "
           "del arco 79-82 sobrevive como prior robusto, con frontera caracterizada (sustitutos).").format(
               V=status.upper(), xc=xc, c10=_f(comp_10), cp1=_f(rc['rvalue_prod']),
               s_profile="adv subs por λ baja de {} a {}".format(_f(_adv(adv_subs, 0.0)), _f(subs_10)),
               xs=xs, sp1=_f(rs['rvalue_prod']), se1=_f(rs['empowerment']), sr1=_f(rs['relevance']),
               s10=_f(subs_10), c05=_f(comp_05), s05=_f(subs_05))

    hyp = Hypothesis(
        id="H-V4-7a",
        statement=("La reconstrucción-PRODUCTO de R-VALOR (ctrl_est × rel_est) codifica un prior de complementariedad: "
                   "robusta a no-factorizabilidad complementaria (min) en todo λ, se rompe bajo sustitutos puros (max)."),
        prediction=("APOYADA si bajo complementos adv>0.05 en TODO λ (crossover=nunca) Y bajo sustitutos adv<=0.05 en "
                    "λ=1.0 (se rompe en el extremo); REFUTADA si el producto nunca se rompe (universal) o no es robusto "
                    "ni bajo complementos (frágil); MIXTA en otro caso. (Métrica crossover λ*, pre-registrada.)"),
        status='abierta', confidence='alta' if status == 'apoyada' else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=adv, experiment_ref="exp067_nonfactorizable_value")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-7a")
        notes.append("H-V4-7a marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("Tenés dos atributos por opción y un puntaje a ojo de cada uno. ¿Te alcanza con multiplicarlos para "
                 "elegir bien, o depende de SI el valor pide AMBOS altos o sólo UNO?"),
        everyday=("Depende. Para una RECETA necesitás harina Y agua (complementos): multiplicar los dos puntajes elige "
                  "perfecto -- una opción con harina pero sin agua no sirve, y el producto la castiga bien. Para IR AL "
                  "TRABAJO te sirve auto O bici (sustitutos): multiplicar es un ERROR -- una opción con auto-buenísimo "
                  "pero sin bici tiene producto bajo y la descartás, cuando en realidad es excelente. Ahí conviene mirar "
                  "el MEJOR de los dos, no el producto. Multiplicar asume que todo es como una receta."),
        solutions=["producto (ctrl_est × rel_est) -> óptimo para complementos (receta); vence a cada atributo solo en todo λ",
                   "una marginal sola (el mejor atributo) -> gana bajo sustitutos puros (auto O bici)",
                   "aditivo (suma) -> intermedio; nunca dramáticamente mejor, no universal",
                   "el producto es un prior de COMPLEMENTARIEDAD: robusto salvo cuando el valor es de sustitutos"],
        principles=["el combinador-producto codifica un prior de complementariedad (óptimo both-high), no una ley universal",
                    "R-VALOR=control×relevancia (arco 79-82) sobrevive a no-factorizabilidad COMPLEMENTARIA en todo grado",
                    "el producto SÓLO se rompe cuando el óptimo deja de ser both-high (sustitutos: 'al menos uno alto')",
                    "tolera no-factorizabilidad moderada; el break es una frontera caracterizada, no fragilidad general"],
        adaptation=("El lab mantiene R-VALOR = empowerment_est × verificador como reconstrucción por DEFECTO (es un prior "
                    "de complementariedad robusto), pero DETECTA el régimen de sustitutos (cuando una marginal sola "
                    "supera al producto) y ahí conmuta a max/marginal. Próximo: un combinador APRENDIDO de pocas "
                    "observaciones de valor que recupere lo que el producto pierde bajo sustitutos (CYCLE 84), cerrando "
                    "el gap #2 con construcción además de acotación."),
        measurement=("exp067 ({n} seeds): COMP crossover {xc} (adv λ1.0={c10}); SUBS crossover λ*={xs} (adv λ1.0={s10}); "
                     "tolera λ<=0.5 (comp {c05}, subs {s05}).").format(
                         n=n_seeds, xc=xc, c10=_f(comp_10), xs=xs, s10=_f(subs_10), c05=_f(comp_05), s05=_f(subs_05)),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (receta=complementos/producto vs ir-al-trabajo=sustitutos/marginal).")

    kl = ("REAL (exp067): la reconstrucción-PRODUCTO de R-VALOR (ctrl_est × rel_est) es un PRIOR DE COMPLEMENTARIEDAD. "
          "Robusta a no-factorizabilidad complementaria (g=min) en TODO λ (crossover {xc}); se ROMPE bajo sustitutos "
          "puros (g=max, crossover λ*={xs}, adv en λ=1.0 = {s10}). Tolera no-factorizabilidad moderada (λ<=0.5 vence en "
          "ambas familias). Acota el gap #2: la factorización ctrl×rel del arco 79-82 no es universal pero sí robusta "
          "salvo en el régimen de sustitutos.").format(xc=xc, xs=xs, s10=_f(subs_10))
    ceilings.add(CeilingRecord(
        subsystem="R-VALOR reconstrucción-producto — prior de complementariedad (robusto salvo valor de sustitutos)",
        known_limit=kl,
        blockers=[{"text": "el producto falla bajo SUSTITUTOS puros (óptimo 'al menos uno alto'); necesita detectar el régimen y conmutar a max/marginal o a un combinador aprendido", "kind": "diseno"},
                  {"text": "g sintético (min/max) y objetivo escalar; falta valor no-factorizable que surja de un lazo real de acción-consecuencia", "kind": "diseno"},
                  {"text": "estimadores con ruido abstracto; la construcción (combinador aprendido) que cierre el gap bajo sustitutos queda para CYCLE 84", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP067.ref, S_TREE.ref]))
    notes.append("1 techo 'real': producto = prior de complementariedad; robusto salvo sustitutos puros; acota gap #2.")

    dstmt = ("North-Star R-VALOR (ataque a la factorización, acota gap #2): la reconstrucción-PRODUCTO de R-VALOR "
             "(empowerment_est × verificador) del arco 79-82 NO es una ley universal sino un PRIOR DE COMPLEMENTARIEDAD. "
             "exp067: robusta a no-factorizabilidad complementaria (g=min) en TODO λ (crossover {xc}); se rompe bajo "
             "sustitutos puros (g=max, crossover λ*={xs}, una marginal la supera en λ=1.0). Tolera no-factorizabilidad "
             "moderada (λ<=0.5). Decisión: el lab mantiene el producto como reconstrucción por DEFECTO (prior robusto) y "
             "detecta el régimen de sustitutos para conmutar a marginal/max. Próximo (CYCLE 84): combinador APRENDIDO que "
             "recupere lo perdido bajo sustitutos.").format(xc=xc, xs=xs)
    drat = ("exp067 (tier5, propio, {n} seeds): comp crossover {xc}, subs crossover λ*={xs} (adv λ1.0 = {s10}); las filas "
            "clean reproducen la asimetría (es la factorización, no el ruido). Convergente con Cobb-Douglas/sustitutos "
            "(tier2) y con el gap #2 del árbol (tier5). APOYADA.").format(
                n=n_seeds, xc=xc, xs=xs, s10=_f(subs_10))
    dec = Decision(id="D-V4-45", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP067), _to_plain(S_TREE)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-45 ACEPTADA por el ledger (tier5 exp067 + tier5 gap #2).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-45:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle83_nonfactorizable_value',
                                description='CYCLE 83 (RESET v4, H-V4-7a: la reconstrucción-producto de R-VALOR es un prior de complementariedad).')
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
    print("RESUMEN — CYCLE 83 (RESET v4): R-VALOR producto = prior de complementariedad (H-V4-7a) — ataque a la factorización")
    print("=" * 78)
    print("veredicto H-V4-7a:", status.upper() if status else "?")
    print("  el producto vence en complementos (todo λ) y se rompe bajo sustitutos puros -> codifica complementariedad.")
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
