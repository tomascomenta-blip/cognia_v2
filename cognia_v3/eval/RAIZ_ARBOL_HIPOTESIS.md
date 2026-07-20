# ÁRBOL DE HIPÓTESIS — Raíz del techo 27/40 (código duro, colonia ≤7B)

**Firma de la autopsia local:** 0/13 basura, 7 fallan UN borde de spec larga, 4 parsers con bug no depurado, 2 sin clasificar. La literatura 2024-2026 predice que esa firma es techo de BÚSQUEDA+ORÁCULO (rompible en inferencia), no de capacidad. Precedente local: el juez BoN ya descartó una vez el candidato correcto del 7B (FASE 4).

---

## PASO 0 obligatorio (decide el árbol entero, costo ~0)

**Diagnóstico de cobertura:** correr los tests OCULTOS sobre los pools YA generados de las 13 tareas (solo diagnóstico, jamás selección). Tres resultados posibles por tarea:
- Algún candidato pasa ocultos pero el juez lo descartó → **rama ORÁCULO** (ya pasó una vez).
- Ninguno pasa, pero coverage crece al regenerar con N=30-50 → **rama BÚSQUEDA**.
- Coverage plano en 0 a N alto → candidata a **CAPACIDAD** (recién ahí).

Costo: ejecución pura sobre pools existentes ≈ minutos. Regenerar N=50/tarea a ~8 tok/s ≈ ~1h/tarea → las 13 en 1-2 noches batcheadas. Es la medición que Brown 2024 / Yue 2025 / 2411.17501 convergen en exigir ANTES de tocar nada.

---

## Rama 1 — BÚSQUEDA (la solución está en la distribución; greedy/BoN no la encuentra)

- **(a) Confirmación local:** coverage@50-100 contra ocultos >> pass@BoN actual en la tarea; log-lineal en N (Monkeys). El 7B corre GREEDY en la cascada = exactamente el modo que CoT-decoding demuestra que oculta paths.
- **(b) Palancas sin entrenar:**
  - Diversificación ESTRUCTURAL del BoN: forzar primer token distinto por candidato (logit_bias/grammar en llama.cpp b9391, KV compartido con cache_prompt) — casi gratis, > que subir temperatura.
  - Candidato de OTRA FAMILIA en el pool (no-Qwen del registry FLEET-30 ya smoked): el "techo compartido 3B/7B" es agujero de distribución Qwen compartida (Yue 2025); familia ≠ tamaño.
  - N extra DIRIGIDO solo a los 4 parsers (no plano: con juez débil el k óptimo es <10).
- **(c) Costo i3:** bifurcación primer-token ≈ solo el decode que ya se paga; modelo extra = 1 generación más por tarea; N=50 dirigido = ~1h/tarea nocturna.

## Rama 2 — ORÁCULO DÉBIL (el juez de tests visibles autogenerados no distingue / veta al correcto)

- **(a) Confirmación local:** en el Paso 0, candidatos que pasan ocultos y el juez descartó; o candidatos SELECCIONADOS que fallan ocultos (FP del juez). EvalPlus/SAGA predicen que suites autogeneradas distinguen ~22-32% de los casos; S* midió que "tests generados con outputs predichos" es la política MÁS DÉBIL (peor que tests públicos solos).
- **(b) Palancas sin entrenar (todas juez-de-EJECUCIÓN, compatibles con juez-LLM-PROHIBIDO):**
  1. **Inputs-only + clustering por ejecución** (S*): el LLM genera solo INPUTS (fácil), se ejecutan los N candidatos, majority-vote por comportamiento real (+11pp en el 7B de S* sin oráculo). El error del oráculo vive en los OUTPUTS predichos.
  2. **Test anchors** (AlphaCodium): jerarquía tests-dados > derivados-de-spec > generados; un test generado nunca veta a un candidato que pasa los anclados. Parche directo al bug ya vivido.
  3. **Tests generados desde la SPEC sola, sin ver candidatos** (rompe el oráculo circular: el modelo codifica su propia mala lectura del borde en el test).
  4. **Inputs distinguidores ejecutados** para desempates: si 2+ candidatos pasan todo lo visible, generar input donde difieran, ejecutar ambos, comparar.
  5. **Acuerdo dual CodeT/B4** en vez de pass-count plano (matriz solución×test, cluster de consenso) — ~decenas de líneas en el juez existente.
  6. **Propiedades ejecutables** (Hypothesis, corre bien en 2 cores) para bordes: empezar por las mecánicas (no-crash, tipo de retorno, round-trip parse/serialize para los parsers).
- **(c) Costo i3:** el más barato del árbol — generar inputs son pocos tokens; el resto es EJECUTAR (CPU trivial). Reusa los pools ya generados.

## Rama 3 — SPEC-NO-DESCOMPUESTA (las 7 de spec larga: el borde nunca se vuelve check explícito)

- **(a) Confirmación local:** A/B en las 7: flow checklist (spec→bullets de reglas→assert ejecutable por regla) vs cascada actual, McNemar N≥40 con réplicas. Señal previa: si el borde que falla APARECE en la lista de reglas extraída, la descomposición habría pagado.
- **(b) Palancas:** AlphaCodium-lite (reflexión en bullets + 6-8 tests de borde + anchors; 19→44% en CodeContests sin entrenar) + DeCRIM: refinamiento dirigido a LA regla violada, no regenerar todo (+7-8pp en 7B con critic débil; acá el critic es un assert ejecutado = extremo alto del rango). Evita el modo flappy-bird (reescribe 85% y pierde mecánicas).
- **(c) Costo i3:** 2-4× llamadas por tarea → aplicar SOLO al escalón final de la cascada y solo en irresueltas (~7 tareas × ~3 gen ≈ una noche).

## Rama 4 — REPAIR-INSUFICIENTE (los 4 parsers: hay traceback y nadie lo usa)

- **(a) Confirmación local:** gate PRE-REGISTRADO — repair 2 rondas con traceback estructurado vs +2 candidatos BoN al MISMO presupuesto de tokens (el placebo-control de 2606.31511: a ≤1.5B empatan pero desbloquean tareas DISTINTAS, split 20/20). Probe adicional de 10 tareas: diff entre rondas ≈ vacío → el modelo resamplea, no edita → cortar.
- **(b) Palancas:** loop de MÁXIMO 2 rondas (R0→R1 concentra casi todo; R3+ ≈ 0); pre-procesado DETERMINISTA del traceback (PyCapsule: frame relevante + input fallido + esperado-vs-obtenido, no el crudo) — es código, cero LLM; corte por no-progreso (reusar el del agent loop 3.8.4); brazo HÍBRIDO mitad-BoN/mitad-repair.
- **(c) Costo i3:** cada ronda = 1 generación (~1-2 min/tarea); acotado a 2 rondas × 4-13 tareas ≈ horas.
- **Dependencia dura:** para las 7 de spec larga, si el test visible no ejercita el borde, NO HAY traceback → esta rama es inútil sin la Rama 2 primero. Y puede RESTAR (BigCodeBench bajó 67.2→65.4 con self-debug).

## Rama 5 — CAPACIDAD REAL (fuera del soporte del trío ≤7B)

- **(a) Confirmación local:** SOLO por exclusión: coverage plano en 0 a N=100 tras oráculo endurecido + diversificación de familia. Muro tipo CodeContests (Gemma-2B: 7% a k=10.000). El residuo multi-nivel profundo (MultiCodeIF 54.5→18.8) es el perfil esperado.
- **(b) Palanca:** ninguna sin más cómputo. Parquear la tarea y declararla honestamente. RL/FT no la rompería tampoco (no expande soporte — 6ª/7ª negativa evitada).
- **(c) Costo:** el diagnóstico ya está pagado por el Paso 0.

---

## Ranking de palancas (prob. de romper techo × viabilidad i3)

| # | Palanca | Ataca | Prob×Viab | Costo CPU |
|---|---------|-------|-----------|-----------|
| 0 | Diagnóstico coverage pools vs ocultos | separa las 5 ramas | **decisiva** | ~0 (ejecución) |
| 1 | Oráculo: inputs-only + clustering + test anchors + tests-desde-spec | 7 spec-largas + FP del juez | ALTA×ALTA | ejecutar es gratis |
| 2 | Acuerdo dual CodeT/B4 en el juez | régimen exacto plausible×plausible | MEDIA-ALTA×ALTA | ~decenas de líneas, 0 tokens |
| 3 | Repair 2 rondas, traceback estructurado, gate vs BoN-mismo-presupuesto | 4 parsers (~2 esperadas al ~45-50%) | MEDIA×ALTA | horas, acotado |
| 4 | Inputs distinguidores ejecutados (desempate S*) | empates en tests débiles | MEDIA×ALTA | pocos tokens + ejecución |
| 5 | AlphaCodium-lite + assert por regla (DeCRIM) | 7 spec-largas | ALTA×MEDIA | 2-4× llamadas, solo escalón final |
| 6 | BoN estructural (primer token bifurcado) | greedy oculta paths | MEDIA×MUY ALTA | casi gratis (KV compartido) |
| 7 | Candidato cross-familia en el pool | agujeros Qwen compartidos | MEDIA×MEDIA | +1 gen/tarea |
| ✗ | Subir N plano (k=10→100) | — | teorema en contra: con juez débil k óptimo <10 y más N puede EMPEORAR | tirar horas |
| ✗ | Más selección post-hoc sobre el mismo pool/juez | — | 26 operadores fallaron en frozen small models → probable 7ª negativa | — |

**Orden de ejecución:** 0 → 1/2 (oráculo primero: el feedback del repair ES el oráculo) → 3/4 → 5 → 6/7. Predicción combinada honesta de la literatura: 27/40 → 30-34; el residuo que no se mueva con coverage alto es capacidad y se parquea.

---

## Advertencias de honestidad

1. **Los tests ocultos son diagnóstico, JAMÁS selección** — filtrarían señal al juez y el número resultante sería mentira (Goodhart directo).
2. **PBT/propiedades nunca medido en ≤7B** (PGS usó Coder-V2/32B): la asimetría 48.9%-vs-1.1% es extrapolación. Gate propio obligatorio (N≥40, McNemar, e2e vivo) antes de creer el transfer; si el 4B no escribe propiedades válidas, degradar a inputs-only.
3. **Los +9.8/+16pp de repair son COTA SUPERIOR**: esos papers realimentan tests ground-truth; la colonia solo tiene visibles autogenerados. Y AssertionError (la clase dominante local) es la MENOS reparable (~45%).
4. **S*/AlphaCodium miden en LiveCodeBench/CodeContests**, no en el set duro local: los +24-25pp del 3B/7B no se transfieren 1:1; pre-registrar cada palanca con gate no-regresión (batería 17/17 intacta) antes de promover.
5. **Toda predicción "27→30-34" es de papers, no de este set**: el único número que vale es el del Paso 0 local. Si coverage@100 ≈ 27/40, todo lo demás es teatro y el techo es cómputo (consistente con "gap a GLM = capacidad cruda").
6. **Riesgo i3 real:** N=50×13 tareas ≈ 13h a ~8 tok/s; presupuestar por noches y con cache_prompt=false en eval (KV flipea ítems, ya cazado).
7. **2606.16999 solo abstract verificado y es ≤1.5B**; su advertencia (selección post-hoc no paga) puede no aplicar igual a 7B — pero la carga de la prueba es de quien apila selección, no al revés.