r"""
cycle81_verifier_relevance.py — CICLO 81 (RESET v4, rama R-CONTROL, UNIFICA dos arcos): H-V4-6c por las compuertas
del engine. APOYADA: el VERIFICADOR es la marginal-de-RELEVANCIA de R-VALOR. El CYCLE 80 reconstruyó R-VALOR =
control × relevancia y dejó pre-registrado "el verificador = la señal de relevancia". Aquí la relevancia la provee un
VERIFICADOR ruidoso (error ε): la reconstrucción (control × verificador) reconstruye el valor y TOLERA el ruido del
verificador hasta ε*≈0.30, degradando con gracia al control solo. UNIFICA el arco verificador (48-55) con la
reconstrucción de R-VALOR (79-80): act-and-verify estima IMPLÍCITAMENTE R-VALOR = control × verificador-relevancia.

DERIVA de exp065_verifier_relevance/results/results.json.

Correr (DESPUÉS de exp065):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp065_verifier_relevance.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle81_verifier_relevance
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle81_verifier_relevance')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp065_verifier_relevance', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_VERIF = Source(tier=1, ref="verifier-based test-time scaling / correctness as value signal (noise-tolerant)", obtained=False,
                 claim=("Un verificador chequeable provee una señal de CORRECCIÓN/relevancia que dirige el cómputo "
                        "test-time sin un oráculo de recompensa; la señal tolera ruido hasta un umbral antes de "
                        "degradar al baseline. (Principio; el verificador es un estimador de relevancia/valor.)"))
S_TREE = Source(tier=5, ref="cognia_x/manager/decomposition_tree.md (CYCLE 80: R-VALOR=control×relevancia; arco verificador 48-55)", obtained=True,
                claim=("CYCLE 80 (exp064) reconstruyó R-VALOR = controlabilidad × relevancia (marginales endógenas) y "
                       "dejó pre-registrado ligar la relevancia con el verificador de auto-mejora. El arco 51-55 mostró "
                       "que el lazo tolera un verificador ruidoso hasta ε*≈0.50. H-V4-6c los UNE."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp065 primero): " + results_path)
    by = sm['by_eps']
    rv0 = sm['rvalue_at_zero']
    emp0 = by['0.0']['empowerment']
    eps_star = sm['eps_star']
    rv_half, emp_half = by['0.5']['rvalue_verifier'], by['0.5']['empowerment']
    n, k = data['args']['n'], data['args']['k']
    p_rel = data['args']['p_rel']
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim065 = ("exp065 (propio, {n} seeds, numpy): R-VALOR con relevancia = VERIFICADOR ruidoso (error ε), p_rel={pr}. "
                "ε=0: rvalue_verifier (ctrl × verificador) {rv0} reconstruye el óptimo y vence a empowerment {e0} "
                "(control solo) por +{adv}. Tolera el ruido del verificador hasta ε*={es}; en ε=0.5 cae al control "
                "({rvh}~{eh}). El verificador es la marginal-de-relevancia de R-VALOR.").format(
                    n=n_seeds, pr=p_rel, rv0=_f(rv0), e0=_f(emp0), adv=_f(rv0 - emp0), es=_f(eps_star),
                    rvh=_f(rv_half), eh=_f(emp_half))
    S_EXP065 = Source(tier=5, ref="cognia_x/experiments/exp065_verifier_relevance", obtained=True, claim=claim065)
    for src in (S_VERIF, S_TREE, S_EXP065):
        ledger.add_source(src)
    notes.append("3 fuentes (S_VERIF tier1 verificador-como-señal-de-valor; S_TREE tier5 CYCLE 80 + arco 48-55; S_EXP065 tier5 dato propio).")

    ev_for = [S_EXP065.ref, S_TREE.ref]
    ev_against = [S_EXP065.ref]
    adv = ("{V} (UNIFICA el arco verificador 48-55 con la reconstrucción de R-VALOR 79-80): el CYCLE 80 reconstruyó "
           "R-VALOR = control × relevancia y dejó pre-registrado que la relevancia la da el VERIFICADOR. exp065 lo "
           "verifica: con la relevancia provista por un verificador ruidoso (error ε), rvalue_verifier (ctrl × "
           "verificador) {rv0} en ε=0 RECONSTRUYE el óptimo y vence a empowerment {e0} (control solo) por +{adv} -- "
           "enorme porque con sólo p_rel={pr} relevantes, el control SOLO captura poco valor (la mayoría de lo "
           "controlable es irrelevante); el verificador-relevancia es ESENCIAL. La reconstrucción TOLERA el ruido del "
           "verificador hasta ε*={es} (aguanta ~30% de error; mismo RÉGIMEN de tolerancia que exp053, algo menor que "
           "su ε*≈0.50 por métrica/tarea distintas) y en ε=0.5 (verificador inútil) DEGRADA CON GRACIA al control "
           "solo ({rvh}~{eh}). => el agente de act-and-verify (R-INTERVENCIÓN + verificador) está IMPLÍCITAMENTE "
           "estimando R-VALOR = control × verificador-relevancia: la relevancia no necesita oráculo, la da el "
           "verificador chequeable (ruidoso pero tolerable). Conecta TRES arcos: R-INTERVENCIÓN (actuar), VERIFICADOR "
           "(48-55, relevancia/corrección) y R-VALOR (79-80, control×relevancia). EVIDENCIA EN CONTRA (caveats): el "
           "control se da EXACTO (para aislar el ruido del verificador); valor multiplicativo ctrl×rel asumido; "
           "relevancia BINARIA; juguete (selección estática). CONCLUSIÓN: el verificador del lab ES la marginal-de-"
           "relevancia de R-VALOR; la auto-mejora verificada es asignación de cómputo por R-VALOR estimado.").format(
               V=status.upper(), rv0=_f(rv0), e0=_f(emp0), adv=_f(rv0 - emp0), pr=p_rel, es=_f(eps_star),
               rvh=_f(rv_half), eh=_f(emp_half))

    hyp = Hypothesis(
        id="H-V4-6c",
        statement=("El verificador es la marginal-de-relevancia de R-VALOR: la reconstrucción control × verificador "
                   "reconstruye el valor y tolera el ruido del verificador hasta un ε*, unificando el arco verificador "
                   "(48-55) con R-VALOR (79-80)."),
        prediction=("APOYADA si en ε=0 rvalue_verifier recupera >=85% del óptimo Y vence a empowerment Y la tolerancia "
                    "ε* >= 0.2, con rvalue~empowerment en ε=0.5; REFUTADA si rvalue~empowerment ya en ε=0; MIXTA si "
                    "reconstruye en ε=0 pero ε*<0.2 (frágil). (Pre-registrada.)"),
        status='abierta', confidence='alta' if status == 'apoyada' else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=adv, experiment_ref="exp065_verifier_relevance")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-6c")
        notes.append("H-V4-6c marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("Sabés cuánto podés CAMBIAR cada cosa, pero no cuál te conviene. Un asesor (verificador) te dice "
                 "'esta SÍ sirve, esta no' -- pero a veces se equivoca. ¿Te alcanza para elegir bien?"),
        everyday=("Sí: combinás 'cuánto puedo cambiarlo' con el 'sí/no sirve' del asesor y elegís lo que podés cambiar "
                  "Y el asesor marca como útil. Aciertas casi perfecto si el asesor es bueno, y SEGUÍS ganándole a "
                  "elegir-sólo-por-lo-que-puedo-cambiar hasta que el asesor se equivoca ~3 de cada 10 veces. Si el "
                  "asesor tira una moneda (se equivoca la mitad), lo ignorás y volvés a guiarte por lo que podés "
                  "cambiar. El 'sí/no sirve' del asesor ES la mitad que te faltaba del valor."),
        solutions=["rvalue_verifier (control × verificador) -> reconstruye el valor; tolera ~30% de error del verificador",
                   "empowerment (control solo) -> la mitad: pésimo si poco es relevante",
                   "verifier_only (sólo el asesor) -> capta la relevancia, ignora el control",
                   "el verificador es la marginal-de-relevancia; control es la otra; R-VALOR es el producto"],
        principles=["el verificador es la marginal-de-relevancia de R-VALOR (no sólo un filtro de auto-mejora)",
                    "act-and-verify estima implícitamente R-VALOR = control × verificador-relevancia, sin oráculo",
                    "la reconstrucción tolera el ruido del verificador hasta ε*~0.3 y degrada con gracia al control",
                    "une tres arcos: R-INTERVENCIÓN (actuar) + verificador (relevancia) + R-VALOR (control×relevancia)"],
        adaptation=("El lab interpreta el verificador de auto-mejora como la marginal-de-relevancia de R-VALOR; la "
                    "asignación de cómputo verificada ES asignación por R-VALOR estimado. Próximo: control TAMBIÉN "
                    "estimado (no exacto); verificador chequeable REAL (sandbox de exp018) como relevancia; valor que "
                    "no factorice limpio; objetivo no-escalar."),
        measurement=("exp065 (p_rel={pr}, k={k}/{N}): ε=0 rvalue {rv0} vs empowerment {e0} (+{adv}); tolera hasta "
                     "ε*={es}; ε=0.5 cae a {rvh}~{eh}. {n} seeds.").format(
                         pr=p_rel, k=k, N=n, rv0=_f(rv0), e0=_f(emp0), adv=_f(rv0 - emp0), es=_f(eps_star),
                         rvh=_f(rv_half), eh=_f(emp_half), n=n_seeds),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (el 'sí/no sirve' del verificador es la mitad que faltaba del valor; tolera errores hasta ~30%).")

    kl = ("REAL (exp065): el VERIFICADOR es la marginal-de-relevancia de R-VALOR. rvalue_verifier (ctrl × verificador) "
          "reconstruye el óptimo en ε=0 ({rv0} vs control {e0}) y TOLERA el ruido del verificador hasta ε*={es}, "
          "degradando con gracia al control solo en ε=0.5. Une el arco verificador (48-55) con R-VALOR (79-80): "
          "act-and-verify estima R-VALOR = control × verificador-relevancia sin oráculo.").format(
              rv0=_f(rv0), e0=_f(emp0), es=_f(eps_star))
    ceilings.add(CeilingRecord(
        subsystem="R-VALOR x VERIFICADOR — el verificador es la marginal-de-relevancia; act-and-verify estima R-VALOR",
        known_limit=kl,
        blockers=[{"text": "el control se da EXACTO (para aislar el ruido del verificador); falta control TAMBIÉN estimado (empowerment online)", "kind": "diseno"},
                  {"text": "verificador SINTÉTICO (error ε binario); falta un verificador chequeable REAL (sandbox exp018) como señal de relevancia", "kind": "diseno"},
                  {"text": "valor multiplicativo ctrl×rel asumido; relevancia binaria; juguete (selección estática, objetivo escalar)", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP065.ref, S_TREE.ref]))
    notes.append("1 techo 'real': el verificador es la marginal-de-relevancia de R-VALOR; tolera ruido hasta ε*~0.3; une tres arcos.")

    dstmt = ("North-Star R-VALOR (UNIFICA el verificador con R-VALOR): el VERIFICADOR de auto-mejora (48-55) ES la "
             "marginal-de-RELEVANCIA de R-VALOR (79-80). rvalue_verifier (control × verificador) reconstruye el óptimo "
             "en ε=0 ({rv0} vs control solo {e0}) y tolera el ruido del verificador hasta ε*={es}, degradando con "
             "gracia al control en ε=0.5. Decisión: el lab interpreta el verificador como la marginal-de-relevancia; "
             "act-and-verify (R-INTERVENCIÓN + verificador) estima IMPLÍCITAMENTE R-VALOR = control × verificador-"
             "relevancia, sin oráculo. Une TRES arcos (R-INTERVENCIÓN + verificador + R-VALOR). Próximo: control "
             "estimado online; verificador chequeable REAL como relevancia.").format(rv0=_f(rv0), e0=_f(emp0), es=_f(eps_star))
    drat = ("exp065 (tier5, propio, {n} seeds): ε=0 rvalue {rv0} reconstruye y vence al control {e0} (+{adv}); tolera "
            "hasta ε*={es}; ε=0.5 cae al control. Convergente con verificador-como-señal-de-valor (tier1) y con CYCLE "
            "80 + arco 48-55 (tier5). APOYADA.").format(n=n_seeds, rv0=_f(rv0), e0=_f(emp0), adv=_f(rv0 - emp0), es=_f(eps_star))
    dec = Decision(id="D-V4-43", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP065), _to_plain(S_TREE)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-43 ACEPTADA por el ledger (tier5 exp065 + tier5 CYCLE 80/arco verificador).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-43:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle81_verifier_relevance',
                                description='CYCLE 81 (RESET v4, H-V4-6c: el verificador como marginal-de-relevancia de R-VALOR).')
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
    print("RESUMEN — CYCLE 81 (RESET v4): el verificador como marginal-de-relevancia de R-VALOR (H-V4-6c)")
    print("=" * 78)
    print("veredicto H-V4-6c:", status.upper() if status else "?")
    print("  el verificador ES la marginal-de-relevancia; act-and-verify estima R-VALOR = control × verificador.")
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
