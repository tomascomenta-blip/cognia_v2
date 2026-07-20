r"""
cycle118_contrastive_grounding.py — CICLO 118 (RESET v4, rama R-VALOR, ataca la FRONTERA de 115-117): H-V4-8x por las
compuertas del engine. REFUTADA (inestable, pero INFORMATIVA): la hipótesis viva del arco de fragilidad era que una señal
NEGATIVA/CONTRASTIVA (penalizar lo verificado-incorrecto, no sólo imitar lo correcto) PRESERVARÍA la calibración que la
imitación-positiva no cura. RESULTADO: el contrastivo NAIVE (ascenso de gradiente sobre el CE de los negativos) DESESTABILIZA
el tiny model -- la señal de calibración SÍ mejora en la dirección correcta (corr menos negativa) PERO el downstream COLAPSA
a ~0 (el modelo se vuelve degenerado). => la DIRECCIÓN (usar negativos) es correcta, pero la IMPLEMENTACIÓN naive sacrifica
la capacidad por la calibración: hace falta un unlikelihood ACOTADO/propio (no ascenso de CE crudo), o recalibración
externa. Sharpea la frontera de 115-117.

DERIVA de exp102_contrastive_grounding/results/results.json.

Correr (DESPUÉS de exp102):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp102_contrastive_grounding.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle118_contrastive_grounding
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle118_contrastive_grounding')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp102_contrastive_grounding', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="unlikelihood training: el ascenso de gradiente crudo sobre el CE de ejemplos negativos es INESTABLE (empuja a distribuciones degeneradas y destruye la capacidad); el unlikelihood ACOTADO -log(1-p) sobre tokens preserva la capacidad. La dirección (penalizar negativos) es correcta; la formulación importa", obtained=False,
                     claim=("Penalizar ejemplos negativos via ASCENSO DE GRADIENTE sobre su CE es inestable: empuja al "
                            "modelo a una distribución degenerada y destruye la capacidad de generar lo correcto. La "
                            "formulación estable es el unlikelihood ACOTADO (-log(1-p) sobre los tokens no deseados). La "
                            "DIRECCIÓN (usar negativos para calibrar) es correcta; la implementación naive no. (Principio.)"))
S_C117 = Source(tier=5, ref="cognia_x/experiments/exp101_targeted_grounding", obtained=True,
                claim=("CYCLE 115-117: la señal de valor colapsa bajo auto-entrenamiento y la imitación de positivos "
                       "(replay random/dirigido) no la cura. Hipótesis viva: una señal NEGATIVA/contrastiva. H-V4-8x la "
                       "testea."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp102 primero): " + results_path)

    tp = sm['trend_pos']; tc = sm['trend_contrastive']
    clp = sm['corr_last_pos']; clc = sm['corr_last_contrastive']
    rlp = sm['real_last_pos']; rlc = sm['real_last_contrastive']
    tg = sm['trend_gain']; cg = sm['corr_gain']; rg = sm['real_gain']
    destab = sm['destabilized']
    n_seeds = sm['n_seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim102 = ("exp102 (propio, {n} seeds, PyTorch CPU, lazo real exp018): el contrastivo NAIVE (ascenso de gradiente "
                "sobre el CE de negativos) DESESTABILIZA -- real_acc contrastive={rlc} vs pos_only={rlp} (Δ{rg}, "
                "destabilized={d}); la señal de calibración mejora en dirección (corr_gain +{cg}, trend +{tg}) pero el "
                "downstream COLAPSA. La dirección (negativos) es correcta, la implementación naive no.").format(
                    n=n_seeds, rlc=_f(rlc), rlp=_f(rlp), rg=_f(rg), d=destab, cg=_f(cg), tg=_f(tg))
    S_EXP102 = Source(tier=5, ref="cognia_x/experiments/exp102_contrastive_grounding", obtained=True, claim=claim102)
    for src in (S_PRINCIPLE, S_C117, S_EXP102):
        ledger.add_source(src)
    notes.append("3 fuentes (S_PRINCIPLE tier2 unlikelihood-acotado-vs-ascenso-crudo; S_C117 tier5 fragilidad 115-117; S_EXP102 tier5 dato propio).")

    ev_for = [S_EXP102.ref, S_PRINCIPLE.ref]
    ev_against = [S_EXP102.ref]
    advtext = ("{V} (ataca la FRONTERA de 115-117; REFUTADA INESTABLE pero INFORMATIVA): el arco de fragilidad (la señal de "
               "valor colapsa bajo auto-entrenamiento y la imitación de positivos no la cura, 115-117) dejó como hipótesis "
               "viva una señal NEGATIVA/CONTRASTIVA: penalizar lo verificado-INCORRECTO (no sólo imitar lo correcto) para "
               "que el modelo aprenda a BAJAR la confianza en lo que está mal. H-V4-8x la testea con el contrastivo más "
               "simple (ascenso de gradiente sobre el CE de los negativos, peso chico + grad-clip). RESULTADO: "
               "DESESTABILIZA. El downstream COLAPSA -- real_acc contrastive={rlc} vs pos_only={rlp} (Δ{rg}) -- aun con "
               "peso chico (probado 0.2 y 0.05). DATO INFORMATIVO: la señal de CALIBRACIÓN sí se movió en la dirección "
               "CORRECTA (corr_gain +{cg}, trend +{tg}: el término negativo ayuda a la calibración) PERO al costo de "
               "DESTRUIR la capacidad (el modelo se vuelve degenerado, real_acc -> ~0). => el ascenso de gradiente crudo "
               "sobre negativos NO es viable en el tiny model: SACRIFICA la capacidad por la calibración. La DIRECCIÓN "
               "(usar negativos para curar la sobreconfianza) es correcta -- consistente con el principio (tier2) y con "
               "que 115-117 apuntaban ahí -- pero la IMPLEMENTACIÓN naive no sirve; hace falta un unlikelihood ACOTADO "
               "(-log(1-p) sobre los tokens no deseados, que NO destruye la capacidad) o recalibración externa. SHARPEA la "
               "frontera: no es 'usar negativos sí/no' sino 'CÓMO usarlos sin colapsar la capacidad'. EVIDENCIA EN CONTRA "
               "/ caveats HONESTOS: NO se probó el unlikelihood acotado propio (sólo el ascenso de CE crudo) -- queda como "
               "frontera; tiny model (la inestabilidad puede ser peor en tiny que a escala); 4 seeds, CPU. Honestidad: el "
               "resultado es un FRACASO de implementación que igualmente informa (la dirección negativa mueve la "
               "calibración; el método crudo colapsa la capacidad).").format(
                   V=status.upper(), rlc=_f(rlc), rlp=_f(rlp), rg=_f(rg), cg=_f(cg), tg=_f(tg))

    hyp = Hypothesis(
        id="H-V4-8x",
        statement=("Una señal NEGATIVA/contrastiva (penalizar lo verificado-incorrecto) preserva la calibración que la "
                   "imitación-positiva no cura (115-117). [REFUTADA-inestable: el contrastivo naive (ascenso de CE sobre "
                   "negativos) mueve la calibración en la dirección correcta pero DESTRUYE la capacidad (real_acc->0); "
                   "hace falta unlikelihood acotado o recalibración externa.]"),
        prediction=("APOYADA si contrastive preserva la calibración mejor que pos_only (+>0.04) sin desestabilizar; "
                    "REFUTADA si no preserva mejor o desestabiliza (real_acc << pos_only); MIXTA en otro caso. "
                    "(Pre-registrada, lazo real exp018, 4 seeds, neg_w=0.2.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp102_contrastive_grounding")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-8x")
        notes.append("H-V4-8x marcada '{}' con DoD completo (contrastivo naive desestabiliza; la dirección negativa es correcta, la implementación no).".format(status))

    analogy = AnalogyRecord(
        problem=("Para dejar de creerme infalible, intento CASTIGARME fuerte cada vez que me equivoco. ¿Funciona, o me "
                 "rompe?"),
        everyday=("Me rompe. Castigarme crudo por cada error sí me hace más cauto (mejora mi calibración un poco) PERO me "
                  "bloquea: de tanto evitar equivocarme dejo de producir cualquier cosa útil (me vuelvo inútil). La idea "
                  "de aprender de los errores es CORRECTA, pero castigarme a lo bruto sacrifica mi capacidad. Necesito una "
                  "forma MEDIDA de corregir los errores (bajar un poco la confianza en lo malo) sin destruir lo que sé "
                  "hacer -- o que alguien de afuera me recalibre."),
        solutions=["contrastivo naive (ascenso de gradiente sobre negativos): desestabiliza, real_acc -> 0",
                   "la señal negativa mueve la calibración en la dirección correcta (corr mejora) pero destruye la capacidad",
                   "la dirección (usar negativos) es correcta; la implementación cruda no",
                   "hace falta unlikelihood ACOTADO (-log(1-p)) o recalibración externa -- frontera no testeada"],
        principles=["el ascenso de gradiente crudo sobre negativos es inestable (degenera la capacidad)",
                    "usar negativos mueve la calibración en la dirección correcta -> la dirección es válida",
                    "la frontera no es 'usar negativos sí/no' sino CÓMO usarlos sin colapsar la capacidad (unlikelihood acotado)",
                    "sharpea 115-117: la cura de la durabilidad necesita una formulación negativa ESTABLE o recalibración externa"],
        adaptation=("El lab descarta el contrastivo NAIVE (ascenso de CE sobre negativos) como cura -- desestabiliza el "
                    "tiny model (sacrifica capacidad por calibración) -- pero CONFIRMA que la dirección negativa mueve la "
                    "calibración en el sentido correcto. La frontera se sharpea: implementar un unlikelihood ACOTADO "
                    "(-log(1-p) sobre los tokens no deseados) que penalice lo incorrecto SIN degenerar, o una "
                    "recalibración externa explícita. Política interina (sin esa pieza): selector endógeno válido por "
                    "tramos cortos + re-anclaje externo del outcome (115). Próximo: unlikelihood acotado propio; "
                    "recalibración externa; y SCALE."),
        measurement=("exp102 ({n} seeds, lazo real): contrastive real_acc={rlc} vs pos_only={rlp} (Δ{rg}, destabilized={d}); "
                     "corr_gain +{cg} (dirección correcta, capacidad destruida).").format(
                         n=n_seeds, rlc=_f(rlc), rlp=_f(rlp), rg=_f(rg), d=destab, cg=_f(cg)),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (castigarse a lo bruto por cada error: más cauto pero inútil; la idea es correcta, el método no).")

    kl = ("REAL (exp102): el contrastivo NAIVE (ascenso de gradiente sobre el CE de negativos) DESESTABILIZA el tiny model "
          "-- real_acc contrastive={rlc} vs pos_only={rlp} (Δ{rg}); la señal de calibración se mueve en la dirección "
          "correcta (corr_gain +{cg}) pero la CAPACIDAD colapsa (real_acc -> ~0). La dirección (negativos) es correcta, la "
          "implementación naive no. TECHO: NO se probó el unlikelihood ACOTADO (-log(1-p)) ni recalibración externa "
          "(frontera); tiny model (inestabilidad puede ser peor en tiny); 4 seeds, CPU.").format(
              rlc=_f(rlc), rlp=_f(rlp), rg=_f(rg), cg=_f(cg))
    ceilings.add(CeilingRecord(
        subsystem="Cura de la fragilidad — el contrastivo NAIVE (ascenso de CE sobre negativos) desestabiliza (sacrifica capacidad por calibración); la dirección negativa es correcta, la implementación no -> frontera: unlikelihood acotado o recalibración externa",
        known_limit=kl,
        blockers=[{"text": "el ascenso de gradiente crudo sobre el CE de negativos degenera el modelo (real_acc -> 0): sacrifica capacidad por calibración -> no viable como cura aunque la calibración mejore en dirección", "kind": "fisico"},
                  {"text": "el unlikelihood ACOTADO propio (-log(1-p) sobre los tokens no deseados), que penaliza lo incorrecto SIN destruir la capacidad, NO se testeó aquí -- queda como la frontera concreta", "kind": "diseno"},
                  {"text": "tiny model (la inestabilidad del contrastivo puede ser peor en tiny que a escala); 4 seeds, CPU; recalibración externa explícita y SCALE pendientes", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP102.ref, S_C117.ref]))
    notes.append("1 techo 'real': el contrastivo naive desestabiliza (capacidad->0); la dirección negativa es correcta, falta unlikelihood acotado (frontera).")

    dstmt = ("North-Star R-VALOR (ataca la frontera de durabilidad de 115-117): la cura de la sobreconfianza con una señal "
             "NEGATIVA/contrastiva tiene la DIRECCIÓN correcta (el término negativo mueve la calibración en el sentido "
             "bueno) pero el contrastivo NAIVE (ascenso de gradiente sobre el CE de negativos) DESESTABILIZA el modelo "
             "(real_acc -> ~0: sacrifica capacidad por calibración) -> no es viable como cura. Decisión: descartar el "
             "ascenso de CE crudo; la frontera concreta para la durabilidad es un unlikelihood ACOTADO (-log(1-p) sobre "
             "los tokens no deseados) que penalice lo incorrecto SIN degenerar, o recalibración externa explícita. "
             "Interino: selector endógeno válido por tramos cortos + re-anclaje externo del outcome (115). Próximo: "
             "unlikelihood acotado propio; recalibración externa; y SCALE.")
    drat = ("exp102 (tier5, propio, {n} seeds, PyTorch CPU, lazo real exp018): contrastivo naive real_acc={rlc} << "
            "pos_only={rlp} (Δ{rg}, destabilized) aunque corr_gain +{cg} (dirección correcta). Convergente con "
            "unlikelihood-acotado-vs-ascenso-crudo (tier2) y con la frontera de 115-117 (tier5). REFUTADA-inestable: la "
            "dirección negativa es correcta, la implementación naive no.").format(
                n=n_seeds, rlc=_f(rlc), rlp=_f(rlp), rg=_f(rg), cg=_f(cg))
    dec = Decision(id="D-V4-80", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP102), _to_plain(S_C117)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-80 ACEPTADA por el ledger (tier5 exp102 + tier5 exp101).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-80:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle118_contrastive_grounding',
                                description='CYCLE 118 (RESET v4, H-V4-8x REFUTADA-inestable: el contrastivo naive desestabiliza; la dirección negativa es correcta, la implementación no).')
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
    print("RESUMEN — CYCLE 118 (RESET v4): el contrastivo naive desestabiliza; la dirección negativa es correcta, la implementación no (H-V4-8x)")
    print("=" * 78)
    print("veredicto H-V4-8x:", status.upper() if status else "?")
    print("  ascenso de CE sobre negativos -> real_acc->0 (sacrifica capacidad por calibración); falta unlikelihood acotado / recalibración externa.")
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
