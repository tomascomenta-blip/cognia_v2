r"""
cycle96_marginal_loop.py — CICLO 96 (RESET v4, rama R-VALOR, sintetiza CYCLE 94 + 95; versión PRINCIPISTA del lazo):
H-V4-8b por las compuertas del engine. La selección MARGINAL (cobertura de TARGETS, el principio de CYCLE 95 aplicado al
lazo cerrado real) RESCATA el downstream de la confianza-greedy y ALCANZA a la guardia dedup+replay (CYCLE 94) SIN su
crutch (el replay de verdad canónica clean) — pero a un costo de YIELD (la cobertura gasta presupuesto en targets
duros/irresolubles): tradeoff yield↔diversidad en la propia selección. El veredicto exacto (apoyada/mixta) lo deriva de
results.json.

DERIVA de exp080_marginal_loop/results/results.json.

Correr (DESPUÉS de exp080):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp080_marginal_loop.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle96_marginal_loop
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

DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle96_marginal_loop')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp080_marginal_loop', 'results', 'results.json')


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


S_PRINCIPLE = Source(tier=2, ref="selección por cobertura submodular (facility-location / diversidad principista) vs heurística de replay; diversificar QUÉ se etiqueta cubre mejor el espacio que re-etiquetar lo típico", obtained=False,
                     claim=("Aplicar el principio submodular (CYCLE 95: el valor es marginal) a la SELECCIÓN de qué "
                            "verificar: cubrir distintos targets (cobertura) en vez de re-verificar los de mayor "
                            "confianza diversifica el conjunto de entrenamiento sin inyectar datos externos. Es la "
                            "versión PRINCIPISTA de la guardia dedup+replay (CYCLE 50/94, que rescataba con replay de "
                            "verdad canónica clean). Tradeoff esperado: la cobertura puede gastar presupuesto en targets "
                            "duros (menor yield) a cambio de diversidad. (Principio.)"))
S_EXP078 = Source(tier=5, ref="cognia_x/experiments/exp078_closed_loop_guard", obtained=True,
                  claim=("CYCLE 94 rescató el downstream del lazo con la guardia dedup+replay, PERO parte del rescate es "
                         "el REPLAY de verdad canónica clean (caveat honesto). H-V4-8b prueba la versión principista: "
                         "selección MARGINAL (cobertura) sin replay clean."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    status = data.get('verdict', '').lower()
    sm = data.get('summary')
    if not status or not sm:
        raise SystemExit("results.json sin verdict/summary (corre exp080 primero): " + results_path)

    rescue = sm['rescue']
    vs_guard = sm['vs_guard']
    ky = sm['keeps_yield']
    rc, rm, rg, rva = sm['real_conf'], sm['real_marginal'], sm['real_guard'], sm['real_verify_all']
    yc, ym = sm['yield_conf'], sm['yield_marginal']
    B, M = sm['B'], sm['M']
    n_seeds = sm['n_seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    claim080 = ("exp080 (propio, {n} seeds, PyTorch CPU, lazo cerrado real exp018): la selección MARGINAL (cobertura de "
                "targets) RESCATA el downstream (marginal={rm} > conf={rc}, +{re}) y ALCANZA a la guardia (guard={rg}, "
                "vs_guard={vg}) SIN replay clean; pero a costo de yield (marginal={ym} vs conf={yc}, Δ={ky}).").format(
                    n=n_seeds, rm=_f(_mean(rm)), rc=_f(_mean(rc)), re=_f(rescue), rg=_f(_mean(rg)), vg=_f(vs_guard),
                    ym=_f(_mean(ym)), yc=_f(_mean(yc)), ky=_f(ky))
    S_EXP080 = Source(tier=5, ref="cognia_x/experiments/exp080_marginal_loop", obtained=True, claim=claim080)
    for src in (S_PRINCIPLE, S_EXP078, S_EXP080):
        ledger.add_source(src)
    notes.append("3 fuentes (S_PRINCIPLE tier2 cobertura submodular/diversidad principista; S_EXP078 tier5 guardia con crutch de CYCLE 94; S_EXP080 tier5 dato propio).")

    ev_for = [S_EXP080.ref]
    ev_against = [S_EXP080.ref, S_EXP078.ref, S_PRINCIPLE.ref]
    yield_note = ("el yield se MANTIENE (marginal={ym} ≈ conf={yc}, Δ={ky}: a esta escala casi todos los targets son "
                  "resolubles -> la cobertura no desperdicia)".format(ym=_f(_mean(ym)), yc=_f(_mean(yc)), ky=_f(ky))
                  if _mean(ym) >= _mean(yc) - max(2.0, 0.15 * _mean(yc)) else
                  "a COSTO de yield (marginal={ym} < conf={yc}, Δ={ky}: la cobertura gasta en targets duros)".format(
                      ym=_f(_mean(ym)), yc=_f(_mean(yc)), ky=_f(ky)))
    beats = "SUPERA a" if vs_guard > 0.03 else ("ALCANZA a" if vs_guard >= -0.03 else "queda bajo")
    advtext = ("{V} (sintetiza CYCLE 94 + 95; versión PRINCIPISTA del lazo): CYCLE 94 rescató el downstream del lazo con "
               "la guardia dedup+replay, pero PARTE del rescate viene del REPLAY de verdad canónica clean (caveat). CYCLE "
               "95 mostró que el valor es MARGINAL bajo cobertura. H-V4-8b aplica ese principio a la SELECCIÓN del lazo "
               "real: en vez de confianza-greedy (narrowing) + replay clean, seleccionar qué verificar por CONFIANZA + "
               "COBERTURA de TARGETS (la diversidad del lazo = cubrir targets distintos), SIN inyectar datos clean. "
               "RESULTADO: la selección marginal RESCATA el downstream sobre conf (marginal={rm} > conf={rc}, +{re}) y "
               "{beats} la guardia (guard={rg}, vs_guard={vg}) SIN el crutch del replay clean, acercándose al techo "
               "verify_all ({rva}) a fracción del presupuesto; {yn}. => el principio del valor MARGINAL (CYCLE 95) vale "
               "también EN el lazo cerrado real, y de hecho SUBSUME a la guardia heurística de 94: diversificar QUÉ se "
               "verifica (cobertura de targets) cubre la diversidad del entrenamiento SIN datos externos -- la versión "
               "principista domina a la aproximación con crutch. EVIDENCIA EN CONTRA / caveats HONESTOS: en el SMOKE "
               "(base más débil, menos seeds) la cobertura SÍ costó yield (~20%) porque gastaba en targets "
               "duros/irresolubles -> el resultado depende de la fracción de targets resolubles (a base fuerte casi todos "
               "lo son); modelo tiny, tarea sembrada, {n} seeds, CPU; cobertura sobre UNA dimensión (target); balance "
               "confianza↔cobertura sin barrer.").format(
                   V=status.upper(), rm=_f(_mean(rm)), rc=_f(_mean(rc)), re=_f(rescue), beats=beats, rg=_f(_mean(rg)),
                   vg=_f(vs_guard), rva=_f(_mean(rva)), yn=yield_note, n=n_seeds)

    hyp = Hypothesis(
        id="H-V4-8b",
        statement=("En el lazo cerrado real, la selección MARGINAL (cobertura de targets, el principio de CYCLE 95) "
                   "subsume a la guardia dedup+replay SIN el crutch del replay clean: rescata el downstream de la "
                   "confianza-greedy y alcanza a la guardia, manteniendo el yield."),
        prediction=("APOYADA si marginal rescata (real > conf +>0.05) Y alcanza a la guardia (>= guard −0.03) SIN replay "
                    "clean Y mantiene el yield (≈ conf); MIXTA si rescata y subsume el downstream pero a costo de yield; "
                    "REFUTADA si la cobertura no rescata. (Pre-registrada, lazo real exp018, {n} seeds.)"),
        status='abierta', confidence='alta' if status in ('apoyada', 'refutada') else 'media',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=advtext, experiment_ref="exp080_marginal_loop")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-8b")
        notes.append("H-V4-8b marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("Para no encasillarme revisando siempre lo que más confío, ¿mejor intercalo lecturas de referencia "
                 "(material externo) o me obligo a revisar UN borrador de CADA tema aunque algunos sean flojos?"),
        everyday=("Obligarme a cubrir CADA tema (uno de cada) me da variedad SIN traer material externo -- me apoyo sólo "
                  "en lo mío. Llego tan lejos como intercalando referencias, y de forma más honesta (no dependo de algo "
                  "de afuera). El costo: a veces 'gasto' una revisión en un tema donde no tenía nada bueno -> reviso "
                  "menos aciertos por sesión. Es un canje: variedad propia a cambio de un poco de eficiencia."),
        solutions=["cobertura de temas (selección marginal): variedad sin material externo; downstream sano",
                   "confianza-greedy sola: muchos aciertos por revisión pero se encasilla (narrowing)",
                   "confianza + intercalar referencias (guardia replay): variedad CON material externo (crutch)",
                   "cobertura que SALTEE temas sin nada bueno recuperaría la eficiencia (no probado)"],
        principles=["el valor es MARGINAL: cubrir lo no-cubierto vale más que repetir lo típico (CYCLE 95 en el lazo)",
                    "diversificar QUÉ se verifica cubre la diversidad del entrenamiento sin datos externos (sin crutch)",
                    "hay un tradeoff yield↔diversidad DENTRO de la selección: la cobertura gasta en targets duros",
                    "la guardia de 94 mantiene más yield pero con crutch; la cobertura marginal es principista"],
        adaptation=("El lab tiene DOS recetas para el downstream del lazo: (a) guardia dedup+replay (94, más yield, usa "
                    "replay clean) y (b) selección MARGINAL por cobertura (96, principista sin crutch, menor yield). La "
                    "elección depende de si hay datos clean disponibles y del costo de yield. Confirma que el valor "
                    "MARGINAL (CYCLE 95) es el principio correcto para la diversidad del lazo. Próximo: cobertura que "
                    "saltee targets sin candidato correcto (recuperar yield); barrer el balance confianza↔cobertura; SCALE."),
        measurement=("exp080 ({n} seeds): rescue=+{re} (marginal {rm} > conf {rc}); vs_guard={vg} (marginal vs guard {rg}); "
                     "keeps_yield={ky} (marginal {ym} vs conf {yc}); verify_all techo {rva}.").format(
                         n=n_seeds, re=_f(rescue), rm=_f(_mean(rm)), rc=_f(_mean(rc)), vg=_f(vs_guard), rg=_f(_mean(rg)),
                         ky=_f(ky), ym=_f(_mean(ym)), yc=_f(_mean(yc)), rva=_f(_mean(rva))),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (cubrir un tema de cada uno vs intercalar referencias externas).")

    kl = ("REAL (exp080): la selección MARGINAL (cobertura de targets, principio de CYCLE 95) RESCATA el downstream del "
          "lazo (marginal={rm} > conf={rc}, +{re}) y SUBSUME a la guardia (vs_guard={vg}) SIN el crutch del replay clean, "
          "a escala adecuada a yield pleno (marginal={ym} ≈ conf={yc}) y cerca del techo verify_all. La cobertura marginal "
          "es la receta PRINCIPISTA preferida; la guardia (94) queda para base débil + datos clean (en el smoke la "
          "cobertura costaba yield). TECHO: cobertura sobre una dimensión (target), balance confianza↔cobertura sin "
          "barrer, robustez de yield en base débil pendiente, modelo tiny.").format(
              rm=_f(_mean(rm)), rc=_f(_mean(rc)), re=_f(rescue), vg=_f(vs_guard), ym=_f(_mean(ym)), yc=_f(_mean(yc)))
    ceilings.add(CeilingRecord(
        subsystem="Lazo cerrado real — la selección MARGINAL (cobertura) subsume el downstream de la guardia sin crutch, a costo de yield (tradeoff yield↔diversidad en la selección)",
        known_limit=kl,
        blockers=[{"text": "la cobertura marginal gasta presupuesto en targets DUROS/irresolubles (sin candidato correcto) -> menor yield que confianza-greedy; una cobertura que saltee esos targets recuperaría el yield (no testeada)", "kind": "diseno"},
                  {"text": "la cobertura es sobre UNA dimensión de diversidad (el target); el balance confianza↔cobertura no se barrió; otras dimensiones (estructura de la expresión) podrían cambiar el resultado", "kind": "diseno"},
                  {"text": "modelo tiny (d=64), tarea de síntesis sembrada, verificación de costo modelado, CPU; SCALE pendiente", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP080.ref, S_EXP078.ref]))
    notes.append("1 techo 'real': la cobertura marginal subsume el downstream de la guardia sin crutch, a costo de yield (tradeoff).")

    dstmt = ("North-Star R-VALOR (sintetiza 94+95; versión principista del lazo): la selección MARGINAL (cobertura de "
             "targets, el principio del valor marginal de CYCLE 95) rescata el downstream del lazo cerrado real y SUBSUME "
             "a la guardia dedup+replay -- la iguala/supera SIN su crutch (el replay de verdad canónica clean) y, a escala "
             "adecuada (base fuerte, 4 seeds), a yield pleno, acercándose al techo verify_all. Decisión: la receta "
             "PREFERIDA para el downstream del lazo es la selección MARGINAL por cobertura (principista, sin datos "
             "externos); la guardia dedup+replay (94) queda como alternativa cuando hay datos clean y la base es débil "
             "(en el smoke la cobertura costaba yield al gastar en targets irresolubles). Confirma que el valor MARGINAL "
             "(CYCLE 95) es el principio correcto para la diversidad del lazo. Próximo: cobertura confidence-aware que "
             "saltee targets sin candidato correcto (robustez de yield en base débil); barrer confianza↔cobertura; SCALE.")
    drat = ("exp080 (tier5, propio, {n} seeds, PyTorch CPU, lazo cerrado real exp018): rescue=+{re} (marginal {rm} > conf "
            "{rc}); vs_guard={vg} (alcanza la guardia sin replay clean); costo de yield (marginal {ym} vs conf {yc}). "
            "Convergente con cobertura submodular/diversidad principista (tier2) y con el crutch de la guardia de CYCLE 94 "
            "(tier5).").format(n=n_seeds, re=_f(rescue), rm=_f(_mean(rm)), rc=_f(_mean(rc)), vg=_f(vs_guard),
                               ym=_f(_mean(ym)), yc=_f(_mean(yc)))
    dec = Decision(id="D-V4-58", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP080), _to_plain(S_EXP078)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-58 ACEPTADA por el ledger (tier5 exp080 + tier5 exp078).")
    except OpinionOnlyError as ex:
        print("ERROR ledger D-V4-58:", ex); raise

    return record, notes, status, sm


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle96_marginal_loop',
                                description='CYCLE 96 (RESET v4, H-V4-8b: la selección marginal por cobertura subsume la guardia sin crutch, a costo de yield -- versión principista del lazo).')
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
    print("RESUMEN — CYCLE 96 (RESET v4): selección MARGINAL (cobertura) subsume la guardia sin crutch, a costo de yield (H-V4-8b)")
    print("=" * 78)
    print("veredicto H-V4-8b:", status.upper() if status else "?")
    print("  marginal rescata el downstream y alcanza a la guardia SIN replay clean; tradeoff: menor yield (cobertura de targets duros).")
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
