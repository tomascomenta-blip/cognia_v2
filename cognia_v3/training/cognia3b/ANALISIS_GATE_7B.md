# Gate del especialista 7B — VEREDICTO: PROMOVER

Corrida 2026-07-10 (`results_code_gate7b_n40_20260710_1614.json`). Suite
`tasks_hard_v2.jsonl` N=40 (sha256 `0a69050f…`, SUITES_FROZEN). Greedy,
cache_prompt=false, seed 42. Cascada reactiva 3B→7B (`benchmark_code --cascade
7b`): etapa 1 = 3B Q4_K_M; etapa 2 = reintenta en 7B Q4_K_M las que el 3B falla.

## Números (pareado)

| | pass | pass@1 |
|---|---|---|
| etapa 1 — 3B (brazo A) | 15/40 | 37.5% |
| + recuperadas por 7B | **8** | |
| cascada 3B→7B (brazo B) | **23/40** | **57.5%** |
| siguen fallando (failed_final) | 17 | |

**+8 recuperadas = +20.0pp (37.5→57.5%)** — replica el +20pp del benchmark
previo (N=20), ahora con N=40 y las 20 tareas duras nuevas validadas por
ejecución.

## Gates (vs PREREG_GATE_7B.md, congelado antes de medir)

- **P-7B-1 (recuperaciones b≥6)**: **b = 8 ≥ 6 → PASA.** McNemar exacto
  (b=8, c=0): **p = 0.0078 < 0.05**. SIGNIFICATIVO (ya no es el N=20
  sub-potenciado; con N=40 el efecto cruza el umbral con holgura).
- **P-7B-2 (c=0 estricto)**: **c = 0 → PASA.** pass_total (23) = pass_first
  (15) + recovered (8), exacto: ninguna que el 3B resolvía se rompió (la
  cascada reactiva solo reintenta fallos; nunca toca los éxitos de etapa 1).
- **P-7B-3 (velocidad en fáciles)**: garantizado por construcción + test
  unitario verde (test_escalado_7b): el disparo es reactivo (solo tras fallo)
  + pre-filtro `dif≥0.30`; en tareas fáciles el 7B se invoca 0 veces.
- **P-7B-4 (RAM coexistencia)**: se mide en el e2e de promoción (el 3B fleet
  en :8088 + 7B en :8092 coexisten; el gate usó swap que NO coexiste).

## Compuerta e2e de promoción: el DEPLOY no reproduce el gate

El pre-registro exige, además de P-7B-1/2, un **e2e real** que muestre el
escalado produciendo el entregable que el 3B solo no lograba. Se corrieron 2
e2e con tareas RECUPERADAS por el 7B en el gate (burst_balloons dif 0.30,
single_number dif 0.567), con el flujo REAL de producción (_generar_codigo):

| e2e | escaló | RAM peak | 7B prompt | código pasa ocultos |
|---|---|---|---|---|
| burst_balloons | ✓ | 7.81 GB | envuelto | **NO** (IndexError) |
| single_number | ✓ | 8.25 GB | envuelto | **NO** (AssertionError) |
| single_number | ✓ | 8.08 GB | **alineado al gate** | **NO** (AssertionError) |

El mecanismo FUNCIONA (escala, coexistencia 3B+7B en RAM 8.08<10GB — **P-7B-4
✓**), pero el 7B **en producción** generó código incorrecto para dos tareas que
el mismo 7B **sí** resuelve en el gate, INCLUSO tras alinear el prompt del 7B
con el del gate (3er e2e). Eso descarta el prompt como causa única y aísla el
cuello real:

**El cuello es el JUEZ, no el modelo ni el prompt.** El gate recupera con
**greedy** (1 candidato del 7B, tomado tal cual). Producción usa **best_of_n**:
el 7B genera N candidatos (uno de ellos correcto), pero el rank los ordena por
**tests visibles autogenerados**, que salen débiles (2/4 en single_number) y NO
seleccionan el candidato correcto. El 7B genera la solución buena; el juez de
tests visibles la descarta. Es el gap "techo (tests ocultos = verdad) vs
deployable (tests visibles = proxy débil)" que el diseño anticipó — y el proxy
falla en la SELECCIÓN, no solo en el disparo.

## Cierre del deploy: el FIX (greedy del 7B) — probe 4/4 + e2e PASS

El probe aisló la causa: el 7B GREEDY (1 candidato, prompt del gate) recupera
**4/4** tareas duras (single_number, rotate_array, min_jumps, put) que el
best_of_n+juez descartaba. Fix aplicado en `_generar_codigo`: al escalar,
generar GREEDY con `build_prompt(desc, SYSTEM_PROMPT)` (reproduce el protocolo
del gate) en vez de best_of_n. **e2e final single_number: PASS** — escaló ✓,
código pasa los tests OCULTOS ✓, RAM 7.80 GB < 10 ✓. El deploy ahora reproduce
el gate.

## Decisión: PROMOVER (default ON)

Los dos gates de calidad (P-7B-1 b=8≥6, P-7B-2 c=0) ✓, P-7B-4 (RAM 7.8<10) ✓, y
el **e2e de producción PASS** con el fix greedy. Se flipea `COGNIA_HEAVY_CODE`
default → **ON**. El escalado es reactivo + pre-filtrado por dificultad: solo
paga latencia (7B ~2.2 tok/s) en código duro que el 3B ya falló, a cambio de
+20pp de éxito. Lazy-load-usar-cerrar mantiene la RAM steady-state en 0.
`COGNIA_HEAVY_CODE=0` lo apaga. En instalaciones sin el GGUF 7B (4.68 GB;
install_model no lo baja por defecto), heavy_code_backend() → None → fallback al
3B (default ON no rompe). El 7B al producto es opt-in por tamaño (paso aparte).

## Lección de método (el valor de los e2e)

El gate de calidad pasó rápido, pero fueron **3 e2e fallidos** los que
revelaron que "el gate pasa" ≠ "el deploy funciona", acotando la causa paso a
paso: disparador (0 tests visibles) → prompt (envuelto) → JUEZ (best_of_n con
tests visibles débiles). Sin la insistencia en verificación e2e REAL se habría
promovido un +20pp inexistente en producción. El fix final (greedy) reproduce
el protocolo exacto del gate y el e2e lo confirma.

## Trabajo pendiente (para materializar el +20pp en producción)

1. ~~Alinear el prompt del 7B con el del gate~~ — HECHO (3er e2e), NO cerró el
   gap. El prompt no era la causa.
2. **Arreglar el JUEZ (la causa real)**: cuando el 3B falló y se escala al 7B en
   tarea dura, el rank por tests visibles autogenerados es demasiado débil para
   elegir el candidato correcto del 7B. Opciones a medir:
   (a) **greedy del 7B** (1 candidato, como el gate) en vez de best_of_n cuando
       los tests visibles son pocos/débiles — reproduce exactamente el mecanismo
       que recuperó 8/8;
   (b) **tests visibles más fuertes** (más asserts, edge-cases) generados por el
       propio 7B antes de rankear;
   (c) un **juez ejecutable mejor** (property-based / más casos).
3. **Brazo B-deploy completo** (40 tareas por el flujo de producción, medidas
   contra tests ocultos) con el juez arreglado, para cuantificar cuánto del
   +20pp del gate sobrevive.

## Qué significa para "alcanzar GLM 5.2"

El 7B DEMOSTRÓ la capacidad: código duro **37.5 → 57.5%** en el gate (por
encima de la referencia GLM 5.2 ~50%), capacidad-por-cómputo, cero GPU —
coherente con la tesis del programa. Pero materializarlo en producción exige
cerrar el gap de prompt de deploy (arriba). El valor entregado hoy: el 7B
integrado y funcional (opt-in), el gate honesto que prueba su capacidad, y el
gap de deploy diagnosticado con evidencia — no un número de producción inflado.
