r"""
cycle79_empowerment_limits.py — CICLO 79 (RESET v4, PIVOTE: abre la rama R-CONTROL): H-V4-6a por las compuertas del
engine. Test ADVERSARIAL de empowerment-como-valor. MIXTA: el empowerment es un PROXY PARCIAL del valor (la
marginal-de-controlabilidad), no un valor endógeno UNIVERSAL ni inútil. Recupera exp024/025 cuando lo controlable
coincide con lo útil, pero degrada al desalinearse (malgasta en lo controlable-inútil, simétrico a la predicción en
lo predecible-inútil). UNIFICA el rival CONTESTADO del árbol bajo R-VALOR (referido al objetivo).

DERIVA de exp063_empowerment_limits/results/results.json. Abre la rama que el árbol marcaba como la "faltante más
grande" (inteligencia=control/acción) y la acota honestamente -- la corrida la había aceptado (CYCLE 38/39) sin
este test.

Correr (DESPUÉS de exp063):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp063_empowerment_limits.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle79_empowerment_limits
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle79_empowerment_limits')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp063_empowerment_limits', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_EMP = Source(tier=1, ref="empowerment / intrinsic motivation (Klyubin et al. 2005; channel capacity action->future)", obtained=False,
               claim=("El empowerment es la capacidad de canal entre las acciones y los estados futuros: un objetivo "
                      "INTRÍNSECO que maximiza la CONTROLABILIDAD sin referencia a recompensa. Propuesto como valor "
                      "universal libre de objetivo. (Principio del rival control/acción.)"))
S_TREE = Source(tier=5, ref="cognia_x/manager/decomposition_tree.md (rival CONTESTADO control/empowerment; exp024/025)", obtained=True,
                claim=("El árbol marca 'inteligencia=control/acción (empowerment)' como la rama CONTESTADA / faltante "
                       "más grande. CYCLE 38/39 (exp024/025) ACEPTARON empowerment>predicción como valor, pero sólo "
                       "donde lo controlable era útil. H-V4-6a hace el test adversarial que faltaba."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp063 primero): " + results_path)
    hi, lo, rl, swing = sm['emp_high_rho'], sm['emp_low_rho'], sm['random_low_rho'], sm['swing']
    n, k = data['args']['n'], data['args']['k']
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim063 = ("exp063 (propio, {n} seeds, numpy): asignación de capacidad k/{N}, valor=ctrl×rel, sweep de "
                "correlación control↔relevancia. empowerment (top-k por ctrl) captura del óptimo: rho=1 {hi} "
                "(recupera exp024/025), rho=0 {lo} (vs random {rl}), monótono decreciente (swing {sw}). El "
                "empowerment es un PROXY PARCIAL: la marginal-de-controlabilidad del valor, no el valor.").format(
                    n=n_seeds, N=n, hi=_f(hi), lo=_f(lo), rl=_f(rl), sw=_f(swing))
    S_EXP063 = Source(tier=5, ref="cognia_x/experiments/exp063_empowerment_limits", obtained=True, claim=claim063)
    for src in (S_EMP, S_TREE, S_EXP063):
        ledger.add_source(src)
    notes.append("3 fuentes (S_EMP tier1 empowerment/intrinsic-motivation; S_TREE tier5 rival contestado + exp024/25; S_EXP063 tier5 dato propio).")

    ev_for = [S_EXP063.ref, S_TREE.ref]       # apoya que empowerment ES un valor parcial (recupera exp024/25 en rho=1)
    ev_against = [S_EXP063.ref]               # refuta que sea UNIVERSAL (degrada, le falta relevancia)
    adv = ("{V} (PIVOTE: abre la rama R-CONTROL y acota el rival CONTESTADO bajo R-VALOR): el árbol marca el "
           "empowerment como la rama faltante más grande y la corrida lo ACEPTÓ (CYCLE 38/39) sin el test adversarial. "
           "exp063 lo hace: con valor=ctrl×rel y un sweep de correlación control↔relevancia, el empowerment (top-k por "
           "ctrl) captura del óptimo {hi} cuando control≈valor (rho=1, RECUPERA exp024/025: lo controlable ES lo útil) "
           "y degrada MONÓTONO al desalinearse hasta {lo} en rho=0 (random {rl}), {lo2} con control ANTI-valor. "
           "MATIZ FINO (más honesto que el pre-registro APOYADA): el empowerment NO colapsa a random aun con "
           "control ⊥ relevancia, porque la controlabilidad ES un componente multiplicativo del valor (ctrl×rel) -- "
           "el empowerment captura SIEMPRE el factor ctrl, le falta el factor REL. Es un PROXY PARCIAL = la "
           "marginal-de-controlabilidad de R-VALOR, no un valor universal ni inútil. EVIDENCIA A FAVOR (de que es un "
           "valor REAL parcial): recupera el óptimo cuando control=valor (consistente con exp024/025). EVIDENCIA EN "
           "CONTRA (de que sea UNIVERSAL): degrada al desalinearse; le falta la relevancia. CONCLUSIÓN: ni control "
           "(empowerment) ni predicción PURO es el valor universal -- la predicción malgasta en lo predecible-inútil "
           "(exp024), el empowerment en lo controlable-inútil (exp063, simétrico); el general es R-VALOR (referido al "
           "OBJETIVO), del que ambos son MARGINALES/proxies. Resuelve el rival contestado: empowerment es un COMPONENTE "
           "de R-VALOR, no su reemplazo. CAVEAT: juguete (selección estática, valor multiplicativo ctrl×rel asumido); "
           "falta empowerment ESTIMADO online y un objetivo no-escalar.").format(
               V=status.upper(), hi=_f(hi), lo=_f(lo), rl=_f(rl),
               lo2=_f(data['summary']['by_rho'].get('-0.5', {}).get('empowerment', lo)))

    hyp = Hypothesis(
        id="H-V4-6a",
        statement=("El empowerment NO es un valor endógeno universal: rinde sólo cuando lo controlable coincide con lo "
                   "útil; al desalinearse malgasta en lo controlable-inútil (simétrico a la predicción en lo "
                   "predecible-inútil). El general es R-VALOR (referido al objetivo)."),
        prediction=("APOYADA si empowerment recupera el óptimo con control≈valor (rho=1>=0.85) Y colapsa cerca de "
                    "random con control ⊥ valor (rho=0) con swing>0.25; REFUTADA si ~oracle para todo rho (universal); "
                    "MIXTA si depende del régimen pero no colapsa/recupera limpio en los extremos. (Pre-registrada.)"),
        status='abierta', confidence='media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=adv, experiment_ref="exp063_empowerment_limits")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-6a")
        notes.append("H-V4-6a marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("Te dicen: 'enfocate en lo que PODÉS cambiar' (empowerment). ¿Es siempre buen consejo, aunque lo "
                 "que podés cambiar no sirva para tu objetivo?"),
        everyday=("Es buen consejo SÓLO si lo que podés cambiar coincide con lo que te importa. Si dedicás tu energía "
                  "a cosas que controlás pero que no te acercan a tu meta (mover una palanca que no hace nada), "
                  "malgastás -- igual que el que se obsesiona con PREDECIR cosas inútiles. Lo que sirve es enfocarte "
                  "en lo que podés cambiar Y te importa (control × relevancia). 'Lo que podés cambiar' es la mitad de "
                  "la historia: captura parte del valor, le falta '¿para qué sirve?'."),
        solutions=["empowerment (top-k por controlabilidad) -> recupera el óptimo si control=valor; parcial si no",
                   "oracle_value (top-k por ctrl×rel) -> el valor completo (referido al objetivo)",
                   "predicción (exp024) -> malgasta en lo predecible-inútil (simétrico al empowerment)",
                   "R-VALOR = ctrl×rel -> el general; empowerment y predicción son marginales/proxies"],
        principles=["el empowerment es la marginal-de-controlabilidad del valor, no el valor universal",
                    "ni control ni predicción puro es el valor: ambos malgastan cuando su target diverge del objetivo",
                    "el valor general es R-VALOR (referido al objetivo/recompensa); empowerment es un componente",
                    "la controlabilidad ES parte del valor (multiplicativa) -> empowerment nunca es inútil, pero es incompleto"],
        adaptation=("El lab trata el empowerment como un COMPONENTE de R-VALOR (la marginal de controlabilidad), no "
                    "como valor universal. Próximo: empowerment ESTIMADO online (¿sobrevive como en la memoria 72?); "
                    "combinar empowerment (control) con relevancia estimada para reconstruir R-VALOR sin oráculo; "
                    "objetivo no-escalar."),
        measurement=("exp063 (k={k}/{N}): empowerment captura del óptimo rho=1 {hi}, rho=0 {lo} (random {rl}), swing "
                     "{sw} monótono. {n} seeds.").format(k=k, N=n, hi=_f(hi), lo=_f(lo), rl=_f(rl), sw=_f(swing), n=n_seeds),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada ('enfocate en lo que podés cambiar' sirve sólo si coincide con lo que importa).")

    kl = ("REAL (exp063): el empowerment es un PROXY PARCIAL del valor (la marginal-de-controlabilidad), no universal. "
          "Captura del óptimo {hi} con control≈valor (recupera exp024/025) y degrada monótono a {lo} (random {rl}) al "
          "desalinearse; le falta el componente de RELEVANCIA. Ni control ni predicción puro es el valor; el general "
          "es R-VALOR (referido al objetivo); empowerment y predicción son sus marginales.").format(
              hi=_f(hi), lo=_f(lo), rl=_f(rl))
    ceilings.add(CeilingRecord(
        subsystem="R-CONTROL (empowerment) acotado bajo R-VALOR — empowerment = marginal-de-controlabilidad, no valor universal",
        known_limit=kl,
        blockers=[{"text": "empowerment captura sólo el factor controlabilidad (valor=ctrl×rel); le falta la relevancia -> incompleto cuando control != valor", "kind": "diseno"},
                  {"text": "juguete: selección estática, valor multiplicativo ctrl×rel asumido; falta empowerment ESTIMADO online y objetivo no-escalar", "kind": "diseno"},
                  {"text": "la corrida había aceptado empowerment como valor (CYCLE 38/39) sin este test adversarial -> sesgo corregido", "kind": "historico"}],
        real_or_assumed="real", evidence=[S_EXP063.ref, S_TREE.ref]))
    notes.append("1 techo 'real': empowerment es la marginal-de-controlabilidad de R-VALOR, no el valor universal; acota el rival contestado.")

    dstmt = ("North-Star R-VALOR (PIVOTE: rama R-CONTROL acotada bajo R-VALOR): el empowerment NO es un valor endógeno "
             "universal -- es la MARGINAL-de-controlabilidad de R-VALOR. Recupera el óptimo cuando control≈valor "
             "(rho=1 {hi}, consistente con exp024/025) y degrada monótono a {lo} (random {rl}) al desalinearse, "
             "malgastando en lo controlable-inútil (simétrico a la predicción en lo predecible-inútil, exp024). "
             "Decisión: el lab trata empowerment Y predicción como MARGINALES/proxies de R-VALOR (ctrl×rel, referido "
             "al objetivo), no como valores universales. Resuelve el rival CONTESTADO del árbol: empowerment es un "
             "COMPONENTE de R-VALOR, no su reemplazo. Próximo: empowerment estimado online; reconstruir R-VALOR "
             "combinando control + relevancia estimada.").format(hi=_f(hi), lo=_f(lo), rl=_f(rl))
    drat = ("exp063 (tier5, propio, {n} seeds): empowerment captura del óptimo rho=1 {hi} (recupera exp024/025), "
            "degrada monótono a rho=0 {lo} (random {rl}), swing {sw}. Convergente con empowerment/intrinsic-motivation "
            "(tier1) acotado. MIXTA.").format(n=n_seeds, hi=_f(hi), lo=_f(lo), rl=_f(rl), sw=_f(swing))
    dec = Decision(id="D-V4-41", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP063), _to_plain(S_TREE)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-41 ACEPTADA por el ledger (tier5 exp063 + tier5 rival contestado).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-41:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle79_empowerment_limits',
                                description='CYCLE 79 (RESET v4, H-V4-6a: test adversarial de empowerment -- abre rama R-CONTROL).')
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
    print("RESUMEN — CYCLE 79 (RESET v4): test adversarial de empowerment (H-V4-6a) — abre rama R-CONTROL")
    print("=" * 78)
    print("veredicto H-V4-6a:", status.upper() if status else "?")
    print("  empowerment = marginal-de-controlabilidad de R-VALOR; valor universal sólo si control=valor.")
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
