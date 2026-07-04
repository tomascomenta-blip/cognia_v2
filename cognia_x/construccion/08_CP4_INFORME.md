# CP4 — Informe honesto: agente MoM (3B andamiado) vs umbrales "cerca de GLM-5.2"

**Fecha:** 2026-07-03 · **Base:** benchmarks pre-registrados en `06_AGENTE_PLAN.md`
§4, corridos con el modelo REAL (Qwen2.5-Coder-3B Q4_K_M vía llama.cpp, CPU) ·
**Regla:** los umbrales, predicciones y definiciones de "cerca" se congelaron ANTES
de correr; acá se reportan los números reales contra ellos, sin editar los
umbrales. Las predicciones que fallaron se declaran como tales.

---

## 0. Resumen ejecutivo (una tabla, sin adornos)

| eje | baseline pelado | v1 (andamiaje) | Δ | umbral "cerca" pre-reg | ¿cumple? |
|---|---|---|---|---|---|
| **tool-calling** (BFCL slice) | 24.0% (48/200) | **86.0%** (172/200) | **+62pp** | ≥65.2% | **SÍ** (con caveat, §2) |
| **programación** (bench duro) | 40.0% (8/20) | **50.0%** (10/20) | **+10pp** | gate ≥+8pp; target 55% | **gate SÍ**, target no |
| **diseño** (HTML/CSS por spec) | 93.7% (340/363) | [pendiente --repair] | — | ≥85% | **SÍ ya en baseline** |
| **AG-ARB** (árbitro del paper) | — | contratos 50% vs LLM 31% | — | contratos ≥80% en oráculo | **SÍ** (100% design+code) |

**Titular honesto:** el andamiaje (ingeniería barata: ejemplos concretos,
Best-of-N con juez ejecutable, test-first, validación-repair) mueve la aguja de
forma GRANDE donde el cuello es formato/proceso (tool-calling, tareas cortas
verificables) y de forma REAL pero acotada donde el cuello es capacidad
(programación dura). NO es paridad global con un MoE de 753B, y no se afirma
como tal — se afirma exactamente lo que los números soportan, por eje.

---

## 1. Qué es GLM-5.2 y por qué "cerca" se define POR EJE

GLM-5.2 (Zhipu/Z.ai, MoE ~753B, 2026-06-13, MIT) publica: SWE-bench Pro 62.1,
Terminal-Bench 2.1 81.0, tau3-banking 27%, AIME 99.2, GPQA-D 91.2. NO publica
BFCL/LiveCodeBench/HumanEval (proxies: GLM-4.5 BFCL v3 76.7% overall; GLM-4.7
LiveCodeBench-v6 84.9%; GLM-5 base SWE-Verified 77.8%). Comparar un 3B local
contra un 753B API globalmente es un sinsentido; "cerca" se definió por-eje y
ANTES de correr, distinguiendo dónde domina el andamiaje vs la capacidad
(brecha de 4-5 órdenes de cómputo que ningún prompt cierra).

---

## 2. Eje 1 — Tool-calling: 24% → 86% (+62pp)

**Slice congelada:** BFCL v3, 200 ítems (40 × simple/multiple/parallel/
parallel_multiple/live_simple), checker AST oficial vendorizado, seed 42.

**Resultado:** baseline pelado **24.0%** → v1 (few-shot 2 + validación/repair)
**86.0%**. Por categoría (v1 vs baseline): simple 38/40 (7), multiple 38/40 (13),
parallel 37/40 (5), parallel_multiple 28/40 (16), live_simple 31/40 (7).

**Diagnóstico de causa raíz (lo importante):** el baseline 24% estaba
ARTIFICIALMENTE deflado por un **artefacto de prompt**. El system prompt pelado
decía "using Python syntax: `func(param=value)`" y el 3B lo tomó LITERAL,
emitiendo `func(convert_currency(base_currency="JPY", ...))` — la llamada real
anidada dentro de un `func()` placeholder → el checker veía la función "func" →
`wrong_func_name`. **142 de 152 fallos del baseline (93%) eran este artefacto de
formato.** El andamiaje v1 (2 ejemplos CONCRETOS de llamadas reales, cero leakage
de la slice) colapsó los errores de formato de 142 → 5. Los 28 fallos restantes
del v1 son mayormente **errores reales de valor/argumento (23), no de formato (5)**
— o sea, ahora sí es el techo genuino del 3B en esta slice.

**Lección de ingeniería-barata (la que el dueño pidió hornear):** para modelos
chicos, **un ejemplo concreto >> una instrucción de formato abstracta**. La misma
lección apareció en la síntesis de auto-tools (§5): el 3B necesita ver el formato,
no que se lo describan.

**Honestidad sobre el umbral y GLM:** v1 (86%) supera el umbral "cerca"
pre-registrado (≥65.2% = 0.85 × 76.7). PERO: (a) nuestra slice es single-turn y
más FÁCIL que el BFCL-overall de GLM (que incluye multi-turn, donde el frontier
mismo se derrumba); (b) posible contaminación de BFCL en el pretraining de
Qwen2.5. Por eso el claim honesto es: *"el 3B andamiado resuelve tool-calling
single-turn a 86% en esta slice, arriba de nuestro umbral, PERO esto NO es
paridad con la cifra 76.7% de GLM (tarea distinta, más fácil)"*. El Δ del
andamiaje (+62pp) es el hallazgo sólido; el nivel absoluto tiene los dos caveats
declarados. El +62pp está inflado por arreglar un prompt roto — pero ese arreglo
ES la lección (concreto > abstracto).

**Costo:** el repair no disparó (0/200) — el few-shot ya dejaba las llamadas
válidas, así que v1 cuesta ~lo mismo que el baseline (una generación por ítem).
Velocidad intacta.

---

## 3. Eje 2 — Programación dura: 40% → 50% (+10pp, gate PASADO)

**Bench:** `tasks_hard.jsonl` (20 tareas duras, pass@1 con ejecución REAL, greedy).

**Resultado:** baseline **40.0%** (8/20, reproduce EXACTO el 40% pre-registrado)
→ v1 **50.0%** (10/20) con Best-of-N (8 candidatos) + juez por tests visibles
ejecutados. **Gate CP1 (≥+8pp) PASADO con +10pp.**

**Mecanismo (limpio):** 2 tareas flipearon FAIL→PASS (ALG4, LONG4), **0
regresiones** (el candidato greedy siempre está en el pool → BoN no puede
empeorar). Las 20/20 activaron BoN con **oráculo real** (rank_mode=tests): el 3B
generó tests visibles ejecutables para cada tarea, así que el juez nunca eligió
"a ojo". Las 2 ganadas pasaron 4/4 y 3/4 de sus tests visibles, elegidas entre 8
candidatos únicos.

**Honestidad:** v1 (50%) NO llega al target absoluto de 55% pre-registrado. Pero
el +8pp era la prueba de TRANSFERENCIA (¿la palanca del paper de un 3B-coder
transfiere a NUESTRO bench?), y transfiere con +10pp. Declarado en §4 del plan:
en LiveCodeBench/SWE-bench-Pro (GLM 62-85%) NO estamos cerca y no se prometió —
la brecha ahí es de capacidad; un 3B queda <10-15%. Nuestro 50% es la serie
interna, no comparable a SWE-Pro 62.1 (tarea mucho más dura).

**Costo:** ~2200 tokens/tarea (test-gen + 8 candidatos), 0 GPU. El BoN multiplica
generación pero se activa SOLO en tareas de código con entry point (detector
barato), no always-on.

---

## 4. Eje 3 — Diseño: baseline 93.7% (ya arriba del umbral)

**Bench congelado:** 25 specs textuales → HTML/CSS single-file, 363 asserts DUROS
(checker DOM/CSS mecánico, CERO juez LLM).

**Resultado:** baseline pelado **93.7%** (340/363). 12/25 specs perfectas; las
fallas son reglas CSS específicas (16) + algunos elementos (5). **Ya supera el
umbral "cerca" ≥85% SIN andamiaje.**

**Predicción que FALLÓ (declarada):** predije baseline 55-65% — fue **demasiado
pesimista**. El 3B (coder-tuned) es genuinamente bueno en HTML/CSS por spec
explícita. Consecuencia honesta: **en este eje el margen del andamiaje es chico**
(23 asserts de headroom). El v1 (--repair dirigido por assert fallido) está
corriendo; se espera un incremento pequeño (~93.7% → ~96%). [PENDIENTE: número
final del v1.]

**GLM:** no hay benchmark de diseño publicado para GLM-5.2; el eje se mide contra
el bar absoluto de asserts, no contra GLM (declarado).

---

## 5. AG-ARB — Falsación del árbitro del paper del dueño (ver `07_ARBITRO_MEJORA_PAPER.md`)

32 casos (8 base × 4 etapas), falla seeded verificada en build. **Verificación por
etapa (contratos) = 50% global pero 100% (16/16) en las etapas con oráculo
ejecutable (design, code)**; árbitro-LLM global y con-traza = 31.2% (sesgo medido
de "culpar al artefacto terminal": predijo `code` en 24-30/32, nunca detectó
plan/design). **Veredicto pre-registrado: gana la verificación por etapa** → el
árbitro del paper se re-especifica como cascada contratos-primero con LLM de
fallback. Hallazgo nuevo que mejora el paper: más contexto EMPEORA al juez chico.

---

## 6. Capacidades del agente demostradas e2e (no solo medidas)

- **Auto-herramientas estilo HERMES (CP2):** demo e2e con el modelo real
  (`cp2_selftooling_demo.py`, TODOS los checks OK): el 3B genera una tool pura →
  verificada por ejecución en sandbox → registrada 'staged' → reusada → asciende
  a 'verified' → gate crear-vs-reusar rechaza duplicados → captura skill nivel-2.
  Todo con el scan de seguridad endurecido (se cerró un bypass RCE real,
  `__builtins__.eval`, que la revisión adversarial encontró).
- **BoN + juez + generate-then-structure:** wired al loop y medido en el bench.
- **Detectores baratos:** cada palanca cara corre solo donde aplica (regex, cero
  LLM), heredando el patrón stepwise medido.

---

## 7. Qué NO se logró / límites honestos

1. **No hay paridad global con GLM-5.2** (MoE 753B); "cerca" existe SOLO por-eje
   según §2-4, y en programación dura/SWE se declara explícitamente NO-cerca.
2. **El +62pp de tool-calling está inflado** por arreglar un prompt roto; el nivel
   absoluto (86%) tiene caveats de slice-más-fácil y contaminación.
3. **eje-2 no llegó al target absoluto 55%** (llegó a 50%); pasó el gate de
   transferencia (+10pp), que es lo que se pre-registró como prueba.
4. **eje-3 v1 con headroom chico** (baseline ya 93.7%).
5. **Multi-turn agentic no se midió** (el frontier mismo saca 27% en tau3; no era
   una apuesta ganable, declarado en el plan).
6. **Wire de BoN al loop /hacer en vivo** validado por unit-tests + demo; la
   integración e2e completa del loop live es trabajo siguiente (el bench mide la
   capacidad; el loop es la entrega).
7. **CPU-bound:** todo corrió en un i3 a ~5 tok/s; los presupuestos asumen
   corridas largas. Sin sacrificio de velocidad: el andamiaje que paga (few-shot,
   detectores) es casi gratis; el BoN se activa selectivamente.

---

## 8. Veredicto

En los 3 ejes que el dueño priorizó, el 3B andamiado quedó: **tool-calling** muy
por arriba del umbral (con caveats honestos), **programación dura** pasando el
gate de transferencia del andamiaje (+10pp, sin regresiones), y **diseño** ya
sobre el umbral desde el baseline. Además ejecuta y evoluciona sus propias
herramientas (HERMES) de forma verificada y segura, y el experimento AG-ARB
mejoró la teoría del paper del dueño con datos. La honestidad del método
(pre-registro, predicciones que fallaron declaradas, un run perdido por un bug y
rehecho, un RCE encontrado y cerrado) es parte del resultado: los números que se
reportan son los que el código produjo de verdad.
