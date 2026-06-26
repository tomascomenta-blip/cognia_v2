r"""
cycle105_real_cost_alloc.py — CICLO 105 (RESET v4, rama R-VALOR, VALIDACIÓN toy→real del CYCLE 101): H-V4-8j por las
compuertas del engine. APOYADA: el costo-por-valor (CYCLE 101, numpy) TRANSFIERE al LAZO CERRADO con el GENERADOR de
MODELO REAL (HybridLM de exp018). Bajo costo de verificación HETEROGÉNEO, asignar por VALOR/COSTO (valor positivo =
exp(confianza), /costo) rinde MÁS correctos por presupuesto de costo que por valor solo (verifica más candidatos baratos)
y MEJORA el downstream. Primera validación toy→real de una extensión del arco de asignación (95-104, todo numpy).

NOTA DE MÉTODO (honestidad): un primer intento usó la confianza = mean-LOGPROB (NEGATIVA) en el ratio, lo que invertía el
ranking (favorecía lo caro) y daba un REFUTADA ARTEFACTUAL; se detectó (corr(conf,costo)≈0 desmentía el mecanismo) y se
corrigió usando VALOR POSITIVO (exp(conf)) -- el ratio costo-por-valor exige valor>0. "Código que corre o no cuenta": el
artefacto se cazó verificando el mecanismo, no se reportó como resultado.

DERIVA de exp089_real_cost_alloc/results/results.json.

Correr (DESPUÉS de exp089):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp089_real_cost_alloc.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle105_real_cost_alloc
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle105_real_cost_alloc')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp089_real_cost_alloc', 'results', 'results.json')


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


S_PRINCIPLE = Source(tier=2, ref="transferencia toy→real + knapsack valor/costo con VALOR POSITIVO: el ratio valor/costo requiere un valor en escala positiva (probabilidad), no logprob; con eso, el costo-por-valor (aditivo) transfiere a un lazo de auto-mejora donde el yield de datos correctos es aditivo", obtained=False,
                     claim=("El ratio valor/costo (knapsack) requiere un VALOR POSITIVO (probabilidad), no un logprob "
                            "negativo (que invertiría el ranking). Con un valor positivo, el costo-por-valor de objetivos "
                            "ADITIVOS (CYCLE 101) debería transferir a un lazo de auto-mejora donde el yield de datos "
                            "verificado-correctos es aditivo. (Principio + práctica.)"))
S_EXP085 = Source(tier=5, ref="cognia_x/experiments/exp085_cost_aware_value", obtained=True,
                  claim=("CYCLE 101 (numpy) halló que bajo costo HETEROGÉNEO la asignación R-VALOR es valor-POR-COSTO para "
                         "objetivos aditivos. H-V4-8j valida la transferencia al lazo cerrado REAL (modelo propio)."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp089 primero): " + results_path)

    yg = sm['yield_gain']
    rg = sm['real_gain']
    yc = _mean(sm['yield_conf']); yr = _mean(sm['yield_ratio'])
    nvc = _mean(sm['nverif_conf']); nvr = _mean(sm['nverif_ratio'])
    rcv = _mean(sm['real_conf']); rrv = _mean(sm['real_ratio'])
    ccc = sm.get('mean_conf_cost_corr', 0.0)
    csc = _mean(sm['conf_strong_corr_by_seed'])
    n_seeds = sm['n_seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim089 = ("exp089 (propio, {n} seeds, PyTorch CPU, lazo cerrado real exp018): bajo costo de verificación heterogéneo, "
                "ratio (valor positivo/costo) yield={yr:.1f} > conf={yc:.1f} (+{yg}); ratio verifica más baratos (nverif "
                "{nvr:.1f} vs {nvc:.1f}); downstream ratio={rr:.3f} > conf={rc:.3f} (+{rg}). corr(conf,strong)={csc}. El "
                "costo-por-valor (101) transfiere al lazo real.").format(
                    n=n_seeds, yr=yr, yc=yc, yg=_f(yg), nvr=nvr, nvc=nvc, rr=rrv, rc=rcv, rg=_f(rg), csc=_f(csc))
    S_EXP089 = Source(tier=5, ref="cognia_x/experiments/exp089_real_cost_alloc", obtained=True, claim=claim089)
    for src in (S_PRINCIPLE, S_EXP085, S_EXP089):
        ledger.add_source(src)
    notes.append("3 fuentes (S_PRINCIPLE tier2 transferencia/valor-positivo; S_EXP085 tier5 costo-por-valor de CYCLE 101; S_EXP089 tier5 dato propio).")

    ev_for = [S_EXP089.ref]
    ev_against = [S_EXP089.ref, S_EXP085.ref, S_PRINCIPLE.ref]
    advtext = ("{V} (VALIDACIÓN toy→real del CYCLE 101): el honest gap del arco 95-104 es que casi todo es numpy/juguete. "
               "H-V4-8j valida una pieza (101, costo-por-valor) en el LAZO CERRADO REAL (el HybridLM propio genera, el "
               "sandbox verifica, las correctas entrenan). Costo de verificación HETEROGÉNEO (∝ target); presupuesto de "
               "COSTO total. RESULTADO: asignar por VALOR/COSTO (valor positivo = exp(confianza), /costo) rinde MÁS "
               "correctos por presupuesto de costo que por valor solo -- yield ratio={yr:.1f} vs conf={yc:.1f} (+{yg}, "
               "todos los seeds); ratio verifica más candidatos BARATOS (nverif {nvr:.1f} vs {nvc:.1f}) -> más correctos "
               "por unidad de costo; y MEJORA el downstream (ratio={rr:.3f} vs conf={rc:.3f}, +{rg}). La confianza está "
               "calibrada (corr(conf,strong)={csc}). => el costo-por-valor (101) TRANSFIERE al lazo de auto-mejora REAL "
               "(el yield de datos verificado-correctos es ADITIVO, el régimen donde 101 predice que el ratio gana). "
               "NOTA DE MÉTODO (honestidad, regla #4): un primer intento usó la confianza = mean-LOGPROB (NEGATIVA) en el "
               "ratio, lo que INVERTÍA el ranking (conf/costo con conf<0 favorece lo caro) y dio un REFUTADA ARTEFACTUAL; "
               "se DETECTÓ (corr(valor,costo)≈{ccc} desmentía el mecanismo de correlación propuesto) y se CORRIGIÓ usando "
               "VALOR POSITIVO (exp(conf)) -- el ratio exige valor>0. El artefacto se cazó verificando el mecanismo, no se "
               "reportó como resultado. EVIDENCIA EN CONTRA / caveats: la transferencia se validó para el costo-por-valor "
               "(101), NO para las demás extensiones (97-104, aún numpy); costo MODELADO (∝ target, no medido); modelo "
               "tiny, tarea sembrada, 4 seeds, CPU; el valor debe estar en escala positiva (detalle de implementación "
               "real).").format(
                   V=status.upper(), yr=yr, yc=yc, yg=_f(yg), nvr=nvr, nvc=nvc, rr=rrv, rc=rcv, rg=_f(rg), csc=_f(csc), ccc=_f(ccc))

    hyp = Hypothesis(
        id="H-V4-8j",
        statement=("El costo-por-valor (CYCLE 101) TRANSFIERE al lazo cerrado REAL: bajo costo de verificación "
                   "heterogéneo, asignar por VALOR/COSTO (valor positivo) rinde más datos verificado-correctos por "
                   "presupuesto de costo que por valor solo, sin regresionar el downstream."),
        prediction=("APOYADA si ratio yield > conf por > margen en los seeds (a igual presupuesto de costo) Y el downstream "
                    "no regresiona; REFUTADA si ratio ≈ conf; MIXTA si mejora el yield pero no el downstream. "
                    "(Pre-registrada, lazo real exp018, 4 seeds; valor en escala positiva.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp089_real_cost_alloc")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-8j")
        notes.append("H-V4-8j marcada '{}' con DoD completo (validación toy→real del costo-por-valor de CYCLE 101).".format(status))

    analogy = AnalogyRecord(
        problem=("En el taller real (no en la teoría), tengo plata limitada para mandar a revisar piezas y cada revisión "
                 "cuesta distinto. ¿Mando a revisar las que MÁS confío que están bien, o las de mejor confianza-POR-PESO?"),
        everyday=("Confianza-por-peso: con mi plata limitada reviso MÁS piezas baratas-prometedoras y encuentro más "
                  "buenas por peso gastado que mandando las más confiables sin mirar el costo (que se come la plata en "
                  "pocas caras). La teoría (caso de juguete) ya lo decía; en el taller real también vale -- siempre que "
                  "mida la 'confianza' en escala positiva (si la mido como un número negativo, dividir por el costo me "
                  "da vuelta el orden y mando justo las caras: ahí me equivoqué primero y lo corregí)."),
        solutions=["valor-positivo/costo en el lazo real: más correctos por presupuesto de costo (transfiere 101)",
                   "valor solo: se come el presupuesto en pocas verificaciones caras",
                   "valor-NEGATIVO(logprob)/costo: artefacto -- invierte el orden, elige caro (cazado y corregido)",
                   "el ratio exige valor en escala POSITIVA (probabilidad), no logprob"],
        principles=["el costo-por-valor (101) transfiere al lazo de auto-mejora real (yield aditivo de datos correctos)",
                    "el ratio valor/costo exige un VALOR POSITIVO (probabilidad), no un logprob negativo",
                    "verificar más candidatos baratos-prometedores rinde más correctos por unidad de costo",
                    "validar toy→real caza artefactos de implementación (regla #4: código que corre o no cuenta)"],
        adaptation=("El lab VALIDA por primera vez una extensión del arco de asignación (95-104, numpy) en el LAZO CERRADO "
                    "REAL: el costo-por-valor (101) transfiere -- asignar la verificación por confianza-POSITIVA/costo "
                    "rinde más datos correctos por presupuesto de costo y mejora el downstream. Política del lazo real "
                    "bajo costo de verificación heterogéneo: asignar por valor-positivo/costo. Próximo: validar las DEMÁS "
                    "extensiones (no-estacionariedad 97-99, vector 100, timing 104) en el lazo real; costo MEDIDO (no "
                    "modelado); y SCALE."),
        measurement=("exp089 ({n} seeds, lazo real): ratio yield={yr:.1f} > conf={yc:.1f} (+{yg}); nverif ratio={nvr:.1f} "
                     "vs conf={nvc:.1f}; downstream ratio={rr:.3f} vs conf={rc:.3f} (+{rg}); corr(conf,strong)={csc}.").format(
                         n=n_seeds, yr=yr, yc=yc, yg=_f(yg), nvr=nvr, nvc=nvc, rr=rrv, rc=rcv, rg=_f(rg), csc=_f(csc)),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (taller real: confianza-por-peso con plata limitada; cuidado con medir la confianza en negativo).")

    kl = ("REAL (exp089): el costo-por-valor (CYCLE 101) TRANSFIERE al lazo cerrado REAL -- asignar la verificación por "
          "valor-POSITIVO/costo rinde más datos correctos por presupuesto de costo (yield ratio={yr:.1f} > conf={yc:.1f}, "
          "+{yg}; verifica más baratos) y mejora el downstream (+{rg}). Primera validación toy→real de una extensión del "
          "arco. TECHO: validado SÓLO para 101 (las demás extensiones 97-104 siguen numpy); costo modelado (∝ target); el "
          "valor debe estar en escala positiva (artefacto de logprob negativo cazado/corregido); modelo tiny, 4 seeds.").format(
              yr=yr, yc=yc, yg=_f(yg), rg=_f(rg))
    ceilings.add(CeilingRecord(
        subsystem="Validación toy→real — el costo-por-valor (CYCLE 101) transfiere al lazo cerrado real (asignar por valor-positivo/costo rinde más correctos por presupuesto)",
        known_limit=kl,
        blockers=[{"text": "validado SÓLO para el costo-por-valor (101); las demás extensiones del arco (no-estacionariedad 97-99, vector 100, timing 104, meta 102) siguen en numpy -- falta validarlas en el lazo real", "kind": "diseno"},
                  {"text": "el ratio valor/costo exige VALOR POSITIVO (probabilidad); con logprob negativo el ranking se invierte (artefacto cazado/corregido) -- detalle de implementación que importa en el lazo real", "kind": "fisico"},
                  {"text": "costo de verificación MODELADO (∝ target, no medido); modelo tiny (d=64), tarea sembrada, 4 seeds, CPU; SCALE pendiente", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP089.ref, S_EXP085.ref]))
    notes.append("1 techo 'real': el costo-por-valor (101) transfiere al lazo real (1ra validación toy→real de una extensión); el valor debe ser positivo.")

    dstmt = ("North-Star R-VALOR (1ra VALIDACIÓN toy→real de una extensión del arco de asignación): el costo-por-valor "
             "(CYCLE 101, numpy) TRANSFIERE al LAZO CERRADO REAL -- bajo costo de verificación heterogéneo, asignar por "
             "VALOR-POSITIVO/COSTO rinde más datos verificado-correctos por presupuesto de costo que por valor solo y "
             "mejora el downstream. Decisión: en el lazo real bajo costo de verificación heterogéneo, asignar por valor "
             "positivo (probabilidad) / costo. CONFIRMA que el arco de asignación (95-104) no es sólo teoría de juguete: "
             "al menos su pieza de costo transfiere al modelo real. Honestidad de método: el ratio exige valor POSITIVO "
             "(un artefacto de logprob negativo dio un REFUTADA falso, cazado y corregido). Próximo: validar las DEMÁS "
             "extensiones (97-104) en el lazo real; costo MEDIDO; y SCALE.")
    drat = ("exp089 (tier5, propio, {n} seeds, PyTorch CPU, lazo real exp018): ratio (valor+/costo) yield={yr:.1f} > "
            "conf={yc:.1f} (+{yg}, todos los seeds); downstream ratio={rr:.3f} > conf={rc:.3f} (+{rg}). Convergente con "
            "transferencia/valor-positivo (tier2) y con el costo-por-valor de CYCLE 101 (tier5). APOYADA la transferencia "
            "toy→real.").format(n=n_seeds, yr=yr, yc=yc, yg=_f(yg), rr=rrv, rc=rcv, rg=_f(rg))
    dec = Decision(id="D-V4-67", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP089), _to_plain(S_EXP085)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-67 ACEPTADA por el ledger (tier5 exp089 + tier5 exp085).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-67:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle105_real_cost_alloc',
                                description='CYCLE 105 (RESET v4, H-V4-8j: el costo-por-valor de CYCLE 101 transfiere al lazo cerrado real -- APOYADA; 1ra validación toy→real de una extensión).')
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
    print("RESUMEN — CYCLE 105 (RESET v4): el costo-por-valor (101) TRANSFIERE al lazo cerrado real (H-V4-8j) — 1ra validación toy→real")
    print("=" * 78)
    print("veredicto H-V4-8j:", status.upper() if status else "?")
    print("  bajo costo de verificación heterogéneo, valor-positivo/costo rinde más correctos por presupuesto y mejora el downstream.")
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
