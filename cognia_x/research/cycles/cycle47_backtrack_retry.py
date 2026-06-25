r"""
cycle47_backtrack_retry.py — CICLO 47 (RESET v4): H-V4-1l por las compuertas del engine.

H-V4-1l: ¿reintentar un paso que no verificó (RETRY: segunda tanda desde el pool, en vez de abstener la cadena
entera) recupera COBERTURA sin perder PRECISIÓN, a IGUAL presupuesto total? Ataca el colapso de cobertura de
exp032 (CYCLE 46). DERIVA de exp033_backtrack_retry/results/results.json.

RESULTADO REAL: MIXTA (recupera cobertura, pero la UTILIDAD está gateada por el verificador; 4 seeds). Curva
K|vn->ABST_cov/RETRY_cov(Δcov) prec:
  2|0.0:0.54/0.54(+0.00)p1.00  2|0.1:0.73/0.73(+0.00)p0.57  4|0.1:0.62/0.69(+0.08)p0.28  6|0.0:0.30/0.37(+0.07)p1.00
  6|0.1:0.51/0.70(+0.19)p0.18  6|0.2:0.75/0.86(+0.11)p0.04
  - RETRY recupera cobertura material en cadenas largas (Δcov +0.19 a K6/vn0.1, +0.11 a K6/vn0.2) SIN bajar la
    precisión (prec_drop<=0) -> cumple literalmente la condición pre-registrada.
  - PERO su VALOR está gateado por la calidad del verificador: donde recupera MUCHO (ruido alto) la precisión
    absoluta es BAJA (0.18, 0.04 = rescata cadenas confiadamente-MAL); donde la precisión es alta (vn=0) el
    gain es sub-margen (+0.07 < 0.10). No hay régimen con Δcov>=0.10 Y precisión útil (>=0.5).
  => backtracking/retry NO resuelve el colapso de cobertura de forma útil: recupera cobertura sin dañar
     precisión, pero la cobertura recuperada es tan fiable como el verificador la permita. El fix real del
     colapso sigue siendo la PRECISIÓN POR PASO (mejor modelo/verificador), no insistir.

NOTA DE MÉTODO (honesta): el piso de precisión útil (retry_prec>=0.5) NO estaba en la pre-registración; se
agregó al ver que a ruido alto se rescataban cadenas mal. Se REPORTA explícitamente y NO se usa para forzar un
REFUTADA: la pre-registración (Δcov>=0.10 sin caída de precisión) SÍ se cumple en el régimen duro -> por eso
MIXTA (recupera) y no REFUTADA; el piso sólo impide el APOYADA limpio.

Correr (DESPUÉS de exp033):
    venv312\Scripts\python.exe -m cognia_x.experiments.exp033_backtrack_retry.run
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle47_backtrack_retry
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
                             'cycle47_backtrack_retry')
DEFAULT_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                               'experiments', 'exp033_backtrack_retry', 'results', 'results.json')


def _safe_utf8():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _to_plain(obj):
    return to_dict(obj) if dataclasses.is_dataclass(obj) else dict(obj)


def _fmt(x):
    return "{:.3f}".format(x) if isinstance(x, (int, float)) else str(x)


S_BT = Source(tier=1, ref="search-backtracking-reasoning", obtained=False,
              claim=("Reintentar/backtrack en razonamiento (Tree-of-Thoughts, self-refine) recupera soluciones "
                     "que un único intento abandona, a costa de cómputo. (Principio, no re-obtenido esta sesión.)"))
S_EXP032 = Source(tier=5, ref="cognia_x/experiments/exp032_abstention_noisy", obtained=True,
                  claim=("exp032 (CYCLE 46): abstenerse al primer paso fallido sube la precisión pero la "
                         "cobertura COLAPSA en cadenas largas (abstiene todo)."))


def run(store, results_path):
    with open(results_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    v = data.get('verdict')
    st = data.get('stats')
    if not v or not st:
        raise SystemExit("results.json sin verdict/stats (corre exp033 primero): " + results_path)
    status = v.lower()
    curve = st['curve']
    hard = st['at_hard']
    best_key = st['best_regime']
    best = st['best']
    floor = st.get('prec_floor', 0.5)
    n_seeds = st['n_seeds']

    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)
    notes = []

    S_EXP033 = Source(tier=5, ref="cognia_x/experiments/exp033_backtrack_retry", obtained=True,
                      claim=("exp033 (propio, {n} seeds, modelo HybridLM, cadena mod 20, verificador ruidoso "
                             "per-step): RETRY del paso fallido recupera cobertura material en cadenas largas "
                             "(régimen duro K{km}/vn{vm}: Δcov={dc} sin bajar precisión) PERO su utilidad está "
                             "gateada por el verificador: donde recupera mucho la precisión es baja (rescata "
                             "cadenas confiadamente-mal); donde la precisión es alta el gain es sub-margen.").format(
                                 n=n_seeds, km=st['Kmax'], vm=st['vmod'], dc="%+.3f" % hard['cov_gain']))
    for src in (S_BT, S_EXP032, S_EXP033):
        ledger.add_source(src)
    notes.append("3 fuentes (S_BT tier1 backtracking/retry; S_EXP032 tier5 colapso de cobertura; S_EXP033 tier5 dato propio).")

    ev_for = [S_EXP033.ref]          # SÍ recupera cobertura sin dañar precisión (cumple lo pre-registrado)
    ev_against = [S_EXP033.ref, S_EXP032.ref]   # pero la cobertura recuperada es tan fiable como el verificador
    adv = ("MIXTA. A FAVOR (cumple lo pre-registrado): RETRY del paso fallido recupera COBERTURA material en "
           "cadenas largas — régimen duro [K{km}/vn{vm}]: ABSTAIN cov {ac} -> RETRY cov {rc} (Δcov {dc}) SIN "
           "bajar la precisión (prec_drop {pd}). El mecanismo funciona: insistir desde el pool rescata cadenas "
           "que la abstención abandonaba por un solo paso. EN CONTRA (la razón del MIXTA): la cobertura "
           "recuperada es tan fiable como el verificador la permita -> donde RETRY recupera MUCHO (ruido alto: "
           "K6/vn0.1 Δcov+0.19, K6/vn0.2 Δcov+0.11) la precisión absoluta es BAJA ({rp}: rescata cadenas "
           "confiadamente-MAL); donde la precisión es alta (vn=0) el gain es sub-margen (+0.07<0.10). No hay "
           "régimen con Δcov>=0.10 Y precisión útil (>={fl}). NOTA DE MÉTODO HONESTA: el piso de precisión útil "
           "(retry_prec>={fl}) NO estaba pre-registrado; se agregó al ver el rescate de basura y se REPORTA "
           "explícitamente; NO se usó para forzar un REFUTADA (la pre-registración Δcov>=0.10 sin caída de "
           "precisión SÍ se cumple -> MIXTA, no REFUTADA; el piso sólo impide el APOYADA limpio). LECCIÓN: "
           "backtracking/retry no resuelve el colapso de cobertura de forma ÚTIL; el fix real es la PRECISIÓN "
           "POR PASO (mejor modelo/verificador), no insistir. Conecta de nuevo con 41/43/46: todo depende del "
           "verificador.").format(
               km=st['Kmax'], vm=st['vmod'], ac=_fmt(hard['abstain_cov']), rc=_fmt(hard['retry_cov']),
               dc="%+.3f" % hard['cov_gain'], pd="%+.3f" % (-hard['prec_drop']), rp=_fmt(hard['retry_prec']), fl=_fmt(floor))

    hyp = Hypothesis(
        id="H-V4-1l",
        statement=("Reintentar el paso fallido (RETRY desde el pool) en vez de abstener la cadena recupera "
                   "cobertura sin perder precisión, a igual presupuesto total."),
        prediction=("APOYADA si Δcov>=0.10 con prec_drop<=0.10 Y la cobertura recuperada es útil (precisión "
                    ">=0.5); MIXTA si recupera cobertura sin dañar precisión pero su utilidad está gateada por "
                    "el verificador; REFUTADA si no recupera o hunde la precisión. (Pre-registrada + nota de "
                    "método sobre el piso de utilidad.)"),
        status='abierta', confidence='alta',
        evidence_for=ev_for, evidence_against=ev_against,
        adversarial_verdict=adv, experiment_ref="exp033_backtrack_retry")
    hyps.add(hyp)
    if status in ('apoyada', 'refutada', 'mixta'):
        {'apoyada': hyps.mark_supported, 'refutada': hyps.mark_refuted, 'mixta': hyps.mark_mixta}[status]("H-V4-1l")
        notes.append("H-V4-1l marcada '{}' con DoD completo.".format(status))

    analogy = AnalogyRecord(
        problem=("En la cuenta larga, si un paso no te sale al primer intento, ¿tirás toda la cuenta o insistís "
                 "en ese paso? ¿Y sirve insistir si tu 'sensación de que está bien' (el verificador) falla?"),
        everyday=("Insistir en el paso difícil RESCATA cuentas que abandonabas por un solo tropiezo (recuperás "
                  "cobertura). Pero si tu corrector interno se equivoca, insistir sólo te hace 'completar' la "
                  "cuenta con un número que CREÉS bueno y está mal: más cuentas entregadas, pero no más "
                  "correctas. Insistir ayuda sólo si el corrector es confiable."),
        solutions=["RETRY (insistir en el paso fallido) -> recupera cobertura (Δcov +0.19 a K6/vn0.1) sin dañar precisión",
                   "ABSTAIN (rendirse al primer fallo) -> precisión alta pero cobertura colapsa en cadenas largas",
                   "con verificador RUIDOSO, lo recuperado por RETRY es poco fiable (precisión baja = basura)",
                   "con verificador PERFECTO, RETRY recupera poco (los fallos son pasos genuinamente difíciles)"],
        principles=["reintentar recupera cobertura sin dañar precisión, pero su VALOR depende de la calidad del verificador",
                    "rescatar cobertura no sirve si lo rescatado es confiadamente-incorrecto (verificador ruidoso)",
                    "el colapso de cobertura no se arregla insistiendo: el fix real es la precisión POR PASO",
                    "todo el integrador multi-paso converge a lo mismo: la calidad del verificador es el cuello de botella"],
        adaptation=("El integrador puede ofrecer RETRY como recuperación de cobertura, pero sólo paga con un "
                    "verificador confiable (o la política calibrada de 43 decidiendo cuándo insistir). El "
                    "verdadero próximo lever NO es más recuperación sino MEJORAR la precisión por paso: mejor "
                    "modelo base / verificador real-chequeable (código→sandbox)."),
        measurement=("exp033: régimen duro [K{km}/vn{vm}] ABSTAIN cov {ac} -> RETRY cov {rc} (Δcov {dc}), "
                     "precisión {rp}; mejor régimen [{bk}]. {n} seeds.").format(
                         km=st['Kmax'], vm=st['vmod'], ac=_fmt(hard['abstain_cov']), rc=_fmt(hard['retry_cov']),
                         dc="%+.3f" % hard['cov_gain'], rp=_fmt(hard['retry_prec']), bk=best_key, n=n_seeds),
        iterations=2)
    extract_principles(analogy)
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas registrada (insistir en el paso difícil rescata cobertura, pero sólo sirve si el corrector es confiable).")

    ceilings.add(CeilingRecord(
        subsystem="Multi-paso — BACKTRACKING/RETRY recupera cobertura pero su utilidad está gateada por el verificador",
        known_limit=("REAL (exp033): RETRY del paso fallido recupera cobertura material en cadenas largas (Δcov "
                     "{dc} a K{km}/vn{vm}) SIN dañar precisión, PERO la cobertura recuperada es tan fiable como "
                     "el verificador: a ruido alto rescata cadenas confiadamente-MAL (precisión {rp}); a "
                     "verificador perfecto el gain es sub-margen. El colapso de cobertura NO se arregla "
                     "insistiendo.").format(dc="%+.3f" % hard['cov_gain'], km=st['Kmax'], vm=st['vmod'], rp=_fmt(hard['retry_prec'])),
        blockers=[{"text": "la cobertura recuperada hereda la precisión del régimen (verificador); RETRY no la mejora -> el cuello de botella es la PRECISIÓN POR PASO", "kind": "diseno"},
                  {"text": "el verdadero lever pendiente es mejor precisión por paso: mejor modelo base + verificador real-chequeable (código→sandbox), no más recuperación", "kind": "diseno"},
                  {"text": "decidir CUÁNDO insistir vs abstener debería usar la fiabilidad estimada del verificador (política de 43), no insistir siempre", "kind": "diseno"}],
        real_or_assumed="real", evidence=[S_EXP033.ref, S_EXP032.ref]))
    notes.append("1 techo 'real': RETRY recupera cobertura sin dañar precisión, pero su utilidad está gateada por el verificador (no arregla el colapso).")

    dstmt = ("Cierra el barrido de mecanismos del integrador multi-paso (44-47): la verificación de PROCESO "
             "frena el compounding (44), el presupuesto ADAPTATIVO per-step rescata cadenas largas (45), la "
             "ABSTENCIÓN sube la precisión-sobre-respondidas (46) y el BACKTRACKING/RETRY recupera cobertura "
             "(47) — PERO los cuatro convergen al mismo cuello de botella: la CALIDAD/PRECISIÓN del verificador "
             "y del paso. RETRY recupera cobertura sin dañar precisión, pero lo recuperado es tan fiable como el "
             "verificador (a ruido alto rescata basura). Decisión: el próximo lever del integrador NO es más "
             "orquestación de cómputo sino MEJORAR la precisión por paso — mejor modelo base y/o verificador "
             "REAL-chequeable (código→sandbox, exp018) en vez del sintético. Esto reorienta el roadmap del "
             "integrador hacia el sustrato (modelo + verificador real), no hacia más control de cómputo.")
    drat = ("exp033 (tier5, propio, {n} seeds): RETRY recupera cobertura (Δcov {dc} a K{km}/vn{vm}) sin dañar "
            "precisión, pero gateado por el verificador (precisión {rp} a ruido alto = rescata mal; sub-margen a "
            "vn=0). MIXTA con nota de método (piso de utilidad post-hoc, reportado). Convergente con "
            "backtracking en razonamiento y con 41/43/46.").format(
                n=n_seeds, dc="%+.3f" % hard['cov_gain'], km=st['Kmax'], vm=st['vmod'], rp=_fmt(hard['retry_prec']))
    dec = Decision(id="D-V4-12", statement=dstmt, rationale=drat,
                   sources=[_to_plain(S_EXP033), _to_plain(S_EXP032)], important=True)
    try:
        ledger.record_decision(dec)
        notes.append("D-V4-12 ACEPTADA por el ledger (tier5 exp033 + tier5 exp032).")
    except OpinionOnlyError as e:
        print("ERROR ledger D-V4-12:", e); raise

    return record, notes, status, st


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(prog='python -m cognia_x.research.cycles.cycle47_backtrack_retry',
                                description='CYCLE 47 (RESET v4, H-V4-1l: backtracking/retry del paso fallido).')
    p.add_argument('--store', default=DEFAULT_STORE)
    p.add_argument('--results', default=DEFAULT_RESULTS)
    p.add_argument('--reset', dest='reset', action='store_true', default=True)
    p.add_argument('--no-reset', dest='reset', action='store_false')
    args = p.parse_args(argv)
    store = os.path.abspath(args.store)
    if args.reset and os.path.isdir(store):
        shutil.rmtree(store)
    os.makedirs(store, exist_ok=True)
    record, notes, status, st = run(store, os.path.abspath(args.results))
    res = record.verify_no_loss()
    print("=" * 78)
    print("RESUMEN — CYCLE 47 (RESET v4): backtracking/RETRY del paso fallido (H-V4-1l)")
    print("=" * 78)
    print("veredicto H-V4-1l:", status.upper() if status else "?")
    print("  RETRY recupera cobertura sin dañar precisión, pero su utilidad está gateada por el verificador.")
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
