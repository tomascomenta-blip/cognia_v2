r"""
cycle35_endogenous_value.py — CICLO 35 a través del Investigation Engine (RESET v4, frente R-VALOR).

H-V4-1: un VALOR ENDÓGENO (info-gain sobre el propio modelo, sin verificador externo de la verdad)
construye una representación más causal que la predicción PASIVA, visible bajo INTERVENCIÓN.

DERIVA el veredicto de exp022_endogenous_value/results/results.json y lo pasa por las compuertas:
EvidenceLedger (fuentes + decisión fundada), HypothesisRegistry (DoD), analogy (7 etapas),
CeilingTracker (real/asumido), PermanentRecord (verify_no_loss).

RESULTADO REAL (exp022, 24 seeds): MIXTA.
  - R-INTERVENCIÓN demostrada limpiamente: la política PASIVA (A) se queda PLANA bajo intervención por
    más presupuesto que reciba (~0.65-0.69, flatness ~0.013) = muro INFORMACIONAL, no de recursos;
    mientras las políticas ACTIVAS (B info-gain, C azar) identifican la causa (->1.0). B-A=+0.31.
  - El gap es INVISIBLE i.i.d. (|A-B|~0.04): solo aparece bajo intervención.
  - R-VALOR específico NO aislado: el AZAR-activo (C) también lo logra con presupuesto suficiente y le
    empata/gana a info-gain a presupuesto chico (B-C ~ -0.007) => este experimento NO separa "valor
    info-gain" de "intervención activa". Genera la hija H-V4-1b.

Correr (DESPUÉS de exp022):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp022_endogenous_value.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle35_endogenous_value
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
                             'cycle35_endogenous_value')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp022_endogenous_value', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _fmt(x):
    return "{:.3f}".format(x) if isinstance(x, (int, float)) else str(x)


# ── fuentes (sin citas inventadas; las externas NO se re-obtuvieron esta sesión -> obtained=False) ──
S_PEARL = Source(tier=2, ref="Pearl 2009, Causality (2nd ed., Cambridge Univ. Press)", obtained=False,
                 claim=("Identificabilidad causal: la dirección causa->efecto NO se recupera de datos "
                        "puramente OBSERVACIONALES; requiere intervención do(X) o variación de "
                        "distribución. (Conocimiento previo, no re-obtenido esta sesión.)"))
S_BALD = Source(tier=1, ref="arXiv:1112.5745 (Houlsby et al. 2011, BALD)", obtained=False,
                claim=("Active learning bayesiano por information-gain: elegir la consulta que maximiza "
                       "la información esperada sobre el posterior del modelo. Es un VALOR endógeno de "
                       "exploración. (Conocimiento previo, no re-obtenido esta sesión.)"))
S_EXP017 = Source(tier=5, ref="cognia_x/experiments/exp017_noisy_verifier", obtained=True,
                  claim=("exp017 (propio): el lab demostró que un verificador EXTERNO ejecutable funciona "
                         "(dose-response net +0.116->-0.001, eps*~0.15). En 34 ciclos NUNCA se probó un "
                         "valor ENDÓGENO -> exp022 ataca ese hueco."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    s = data.get('summary')
    if not s or 'verdict' not in s:
        raise SystemExit("results.json sin summary.verdict (corre exp022 primero): " + results_path)
    status = s['verdict']
    bb = s['by_budget']
    Kmax = str(max(s['budgets']))
    A_max = bb[Kmax]['A_pasivo']['interv_mean']
    B_max = bb[Kmax]['B_infogain']['interv_mean']
    C_max = bb[Kmax]['C_aleatorio']['interv_mean']
    dv = s['diag_values']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    S_EXP022 = Source(tier=5, ref="cognia_x/experiments/exp022_endogenous_value", obtained=True,
                      claim=("exp022 (propio, CPU, numpy, 24 seeds, mundo causal confundido): bajo "
                             "INTERVENCIÓN la política PASIVA queda PLANA en ~{a} por más presupuesto "
                             "(flatness {fl}); las ACTIVAS (info-gain {b}, azar {c}) identifican la causa. "
                             "Gap invisible i.i.d. (|A-B| {ig}). info-gain NO supera al azar de forma "
                             "consistente (B-C a K chico {ve}).").format(
                                 a=_fmt(A_max), fl=_fmt(dv['A_flatness_Kmid->Kmax']), b=_fmt(B_max),
                                 c=_fmt(C_max), ig=_fmt(dv['iid_gap_Kmid']), ve=_fmt(dv['value_edge_lowK(B-C)'])))
    for src in (S_PEARL, S_BALD, S_EXP017, S_EXP022):
        ledger.add_source(src)
    notes.append("4 fuentes (S_PEARL tier2 identificabilidad; S_BALD tier1 info-gain; S_EXP017 tier5 "
                 "verificador-externo; S_EXP022 tier5 dato propio).")

    # ── Hipótesis H-V4-1 con DoD completo ──
    ev_for = [S_EXP022.ref, S_PEARL.ref]                # activa>>pasiva bajo intervención, muro informacional
    ev_against = [S_EXP022.ref, S_EXP017.ref]           # (a) invisibilidad i.i.d.; (b) azar-activo basta;
    #                                                      (c) lab solo tiene valor externo, no endógeno aislado
    adv = ("MIXTA. APOYADO: una política ENDÓGENA-ACTIVA (info-gain) construye un modelo causal que la "
           "PASIVA no puede; A queda PLANA bajo intervención por más presupuesto (muro INFORMACIONAL, no "
           "de recursos; flatness ~{fl}), B-A=+{ba} a Kmax, gap INVISIBLE i.i.d. (|A-B|~{ig}). "
           "NO AISLADO (lo que lo vuelve MIXTA, no apoyada): el AZAR-activo (C) también identifica la causa "
           "con presupuesto suficiente y empata/gana a info-gain a presupuesto chico (B-C~{ve}), así que "
           "exp022 demuestra R-INTERVENCIÓN (intervenir>observar) pero NO separa 'valor info-gain' de "
           "'intervención activa per se'. Ataque considerado: 'quizá el pasivo identifica con más datos' "
           "-> REFUTADO por la planitud de A en K. Hija: H-V4-1b (aislar VALOR en régimen "
           "presupuesto-chico/ruido-alto/espacio-grande).").format(
               fl=_fmt(dv['A_flatness_Kmid->Kmax']), ba=_fmt(dv['B_minus_A_Kmax']),
               ig=_fmt(dv['iid_gap_Kmid']), ve=_fmt(dv['value_edge_lowK(B-C)']))

    hyp = Hypothesis(
        id="H-V4-1",
        statement=("Un valor ENDÓGENO (info-gain sobre el propio modelo, sin verificador externo) construye "
                   "una representación más causal que la predicción PASIVA, visible bajo INTERVENCIÓN."),
        prediction=("i.i.d. A~=B (gap invisible); bajo intervención A queda PLANA en K (muro informacional) y "
                    "B la supera por >0.20. REFUTADA si A alcanza a B con más presupuesto (<0.05) o B no "
                    "supera a A por >0.20."),
        status='abierta', confidence='media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=adv, experiment_ref="exp022_endogenous_value")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-1")
        notes.append("H-V4-1 marcada '{}' con DoD completo.".format(status))

    # ── analogía de 7 etapas ──
    analogy = AnalogyRecord(
        problem=("Todo está correlacionado: el interruptor y la sombra de la cortina suben SIEMPRE juntos. "
                 "¿Cuál ENCIENDE la luz? Mirando no se sabe."),
        everyday=("Dos chicos aprenden qué prende la luz. Uno solo MIRA el cuarto (ve interruptor y sombra "
                  "moverse juntos). El otro TOCA el interruptor con la cortina quieta — interviene."),
        solutions=["El que solo mira NUNCA distingue interruptor de cortina (suben juntos) -> confundido por "
                   "más que mire = muro informacional (es A pasivo).",
                   "El que toca cosas AL AZAR eventualmente prueba el interruptor con la cortina quieta y "
                   "descubre, pero gasta intentos (es C azar-activo).",
                   "El que toca lo que MÁS DUDA (curiosidad dirigida = info-gain) descubre con menos "
                   "intentos... pero si hay tiempo, el azar también alcanza (es B info-gain).",
                   "Que un adulto le DIGA cuál es = verificador externo (lo que el lab ya sabía, exp017); "
                   "aquí NO se usa: el único feedback es la consecuencia de tocar."],
        principles=["intervenir (actuar) revela causa que observar NO puede: es un límite INFORMACIONAL, "
                    "no de cuánto mires/cuánta capacidad tengas",
                    "el motor demostrado es ACTUAR/INTERVENIR; la curiosidad dirigida (valor) solo recorta "
                    "intentos cuando el tiempo/presupuesto es escaso",
                    "el valor ENDÓGENO (reducir mi propia duda) no necesita un oráculo externo de la verdad",
                    "separar 'valor' de 'actividad' exige un régimen donde el azar NO alcance (poco "
                    "presupuesto, mucho ruido, espacio grande)"],
        adaptation=("El reset v4 adopta ACTUAR/INTERVENIR como motor verificado (R-INTERVENCIÓN). R-VALOR "
                    "específico queda ABIERTO: H-V4-1b debe aislar info-gain vs azar donde el presupuesto "
                    "obligue a ser eficiente."),
        measurement=("exp022: A plano ~{a} (flatness {fl}); B/C ->{b}/{c}; B-A=+{ba}; |A-B| i.i.d. {ig}; "
                     "B-C(K chico) {ve}.").format(
                         a=_fmt(A_max), fl=_fmt(dv['A_flatness_Kmid->Kmax']), b=_fmt(B_max), c=_fmt(C_max),
                         ba=_fmt(dv['B_minus_A_Kmax']), ig=_fmt(dv['iid_gap_Kmid']),
                         ve=_fmt(dv['value_edge_lowK(B-C)'])),
        iterations=1)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (interruptor/cortina: intervenir vs mirar).")

    # ── techo: R-VALOR endógeno sigue ASUMIDO; R-INTERVENCIÓN pasa a real ──
    ceilings.add(CeilingRecord(
        subsystem="R-VALOR — función de valor ENDÓGENA (qué información importa, sin meta externa)",
        known_limit=("ABIERTO: exp022 muestra que ACTUAR>observar (R-INTERVENCIÓN, informacional) pero NO "
                     "aísla que un VALOR endógeno (info-gain) sea el lever vs el azar-activo. Que un valor "
                     "AUTO-GENERADO (homeostasis/autopoiesis/empowerment), y no solo una meta de exploración "
                     "DISEÑADA por nosotros, sea construible y supere al azar sigue SIN demostrarse."),
        blockers=[{"text": "info-gain es un objetivo de exploración DISEÑADO, no una teleología auto-generada", "kind": "diseno"},
                  {"text": "el azar-activo iguala al info-gain con presupuesto suficiente: falta un régimen que obligue a ser eficiente para aislar el VALOR", "kind": "diseno"},
                  {"text": "en 34 ciclos el lab solo demostró valor EXTERNO (exp017); el endógeno nunca se probó", "kind": "historico"}],
        real_or_assumed="asumido", evidence=[S_EXP022.ref, S_EXP017.ref]))
    ceilings.add(CeilingRecord(
        subsystem="R-INTERVENCIÓN — identificar causa requiere variación de distribución (do/shift)",
        known_limit=("REAL (medido en exp022): una política PASIVA sobre un corpus confundido se queda PLANA "
                     "bajo intervención por más presupuesto que reciba (flatness ~{fl}); solo políticas que "
                     "INTERVIENEN cruzan a ~1.0. Es un límite INFORMACIONAL (la dirección causal no está en "
                     "lo observacional), no de capacidad ni de datos.").format(fl=_fmt(dv['A_flatness_Kmid->Kmax'])),
        blockers=[{"text": "la dirección causal no está contenida en datos puramente observacionales (identificabilidad)", "kind": "fisico"},
                  {"text": "sin acción/intervención no hay señal que rompa la simetría causa-espuria", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP022.ref, S_PEARL.ref]))
    notes.append("2 techos: R-VALOR 'asumido' (backlog de refutación -> H-V4-1b); R-INTERVENCIÓN 'real' (medido).")

    # ── decisión fundada ──
    dstmt = ("El reset v4 adopta R-VALOR como North Star del laboratorio (qué información importa, generado "
             "por el propio sistema), y como PRIMER motor verificado adopta ACTUAR/INTERVENIR (R-INTERVENCIÓN, "
             "medido en exp022: intervenir rompe el muro informacional que observar no puede). El siguiente "
             "ciclo (H-V4-1b) debe AISLAR el valor info-gain del azar-activo en un régimen "
             "presupuesto-chico/ruido-alto/espacio-grande; en paralelo H-V4-2 formaliza la identificabilidad "
             "sin cuerpo. La tesis previa (bytes-por-token/híbrido) se conserva como restricción de VIABILIDAD "
             "(todo corre en CPU finita), NO como dirección a la raíz.")
    drat = ("exp022 (tier5 propio): A pasivo plano ~{a} bajo intervención (flatness {fl}), B/C activos ->{b}/{c}, "
            "B-A=+{ba}, gap invisible i.i.d. {ig}. R-INTERVENCIÓN demostrada; R-VALOR específico abierto "
            "(B-C~{ve}). Coherente con la convergencia del árbol v4 (5/6 lentes -> R-VALOR; intervención/shift "
            "como condición de identificabilidad).").format(
                a=_fmt(A_max), fl=_fmt(dv['A_flatness_Kmid->Kmax']), b=_fmt(B_max), c=_fmt(C_max),
                ba=_fmt(dv['B_minus_A_Kmax']), ig=_fmt(dv['iid_gap_Kmid']), ve=_fmt(dv['value_edge_lowK(B-C)']))
    dec = Decision(id="D-V4-1", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP022), _to_plain(S_EXP017)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-1 ACEPTADA por el ledger (tier5 exp022 + tier5 exp017).")
    except OpinionOnlyError as e:
        print("ERROR ledger D-V4-1:", e); raise

    return record, notes, status, s


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle35_endogenous_value',
                                description='CYCLE 35 (RESET v4, H-V4-1: valor endógeno vs predicción pasiva).')
    p.add_argument('--store', default=DEFAULT_STORE)
    p.add_argument('--results', default=DEFAULT_RESULTS)
    p.add_argument('--reset', dest='reset', action='store_true', default=True)
    p.add_argument('--no-reset', dest='reset', action='store_false')
    args = p.parse_args(argv)
    store = os.path.abspath(args.store)
    if args.reset and os.path.isdir(store):
        shutil.rmtree(store)
    os.makedirs(store, exist_ok=True)
    record, notes, status, s = run(store, os.path.abspath(args.results))
    res = record.verify_no_loss()
    print("=" * 78)
    print("RESUMEN — CYCLE 35 (RESET v4): valor endógeno vs predicción pasiva (H-V4-1)")
    print("=" * 78)
    print("veredicto H-V4-1:", status.upper() if status else "?")
    print("  " + s.get('interpretation', ''))
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
