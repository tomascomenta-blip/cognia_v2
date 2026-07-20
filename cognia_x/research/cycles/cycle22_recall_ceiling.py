r"""
cycle22_recall_ceiling.py — CICLO 22 a través del Investigation Engine (proceso end-to-end).

POR QUÉ: la directiva v2 exige que el método de investigación sea CÓDIGO ejecutable, no narrativa.
Este script POBLA el store del engine con TODOS los registros del CYCLE 22 (fuentes, hipótesis,
analogía, techos, decisión, nota de escalabilidad) PASANDO por las compuertas reales del engine:
  - EvidenceLedger.record_decision  -> rechaza decisiones importantes solo-opinión (OpinionOnlyError).
  - HypothesisRegistry.mark_mixta   -> exige el MISMO DoD que apoyada/refutada (PrematureVerdictError).
  - analogy.extract_principles      -> exige 7 etapas / >=3 soluciones (IncompleteAnalogyError).
  - CeilingTracker.add              -> valida kinds + real_or_assumed (ValueError).
  - PermanentRecord.verify_no_loss  -> "pérdida de conocimiento = fallo" chequeable por contenido.

Reproducibilidad: REINICIA el store del ciclo al arrancar (flag --reset, default True). Re-correr
= mismos registros (idempotente por contenido: los datos son literales verificados, no aleatorios).
Toda cita/número viene de evidencia REAL (papers arXiv + exp002/exp009 corridos); nada inventado.

Correr:
    venv312\Scripts\python.exe -m cognia_x.research.cycles.cycle22_recall_ceiling
Inspeccionar:
    venv312\Scripts\python.exe -m cognia_x.research.cli status   --store <store>
    venv312\Scripts\python.exe -m cognia_x.research.cli verify   --store <store>

Escalabilidad (§6): O(1) por registro escrito (append JSONL journaleado); verify_no_loss es O(n)
sobre el histórico de ESTE store. I/O-bound, trivial en 2c/4t sin GPU; el store es JSON portable.
"""
import argparse
import os
import shutil
import sys

from cognia_x.research.schema import (
    Source, Hypothesis, Decision, AnalogyRecord, CeilingRecord, ScalabilityNote,
)
from cognia_x.research.ledger import EvidenceLedger, OpinionOnlyError
from cognia_x.research.hypotheses import HypothesisRegistry, PrematureVerdictError
from cognia_x.research.analogy import extract_principles, IncompleteAnalogyError
from cognia_x.research.ceiling import CeilingTracker
from cognia_x.research.record import PermanentRecord

# Store por defecto del ciclo: aislado del store general (cognia_x/research/store/) para que
# re-correr el ciclo no contamine ni dependa de otros ciclos. Gitignoreado (store/ del paquete).
DEFAULT_STORE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', 'store', 'cycle22_recall_ceiling'
)


def _safe_utf8():
    # POR QUÉ: en consolas Windows (cp1252) los acentos rompen; intentar UTF-8 sin fallar si no se puede.
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Evidencia VERIFICADA del ciclo (papers arXiv reales + experimentos propios corridos).
# NO inventar ni alterar ninguna cita/número: estos literales son la única fuente.
# ---------------------------------------------------------------------------
S1 = Source(
    tier=1, ref="arXiv:2402.18668", obtained=True,
    claim=("Arora et al. 2024 (Based): tradeoff clave entre tamano del estado recurrente y recall; "
           "modelos de estado fijo (Mamba/RWKV/H3) sufren en recall; Based combina atencion lineal + "
           "ventana deslizante y recorre la frontera de Pareto recall-memoria (+6.22 pts en tareas "
           "recall-intensivas)."),
)
S2 = Source(
    tier=1, ref="arXiv:2508.19029", obtained=True,
    claim=("Okpekpe & Orvieto 2025: la recall recurrente depende de cuan bien se comprime el pasado "
           "en el estado; el limite duro (copia exacta requiere estado proporcional a la longitud, "
           "Jelassi et al.) es real, PERO gran parte de la brecha practica es de OPTIMIZACION (con LR "
           "ajustado Mamba resuelve recall asociativo aun en 1 capa), no de expresividad."),
)
S3 = Source(
    tier=5, ref="cognia_x/experiments/exp002_recall_capacity", obtained=True,
    claim=("exp002 (sin entrenar): recall del mezclador lineal proporcional a d^2 (estado d x d); "
           "atencion full ~ilimitada en N."),
)
S4 = Source(
    tier=5, ref="cognia_x/experiments/exp009_recall_ceiling", obtained=True,
    claim=("exp009 (entrenado, n_heads=1, n_pairs=16, seed0, 6000 steps, chance 0.0625): recall lineal "
           "SUBE con d (0.059@d8 -> 0.168@d16 -> 0.183@d24) y luego SATURA ~0.18 (capacidad ENTRENADA "
           "del feature-map ELU+1 muy por debajo del d^2 ideal); el hibrido solo separa claramente a "
           "d=48 (0.292 vs 0.181, gap +0.111); d=8 es piso de aprendibilidad (ambos en chance)."),
)


def run(store):
    """Puebla el store del engine con los registros del CYCLE 22 a través de las compuertas reales."""
    ledger = EvidenceLedger(store)
    hyps = HypothesisRegistry(store)
    ceilings = CeilingTracker(store)
    record = PermanentRecord(store)

    notes = []  # líneas de CHECK para el RESUMEN final.

    # --- 1) FUENTES (todas obtained=True) -----------------------------------
    for s in (S1, S2, S3, S4):
        ledger.add_source(s)
    notes.append("4 fuentes registradas (S1/S2 tier1 papers; S3/S4 tier5 datos propios).")

    # --- 2) HIPÓTESIS H-CEIL-1 (status='mixta', DoD completo) ---------------
    # evidence_for = [S1,S3,S4]; evidence_against = [S2,S4] (S4 es ambas: apoya la subida con d,
    # refuta que la cota efectiva sea d^2). Se citan las refs (trazables al store de sources).
    hyp = Hypothesis(
        id="H-CEIL-1",
        statement=("El recall asociativo de un mezclador de estado fijo (atencion lineal) esta acotado "
                   "por el tamano de su estado; anadir atencion (estado proporcional a la longitud) lo "
                   "levanta — la frontera recall-throughput."),
        prediction=("Lineal: recall crece con el estado (~d^2) y satura. Hibrido/atencion: recall "
                    "~independiente de la carga. REFUTADO si el lineal mantiene recall alto sin importar "
                    "carga/estado, o el hibrido no supera al lineal en el regimen saturado."),
        status='abierta',  # se transiciona a 'mixta' vía el registro (gate DoD).
        confidence='media',
        evidence_for=[S1.ref, S3.ref, S4.ref],
        evidence_against=[S2.ref, S4.ref],
        adversarial_verdict=(
            "HOLDS direccionalmente (recall escala con el estado; la atencion lo levanta) PERO la cota "
            "EFECTIVA en modelos entrenados chicos es la capacidad del feature-map (<< d^2), no el d^2 "
            "teorico. Distincion real (cota informacional d^2) vs asumido (capacidad entrenada limitada "
            "por optimizacion/feature-map)."),
        experiment_ref="exp009_recall_ceiling",
    )
    hyps.add(hyp)
    # mark_mixta enforza el MISMO DoD (prediction + evidence_for>=1 + evidence_against>=1 +
    # adversarial_verdict + experiment_ref). No bypassea ninguna compuerta.
    h_final = hyps.mark_mixta("H-CEIL-1")
    assert h_final.status == 'mixta', "H-CEIL-1 no quedó 'mixta'"
    notes.append("H-CEIL-1 marcada 'mixta' con DoD completo (gate de veredicto no-prematuro pasado).")

    # --- 3) ANALOGÍA (7 etapas, >=4 soluciones) -----------------------------
    analogy = AnalogyRecord(
        problem=("Un mezclador de estado fijo debe recordar muchos pares clave->valor con una memoria "
                 "de tamano fijo."),
        everyday=("Anotar contactos en una agenda de tamano fijo (cuadernito de pocas paginas) vs una "
                  "biblioteca/telefono que crece."),
        solutions=[
            "cuadernito chico (al llenarse los nuevos pisan a los viejos = interferencia)",
            "cuadernito mas grande (mas paginas=mas estado: entran mas antes de pisarse)",
            "biblioteca/indice que crece con lo guardado (atencion: KV proporcional a la longitud: "
            "recordas todo pero ocupa mas)",
            "hibrido: cuadernito para lo frecuente + biblioteca para lo que no entra",
        ],
        principles=[
            "la capacidad de memoria escala con el TAMANO del almacen",
            "almacen fijo => interferencia al exceder su capacidad",
            "un almacen que crece con los datos no se satura pero cuesta mas",
        ],
        adaptation=("estado fijo d x d = cuadernito (cap ~d^2); atencion = biblioteca que crece (KV~L); "
                    "hibrido = ambos -> mayoria lineal + minoria atencion."),
        measurement=("exp009: lineal sube con d y satura ~0.18; hibrido separa a d=48. exp002: recall ~ d^2."),
        iterations=1,
    )
    # extract_principles enforza etapas 1-3 (problem, everyday, >=3 soluciones) antes de principles.
    principles = extract_principles(analogy)
    assert len(analogy.solutions) >= 4, "se requieren >=4 soluciones"
    assert len(principles) >= 3, "extract_principles no devolvió los principios"
    # La analogía no es un store del engine con compuerta de escritura propia; se journaliza como
    # 'analogies' para que verify_no_loss la cubra (pérdida = fallo, igual que el resto).
    record.journaled_append('analogies', _to_plain(analogy), key=analogy.problem[:48])
    notes.append("Analogía 7 etapas: {} soluciones, {} principios extraidos.".format(
        len(analogy.solutions), len(principles)))

    # --- 4) TECHOS (real_or_assumed) — dos registros, más fiel --------------
    # (a) el límite informacional d^2 es REAL (probado: pigeonhole / Jelassi).
    ceiling_real = CeilingRecord(
        subsystem="Recall asociativo — cota informacional del estado fijo",
        known_limit=("Capacidad de recall ~ O(d^2) (estado d x d): copia exacta requiere estado "
                     "proporcional a la longitud (Jelassi et al., via arXiv:2508.19029). Atencion: recall "
                     "~ilimitado en N a coste KV proporcional a L. Cota INFORMACIONAL (pigeonhole), real."),
        blockers=[
            {"text": ("el estado debe ALMACENAR las N asociaciones sin interferencia -> cota "
                      "informacional ~d^2"), "kind": "fisico"},
            {"text": ("se ELIGIO estado fijo para inferencia O(L)/banda — la cota es consecuencia del "
                      "diseno, no obligatoria"), "kind": "diseno"},
        ],
        real_or_assumed="real",
        evidence=[S1.ref, S2.ref, S3.ref],
    )
    ceilings.add(ceiling_real)

    # (b) el hallazgo NUEVO del ciclo: la capacidad ENTRENADA del feature-map queda MUY por debajo de
    # d^2 y es en parte de optimizacion -> límite ASUMIDO-permanente, candidato a refutar (backlog).
    ceiling_asumido = CeilingRecord(
        subsystem="Recall asociativo — capacidad ENTRENADA del feature-map (linear attention / SSM)",
        known_limit=("El techo PRACTICO entrenado del feature-map (ELU+1) queda MUY por debajo del d^2 "
                     "ideal (exp009: satura ~0.18 con n_pairs=16, chance 0.0625; la cota d^2 daria mucho "
                     "mas). Parte de la brecha es OPTIMIZACION/inicializacion, no expresividad "
                     "(Okpekpe&Orvieto arXiv:2508.19029; mimetic init arXiv:2410.11135) -> es un limite "
                     "ASUMIDO-permanente que invita a refutar, no una pared."),
        blockers=[
            {"text": ("la capacidad ENTRENADA del feature-map (ELU+1) queda muy por debajo de d^2; parte "
                      "es optimizacion/inicializacion, mejorable (Okpekpe&Orvieto 2508.19029; mimetic "
                      "init arXiv:2410.11135)"), "kind": "historico"},
            {"text": ("se ELIGIO ELU+1 como feature-map (estado fijo, inferencia O(L)) — la baja "
                      "capacidad efectiva es consecuencia de ese diseno, no obligatoria"), "kind": "diseno"},
        ],
        real_or_assumed="asumido",
        evidence=[S1.ref, S2.ref, S3.ref, S4.ref],
    )
    ceilings.add(ceiling_asumido)
    notes.append("2 techos: 'real' (cota informacional d^2) + 'asumido' (capacidad entrenada feature-map).")

    # --- 5) DECISIÓN D-CEIL-1 (debe pasar el gate del ledger) ---------------
    # Cita tier-1 S1 + tier-5 S3/S4 (todas obtenidas) -> funda; NO debe lanzar OpinionOnlyError.
    decision = Decision(
        id="D-CEIL-1",
        statement=("Mantener el hibrido (mayoria lineal barata + minoria de atencion para recall exacto) "
                   "como arquitectura del lab; la atencion es necesaria para recall a carga alta."),
        rationale=("La frontera recall-throughput (Arora 2024) + exp002 (recall~d^2) + exp009 (lineal "
                   "satura, hibrido separa a d=48) justifican mezclar: lo lineal da coste O(L); las pocas "
                   "capas de atencion compran el recall que el estado fijo no escala. Coincide con Based "
                   "(el lab llego al mismo principio de forma independiente)."),
        sources=[_to_plain(S1), _to_plain(S3), _to_plain(S4)],
        important=True,
    )
    try:
        ledger.record_decision(decision)
        notes.append("D-CEIL-1 ACEPTADA por el ledger (tier1 S1 + tier5 S3/S4 obtenidas -> funda; sin OpinionOnlyError).")
    except OpinionOnlyError as e:
        # No debería pasar con esta evidencia; si pasa, es un fallo de contenido a reportar (no debilitar el gate).
        print("ERROR: el ledger RECHAZÓ D-CEIL-1 (no debería con tier1+tier5): {}".format(e))
        raise

    # --- 6) NOTA DE ESCALABILIDAD (§6) --------------------------------------
    scal = ScalabilityNote(
        component="Recall del hibrido",
        time_complexity=("Lineal O(L) inferencia; Atencion O(L^2) train / O(L) decode con KV; hibrido 3:1 "
                         "dominado por lo lineal"),
        space_complexity="Lineal O(d^2) estado; Atencion O(L*d) KV-cache",
        cpu_behavior=("Decode memory-bandwidth-bound (CPU 2c/4t); lo lineal evita el KV creciente -> "
                      "barato a contexto largo"),
        multidevice="estado fijo facilita sharding por capa; atencion necesita KV (banda local)",
        distribution="exp005: hibrido compra recall full a ~1/7 del coste de decode a contexto largo",
    )
    record.journaled_append('scalability', _to_plain(scal), key=scal.component)
    notes.append("Nota de escalabilidad del híbrido registrada (§6).")

    return ledger, hyps, ceilings, record, notes


def _to_plain(obj):
    """schema.to_dict para dataclasses del engine; pasa dicts tal cual (los sources de la decisión)."""
    from cognia_x.research.schema import to_dict
    import dataclasses
    if dataclasses.is_dataclass(obj):
        return to_dict(obj)
    return dict(obj)


def main(argv=None):
    _safe_utf8()
    p = argparse.ArgumentParser(
        prog='python -m cognia_x.research.cycles.cycle22_recall_ceiling',
        description='CYCLE 22 (techo de recall) a través del Investigation Engine — reproducible.')
    p.add_argument('--store', default=DEFAULT_STORE, help='dir de datos del ciclo')
    p.add_argument('--reset', dest='reset', action='store_true', default=True,
                   help='REINICIA el store del ciclo antes de poblar (default: True, idempotente)')
    p.add_argument('--no-reset', dest='reset', action='store_false',
                   help='NO reinicia (append sobre el store existente)')
    args = p.parse_args(argv)

    store = os.path.abspath(args.store)
    if args.reset and os.path.isdir(store):
        # POR QUÉ: re-correr = mismos registros. Sin reset, el append-only duplicaría todo el ciclo.
        shutil.rmtree(store)
    os.makedirs(store, exist_ok=True)

    ledger, hyps, ceilings, record, notes = run(store)

    # verify_no_loss(): "pérdida de conocimiento = fallo", chequeable por contenido.
    res = record.verify_no_loss()

    print("=" * 78)
    print("RESUMEN — CYCLE 22: techo de recall (mezclador de estado fijo) [Investigation Engine]")
    print("=" * 78)
    print("store: {}".format(store))
    print("")
    for n in notes:
        print("  CHECK  {}".format(n))
    print("")

    # Conteos vivos por store.
    from cognia_x.research.record import count_lines
    for name in ('sources', 'hypotheses', 'analogies', 'ceilings', 'decisions', 'scalability'):
        print("  {:<12}: {}".format(name, count_lines(record.store_path(name))))
    assumed = ceilings.assumed_limits()
    print("  {:<12}: {} (backlog de refutación)".format('asumidos', len(assumed)))
    print("")

    print("  verify_no_loss:")
    for d in res['details']:
        flag = 'OK' if d['ok'] else 'FAIL'
        print("    [{}] {:<12} journaled={} live={} missing={}".format(
            flag, d['store'], d['journaled'], d['live'], d.get('missing', 0)))
    print("")
    if res['ok']:
        print("  verify_no_loss = OK (sin pérdida de conocimiento)")
        print("=" * 78)
        return 0
    print("  verify_no_loss = FAIL (un store tiene menos registros vivos que los journaleados)")
    print("=" * 78)
    return 1


if __name__ == '__main__':
    sys.exit(main())
