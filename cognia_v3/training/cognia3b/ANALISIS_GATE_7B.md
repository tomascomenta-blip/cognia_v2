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

| e2e | escaló al 7B | RAM peak | código pasa tests ocultos |
|---|---|---|---|
| burst_balloons | ✓ | 7.81 GB | **NO** (IndexError) |
| single_number | ✓ | 8.25 GB | **NO** (AssertionError) |

El mecanismo FUNCIONA (escala, coexistencia 3B+7B en RAM 8.25<10GB — **P-7B-4
✓**), pero el 7B **en producción** generó código incorrecto para dos tareas que
el mismo 7B **sí** resuelve en el gate. Causa raíz: el gate genera con
`build_prompt(task_prompt, SYSTEM_PROMPT)` **greedy** (1 candidato); producción
usa `_generar_codigo` con el prompt ENVUELTO ("Escribe UNA funcion COMPLETA…") +
best_of_n. **El wrapper + BoN de producción no extrae el rendimiento que el
greedy del gate sí logra** — es el gap "techo (tests ocultos) vs deployable"
que el diseño (workflow) anticipó, ahora confirmado empíricamente.

## Decisión: OPT-IN (default OFF), NO default ON — negativa honesta del deploy

Gate de CALIDAD ✓ (el 7B vale) + mecanismo ✓ (escala, RAM ok), pero e2e de
producción ✗ (el flujo no materializa el +20pp). Por el pre-registro
("promover solo si e2e pasa"), **NO se flipea default ON**. `COGNIA_HEAVY_CODE`
queda **opt-in** (default OFF): el 7B está disponible y funciona para quien lo
active, sin imponer latencia por default cuando la ganancia no está garantizada
en el flujo real. No inflar: el +20pp es del gate, no del deploy actual.

## Trabajo pendiente (para materializar el +20pp en producción)

1. **Alinear el prompt del 7B de producción con el del gate**: al escalar,
   generar con `build_prompt(desc, SYSTEM_PROMPT)` greedy (reproduce el
   protocolo bajo el que el 7B recuperó 8/8), en vez del code_prompt envuelto +
   BoN. Re-correr los 2 e2e; si pasan → promover.
2. **Brazo B-deploy completo** (40 tareas por el flujo de producción medidas
   contra tests ocultos) para cuantificar cuánto del +20pp del gate sobrevive
   al prompt de deploy.

## Qué significa para "alcanzar GLM 5.2"

El 7B DEMOSTRÓ la capacidad: código duro **37.5 → 57.5%** en el gate (por
encima de la referencia GLM 5.2 ~50%), capacidad-por-cómputo, cero GPU —
coherente con la tesis del programa. Pero materializarlo en producción exige
cerrar el gap de prompt de deploy (arriba). El valor entregado hoy: el 7B
integrado y funcional (opt-in), el gate honesto que prueba su capacidad, y el
gap de deploy diagnosticado con evidencia — no un número de producción inflado.
