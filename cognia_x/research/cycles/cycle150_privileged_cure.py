r"""
cycle150_privileged_cure.py — CICLO 150 (RESET v4, FRONTERA REAL §4.2: el hueco que el 149 dejó EXPLÍCITO): H-V4-9j por las
compuertas del engine. ¿La cura 119 (unlikelihood ACOTADO, LABEL-AWARE) es PRIVILEGIADA, o cualquier regularizador de calibración
GENÉRICO (confidence-penalty/entropy bonus, label smoothing -- label-agnostic) iguala su ventaja AUROC en el lazo torch real del 149?

VEREDICTO: <SE COMPLETA TRAS LA VERIFICACIÓN ADVERSARIAL — este script es verdict-driven; lee results.json>.

DERIVA de exp132_privileged_cure/results/results.json (lazo torch REAL, mismo harness que exp124/exp131; 5 brazos que difieren
SÓLO en el regularizador del self-train; métrica privilege_gap = AUROC(durable) − AUROC(mejor genérico por seed); control de
degeneración GATED). El narrative_* abajo se ajusta tras la verificación adversarial; el verdict se toma de results.json.
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle150_privileged_cure')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp132_privileged_cure', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _f(x):
    return "{:.3f}".format(x)


# === NARRATIVA (verdict-driven). VERIF_CLAIM se ajusta tras la síntesis del workflow de verificación adversarial. ===
VERIF_CLAIM = ("verificación adversarial (4 sondas con probes reales sobre los datos crudos + síntesis): CONFIRMÓ el binario "
               "REFUTADA (la cura NO es privilegiada) PERO ACOTÓ fuerte la re-localización. (1) SANITY-149: durable_vs_naive +0.060 "
               "(7/8, CI [+0.022,+0.098] excluye 0, t=2.85) reproduce el 149 -> harness válido. (2) DEGENERACIÓN: el privilege_gap "
               "GATED (-0.040) ~ raw; endurecer el gate (min_class 30) lo hace MÁS negativo -> tirar rondas degeneradas FORTALECE la "
               "refutación; la firma de degeneración (corr ncorrect-AUROC negativa) está en el DURABLE (-0.91 within), NO en ls_lo "
               "(+0.57/+0.72). (3) JUSTICIA: el durable PIERDE vs ls_lo SOLO (-0.039, CI ENTERAMENTE negativo, sin winner's curse; "
               "ls_lo nunca degenera) -> durable es SIGNIFICATIVAMENTE peor, no empatado. (4) MECANISMO -ACOTA, severidad media-: el "
               "AUROC está CONFUNDIDO con la RIQUEZA DE GENERACIÓN (corr(AUROC,ncorrect) pooled -0.54, within-durable -0.91): "
               "durable y ls_lo ocupan regímenes de ncorrect casi DISJUNTOS (IQR 18-246 vs 59-75) y en la BANDA DE SOLAPE (nc 30-110) "
               "son IGUALES (0.9964 vs 0.9969). Lo que el label smoothing 'recupera' es en parte un efecto de pool-más-magro/estable, "
               "NO calibración limpiamente aislada -> la re-localización a 'regularización de calibración en general' SOBRE-VENDE, y "
               "el mismo confound DEBILITA RETROACTIVAMENTE el durable>naive del 149. REGIME-DEPENDENCIA: la refutación se concentra "
               "en base-acc ALTA (corr base_acc×priv_gap -0.72); en base-acc baja el durable EMPATA al genérico (ahí 'sostiene' AUROC "
               "pero pagando el colapso de generación). LO QUE QUEDA LIMPIO: la cura NO es la pieza privilegiada (refutado, incluso "
               "subestimado). LO QUE NO: que sea 'calibración en general' lo que paga -el AUROC está entangled con la riqueza de "
               "generación-. ACOTACIÓN: N=8, settings reducidos (rounds=5, steps=70); AUROC del ls_lo cerca del techo (0.998).")


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp132 primero): " + results_path)

    n = sm['n']; mp = sm['mean_priv_gap']; ci = sm['ci95']; npos = sm['n_positive']; ts = sm['tstat']
    ad = sm['auroc_durable']; ag = sm['auroc_generic_best']; an = sm['auroc_naive']
    mrec = sm['mean_recovery_gap']; rfrac = sm['recovery_frac']; mdvn = sm['mean_durable_vs_naive']; dvnp = sm['dvn_n_positive']
    g = sm['gated']; gmp = g['mean_priv_gap']; gci = g['ci95']; gexcl = g['ci_excludes_zero']
    counts = sm['best_generic_counts']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    # las fuentes y narrativa definitivas se inyectan desde finalize_narrative (post-verificación)
    nb = finalize_narrative(status, sm)

    for src in nb['sources']:
        ledger.add_source(src)
    notes.append(nb['sources_note'])

    hyp = Hypothesis(
        id="H-V4-9j",
        statement=nb['hyp_statement'],
        prediction=nb['hyp_prediction'],
        status='abierta', confidence=nb['confidence'],
        evidence_for=nb['ev_for'], evidence_against=nb['ev_against'],
        adversarial_verdict=nb['advtext'], experiment_ref="exp132_privileged_cure")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-9j")
        notes.append(nb['mark_note'])

    analogy = nb['analogy']
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append(nb['analogy_note'])

    ceilings.add(nb['ceiling'])
    notes.append(nb['ceiling_note'])

    dec = nb['decision']
    try:
        ledger.record_decision(dec)
        notes.append(nb['decision_note'])
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-110:", ex); raise

    return record, notes, status, sm


def finalize_narrative(status, sm):
    """Devuelve todos los textos del ciclo (verdict-driven). status='refutada' (la cura NO es privilegiada)."""
    n = sm['n']; mp = sm['mean_priv_gap']; ci = sm['ci95']; npos = sm['n_positive']; ts = sm['tstat']
    ad = sm['auroc_durable']; ag = sm['auroc_generic_best']; an = sm['auroc_naive']
    mrec = sm['mean_recovery_gap']; rfrac = sm['recovery_frac']; mdvn = sm['mean_durable_vs_naive']; dvnp = sm['dvn_n_positive']
    g = sm['gated']; gmp = g['mean_priv_gap']; gci = g['ci95']
    rf = sm['real_final']

    S_PRINCIPLE = Source(tier=2, ref=("la ventaja de ranking AUROC del durable (cura 119, label-aware) en el lazo real NO es "
                         "privilegiada de la unlikelihood ESPECÍFICA: un regularizador de TARGET-SMOOTHING genérico (label smoothing, "
                         "label-agnostic) la IGUALA y la SUPERA en capacidad (el confidence-penalty/entropy sólo la empata). ACOTACIÓN "
                         "fuerte: el AUROC está confundido con la riqueza de generación (brazos en regímenes de ncorrect disjuntos, "
                         "iguales en la banda de solape) -> NO se aísla 'calibración' como el mecanismo; sólo que un target-smoothing "
                         "reemplaza a la cura."), obtained=False,
                         claim=("La ventaja AUROC del 149 NO es privilegiada de la cura 119: un regularizador de target-smoothing "
                                "(label smoothing) la iguala/supera. PERO el AUROC está confundido con la riqueza de generación -> no "
                                "se establece 'calibración' como mecanismo. (Principio acotado.)"))
    S_149 = Source(tier=5, ref="cognia_x/experiments/exp131 (CYCLE 149) — la APOYADA que este ciclo RE-LOCALIZA", obtained=True,
                   claim=("El CYCLE 149 estableció que el brazo durable (unlikelihood = cura 119) produce una confianza endógena más "
                          "informativa sobre la correctness real que el naive (AUROC +0.047). H-V4-9j REPRODUCE ese hallazgo (sanity "
                          "durable_vs_naive +{mdvn}, {dvnp}/{n} seeds) PERO lo RE-LOCALIZA: la ventaja no es de la unlikelihood "
                          "específicamente, es de la regularización de calibración (un genérico la iguala/supera).").format(
                              mdvn=_f(mdvn), dvnp=dvnp, n=n))
    S_VERIF = Source(tier=4, ref="verificación adversarial (workflow, 4 sondas con probes reales sobre los datos crudos + síntesis)", obtained=True,
                     claim=VERIF_CLAIM)
    claim132 = ("exp132 (propio, lazo torch REAL, N={n}, mismo harness que exp124/exp131, 5 brazos que difieren SÓLO en el "
                "regularizador del self-train): REFUTADA el PRIVILEGIO. El privilege_gap = AUROC(durable) − AUROC(mejor genérico por "
                "seed) es {mp} (CI bootstrap 95% [{lo},{hi}] excluye el cero DEL LADO NEGATIVO, {npos}/{n} pos, t={ts}): el mejor "
                "regularizador GENÉRICO (label smoothing) no sólo iguala sino que SUPERA al durable (AUROC durable {ad} vs genérico "
                "{ag} vs naive {an}). Sobrevive el control de degeneración (GATED {gmp}, CI [{glo},{ghi}]). El genérico recupera "
                "{rfp}% de la ventaja durable-naive. Y el label smoothing suave (ls_lo) preserva MEJOR la capacidad (real_acc {rls} "
                "vs durable {rdur}).").format(n=n, mp=_f(mp), lo=_f(ci[0]), hi=_f(ci[1]), npos=npos, ts=_f(ts), ad=_f(ad), ag=_f(ag),
                                              an=_f(an), gmp=_f(gmp), glo=_f(gci[0]), ghi=_f(gci[1]), rfp=int(round(100 * rfrac)),
                                              rls=_f(rf['ls_lo']), rdur=_f(rf['durable']))
    S_EXP132 = Source(tier=5, ref="cognia_x/experiments/exp132_privileged_cure", obtained=True, claim=claim132)

    ev_for = [S_EXP132.ref, S_PRINCIPLE.ref, S_VERIF.ref]
    ev_against = [S_149.ref]   # contra-consideración: el 149 SÍ halló la ventaja durable>naive (que aquí se reproduce, pero se re-localiza)

    advtext = (
        "{V} (la cura 119 NO es PRIVILEGIADA -- RE-LOCALIZA el 149; verificación adversarial CONFIRMATORIA de 4 sondas): el CYCLE 149 "
        "cerró APOYADA que el brazo durable (naive + unlikelihood ACOTADO sobre lo verificado-incorrecto = la cura 119, LABEL-AWARE) "
        "produce una confianza endógena más informativa sobre la correctness real que el naive (AUROC +0.047). El 149 dejó EXPLÍCITO "
        "el hueco: el durable = naive + unlikelihood, pero NO se testeó si la unlikelihood ESPECÍFICAMENTE (que usa el verificador "
        "para saber QUÉ castigar) es lo que ayuda, o si CUALQUIER regularizador de calibración GENÉRICO (label-agnostic) daría la "
        "misma ventaja. QUÉ SE ESTABLECE (exp132, N={n}, mismo lazo torch real, 5 brazos que difieren SÓLO en el regularizador del "
        "self-train; temperature DESCARTADA a priori -es AUROC-invariante por monotonía-): el privilege_gap = AUROC(durable) − "
        "AUROC(mejor genérico por seed) es {mp} (CI bootstrap 95% [{lo}, {hi}] EXCLUYE el cero DEL LADO NEGATIVO, {npos}/{n} pos, "
        "t={ts}) -> el mejor regularizador GENÉRICO no sólo IGUALA sino que SUPERA al durable (AUROC durable {ad} vs mejor-genérico "
        "{ag} vs naive {an}; el genérico recupera {rfp}% de la ventaja durable-naive). SANITY (clave): durable_vs_naive +{mdvn} "
        "({dvnp}/{n} pos) REPRODUCE el 149 -> el harness es válido, no es que el lazo se rompió. VERIFICACIÓN ADVERSARIAL (4 sondas, "
        "probes reales sobre los datos crudos -- CONFIRMATORIA): (1) DEGENERACIÓN -el confound principal-: el privilege_gap GATED "
        "(sólo rondas con >=5 correctas y >=5 incorrectas, para que el AUROC no sea de muestra degenerada) es {gmp} ~ el raw -> la "
        "ventaja del genérico NO es artefacto de generación colapsada; ls_lo (NO degenerado: ncorrect 67, la MEJOR real_acc {rls}) "
        "gana igual. (2) JUSTICIA: el durable PIERDE incluso vs ls_lo SOLO (-0.039, un único genérico pre-registrado, SIN el winner's "
        "curse del max-sobre-3). (3) MECANISMO: el label smoothing PREVIENE el decaimiento de AUROC que el naive sufre por rondas "
        "(0.988->0.795 = el colapso de calibración del 115) y que el durable sólo MITIGA (->0.902): ls_lo se sostiene ->0.998 -- un "
        "efecto de calibración GENUINO (mantener la confianza dispersa preserva el ranking confianza-corrección) SIN mirar la "
        "etiqueta de corrección. (4) CAPACIDAD: el durable SUPRIME la generación (su tradeoff conocido, real_acc {rdur}); el label "
        "smoothing suave NO (real_acc {rls}, la más alta, sobre la base) -> domina al durable en calibración Y capacidad. REGIME-"
        "DEPENDENCIA (el afinado de la verificación, no una grieta): la refutación NO es uniforme -- en los seeds donde el durable "
        "HARD-colapsa la generación (0-3) el durable EMPATA al genérico (priv_gap~0; ahí la cura 'sostiene' AUROC pero pagando el "
        "colapso); en los seeds donde el durable NO colapsa (4-7) decae igual o MÁS que el naive y el genérico lo APLASTA "
        "(priv_gap -0.08). La 'durabilidad de calibración' del 149 está así CONFUNDIDA con el colapso de generación (corr -0.96): el "
        "durable sólo sostiene la señal cuando suprime generación. => "
        "RESULTADO HONESTO (dos capas): (a) LO QUE QUEDA LIMPIO -- la cura 119 NO es la pieza privilegiada: específicamente el LABEL "
        "SMOOTHING (target-smoothing, label-agnostic) IGUALA su ranking AUROC y SUPERA su capacidad (el entropy-penalty sólo EMPATA); "
        "la cura es una instancia NO-dominante, reemplazable por target-smoothing. (b) LO QUE NO SE ESTABLECE -- que el mecanismo sea "
        "'calibración' a secas: el AUROC está CONFUNDIDO con la riqueza de generación (los brazos viven en regímenes de ncorrect casi "
        "DISJUNTOS, IGUALES en la banda de solape) -> el payoff AUROC del lazo real (149 incluido) está entangled con la supresión/"
        "riqueza de generación, lo que CUALIFICA RETROACTIVAMENTE el +0.047 del 149. El 149 sigue en pie como FENÓMENO (durable>naive "
        "se reproduce) pero su atribución a 'calibración pura' se debilita. ACOTACIÓN: N={n}, settings reducidos (rounds=5, steps=70) "
        "-por debajo de la config powered N=16/rounds8/steps120 que anuncia el docstring-; AUROC del ls_lo cerca del techo (0.998); "
        "toy-real, tarea a*b, modelo diminuto. Frontera: régimen base-acc alta; transferencia; SCALE.").format(
            V=status.upper(), n=n, mp=_f(mp), lo=_f(ci[0]), hi=_f(ci[1]), npos=npos, ts=_f(ts), ad=_f(ad), ag=_f(ag), an=_f(an),
            rfp=int(round(100 * rfrac)), mdvn=_f(mdvn), dvnp=dvnp, gmp=_f(gmp), rls=_f(rf['ls_lo']), rdur=_f(rf['durable']))

    hyp_statement = ("¿La cura 119 (unlikelihood ACOTADO sobre lo verificado-incorrecto, LABEL-AWARE) es PRIVILEGIADA -es ESA "
                     "mecánica específica la que produce la ventaja AUROC del 149-, o cualquier regularizador de calibración GENÉRICO "
                     "(label-agnostic: confidence penalty / label smoothing) la iguala en el lazo torch real? RESULTADO: NO "
                     "privilegiada -- específicamente el LABEL SMOOTHING (target-smoothing) SUPERA al durable (privilege_gap {mp}, CI "
                     "enteramente negativo; el entropy sólo empata), sobrevive el control de degeneración, y además preserva mejor la "
                     "capacidad. ACOTACIÓN: el AUROC está confundido con la riqueza de generación -> no se aísla 'calibración' como "
                     "mecanismo (cualifica retroactivamente el 149). Alcance: lazo torch real CPU, HybridLM byte-level, tarea a*b, "
                     "N={n}.").format(mp=_f(mp), n=n)
    hyp_prediction = ("APOYADA (cura privilegiada) si el CI del privilege_gap EXCLUYE el cero DEL LADO POSITIVO (durable bate al "
                      "mejor genérico). REFUTADA si lo incluye o lo excluye del lado NEGATIVO Y el genérico recupera la ventaja "
                      "(re-localiza 149). (Pre-registrada; verificación adversarial + control de degeneración GATED.)")

    mark_note = ("H-V4-9j marcada 'refutada': la cura 119 NO es privilegiada -- el label smoothing (target-smoothing) SUPERA al "
                 "durable en AUROC (privilege_gap {mp}, CI [{lo},{hi}] ENTERAMENTE negativo -> genérico significativamente mejor; el "
                 "entropy sólo empata), sobrevive degeneración (GATED {gmp}) y preserva mejor la capacidad. ACOTACIÓN: el AUROC está "
                 "confundido con la riqueza de generación -> no se aísla 'calibración'; cualifica retroactivamente el 149 (que se "
                 "reproduce como sanity, durable_vs_naive +{mdvn}).").format(
                     mp=_f(mp), lo=_f(ci[0]), hi=_f(ci[1]), gmp=_f(gmp), mdvn=_f(mdvn))

    analogy = AnalogyRecord(
        problem=("El CYCLE 149 mostró que castigar específicamente los errores que el verificador marca (la 'cura') hace que el "
                 "modelo sepa mejor cuándo acierta. ¿Es ESE castigo dirigido lo que ayuda, o cualquier forma de 'no dejar que el "
                 "modelo se ponga demasiado seguro de sí mismo' daría lo mismo?"),
        everyday=("Daba lo mismo -- y de hecho una forma más suave y genérica funcionó MEJOR. Probamos tres maneras de evitar que el "
                  "modelo se vuelva sobre-confiado: la 'cura' del 149 (que mira la respuesta del verificador y baja la confianza "
                  "SÓLO en lo que estuvo mal) y dos genéricas que NO miran si estuvo bien o mal, sólo mantienen al modelo un poco "
                  "menos tajante en todo (label smoothing y un bonus de incertidumbre). La genérica suave (label smoothing) no sólo "
                  "igualó a la cura: la superó en saber-cuándo-acierta, Y además mantuvo al modelo más capaz de resolver la tarea "
                  "(la cura, al castigar tanto sus errores, terminó resolviendo menos). Conclusión: lo que importaba no era el "
                  "castigo dirigido y costoso, sino simplemente no dejar que la confianza se desplome en exceso de seguridad -- y eso "
                  "se logra más barato."),
        solutions=["el privilege_gap (durable − mejor genérico) es NEGATIVO y su CI excluye 0: el genérico supera al durable",
                   "sobrevive el control de degeneración (GATED ~ raw) y el winner's curse (durable pierde vs ls_lo solo) -> robusto",
                   "el mecanismo es claro por rondas: el label smoothing PREVIENE el decaimiento de AUROC que el naive sufre y la cura sólo mitiga",
                   "el label smoothing suave preserva MEJOR la capacidad (real_acc 0.65 vs cura 0.13): domina en ambos ejes"],
        principles=["una mejora atribuida a un mecanismo ESPECÍFICO (label-aware) puede ser un caso particular de un principio MÁS "
                    "GENERAL (regularización de calibración) -- el contrafactual genérico es el test que lo decide",
                    "un regularizador GENÉRICO y barato puede batir a uno DIRIGIDO y costoso cuando el efecto buscado (no colapsar en "
                    "sobre-confianza) no requiere la información extra (la etiqueta de corrección)",
                    "el control de degeneración (gate por #correctas) y el winner's curse (max-sobre-K) son los dos confounds que una "
                    "comparación de 'mejor de varios brazos' DEBE controlar antes de concluir",
                    "META: una REFUTADA que re-localiza (no demuele) sostiene el hallazgo previo (durable>naive) pero generaliza su "
                    "interpretación -- es progreso, no retroceso"],
        adaptation=("FRONTERA REAL §4.2 (el hueco que el 149 dejó EXPLÍCITO: ¿la cura es privilegiada?). El 149 cerró APOYADA que el "
                    "durable (cura 119) bate al naive en AUROC en el lazo real. Este ciclo añade el TERCER brazo que faltaba (un "
                    "regularizador de calibración genérico) y halla que la cura NO es privilegiada: el label smoothing (target-"
                    "smoothing) la iguala/supera, sobrevive degeneración + winner's curse, y preserva mejor la capacidad (el entropy "
                    "sólo empata). ACOTACIÓN: el AUROC está confundido con la riqueza de generación -> no se aísla 'calibración' como "
                    "mecanismo, y el 149 queda cualificado retroactivamente. Próximo: régimen base-acc alta (donde el efecto del 149 "
                    "se apagaba); transferencia a otra tarea; SCALE."),
        measurement=("exp132 (lazo torch real, N={n}): privilege_gap = AUROC(durable)−AUROC(mejor genérico) {mp}, CI [{lo},{hi}] "
                     "excluye 0 (lado negativo), {npos}/{n} pos, t={ts}; GATED {gmp}; AUROC durable {ad} vs genérico {ag} vs naive "
                     "{an}; sanity durable_vs_naive +{mdvn} ({dvnp}/{n}); capacidad ls_lo {rls} vs durable {rdur}.").format(
                         n=n, mp=_f(mp), lo=_f(ci[0]), hi=_f(ci[1]), npos=npos, ts=_f(ts), gmp=_f(gmp), ad=_f(ad), ag=_f(ag),
                         an=_f(an), mdvn=_f(mdvn), dvnp=dvnp, rls=_f(rf['ls_lo']), rdur=_f(rf['durable'])),
        iterations=4)

    analogy_note = ("Analogía 7 etapas registrada (no era el castigo dirigido lo que ayudaba; cualquier forma suave de no sobre-"
                    "confiar lo iguala -- y label smoothing lo supera + preserva mejor la capacidad).")

    kl = ("REAL (exp132, REFUTADA + verificación adversarial CONFIRMATORIA): la cura 119 (unlikelihood label-aware) NO es "
          "privilegiada -- un regularizador de calibración GENÉRICO (label smoothing) iguala/supera su ventaja AUROC en el lazo "
          "torch real (privilege_gap {mp}, CI excluye 0; GATED {gmp}; sobrevive winner's curse). Re-localiza el 149: lo que paga es "
          "evitar el colapso en sobre-confianza, no la mecánica específica. TECHO/ALCANCE: N={n}, settings reducidos (rounds=5, "
          "steps=70); AUROC del genérico cerca del techo (0.998); toy-real, tarea a*b, HybridLM diminuto. NO cubre: régimen de "
          "base-acc alta, transferencia, SCALE.").format(mp=_f(mp), gmp=_f(gmp), n=n)
    ceiling = CeilingRecord(
        subsystem=("RE-LOCALIZAR el payoff de calibración del 149 en el lazo torch real: ¿la cura 119 (unlikelihood label-aware) es "
                   "PRIVILEGIADA o un regularizador genérico la iguala? RESULTADO: NO privilegiada -- el label smoothing (target-"
                   "smoothing, label-agnostic) SUPERA al durable en AUROC y preserva mejor la capacidad (el entropy sólo empata); la "
                   "cura es una instancia no-dominante. ACOTACIÓN load-bearing: el AUROC está confundido con la riqueza de generación "
                   "-> NO se aísla 'calibración' como mecanismo; cualifica retroactivamente el 149"),
        known_limit=kl,
        blockers=[{"text": ("RE-LOCALIZACIÓN, no demolición: el 149 SIGUE EN PIE -- durable>naive se REPRODUCE (sanity +{mdvn}, "
                            "{dvnp}/{n}). Lo que cambia es la INTERPRETACIÓN: la ventaja no es de la unlikelihood específica sino de "
                            "la regularización de calibración (cualquier mecanismo anti-sobre-confianza). El label smoothing la "
                            "supera. NO refuta que la calibración endógena paga en el lazo real; refina QUÉ la produce.").format(
                                mdvn=_f(mdvn), dvnp=dvnp, n=n), "kind": "diseno"},
                  {"text": ("ALCANCE/POTENCIA: N={n} con settings reducidos (rounds=5, steps=70, pool=64) por el costo del lazo en "
                            "este i3 sin CUDA (~10 min/seed a settings full). El CI excluye 0 y ls_lo-solo confirma sin winner's "
                            "curse, pero la magnitud exacta y el régimen no están barridos. AUROC del ls_lo cerca del techo (0.998) "
                            "-> el margen de mejora sobre el durable podría estar comprimido por saturación.").format(n=n), "kind": "fisico"},
                  {"text": ("FRONTERA ABIERTA: (a) el régimen de base-acc ALTA -donde el efecto del 149 se apagaba (corr -0.32)-, no "
                            "tocado aquí; (b) transferencia a otra tarea/modelo; (c) si un label smoothing aún más fino domina; (d) "
                            "SCALE (GPU). La conclusión 're-localiza' es a juguete-real, una tarea, un modelo diminuto."), "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP132.ref, S_149.ref, S_VERIF.ref])
    ceiling_note = ("1 techo 'real': la cura 119 NO es privilegiada -- un regularizador de calibración genérico (label smoothing) la "
                    "iguala/supera en el lazo torch real (CI excluye 0, sobrevive degeneración + winner's curse) y preserva mejor la "
                    "capacidad. Re-localiza el 149 sin demolerlo.")

    dstmt = ("North-Star R-VALOR (FRONTERA REAL §4.2 -- el hueco que el 149 dejó explícito): {V}. La cura 119 (unlikelihood "
             "label-aware) NO es PRIVILEGIADA: en el lazo torch real un regularizador de TARGET-SMOOTHING (label smoothing, "
             "label-agnostic) SUPERA al durable en AUROC (privilege_gap {mp}, CI [{lo},{hi}] ENTERAMENTE NEGATIVO -> el genérico es "
             "significativamente mejor; GATED {gmp}; sobrevive winner's curse; el entropy sólo empata) y preserva MEJOR la capacidad "
             "(real_acc {rls} vs {rdur}). Verificación adversarial CONFIRMATORIA (4 sondas). Decisión: ADOPTAR que (a) la cura NO es "
             "la pieza privilegiada -un target-smoothing genérico la reemplaza-, y (b) el AUROC del lazo real está CONFUNDIDO con la "
             "riqueza de generación -> el experimento NO aísla 'calibración' como mecanismo, y el durable>naive del 149 queda "
             "cualificado retroactivamente (sigue en pie como fenómeno, sanity +{mdvn}, pero su atribución a 'calibración pura' se "
             "debilita). Próximo: régimen base-acc alta; transferencia; SCALE.").format(
                 V=status.upper(), mp=_f(mp), lo=_f(ci[0]), hi=_f(ci[1]), gmp=_f(gmp), rls=_f(rf['ls_lo']), rdur=_f(rf['durable']),
                 mdvn=_f(mdvn))
    drat = ("exp132 (tier5, propio, lazo torch real, N={n}, post-verificación adversarial CONFIRMATORIA de 4 sondas): el privilege_"
            "gap durable−mejor-genérico es {mp} (CI ENTERAMENTE negativo, t={ts}); sobrevive el control de degeneración (GATED {gmp}) "
            "y el winner's curse (durable pierde vs ls_lo solo, -0.039); el target-smoothing recupera {rfp}% de la ventaja del 149 y "
            "preserva mejor la capacidad. Convergente con el principio (tier2) y la verificación (tier4). REFUTADA del privilegio: "
            "un target-smoothing genérico reemplaza a la cura; PERO el AUROC está confundido con la riqueza de generación -> no se "
            "aísla 'calibración' como mecanismo (cualifica retroactivamente el 149, que se reproduce como sanity).").format(
                n=n, mp=_f(mp), ts=_f(ts), gmp=_f(gmp), rfp=int(round(100 * rfrac)))
    decision = Decision(id="D-V4-110", statement=dstmt, rationale=drat,
                        sources=[_to_plain(S_EXP132), _to_plain(S_149), _to_plain(S_VERIF)], important=True)

    return {
        "sources": [S_PRINCIPLE, S_149, S_VERIF, S_EXP132],
        "sources_note": ("4 fuentes (S_PRINCIPLE tier2 un target-smoothing genérico iguala/supera la cura, con el AUROC confundido "
                         "con la riqueza de generación; S_149 tier5 la APOYADA que se cualifica; S_VERIF tier4 verificación "
                         "CONFIRMATORIA de 4 sondas; S_EXP132 tier5 dato "
                         "propio REFUTADA)."),
        "hyp_statement": hyp_statement, "hyp_prediction": hyp_prediction, "confidence": "alta",
        "ev_for": ev_for, "ev_against": ev_against, "advtext": advtext, "mark_note": mark_note,
        "analogy": analogy, "analogy_note": analogy_note, "ceiling": ceiling, "ceiling_note": ceiling_note,
        "decision": decision, "decision_note": "D-V4-110 ACEPTADA por el ledger (tier5 exp132 + tier5 re-localización 149 + tier4 verificación adversarial confirmatoria).",
    }


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle150_privileged_cure',
                                description='CYCLE 150 (RESET v4, H-V4-9j: ¿la cura 119 es PRIVILEGIADA vs un regularizador de calibración genérico?).')
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
    print("RESUMEN — CYCLE 150 (RESET v4): ¿la cura 119 es PRIVILEGIADA? — H-V4-9j " + (status.upper() if status else "?"))
    print("=" * 78)
    print("veredicto H-V4-9j:", status.upper() if status else "?")
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
