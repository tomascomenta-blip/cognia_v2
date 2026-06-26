r"""
cycle131_active_probing.py — CICLO 131 (RESET v4, rama control/acción, PUENTE a ACTIVE INFERENCE; MIXTA reencuadrada tras
VERIFICACIÓN ADVERSARIAL): H-V4-10e por las compuertas del engine. Este ciclo es un EJEMPLO DEL MÉTODO funcionando: la 1ra
versión afirmaba "APOYADA: el sondeo activo dirigido por valor paga en ESCASEZ". Una verificación adversarial (workflow de 4
agentes independientes) la DEMOLIÓ -- el "win en escasez" era un ARTEFACTO (a presupuesto chico la pasiva no ajustaba ninguna
dim, lstsq exige >=3 muestras, y quedaba 0.000 por construcción => "activa vs brazo-muerto"); además los brazos NO estaban
PAREADOS (semillas distintas), lo que ocultaba que a escasez genuina la activa empata/pierde; y la grilla saltaba presupuestos
donde la activa PIERDE. La versión honesta (brazos PAREADOS, sin presupuestos degenerados, criterio basado en la FORMA) da
MIXTA: el sondeo dirigido por valor compra eficiencia muestral MODERADA (~20-40% relativo) cuando la CONTROLABILIDAD debe
DESCUBRIRSE, a presupuesto MEDIO, con una U-INVERTIDA ROBUSTA (estable 40-1000 seeds); con la relevancia CONOCIDA el efecto es
chico. La afirmación original ('paga en escasez') queda REFUTADA.

DERIVA de exp115_active_probing/results/results.json.

Correr (DESPUÉS de exp115):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp115_active_probing.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle131_active_probing
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle131_active_probing')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp115_active_probing', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="el sondeo de datos DIRIGIDO POR VALOR (active inference: actuar para aprender lo relevante al control) compra eficiencia muestral sobre la observación uniforme SÓLO cuando la controlabilidad debe DESCUBRIRSE y a presupuesto MEDIO (U-invertida): en escasez genuina el bootstrap dirigido es ruido, en abundancia ambos saturan, y con la relevancia conocida la selección ya está resuelta. Eficiencia muestral de la exploración dirigida por valor, acotada", obtained=False,
                     claim=("El sondeo de datos DIRIGIDO POR VALOR (active inference) compra eficiencia muestral sobre la "
                            "observación uniforme SÓLO en un régimen acotado: cuando la CONTROLABILIDAD debe DESCUBRIRSE "
                            "(relevancia no dada) y a presupuesto MEDIO -- el beneficio es una U-INVERTIDA en presupuesto. En "
                            "escasez genuina el bootstrap dirigido-por-valor es RUIDO (sin datos no hay a qué dirigir), en "
                            "abundancia ambos saturan, y con la relevancia CONOCIDA la selección ya está resuelta (la "
                            "dirección por valor apenas afina). El efecto es MODERADO. (Principio.)"))
S_C128 = Source(tier=5, ref="cognia_x/experiments/exp112_control_discovery", obtained=True,
                claim=("CYCLE 128: la controlabilidad es DESCUBRIBLE actuando, con suficiente data. H-V4-10e mide la "
                       "EFICIENCIA de descubrir+controlar: dirigir el sondeo por valor ayuda en el régimen de descubrimiento "
                       "a presupuesto medio (U-invertida), no en escasez."))
S_C130 = Source(tier=5, ref="cognia_x/experiments/exp114_graded_value", obtained=True,
                claim=("CYCLE 130: el valor (relevancia × controlabilidad-descontada w·b²/(b²+ρ)) es el criterio de "
                       "asignación. H-V4-10e lo usa para DIRIGIR la colección de datos (no sólo la capacidad); el payoff es "
                       "moderado y acotado al régimen de descubrimiento."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp115 primero): " + results_path)

    gd = sm['gaps_descubrir']; gc = sm['gaps_conocida']
    peak = sm['peak_descubrir']; peakB = sm['peak_descubrir_B']; edge = sm['edge_descubrir']
    peak_con = sm['peak_conocida']; ratio = sm['peak_ratio']
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim115 = ("exp115 (propio, {n} seeds, numpy, brazos PAREADOS, tras verificación adversarial de 4 agentes): el sondeo "
                "dirigido por valor da una U-INVERTIDA en presupuesto SÓLO en el régimen DESCUBRIR (controlabilidad escasa): "
                "gaps {gd}, pico +{pk} en B={pb} (bordes +{ed}; la activa rinde {r}× la pasiva); en CONOCIDA (relevancia "
                "dada) el efecto es chico (pico +{pc}). Efecto MODERADO; la afirmación original 'paga en escasez' fue "
                "REFUTADA (artefacto de presupuesto degenerado + brazos no pareados).").format(
                    n=n_seeds, gd=[_f(x) for x in gd], pk=_f(peak), pb=peakB, ed=_f(edge), r=_f(ratio), pc=_f(peak_con))
    S_EXP115 = Source(tier=5, ref="cognia_x/experiments/exp115_active_probing", obtained=True, claim=claim115)
    for src in (S_PRINCIPLE, S_C128, S_C130, S_EXP115):
        ledger.add_source(src)
    notes.append("4 fuentes (S_PRINCIPLE tier2 eficiencia dirigida acotada; S_C128 tier5 descubrir actuando; S_C130 tier5 valor cost-aware; S_EXP115 tier5 dato propio post-verificación).")

    ev_for = [S_EXP115.ref, S_PRINCIPLE.ref]
    ev_against = [S_EXP115.ref]
    advtext = ("{V} (EJEMPLO DEL MÉTODO: la 1ra versión APOYADA fue REFUTADA por verificación adversarial; la honesta es "
               "MIXTA): la 1ra versión de H-V4-10e afirmaba 'el sondeo activo dirigido por valor PAGA en ESCASEZ' (APOYADA). "
               "Un workflow de VERIFICACIÓN ADVERSARIAL (4 agentes independientes, en paralelo) la DEMOLIÓ y cazó: (1) el "
               "'win en escasez' era un ARTEFACTO -- a presupuesto chico la PASIVA reparte <3 probes/dim, por debajo del "
               "umbral de lstsq, y su controlador queda no-op (perf 0.000 por CONSTRUCCIÓN): el 'gap' era 'activa vs "
               "brazo-muerto', no eficiencia; (2) los brazos NO estaban PAREADOS (semillas distintas por brazo), lo que "
               "OCULTABA que a presupuesto escaso-pero-fiteable la activa EMPATA o PIERDE (gap pareado negativo significativo); "
               "(3) la grilla canónica SALTABA presupuestos (B=75-90) donde la activa es SIGNIFICATIVAMENTE PEOR; (4) el "
               "veredicto era inestable por seeds (REFUTADA@50 -> APOYADA@250 -> MIXTA@2000) por umbrales-filo cerca del "
               "tamaño del efecto. La versión HONESTA (brazos PAREADOS sobre las mismas instancias, sin presupuestos "
               "degenerados, criterio basado en la FORMA estable) da MIXTA: el sondeo dirigido por valor compra eficiencia "
               "muestral MODERADA (~20-40% relativo) SÓLO cuando la CONTROLABILIDAD debe DESCUBRIRSE (régimen 'descubrir': "
               "controlabilidad escasa, relevancia no dada) y a presupuesto MEDIO, con una U-INVERTIDA ROBUSTA (estable "
               "40-1000 seeds): gaps {gd}, pico +{pk} en B={pb}, bordes +{ed}, la activa rinde {r}× la pasiva. En 'conocida' "
               "(la relevancia DA la selección) el efecto es chico (pico +{pc}). MECANISMO: en escasez genuina el bootstrap "
               "dirigido-por-valor es RUIDO (sin datos no hay a qué dirigir), en abundancia ambos saturan, y con relevancia "
               "conocida la selección ya está resuelta. CONCLUSIÓN HONESTA: actuar para aprender lo relevante al control "
               "(active inference) paga, pero es un beneficio MODERADO y ACOTADO al régimen de descubrimiento a presupuesto "
               "medio -- NO el 'paga en escasez' original (REFUTADO). Además la activa NAIVE (commit duro a una estimación "
               "rugosa) HACE DAÑO; sólo la robusta iterativa con piso paga. EVIDENCIA: el principio (tier2) lo predice. "
               "EVIDENCIA EN CONTRA / caveats: numpy lineal; el efecto es moderado y vive en una ventana de presupuesto; el "
               "valor de este ciclo es tanto el hallazgo acotado como la DEMOSTRACIÓN de que la verificación adversarial "
               "atrapó un falso positivo antes de contaminar el ledger.").format(
                   V=status.upper(), gd=[_f(x) for x in gd], pk=_f(peak), pb=peakB, ed=_f(edge), r=_f(ratio), pc=_f(peak_con))

    hyp = Hypothesis(
        id="H-V4-10e",
        statement=("El sondeo de datos DIRIGIDO POR VALOR (active inference) compra eficiencia muestral sobre el uniforme "
                   "SÓLO cuando la controlabilidad debe DESCUBRIRSE y a presupuesto MEDIO (U-invertida robusta); el efecto "
                   "es MODERADO (~20-40% relativo). Con la relevancia conocida el efecto es chico; en escasez genuina el "
                   "bootstrap dirigido es ruido (la afirmación original 'paga en escasez' queda REFUTADA). La activa naive "
                   "hace daño."),
        prediction=("APOYADA si la activa DOMINA con U-invertida grande Y contraste con 'conocida'; REFUTADA si no hay "
                    "U-invertida/dominancia; MIXTA si el fenómeno es real pero MODERADO. (Pre-registrada en su 2da versión "
                    "tras verificación adversarial: numpy, brazos PAREADOS, criterio basado en la forma, 1000 seeds.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp115_active_probing")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-10e")
        notes.append("H-V4-10e marcada '{}' con DoD completo (fenómeno real pero MODERADO; la 1ra versión APOYADA fue refutada por verificación adversarial).".format(status))

    analogy = AnalogyRecord(
        problem=("Si tengo poco tiempo para probar cosas y aprender cuáles puedo controlar, ¿me conviene probar AL AZAR un "
                 "poco de todo, o concentrarme en lo que PARECE que voy a controlar? ¿Siempre, o sólo a veces?"),
        everyday=("Sólo a veces, y con cuidado. Si ya SÉ qué me importa (alguien me lo dijo), concentrarme apenas ayuda -- "
                  "ya sé dónde mirar. Si NO sé qué puedo controlar y tengo que descubrirlo, concentrarme en lo prometedor "
                  "SÍ ayuda... PERO sólo si ya probé lo suficiente para saber qué es prometedor: si me concentro demasiado "
                  "temprano (cuando todavía no sé nada), me juego todo a una corazonada ruidosa y me va PEOR que probando "
                  "parejo. El beneficio vive en el medio: ni tan poco que la corazonada es ruido, ni tanto que ya me alcanza "
                  "para todo."),
        solutions=["dirigir el sondeo por valor ayuda SÓLO cuando hay que DESCUBRIR la controlabilidad (no cuando la relevancia es dada)",
                   "y SÓLO a presupuesto MEDIO (U-invertida): en escasez genuina el bootstrap es ruido, en abundancia ambos saturan",
                   "el efecto es MODERADO (~20-40% relativo), no una dominancia limpia",
                   "la versión naive (commit duro a una estimación temprana) HACE DAÑO; hay que ser iterativo y dejar un piso de exploración"],
        principles=["la eficiencia muestral de la exploración dirigida por valor es ACOTADA (régimen descubrir × presupuesto medio)",
                    "dirigir por una estimación sin datos suficientes es ruido (el bootstrap del active inference tiene un costo de arranque)",
                    "con la relevancia conocida la selección ya está resuelta -> el active probing apenas aporta",
                    "META-LECCIÓN: la verificación adversarial atrapó un falso positivo (APOYADA) antes de contaminar el ledger -> el método funciona"],
        adaptation=("El lab obtiene un hallazgo ACOTADO y honesto sobre el active inference como colector de datos, Y una "
                    "demostración del MÉTODO: una primera versión daba APOYADA ('el sondeo activo paga en escasez') y la "
                    "verificación adversarial (workflow de 4 agentes) la REFUTÓ como artefacto (presupuesto degenerado + "
                    "brazos no pareados + grilla que saltaba el régimen donde la activa pierde + umbrales-filo). La verdad: "
                    "dirigir el sondeo por valor compra eficiencia muestral MODERADA sólo cuando hay que DESCUBRIR la "
                    "controlabilidad y a presupuesto MEDIO (U-invertida); con relevancia conocida apenas aporta y en escasez "
                    "genuina daña/empata. Política: usar exploración dirigida por valor SÓLO con un piso de exploración "
                    "(robusta, iterativa) y en el régimen medio de descubrimiento; no fiarse de la dirección con pocos datos. "
                    "Próximo: control no-lineal; el costo de arranque del bootstrap (cuánta exploración uniforme antes de "
                    "dirigir); y el puente formal a active inference (energía libre esperada)."),
        measurement=("exp115 ({n} seeds, pareado): descubrir gaps {gd} (pico +{pk}@B{pb}, bordes +{ed}, {r}×); conocida pico "
                     "+{pc}.").format(n=n_seeds, gd=[_f(x) for x in gd], pk=_f(peak), pb=peakB, ed=_f(edge), r=_f(ratio), pc=_f(peak_con)),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (concentrar el sondeo en lo prometedor ayuda sólo si ya probaste lo suficiente, y sólo cuando hay que descubrir).")

    kl = ("REAL (exp115, post-verificación adversarial): el sondeo DIRIGIDO POR VALOR (active inference) compra eficiencia "
          "muestral MODERADA (~20-40% relativo) sobre el uniforme SÓLO cuando la CONTROLABILIDAD debe DESCUBRIRSE y a "
          "presupuesto MEDIO (U-invertida robusta 40-1000 seeds: gaps {gd}, pico +{pk}@B{pb}, bordes +{ed}, {r}×). Con la "
          "relevancia CONOCIDA el efecto es chico (pico +{pc}). La afirmación original 'paga en escasez' fue REFUTADA "
          "(artefacto de presupuesto degenerado + brazos no pareados). La activa naive HACE DAÑO. TECHO: numpy lineal; "
          "efecto moderado y acotado a una ventana de presupuesto; frontera: costo de arranque del bootstrap, no-lineal, "
          "active inference formal.").format(gd=[_f(x) for x in gd], pk=_f(peak), pb=peakB, ed=_f(edge), r=_f(ratio), pc=_f(peak_con))
    ceilings.add(CeilingRecord(
        subsystem="ACTIVE INFERENCE como colector de datos (rama control/acción) — el sondeo dirigido por valor compra eficiencia muestral MODERADA sólo cuando la controlabilidad debe DESCUBRIRSE y a presupuesto MEDIO (U-invertida); con relevancia conocida apenas aporta y en escasez genuina el bootstrap es ruido. El veredicto fue corregido de APOYADA(artefacto) a MIXTA por verificación adversarial",
        known_limit=kl,
        blockers=[{"text": "numpy lineal; el efecto es MODERADO (~20-40% relativo) y vive en una ventana de presupuesto MEDIA -- no es una dominancia limpia ni 'paga en escasez'", "kind": "diseno"},
                  {"text": "el bootstrap dirigido-por-valor tiene un COSTO DE ARRANQUE no cuantificado (cuánta exploración uniforme hace falta antes de que dirigir deje de ser ruido); la activa naive sin ese piso HACE DAÑO", "kind": "diseno"},
                  {"text": "META: la 1ra versión daba APOYADA por artefactos (presupuesto degenerado pasiva=0 por umbral lstsq, brazos no pareados, grilla que saltaba el régimen perdedor, umbrales-filo inestables a seeds); corregido por verificación adversarial -> registrar que el resultado robusto exigió pareo + criterio de forma", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP115.ref, S_C128.ref, S_C130.ref]))
    notes.append("1 techo 'real': active inference paga eficiencia MODERADA y acotada (descubrir × presupuesto medio); APOYADA inicial corregida a MIXTA por verificación adversarial.")

    dstmt = ("North-Star R-VALOR (active inference como colector de datos -- hallazgo ACOTADO + lección de método): el sondeo "
             "DIRIGIDO POR VALOR compra eficiencia muestral MODERADA sobre el uniforme SÓLO cuando la controlabilidad debe "
             "DESCUBRIRSE y a presupuesto MEDIO (U-invertida robusta: pico +{pk}@B{pb}, bordes +{ed}, {r}×); con relevancia "
             "conocida apenas aporta (+{pc}). La afirmación original 'paga en escasez' quedó REFUTADA por verificación "
             "adversarial (artefacto). Decisión: usar exploración dirigida por valor SÓLO con piso de exploración (iterativa, "
             "robusta) en el régimen medio de descubrimiento; la activa naive daña. META-DECISIÓN: institucionalizar la "
             "verificación adversarial (atrapó un falso positivo antes del ledger). Próximo: costo de arranque del bootstrap; "
             "no-lineal; active inference formal.").format(pk=_f(peak), pb=peakB, ed=_f(edge), r=_f(ratio), pc=_f(peak_con))
    drat = ("exp115 (tier5, propio, {n} seeds, numpy, PAREADO, post-verificación de 4 agentes): U-invertida en descubrir "
            "(pico +{pk}, bordes +{ed}, {r}×) vs efecto chico en conocida (+{pc}); efecto moderado; original 'paga en "
            "escasez' refutado. Convergente con el principio de eficiencia dirigida acotada (tier2); usa descubrir-actuando "
            "(128) y el valor cost-aware (130). MIXTA: fenómeno real pero moderado y acotado.").format(
                n=n_seeds, pk=_f(peak), ed=_f(edge), r=_f(ratio), pc=_f(peak_con))
    dec = Decision(id="D-V4-93", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP115), _to_plain(S_C128), _to_plain(S_C130)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-93 ACEPTADA por el ledger (tier5 exp115 + tier5 exp112 + tier5 exp114).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-93:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle131_active_probing',
                                description='CYCLE 131 (RESET v4, H-V4-10e MIXTA: el sondeo dirigido por valor -active inference- compra eficiencia muestral MODERADA sólo al descubrir la controlabilidad a presupuesto medio; APOYADA inicial refutada por verificación adversarial).')
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
    print("RESUMEN — CYCLE 131 (RESET v4): active inference como colector de datos -- eficiencia MODERADA y acotada (descubrir × presupuesto medio); APOYADA inicial corregida a MIXTA por verificación adversarial — H-V4-10e")
    print("=" * 78)
    print("veredicto H-V4-10e:", status.upper() if status else "?")
    print("  el sondeo dirigido por valor paga eficiencia muestral MODERADA sólo al DESCUBRIR la controlabilidad a presupuesto MEDIO (U-invertida); con relevancia conocida apenas aporta. La verificación adversarial atrapó un falso positivo.")
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
