r"""
cycle149_decisional_resolution.py — CICLO 149 (RESET v4, FRONTERA REAL §4.2 del capstone): H-V4-9i por las compuertas del engine.
RESUELVE A POTENCIA el limbo "underpowered/diluyendo" que arrastraban 140-141.

VEREDICTO: APOYADA (el PRIMER APOYADA limpio del arco de fragilidad; confirmado out-of-sample + verificación adversarial de 1 agente).

QUÉ SE ESTABLECE: en el lazo torch REAL (HybridLM byte-level genera 'N=a*b' -> verificador REAL sandbox -> confianza ENDÓGENA
mean-logprob -> self-train con ancla; el brazo 'durable' agrega unlikelihood sobre lo verificado-incorrecto = cura 119), la confianza
endógena del durable es una señal MÁS INFORMATIVA sobre la correctness REAL que la del naive: ventaja de RANKING AUROC base-rate-
INVARIANTE, gap medio +0.047 a N=16 (mediana +0.042, 14/16 seeds positivos, t=4.22), CI bootstrap 95% [+0.027, +0.069] EXCLUYE el
cero. CONFIRMADO OUT-OF-SAMPLE: 6 seeds NUNCA vistos (16-21) -> 6/6 positivos (mean +0.055, más fuerte) -> combinado N=22 t=5.87, CI
[+0.034, +0.066], 20/22 positivos. Refuta la "dilución/winner's curse" que 141 sospechaba: NO era ruido, era falta de N (el lazo es
RÁPIDO ~2-3 min/seed; el "underpowered" no era restricción de tiempo).

VERIFICACIÓN ADVERSARIAL (1 agente, probes reales sobre los datos): el CI excluye 0 por 5 MÉTODOS (t / percentil / BCa / Wilcoxon
p=0.0008 / sign-test p=0.004); t=4.22 robusto a jackknife (todas las leave-1-out >0, no outlier-driven); el MECANISMO PERSISTE por
rondas (round-1=0 por construcción -> el gap está SUBESTIMADO, conservador); AUROC empíricamente base-rate-INVARIANTE (pooled
corr(nc,auroc)=-0.03). ACOTACIÓN de régimen (refina, NO degrada): el efecto se concentra donde el base-acc tiene MARGEN (incorrectas
que el unlikelihood empuja); se desvanece/invierte en los 2 seeds de base-acc más alta (corr base_acc×gap=-0.32), paralelo a 135-136.

SIGNIFICADO: cierra el hueco #1 de la auditoría (payoff/calibración del R-VALOR FUERA del numpy sintético, en un sistema real con
self-training). La cura 119 (unlikelihood) produce una señal de valor endógena genuinamente más calibrada sobre la correctness real.

DERIVA de exp131_decisional_resolution/results/results.json.
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle149_decisional_resolution')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp131_decisional_resolution', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


S_PRINCIPLE = Source(tier=2, ref="en un lazo de auto-entrenamiento REAL con verificador real, el mecanismo de unlikelihood sobre lo verificado-incorrecto (cura 119) produce una señal de CONFIANZA ENDÓGENA más informativa sobre la correctness real (mejor ranking/AUROC) que el self-training naive -- una ventaja de calibración REAL, base-rate-invariante, que sobrevive a la potencia y replica out-of-sample, concentrada en el régimen donde el modelo base tiene margen (abundancia de incorrectas para el unlikelihood).", obtained=False,
                     claim=("La cura unlikelihood (119) produce una señal de valor endógena más calibrada sobre la correctness real "
                            "en el lazo torch real (ventaja AUROC base-rate-invariante, robusta a la potencia, replica "
                            "out-of-sample). (Principio.)"))
S_140_141 = Source(tier=5, ref="cognia_x/experiments/{exp124 (140), exp125 (141)} — el limbo 'underpowered/diluyendo' del payoff decisional en el lazo real", obtained=True,
                   claim=("Los CYCLEs 140-141 hallaron una ventaja de ranking AUROC del durable sobre el naive en el lazo torch real "
                          "pero la dejaron MIXTA: significancia frágil (sign-test p=0.07 a N=8) y magnitud que DILUÍA con más seeds "
                          "(winner's curse). H-V4-9i lo RESUELVE a potencia: a N=16 el CI bootstrap 95% del gap EXCLUYE el cero y "
                          "replica out-of-sample (6/6 seeds frescos) -> la dilución era artefacto de N chico; el lazo es rápido."))
S_VERIF = Source(tier=4, ref="verificación adversarial de 1 agente (probes reales sobre los datos: 5 métodos de CI, jackknife, mecanismo-por-ronda, base-rate-invariancia) + confirmación OUT-OF-SAMPLE (6 seeds frescos)", obtained=True,
                 claim=("La verificación adversarial CONFIRMÓ el APOYADA (no lo demolió, primera vez en el arco): CI excluye 0 por 5 "
                        "métodos (t/percentil/BCa/Wilcoxon p=0.0008/sign-test p=0.004); jackknife robusto (leave-1-out todas >0); "
                        "mecanismo persiste por rondas (round-1=0 -> conservador); AUROC base-rate-invariante (pooled r=-0.03). "
                        "Out-of-sample: 6/6 seeds frescos positivos -> combinado N=22 t=5.87. ACOTACIÓN de régimen: el efecto se "
                        "concentra donde el base-acc tiene margen (corr base_acc×gap=-0.32), se desvanece en base-acc alta."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    oos = data.get('out_of_sample', {})
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp131 primero): " + results_path)

    mg = sm['mean_gap']; ci = sm['ci95']; npos = sm['n_positive']; n = sm['n']; ts = sm['tstat']
    da = sm['auroc_durable']; na = sm['auroc_naive']; thirds = sm['thirds']
    cn = oos.get('combined_n', n); ct = oos.get('combined_tstat', ts); cci = oos.get('combined_ci95', ci)
    cpos = oos.get('combined_n_positive', npos); fpos = oos.get('fresh_n_positive', 0)

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim131 = ("exp131 (propio, lazo torch REAL, N={n} + {fn} out-of-sample, post-verificación adversarial): {V}. La confianza "
                "ENDÓGENA del durable (unlikelihood = cura 119) es MÁS INFORMATIVA sobre la correctness REAL que la del naive: "
                "ventaja AUROC base-rate-INVARIANTE, gap medio +{mg} ({npos}/{n} seeds pos, t={ts}), CI bootstrap 95% [{lo},{hi}] "
                "EXCLUYE el cero (durable {da} vs naive {na}). CONFIRMADO out-of-sample: {fn}/{fn} seeds frescos positivos -> "
                "combinado N={cn} t={ct}, CI [{clo},{chi}], {cpos}/{cn} pos. Resuelve el limbo de 140-141 (la dilución era N chico). "
                "ACOTACIÓN de régimen: concentrado donde el base-acc tiene margen.").format(
                    n=n, fn=fpos, V=status.upper(), mg=_f(mg), npos=npos, ts=_f(ts), lo=_f(ci[0]), hi=_f(ci[1]), da=_f(da),
                    na=_f(na), cn=cn, ct=_f(ct), clo=_f(cci[0]), chi=_f(cci[1]), cpos=cpos)
    S_EXP131 = Source(tier=5, ref="cognia_x/experiments/exp131_decisional_resolution", obtained=True, claim=claim131)
    for src in (S_PRINCIPLE, S_140_141, S_VERIF, S_EXP131):
        ledger.add_source(src)
    notes.append("4 fuentes (S_PRINCIPLE tier2 la cura 119 da una señal de valor endógena más calibrada en el lazo real; S_140_141 tier5 el limbo underpowered; S_VERIF tier4 verificación CONFIRMATORIA + out-of-sample; S_EXP131 tier5 dato propio {}).".format(status.upper()))

    ev_for = [S_EXP131.ref, S_PRINCIPLE.ref, S_VERIF.ref]
    # refutación CONSIDERADA (testeada y NO sostenida): la dilución/winner's-curse de 141 (refutada out-of-sample) + la acotación de
    # régimen de la verificación (el efecto se apaga en base-acc alta) -- contra-consideraciones reales que acotan sin tumbar.
    ev_against = [S_140_141.ref, S_VERIF.ref]
    advtext = ("{V} (RESUELVE A POTENCIA el limbo 'underpowered/diluyendo' de 140-141; PRIMER APOYADA limpio del arco de fragilidad; "
               "confirmado out-of-sample + verificación adversarial CONFIRMATORIA de 1 agente): los CYCLEs 140-141 hallaron una "
               "ventaja de ranking AUROC del brazo durable (unlikelihood = cura 119) sobre el naive en el lazo torch REAL pero la "
               "dejaron MIXTA -- la significancia era frágil (sign-test p=0.07 a N=8) y la magnitud DILUÍA con más seeds (sospecha "
               "de winner's curse). DESCUBRIMIENTO HABILITANTE: el lazo es RÁPIDO (~2-3 min/seed; el HybridLM byte-level es "
               "diminuto) -> el 'underpowered' NO era restricción de tiempo, se puede RESOLVER. QUÉ SE ESTABLECE (a N={n}, métrica "
               "de potencia LIMPIA): en el lazo torch REAL (HybridLM genera 'N=a*b' -> verificador REAL sandbox -> confianza "
               "ENDÓGENA mean-logprob -> self-train con ancla), la confianza endógena del durable es MÁS INFORMATIVA sobre la "
               "correctness REAL que la del naive -- ventaja de RANKING AUROC base-rate-INVARIANTE, gap medio +{mg} (mediana "
               "+{med}, {npos}/{n} seeds positivos, t={ts}), CI bootstrap 95% [{lo}, {hi}] EXCLUYE el cero (AUROC durable {da} vs "
               "naive {na}); los tercios [{t0}/{t1}/{t2}] NO diluyen. CONFIRMADO OUT-OF-SAMPLE (el test decisivo contra la dilución "
               "de 141): 6 seeds NUNCA vistos (16-21) -> {fp}/6 positivos (mean +0.055, MÁS fuerte que el lote original) -> "
               "combinado N={cn} t={ct}, CI [{clo}, {chi}], {cpos}/{cn} positivos. => la 'dilución/winner's curse' de 141 era "
               "artefacto de N chico; a potencia el efecto es REAL y REPLICA. VERIFICACIÓN ADVERSARIAL (1 agente, probes reales "
               "sobre los datos -- CONFIRMÓ, no demolió, por primera vez en el arco): el CI excluye 0 por 5 MÉTODOS (t / percentil "
               "/ BCa / Wilcoxon p=0.0008 / sign-test p=0.004; el percentil ni siquiera es el más optimista); t={ts} robusto a "
               "jackknife (todas las leave-1-out >0, no outlier-driven); el MECANISMO PERSISTE por rondas (R1=0 por construcción "
               "-mismo modelo base- -> el gap está SUBESTIMADO ~8/7×, conservador; no es un pico temprano); AUROC empíricamente "
               "base-rate-INVARIANTE (el durable genera MENOS correctas -226 vs 243- pero pooled corr(nc,auroc)=-0.03 -> la "
               "ventaja NO es el confound de base-rate que 141 temía -la defensa AUROC se sostiene-). ACOTACIÓN de régimen (refina, "
               "NO degrada): el efecto se CONCENTRA donde el modelo base tiene MARGEN (abundancia de incorrectas que el unlikelihood "
               "empuja hacia abajo); se desvanece/invierte en los 2 seeds de base-acc MÁS alta (corr base_acc×gap=-0.32), "
               "mecanísticamente coherente (poca incorrecta -> poco que empujar) y paralelo al patrón regime-dependent de 135-136. "
               "=> RESULTADO HONESTO: el PRIMER APOYADA limpio del arco -- en un sistema REAL con self-training, la cura 119 "
               "(unlikelihood) produce una señal de valor ENDÓGENA genuinamente más calibrada sobre la correctness REAL; cierra el "
               "hueco #1 de la auditoría (payoff/calibración del R-VALOR FUERA del numpy sintético). Frontera: ¿es la cura 119 "
               "PRIVILEGIADA o cualquier regularizador de calibración sirve (tercer brazo)?; ¿el efecto en base-acc alta?; SCALE.").format(
                   V=status.upper(), n=n, mg=_f(mg), med=_f(sm['median_gap']), npos=npos, ts=_f(ts), lo=_f(ci[0]), hi=_f(ci[1]),
                   da=_f(da), na=_f(na), t0=_f(thirds[0]), t1=_f(thirds[1]), t2=_f(thirds[2]), fp=fpos, cn=cn, ct=_f(ct),
                   clo=_f(cci[0]), chi=_f(cci[1]), cpos=cpos)

    hyp = Hypothesis(
        id="H-V4-9i",
        statement=("¿La ventaja de ranking AUROC del brazo durable (unlikelihood = cura 119) sobre el naive en el lazo torch REAL "
                   "(140-141, dejada underpowered/diluyendo) SOBREVIVE a la potencia, o se diluye a cero? RESULTADO: SOBREVIVE -- a "
                   "N=16 el CI bootstrap 95% del gap EXCLUYE el cero (t=4.22) y REPLICA out-of-sample (6/6 seeds frescos -> "
                   "combinado N=22 t=5.87); la confianza endógena del durable es más informativa sobre la correctness real "
                   "(base-rate-invariante, mecanismo persistente). Acotación: concentrado donde el base-acc tiene margen. Alcance: "
                   "lazo torch real CPU, HybridLM byte-level, tarea a*b."),
        prediction=("APOYADA si a N=16 el CI bootstrap 95% del gap EXCLUYE el cero y NO diluye (y replica out-of-sample). REFUTADA "
                    "si el CI incluye el cero (confirma la dilución de 141). (Pre-registrada; verificación adversarial + "
                    "out-of-sample.)"),
        status='abierta', confidence='alta',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp131_decisional_resolution")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-9i")
        notes.append("H-V4-9i marcada '{}': la ventaja AUROC del durable (cura 119) en el lazo torch real SOBREVIVE a la potencia (N=16 CI excluye 0, t=4.22) y REPLICA out-of-sample (6/6 frescos -> N=22 t=5.87); base-rate-invariante, mecanismo persistente; acotación de régimen (concentrado donde el base-acc tiene margen). Resuelve el limbo de 140-141. PRIMER APOYADA limpio del arco.".format(status))

    analogy = AnalogyRecord(
        problem=("Dos veces antes mediste si una 'mejor forma de aprender de sus propios errores' (castigar lo que el verificador "
                 "marca mal = la cura) hacía que el modelo SUPIERA mejor cuándo acierta -- y las dos veces quedó en 'quizás, no "
                 "alcanza la evidencia'. ¿Era real o ruido?"),
        everyday=("Era REAL -- lo que faltaba era repetir el experimento más veces. Antes lo corriste 4 y 8 veces y el efecto "
                  "parpadeaba (a veces fuerte, a veces no), y hasta parecía achicarse al sumar pruebas, lo que daba miedo de que "
                  "fuera casualidad. Resulta que cada prueba era RÁPIDA, así que la corriste 16 veces: el efecto quedó claro y "
                  "consistente (14 de 16 a favor), con un margen estadístico que no toca el cero por cinco métodos distintos. Y la "
                  "prueba de fuego: lo corriste en 6 casos NUEVOS que nunca habías visto -> los 6 a favor, igual de fuertes -> no "
                  "era que habías elegido casos convenientes. Conclusión: el modelo que se castiga por sus errores verificados SÍ "
                  "termina sabiendo mejor cuándo acierta. Con un asterisco honesto: el beneficio se nota cuando el modelo todavía "
                  "tiene errores que corregir; si ya es casi perfecto, no hay mucho que castigar y el efecto se apaga."),
        solutions=["correr el MISMO lazo real a más potencia (N=16) resuelve el limbo: el CI bootstrap del gap excluye el cero (t=4.22), no diluye",
                   "la confirmación OUT-OF-SAMPLE (6/6 seeds frescos positivos) refuta la sospecha de winner's curse de 141 -- el efecto replica",
                   "el AUROC es base-rate-invariante (el durable genera menos correctas pero su ventaja de ranking no es el confound) -- la defensa de 140-141 se sostiene empíricamente",
                   "acotación de régimen: el efecto se concentra donde el base tiene margen (incorrectas que el unlikelihood empuja), se apaga en base-acc alta"],
        principles=["cuando un experimento es BARATO, el 'underpowered' se resuelve con más N -- no hay que dejar un efecto real en limbo por pereza de cómputo",
                    "la confirmación OUT-OF-SAMPLE (seeds nunca vistos) es el test decisivo contra el winner's curse / la dilución",
                    "una ventaja de ranking (AUROC) es base-rate-invariante por construcción -- la defensa correcta contra el confound de base-rate que mató el precision@m de 140",
                    "META: la verificación adversarial CONFIRMÓ (no demolió) por primera vez en el arco -- el método no sólo caza overclaims, también RATIFICA lo que es real"],
        adaptation=("FRONTERA REAL §4.2 del capstone (salir del oráculo con potencia). Los CYCLEs 140-141 dejaron la ventaja AUROC "
                    "del durable (cura 119) en el lazo torch real como underpowered/diluyendo. Este ciclo la RESUELVE: descubrir "
                    "que el lazo es rápido habilitó N=16, donde el CI bootstrap del gap excluye el cero (t=4.22) y -el test "
                    "decisivo- REPLICA out-of-sample (6/6 seeds frescos -> combinado N=22 t=5.87). La verificación adversarial "
                    "CONFIRMÓ (5 métodos de CI, jackknife, mecanismo persistente, base-rate-invariancia) con una acotación de "
                    "régimen honesta (concentrado donde el base tiene margen). APORTE: el PRIMER APOYADA limpio del arco -- en un "
                    "sistema REAL con self-training la cura 119 produce una señal de valor endógena genuinamente más calibrada "
                    "sobre la correctness real; cierra el hueco #1 de la auditoría. Próximo: ¿es la cura PRIVILEGIADA o cualquier "
                    "regularizador sirve (tercer brazo)?; el régimen de base-acc alta; SCALE."),
        measurement=("exp131 (lazo torch real): N={n} gap AUROC durable-naive +{mg} ({npos}/{n} pos, t={ts}), CI95 [{lo},{hi}] "
                     "excluye 0; out-of-sample {fp}/6 frescos pos -> N={cn} t={ct} CI [{clo},{chi}]; AUROC durable {da} vs naive "
                     "{na}; base-rate-invariante (pooled r=-0.03); régimen: concentrado donde base-acc tiene margen.").format(
                         n=n, mg=_f(mg), npos=npos, ts=_f(ts), lo=_f(ci[0]), hi=_f(ci[1]), fp=fpos, cn=cn, ct=_f(ct),
                         clo=_f(cci[0]), chi=_f(cci[1]), da=_f(da), na=_f(na)),
        iterations=3)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (era REAL, faltaba repetir más veces; el lazo es rápido -> N=16 lo resolvió; 6/6 out-of-sample refuta el winner's curse; asterisco: se nota donde el modelo tiene margen).")

    kl = ("REAL (exp131, {V} confirmado out-of-sample + verificación adversarial): en el lazo torch REAL (verificador real, confianza "
          "endógena, self-train con ancla) la confianza endógena del brazo durable (unlikelihood = cura 119) es MÁS INFORMATIVA "
          "sobre la correctness REAL que la del naive -- ventaja AUROC base-rate-INVARIANTE, gap +{mg} a N={n} (CI [{lo},{hi}] excluye "
          "0, t={ts}), REPLICA out-of-sample ({fp}/6 frescos -> N={cn} t={ct}). TECHO/ALCANCE: el efecto se CONCENTRA donde el base-"
          "acc tiene MARGEN (incorrectas que el unlikelihood empuja); se desvanece/invierte en base-acc alta (corr base_acc×gap="
          "-0.32, paralelo a 135-136); lazo torch CPU, HybridLM byte-level, tarea a*b, magnitud MODESTA (+0.05 de AUROC). Frontera: "
          "¿la cura 119 es PRIVILEGIADA (vs un regularizador genérico, tercer brazo)?; el régimen de base-acc alta; SCALE.").format(
              V=status.upper(), mg=_f(mg), n=n, lo=_f(ci[0]), hi=_f(ci[1]), ts=_f(ts), fp=fpos, cn=cn, ct=_f(ct))
    ceilings.add(CeilingRecord(
        subsystem="RESOLVER a potencia el payoff/calibración del R-VALOR en el lazo torch REAL (cierra el hueco #1 de la auditoría — salir del oráculo) — la confianza ENDÓGENA del brazo durable (unlikelihood = cura 119) es MÁS INFORMATIVA sobre la correctness REAL que la del naive: ventaja AUROC base-rate-INVARIANTE robusta a la potencia (N=16 CI excluye 0, t=4.22) y REPLICA out-of-sample (6/6 frescos -> N=22 t=5.87). PRIMER APOYADA limpio del arco. Acotación de régimen: concentrado donde el base-acc tiene margen",
        known_limit=kl,
        blockers=[{"text": "MAGNITUD MODESTA + RÉGIMEN: la ventaja es REAL y significativa pero MODESTA (+0.05 de AUROC, de 0.83 a 0.88); y CONCENTRADA en el régimen donde el modelo base tiene MARGEN (abundancia de incorrectas que el unlikelihood empuja). Se desvanece/invierte en los 2 seeds de base-acc más alta (corr base_acc×gap=-0.32, paralelo regime-dependent a 135-136). NO es una ventaja uniforme a través de seeds; vive donde hay margen de mejora", "kind": "diseno"},
        {"text": "FRONTERA ABIERTA -- ¿la cura 119 es PRIVILEGIADA? El durable = naive + unlikelihood. Este ciclo establece que el durable bate al naive, PERO no testea si la unlikelihood ESPECÍFICAMENTE es lo que ayuda o si cualquier regularizador de calibración (entropy bonus, label smoothing, temperatura) daría la misma ventaja AUROC. Requiere un TERCER brazo (regularizador genérico). §4.2 del capstone, abierta", "kind": "diseno"},
        {"text": "ALCANCE: lazo torch CPU, HybridLM byte-level diminuto (~200k params), tarea aritmética a*b, verificador exp018, N=16+6. NO cubre: modelos/tareas reales a escala, el régimen de base-acc alta (donde el efecto se apaga), la transferencia a otras tareas, SCALE (GPU). La señal es REAL pero a juguete-real, no a escala", "kind": "fisico"}],
        real_or_assumed="real", evidence=[S_EXP131.ref, S_140_141.ref, S_VERIF.ref]))
    notes.append("1 techo 'real': la ventaja AUROC del durable (cura 119) en el lazo torch real es REAL y robusta a la potencia (N=16 CI excluye 0) + replica out-of-sample (N=22 t=5.87), base-rate-invariante; PERO modesta (+0.05) y concentrada donde el base-acc tiene margen. Frontera: ¿es la cura privilegiada (tercer brazo)?; SCALE.")

    dstmt = ("North-Star R-VALOR (FRONTERA REAL §4.2 -- salir del oráculo con potencia): {V}. RESUELVE el limbo 'underpowered/"
             "diluyendo' de 140-141: en el lazo torch REAL la confianza endógena del durable (unlikelihood = cura 119) es MÁS "
             "INFORMATIVA sobre la correctness REAL que la del naive (ventaja AUROC base-rate-invariante, gap +{mg} a N={n}, CI "
             "[{lo},{hi}] excluye 0, t={ts}; REPLICA out-of-sample {fp}/6 -> N={cn} t={ct}). Verificación adversarial CONFIRMATORIA "
             "(5 métodos de CI, jackknife, mecanismo persistente, base-rate-invariante). Decisión: ADOPTAR que la cura 119 produce "
             "una señal de valor endógena genuinamente más calibrada en un sistema REAL (PRIMER APOYADA limpio del arco; cierra el "
             "hueco #1 de la auditoría), con la acotación de que el efecto es modesto y régimen-dependiente (concentrado donde el "
             "base tiene margen). META-DECISIÓN: la verificación ratificó (no demolió) por primera vez. Próximo: ¿cura privilegiada "
             "(tercer brazo)?; régimen base-acc alta; SCALE.").format(
                 V=status.upper(), mg=_f(mg), n=n, lo=_f(ci[0]), hi=_f(ci[1]), ts=_f(ts), fp=fpos, cn=cn, ct=_f(ct))
    drat = ("exp131 (tier5, propio, lazo torch real, N={n}+{fp} out-of-sample, post-verificación adversarial CONFIRMATORIA): la "
            "ventaja AUROC del durable sobre el naive SOBREVIVE a la potencia (CI bootstrap excluye 0 por 5 métodos, t={ts}) y "
            "REPLICA out-of-sample (6/6 -> N={cn} t={ct}); base-rate-invariante (pooled r=-0.03); mecanismo persistente; régimen-"
            "dependiente (concentrado donde el base tiene margen). Convergente con el principio (tier2) y la verificación (tier4); "
            "resuelve el limbo de 140-141 (tier5). APOYADA: primer resultado positivo limpio del arco, cierra el hueco #1 de la "
            "auditoría.").format(n=n, fp=fpos, ts=_f(ts), cn=cn, ct=_f(ct))
    dec = Decision(id="D-V4-109", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP131), _to_plain(S_140_141), _to_plain(S_VERIF)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-109 ACEPTADA por el ledger (tier5 exp131 + tier5 limbo-140-141 + tier4 verificación adversarial confirmatoria + out-of-sample).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-109:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle149_decisional_resolution',
                                description='CYCLE 149 (RESET v4, H-V4-9i APOYADA: RESUELVE a potencia el limbo de 140-141 -- en el lazo torch real la confianza endógena del durable (cura 119) es más informativa sobre la correctness real, ventaja AUROC robusta a la potencia + replica out-of-sample; PRIMER APOYADA limpio del arco, verificación adversarial CONFIRMATORIA).')
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
    print("RESUMEN — CYCLE 149 (RESET v4): RESUELVE el lazo real a potencia (PRIMER APOYADA limpio del arco) — H-V4-9i " + (status.upper() if status else "?"))
    print("=" * 78)
    print("veredicto H-V4-9i:", status.upper() if status else "?")
    print("  En el lazo torch REAL la confianza ENDÓGENA del durable (unlikelihood = cura 119) es MÁS INFORMATIVA sobre la correctness REAL que la del naive: ventaja AUROC base-rate-INVARIANTE robusta a la potencia (N=16 CI excluye 0, t=4.22) y REPLICA out-of-sample (6/6 frescos -> N=22 t=5.87). Verificación adversarial CONFIRMATORIA (5 métodos de CI, jackknife, mecanismo persistente). Acotación de régimen: concentrado donde el base-acc tiene margen. Cierra el hueco #1 de la auditoría.")
    print("")
    for n_ in notes:
        print("  CHECK ", n_)
    print("")
    for name in ('sources', 'hypotheses', 'analogies', 'ceilings', 'decisions'):
        print("  {:<12}: {}".format(name, count_lines(record.store_path(name))))
    print("  verify_no_loss =", "OK" if res['ok'] else "FAIL")
    print("=" * 78)
    return 0 if res['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
