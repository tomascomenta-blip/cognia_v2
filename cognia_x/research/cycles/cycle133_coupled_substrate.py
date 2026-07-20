r"""
cycle133_coupled_substrate.py — CICLO 133 (RESET v4, rama control/acción, ROBUSTEZ del keystone 129 a un SUSTRATO ACOPLADO;
MIXTA ACOTADA tras VERIFICACIÓN ADVERSARIAL): H-V4-10g por las compuertas del engine. ¿Sobrevive el keystone (129: el control
reconstruye R-VALOR = controlabilidad × relevancia) cuando el SUSTRATO ya NO es de modos INDEPENDIENTES sino que ACOPLA los
modos (actuar sobre uno propaga a otros)? Es la frontera explícita de 132 ("estructura en el SUSTRATO, no sólo en el control");
rompe el supuesto de modos independientes que se mantenía desde CYCLE 127.

RESULTADO VERIFICADO: el PRINCIPIO valor=ctrl×rel SOBREVIVE pero su factor de controlabilidad debe ser de ALCANCE-POR-LA-RED
**y** la selección debe ser ADAPTATIVA (greedy). reach_greedy (alcance acoplado de horizonte completo + selección greedy) es
robusto en TODAS las estructuras (base/multihop/redundant/distractor). El keystone LOCAL 129 (valor_local) recupera 129 sin
acople (κ=0) pero FALLA bajo acople — y la falla es ROBUSTA (también con un modo DISTRACTOR, no sólo en w_driver=0 exacto): la
relevancia DIRECTA es un PROXY INFIEL de la relevancia-POR-ALCANCE. El reach NAIVE (top-K-standalone) colapsa bajo redundancia
submodular; el reach de 1-hop falla bajo multi-hop.

EJEMPLO DEL MÉTODO (3er ciclo consecutivo, con 131/132): una 1ra versión (un único arco, w_driver=0, criterio reach=top-K-
standalone) daba una MIXTA FUERTE. Una VERIFICACIÓN ADVERSARIAL (4 agentes) la ACOTÓ: (1) reach≡oracle por construcción en esa
estructura (no es evidencia ortogonal); (2) el top-K-standalone NO es robusto (colapsa bajo redundancia; hace falta selección
ADAPTATIVA); (3) la magnitud titular era un FILO de medida cero en w_driver=0 (el mecanismo correcto es "proxy infiel", robusto
con distractor). Resistió: _reduction correcto (MC <0.21%), sin leakage, y la falla del local NO es "1-paso vs multi-paso".

DERIVA de exp117_coupled_substrate/results/results.json.

Correr (DESPUÉS de exp117):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp117_coupled_substrate.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle133_coupled_substrate
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle133_coupled_substrate')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp117_coupled_substrate', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="bajo un SUSTRATO ACOPLADO (modos no independientes, actuar uno propaga a otros) la controlabilidad relevante para R-VALOR es de ALCANCE-POR-LA-RED (cuánta relevancia podés regular propagando por el acople) y la selección de qué modelar/actuar debe ser ADAPTATIVA (greedy sobre el alcance acoplado), NO la pendiente directa local ni el top-K marginal: la relevancia directa es un proxy INFIEL de la relevancia-por-alcance, y la selección marginal sobre-compromete con actuadores redundantes. Controlabilidad de-alcance-por-red bajo acople del sustrato", obtained=False,
                     claim=("Bajo un SUSTRATO ACOPLADO, la controlabilidad que importa para R-VALOR es el ALCANCE-POR-LA-RED "
                            "(cuánta relevancia regulás propagando por el acople) y la selección debe ser ADAPTATIVA. La "
                            "PENDIENTE DIRECTA local (keystone 129) falla: la relevancia directa es un PROXY INFIEL de la "
                            "relevancia-por-alcance (no acredita a un actuador controlable-pero-directamente-irrelevante que "
                            "regula un modo relevante por el acople). El top-K marginal sobre-compromete con actuadores "
                            "redundantes. Generaliza la controlabilidad-de-alcance de 132 (saturación del control) al acople "
                            "del sustrato. (Principio.)"))
S_C129 = Source(tier=5, ref="cognia_x/experiments/exp113_value_factorization", obtained=True,
                claim=("CYCLE 129 (keystone): el control reconstruye R-VALOR = controlabilidad × relevancia con controlabilidad "
                       "LOCAL b̂ sobre modos INDEPENDIENTES. H-V4-10g testea su robustez al acople del sustrato: el PRINCIPIO "
                       "sobrevive pero la controlabilidad local NO -- hace falta alcance-por-la-red + selección adaptativa."))
S_C132 = Source(tier=5, ref="cognia_x/experiments/exp116_nonlinear_keystone", obtained=True,
                claim=("CYCLE 132: bajo no-linealidad del CONTROL (saturación) la controlabilidad correcta es el ALCANCE al "
                       "esfuerzo, no la pendiente local. H-V4-10g lo GENERALIZA al SUSTRATO: bajo acople la controlabilidad es "
                       "el ALCANCE-POR-LA-RED -- el alcance vuelve a ser la respuesta, ahora en la red, no en el transfer."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp117 primero): " + results_path)

    gm = sm['greedy_min']; lk0 = sm['local_base0']; lkm = sm['local_baseM']; gbm = sm['greedy_baseM']
    ld = sm['local_dist']; gd = sm['greedy_dist']; tkr = sm['topk_redun']; grr = sm['greedy_redun']
    ohm = sm['onehop_multi']; gmm = sm['greedy_multi']
    n_seeds = data['args']['seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim117 = ("exp117 (propio, {n} seeds, numpy, post-verificación adversarial de 4 agentes): bajo un SUSTRATO ACOPLADO el "
                "PRINCIPIO valor=ctrl×rel sobrevive SÓLO con controlabilidad de ALCANCE-POR-LA-RED + selección ADAPTATIVA "
                "(reach_greedy robusto en TODAS las estructuras, min {gm}). El keystone LOCAL 129 recupera 129 a κ=0 ({lk0}) pero "
                "FALLA bajo acople (base {lkm} vs greedy {gbm}); la falla es ROBUSTA con un DISTRACTOR ({ld} vs {gd}), no un filo "
                "de w=0. El reach NAIVE top-K colapsa bajo redundancia ({tkr} vs greedy {grr}); el reach de 1-hop falla bajo "
                "multi-hop ({ohm} vs {gmm}). reach_greedy ≈ oracle estimado por construcción -> el contenido sustantivo es el "
                "FALLO del local.").format(n=n_seeds, gm=_f(gm), lk0=_f(lk0), lkm=_f(lkm), gbm=_f(gbm), ld=_f(ld), gd=_f(gd),
                                           tkr=_f(tkr), grr=_f(grr), ohm=_f(ohm), gmm=_f(gmm))
    S_EXP117 = Source(tier=5, ref="cognia_x/experiments/exp117_coupled_substrate", obtained=True, claim=claim117)
    for src in (S_PRINCIPLE, S_C129, S_C132, S_EXP117):
        ledger.add_source(src)
    notes.append("4 fuentes (S_PRINCIPLE tier2 controlabilidad de-alcance-por-red + selección adaptativa; S_C129 tier5 el keystone testeado; S_C132 tier5 el alcance bajo saturación que se generaliza; S_EXP117 tier5 dato propio post-verificación de 4 agentes).")

    ev_for = [S_EXP117.ref, S_PRINCIPLE.ref]
    ev_against = [S_EXP117.ref]
    advtext = ("{V} ACOTADA (el keystone sobrevive a un SUSTRATO ACOPLADO sólo con controlabilidad de ALCANCE-POR-LA-RED + "
               "selección ADAPTATIVA; 3er EJEMPLO consecutivo de verificación adversarial acotando un hallazgo): ¿sobrevive el "
               "keystone (129) cuando el sustrato ACOPLA los modos (actuar uno propaga a otros, x'=A·x+b⊙u+ruido con A no "
               "diagonal)? RESULTADO VERIFICADO: el PRINCIPIO valor=ctrl×rel SOBREVIVE pero (a) la controlabilidad debe ser de "
               "ALCANCE-POR-LA-RED y (b) la selección debe ser ADAPTATIVA. reach_greedy (alcance de horizonte completo + greedy) "
               "es robusto en base/multihop/redundant/distractor (min {gm}). (i) El keystone LOCAL 129 recupera 129 sin acople "
               "(κ=0: {lk0}) pero FALLA bajo acople (base {lkm} vs greedy {gbm}, pd_local={pdl}); ROBUSTO/no-knife-edge: con un "
               "DISTRACTOR (vanidad controlable+relevante-directo, sin acople) el local cae a {ld} vs {gd} -- la relevancia "
               "DIRECTA es un PROXY INFIEL de la relevancia-POR-ALCANCE. (ii) El reach NAIVE top-K-standalone NO basta: bajo "
               "REDUNDANCIA submodular (2 drivers->1 target) COLAPSA a {tkr} vs greedy {grr} -> la selección debe ser adaptativa. "
               "(iii) El reach de 1-HOP NO basta: bajo MULTI-HOP cae a {ohm} vs greedy {gmm} -> la controlabilidad debe ser de "
               "horizonte/alcance completo. => bajo acople del sustrato la controlabilidad del keystone es el ALCANCE-POR-LA-RED, "
               "que GENERALIZA el alcance-al-esfuerzo de 132 (el alcance vuelve a ser la respuesta, ahora en la RED). META: la "
               "1ra versión (1 arco, w_driver=0, reach=top-K-standalone) daba una MIXTA FUERTE; una VERIFICACIÓN ADVERSARIAL (4 "
               "agentes) la ACOTÓ con 3 hallazgos reproducidos (reach≡oracle por construcción; top-K no robusto bajo redundancia; "
               "magnitud knife-edge en w=0) -> 3er ciclo seguido (con 131/132) que exige institucionalizar la compuerta. "
               "EVIDENCIA: el principio (tier2) lo predice; generaliza 132 (tier5). EVIDENCIA EN CONTRA / caveats: reach_greedy ≈ "
               "ORACLE estimado por construcción (el contenido sustantivo es el FALLO del local, no el éxito de reach); el "
               "1.000 de reach es CONDICIONAL a system-ID adecuado (N_PROBE>=~50/100) y a relevancia conocida; la MIXTA requiere "
               "K>=2; numpy, acople LINEAL en el sustrato (no-lineal es frontera).").format(
                   V=status.upper(), gm=_f(gm), lk0=_f(lk0), lkm=_f(lkm), gbm=_f(gbm), pdl=_f(sm['pd_local_baseM']),
                   ld=_f(ld), gd=_f(gd), tkr=_f(tkr), grr=_f(grr), ohm=_f(ohm), gmm=_f(gmm))

    hyp = Hypothesis(
        id="H-V4-10g",
        statement=("El keystone (valor=controlabilidad×relevancia) SOBREVIVE a un sustrato ACOPLADO PERO su factor de "
                   "controlabilidad debe ser de ALCANCE-POR-LA-RED y la selección debe ser ADAPTATIVA (reach_greedy robusto en "
                   "base/multihop/redundant/distractor); el keystone LOCAL 129 (valor_local) recupera 129 sin acople pero FALLA "
                   "bajo acople porque la relevancia directa es proxy infiel del alcance (robusto con distractor, no knife-edge); "
                   "el reach naive top-K colapsa bajo redundancia submodular; el reach de 1-hop falla bajo multi-hop. Generaliza "
                   "el alcance-al-esfuerzo de 132 al alcance por el acople del sustrato."),
        prediction=("APOYADA si valor_local se mantiene óptimo aun con acople; REFUTADA si ni reach_greedy sobrevive; MIXTA si el "
                    "PRINCIPIO sobrevive con alcance-por-red + selección adaptativa pero la versión local falla bajo acople, el "
                    "reach naive colapsa bajo redundancia y el reach de 1-hop falla bajo multi-hop. (Pre-registrada en su 2da "
                    "versión tras verificación adversarial de 4 agentes: numpy, 4 estructuras de acople + sweep w_driver, 200 "
                    "seeds; reach_greedy declarado ≈ oracle estimado.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp117_coupled_substrate")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-10g")
        notes.append("H-V4-10g marcada '{}' con DoD completo (keystone sobrevive al acople sólo con alcance-por-red + selección adaptativa; el local falla; MIXTA FUERTE inicial ACOTADA por verificación adversarial de 4 agentes).".format(status))

    analogy = AnalogyRecord(
        problem=("Si mover una cosa MUEVE a otras (todo está conectado), ¿basta mirar qué tan fácil empujás CADA cosa por "
                 "separado para saber en cuáles concentrarte, o tenés que ver qué LOGRÁS mover a través de las conexiones?"),
        everyday=("Tenés que ver qué LOGRÁS mover por la red. Imaginá que querés cambiar la temperatura de una pieza pero el "
                  "termostato de ESA pieza no anda; sin embargo, subir el de la pieza de al lado la calienta por la pared "
                  "compartida. Si elegís perillas mirando sólo '¿esta perilla controla algo que me importa directamente?', "
                  "descartás la perilla de al lado (no me importa esa pieza) y te quedás sin calentar la que sí me importa. Y "
                  "si hay DOS perillas que calientan la misma pieza, no sirve agarrar las dos (redundantes): agarrás una y con "
                  "la otra mano agarrás otra cosa. Hay que pensar en CADENA y elegir de a una mirando lo que ya cubriste."),
        solutions=["bajo un sustrato ACOPLADO la controlabilidad real es el ALCANCE-POR-LA-RED (qué relevante regulás propagando), no la respuesta directa de cada modo",
                   "la relevancia DIRECTA es un proxy INFIEL: un actuador controlable-pero-irrelevante-en-sí puede ser el más valioso si alcanza por el acople un modo relevante",
                   "la selección debe ser ADAPTATIVA (greedy): elegir de a uno mirando lo ya cubierto, porque el top-K marginal sobre-compromete con actuadores redundantes",
                   "el keystone (valor=ctrl×rel) sobrevive al acople PERO con controlabilidad de alcance-por-red; el local falla, y reaparece el ALCANCE de 132 (ahora en la red, no en la saturación del control)"],
        principles=["bajo acople del sustrato la controlabilidad de R-VALOR es el ALCANCE-POR-LA-RED, no la pendiente directa local",
                    "la relevancia directa es un proxy infiel de la relevancia-por-alcance; la selección debe ser adaptativa (no top-K marginal)",
                    "el PRINCIPIO valor=ctrl×rel sobrevive al acople; su factor de controlabilidad Y su selección deben volverse conscientes del acople",
                    "META: 3er ciclo consecutivo donde la verificación adversarial ACOTA un hallazgo (reach≡oracle, top-K no robusto, knife-edge) antes del ledger -> institucionalizarla"],
        adaptation=("El lab testea la robustez de su keystone (129) a un SUSTRATO ACOPLADO -- el supuesto de modos independientes "
                    "que se mantenía desde CYCLE 127 -- y obtiene un hallazgo más fino + una lección de método. El PRINCIPIO "
                    "valor=controlabilidad×relevancia SOBREVIVE, PERO la controlabilidad debe ser de ALCANCE-POR-LA-RED (cuánta "
                    "relevancia regulás propagando por el acople) y la selección debe ser ADAPTATIVA (greedy sobre el alcance "
                    "acoplado), no la pendiente directa local de la versión 129 -- que FALLA bajo acople porque la relevancia "
                    "directa es un proxy infiel del alcance (robusto: también con un distractor, no sólo en el filo w=0). Esto "
                    "GENERALIZA el alcance-al-esfuerzo de 132 (saturación del control) al alcance por el acople del sustrato: el "
                    "ALCANCE vuelve a ser la respuesta, ahora en la RED. Política: estimar la controlabilidad por el alcance "
                    "acoplado de horizonte completo y seleccionar adaptativamente. META-LECCIÓN: 3er ciclo seguido (con 131/132) "
                    "en que la verificación adversarial ACOTA un hallazgo (reach≡oracle por construcción; top-K-standalone no "
                    "robusto bajo redundancia; magnitud knife-edge en w=0) antes del ledger; institucionalizar la compuerta. "
                    "Próximo: acople NO-LINEAL en el sustrato; relevancia ESTIMADA (no dada); el lazo real; active inference formal."),
        measurement=("exp117 ({n} seeds): reach_greedy robusto en todas las estructuras (min {gm}); local base κ0 {lk0} -> κmax "
                     "{lkm} vs greedy {gbm}; distractor local {ld} vs greedy {gd}; redundant top-K {tkr} vs greedy {grr}; "
                     "multihop 1hop {ohm} vs greedy {gmm}.").format(
                         n=n_seeds, gm=_f(gm), lk0=_f(lk0), lkm=_f(lkm), gbm=_f(gbm), ld=_f(ld), gd=_f(gd), tkr=_f(tkr),
                         grr=_f(grr), ohm=_f(ohm), gmm=_f(gmm)),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (bajo acople, lo que controlás es lo que ALCANZÁS por la red -elegí en cadena-, no lo que empujás directo).")

    kl = ("REAL (exp117, post-verificación adversarial de 4 agentes): el keystone (valor=ctrl×rel) SOBREVIVE a un SUSTRATO "
          "ACOPLADO pero sólo con controlabilidad de ALCANCE-POR-LA-RED + selección ADAPTATIVA (reach_greedy robusto en todas "
          "las estructuras, min {gm}); el keystone LOCAL 129 recupera 129 sin acople ({lk0}) pero FALLA bajo acople (base {lkm} "
          "vs greedy {gbm}; robusto con distractor {ld} vs {gd}); el reach naive top-K colapsa bajo redundancia ({tkr} vs {grr}); "
          "el reach de 1-hop falla bajo multi-hop ({ohm} vs {gmm}). Generaliza el alcance-al-esfuerzo de 132. TECHO: numpy, "
          "acople LINEAL en el sustrato; reach_greedy ≈ oracle estimado por construcción (el sustantivo es el FALLO del local); "
          "el 1.000 de reach es condicional a system-ID adecuado y a relevancia conocida; MIXTA requiere K>=2. Frontera: acople "
          "NO-LINEAL, relevancia estimada, lazo real, active inference.").format(
              gm=_f(gm), lk0=_f(lk0), lkm=_f(lkm), gbm=_f(gbm), ld=_f(ld), gd=_f(gd), tkr=_f(tkr), grr=_f(grr),
              ohm=_f(ohm), gmm=_f(gmm))
    ceilings.add(CeilingRecord(
        subsystem="Robustez del keystone a un SUSTRATO ACOPLADO — el principio valor=ctrl×rel sobrevive al acople PERO la controlabilidad debe ser de ALCANCE-POR-LA-RED y la selección ADAPTATIVA (greedy); el keystone LOCAL 129 (pendiente directa) falla porque la relevancia directa es proxy infiel del alcance (robusto con distractor); el reach naive top-K colapsa bajo redundancia submodular; el reach de 1-hop falla bajo multi-hop; generaliza el alcance-al-esfuerzo de 132 (saturación del control) al acople del sustrato",
        known_limit=kl,
        blockers=[{"text": "numpy; el acople en el SUSTRATO es LINEAL (matriz A no diagonal); el acople no-lineal (p.ej. tanh sobre el estado vecino) es frontera; el control es por modelo ESTIMADO pero la regulación de eval es ridge óptima (aísla la asignación, no mide un controlador imperfecto)", "kind": "diseno"},
                  {"text": "reach_greedy ≈ ORACLE estimado por construcción (greedy sobre el alcance acoplado con dinámica estimada); su 1.000 NO es evidencia ortogonal de robustez -- el contenido sustantivo es el FALLO del LOCAL. El 1.000 de reach es además CONDICIONAL a system-ID adecuado (N_PROBE>=~50-100, costo de datos coherente con 128) y a relevancia w CONOCIDA (bajo ruido en w, reach se erosiona)", "kind": "diseno"},
                  {"text": "META/honestidad: la 1ra versión (1 arco, w_driver=0 exacto, reach=top-K-standalone) daba una MIXTA FUERTE; una VERIFICACIÓN ADVERSARIAL (4 agentes) la ACOTÓ con 3 hallazgos reproducidos -> (a) reach≡oracle por construcción, (b) top-K-standalone no robusto -> selección debe ser ADAPTATIVA, (c) magnitud knife-edge en w=0 -> el mecanismo correcto es 'proxy infiel' (robusto con distractor). 3er ciclo seguido (con 131/132) que exige institucionalizar la compuerta. La MIXTA requiere K>=2", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP117.ref, S_C129.ref, S_C132.ref]))
    notes.append("1 techo 'real': el keystone sobrevive al acople sólo con alcance-por-red + selección adaptativa; el local falla; MIXTA FUERTE inicial ACOTADA por verificación adversarial (reach≡oracle, top-K no robusto, knife-edge w=0).")

    dstmt = ("North-Star R-VALOR (robustez del keystone a un SUSTRATO ACOPLADO + lección de método): el PRINCIPIO valor="
             "controlabilidad×relevancia SOBREVIVE al acople del sustrato, PERO su factor de controlabilidad debe ser de "
             "ALCANCE-POR-LA-RED (cuánta relevancia regulás propagando por el acople) y la selección debe ser ADAPTATIVA "
             "(greedy): reach_greedy robusto en todas las estructuras (min {gm}); el keystone LOCAL 129 recupera 129 sin acople "
             "({lk0}) pero FALLA bajo acople (base {lkm} vs greedy {gbm}; robusto con distractor {ld} vs {gd}) porque la "
             "relevancia directa es proxy infiel del alcance; el reach naive top-K colapsa bajo redundancia ({tkr} vs {grr}); el "
             "reach de 1-hop falla bajo multi-hop ({ohm} vs {gmm}). Decisión: estimar la controlabilidad por el ALCANCE acoplado "
             "de horizonte completo y seleccionar adaptativamente; esto GENERALIZA el alcance-al-esfuerzo de 132 (el alcance "
             "vuelve a ser la respuesta, ahora en la red). META-DECISIÓN: 3er ciclo seguido (con 131/132) donde la verificación "
             "adversarial (4 agentes) ACOTA un hallazgo (reach≡oracle por construcción; top-K no robusto -> selección adaptativa; "
             "knife-edge w=0 -> proxy infiel) -> institucionalizarla como compuerta. Próximo: acople no-lineal, relevancia "
             "estimada, lazo real, active inference.").format(
                 gm=_f(gm), lk0=_f(lk0), lkm=_f(lkm), gbm=_f(gbm), ld=_f(ld), gd=_f(gd), tkr=_f(tkr), grr=_f(grr),
                 ohm=_f(ohm), gmm=_f(gmm))
    drat = ("exp117 (tier5, propio, {n} seeds, numpy, post-verificación de 4 agentes): reach_greedy robusto (min {gm}) vs "
            "valor_local que falla bajo acople (base {lkm}<greedy {gbm}, distractor {ld}<{gd}), reach naive top-K que colapsa "
            "bajo redundancia ({tkr}<{grr}) y reach de 1-hop que falla bajo multi-hop ({ohm}<{gmm}). Convergente con el principio "
            "de controlabilidad-de-alcance-por-red + selección adaptativa (tier2); generaliza 132 (tier5); testea el keystone "
            "129 (tier5). MIXTA ACOTADA: el principio sobrevive, la versión local no; reach_greedy ≈ oracle estimado (el "
            "sustantivo es el fallo del local).").format(
                n=n_seeds, gm=_f(gm), lkm=_f(lkm), gbm=_f(gbm), ld=_f(ld), gd=_f(gd), tkr=_f(tkr), grr=_f(grr),
                ohm=_f(ohm), gmm=_f(gmm))
    dec = Decision(id="D-V4-95", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP117), _to_plain(S_C129), _to_plain(S_C132)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-95 ACEPTADA por el ledger (tier5 exp117 + tier5 exp113 + tier5 exp116).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-95:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle133_coupled_substrate',
                                description='CYCLE 133 (RESET v4, H-V4-10g MIXTA ACOTADA: el keystone sobrevive a un sustrato acoplado sólo con controlabilidad de ALCANCE-POR-LA-RED + selección ADAPTATIVA; el local falla; MIXTA FUERTE inicial acotada por verificación adversarial de 4 agentes).')
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
    print("RESUMEN — CYCLE 133 (RESET v4): el keystone sobrevive a un SUSTRATO ACOPLADO sólo con controlabilidad de ALCANCE-POR-LA-RED + selección ADAPTATIVA; el local falla — H-V4-10g")
    print("=" * 78)
    print("veredicto H-V4-10g:", status.upper() if status else "?")
    print("  el principio valor=ctrl×rel sobrevive al acople, pero la controlabilidad debe ser de ALCANCE-POR-LA-RED y la selección ADAPTATIVA; la pendiente directa local (129) falla (relevancia directa = proxy infiel del alcance). MIXTA FUERTE inicial ACOTADA por verificación adversarial de 4 agentes (reach≡oracle, top-K no robusto, knife-edge w=0) — 3er ciclo seguido.")
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
