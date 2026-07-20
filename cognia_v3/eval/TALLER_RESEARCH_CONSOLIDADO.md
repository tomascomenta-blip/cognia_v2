# TALLER-EFICIENTE — Consolidación (2026-07-12)

## 1) RANKING top-5 (ganancia × viabilidad × costo) + gate pre-registrable

### #1 — Higiene KV/RAM: acotar `--cache-ram` + auditoría de prefijos estables + telemetría `prompt_eval`
- **Por qué #1:** costo ~2h, riesgo REAL activo hoy: b9391 trae `-cram 8192` por default sin que nadie lo pidiera, compitiendo con la coexistencia 3B+7B+4B (7.8GB medidos < 10 en caja de 12GB) → swap bajo carga larga. Un solo prefijo inestable anula ~100s/turno de reuso ya desplegado.
- **Gate (pre-registrar):** (a) `-cram` explícito 1024-2048 MiB en el cmd del server; corrida larga de prod midiendo RAM pico <10GB y latencia/turno pareada vs default; (b) loguear `prompt_eval` de /completion en la telemetría BoN (gap ya señalado en MANAGER_LOG) y exigir hit-rate >90% en flujo agente con historia 2k; (c) grep de timestamps/ids/few-shots rotativos ANTES de la historia en system prompts del agente/router/molde-portero. Cero cambio de outputs; eval sigue con `cache_prompt=false`.
- **Integración:** 1 línea en `node/llama_backend.py` (cmd del server). Todo pasa por `activate_expert()` — regla dura vigente por el bug LoRA-swap→KV inválido ya cazado. No toca BoN/cascada/router.

### #2 — Presupuesto adaptativo por dificultad: N por ítem + escalado predictivo de cascada (ACTSC/BEST-Route adaptado)
- **Qué:** clasificador logístico sobre embeddings del Qwen3-Embedding-0.6B (wiring pendiente igual) + features de logprob del sample 1, entrenado con el ledger propio (192 registros + results_*.json, etiqueta "el 3B lo resolvió" POR MIEMBRO). Decide cap de N y salto directo a 7B/4B. Sustituye las activaciones internas de los papers (b9391 no las expone).
- **Ganancia esperada honesta:** −30/−50% latencia media BoN a igual accuracy; ~0pp (el techo 67.5% no sube; llega más rápido).
- **Gate:** fase offline primero — replay contra la telemetría BoN (192): CV 5-fold + calibración Platt, pre-registro: −≥25% muestras a igual resultado del replay. Luego online N=40 en tasks_hard_v2: no-inferioridad en pass (McNemar) + latencia media −≥20%. Umbral de escalado CONSERVADOR (un FP fácil→7B cuesta 3.6× y bloquea la cola) y fallback reactivo intacto.
- **Integración:** se monta SOBRE el BoN early-stop lossless existente (le agrega el cap de arranque, no lo reemplaza); cascada reactiva queda como red; el embedder entra al fleet vía `activate_expert()`. Ledger sigue siendo la fuente de verdad.

### #3 — Exemplar retrieval del ledger propio → few-shot SOLO para el 3B (RACG + MMR + umbral de abstención)
- **Qué:** el ledger ya ES un banco de soluciones verificadas-por-ejecución (= inducción ASI con curación determinista, nunca "el 3B resume"). BM25 (rank_bm25, CPU-trivial) o embedder; top-20 → MMR λ≈0.5-0.7 → k≤3; si el vecino más cercano está lejos, caer a zero-shot.
- **Ganancia esperada honesta:** +3-8pp código en el 3B (banda con corpus abierto, NO los +17-62pp gold); 0 a −4pp en 7B/4B (DeepSeekCoder-7B PIERDE con contexto extra) → gate por miembro, default OFF para 7B/4B.
- **Gate:** condición dura previa: dedup banco vs TODOS los evals (hash enunciado + near-dup por embedding); biblioteca CONGELADA durante el gate. A/B N=40 tasks_hard_v2 McNemar **sobre el pipeline BoN completo, no single-shot** (los exemplars correlacionan los N candidatos; el juez no rescata el candidato que nunca se generó). G2R solo como control de no-regresión — NO gastar este lever en razonamiento (~0pp medido en math).
- **Integración:** inyección prompt-only al final del prompt (patrón "KV-safe" ya usado por el recap) para no romper el prefijo cacheado del #1; +600-1200 tok de prefill caben en ctx 16k; BoN+juez quedan intactos como red contra exemplar engañoso (−8/−11pp medidos sin mitigación).

### #4 — Abort temprano de candidatos BoN: chequeo sintáctico incremental (ROCODE-lite) + self-certainty gratis
- **Qué:** streaming client-side; `ast.parse` del prefijo TRUNCADO a la última sentencia completa (falsos positivos si no); abort = cortar stream, ahorrar el decode restante (~50s/candidato malo a 8 tok/s). Self-certainty desde logprobs (`n_probs` que b9391 ya devuelve) como desempate cuando varios candidatos pasan tests visibles débiles — exactamente la causa raíz del bug del deploy 7B.
- **Ganancia esperada honesta:** −20/−40% del tiempo BoN (el 16-32× de los papers es batch GPU); pp ~0 (el techo del set duro es de lógica, no de sintaxis). Venderlo como cómputo, no capacidad.
- **Gate:** pareado con/sin abort sobre los mismos ítems del ledger, pre-registro: 0 flips de pass (lossless) + −≥20% tokens. ANTES: validar correlación prefijo→final contra la telemetría propia (está demostrada con PRMs en math, no con juez de ejecución) y medir overhead de `n_probs` en streaming. Ojo trampa medida propia: el 3B arregla ~85% por REESCRITURA — el abort puede matar trayectorias auto-correctivas; el gate pareado decide, no el paper.
- **Integración:** envuelve el BoN existente; regeneración desde prefijo bueno reutiliza `cache_prompt` en prod (eval sigue false). Sin PRM (prohibido), sin modelos nuevos, sin RAM extra.

### #5 — Review-then-fix: crítica corta del 4B → repair del 3B, SOLO donde los tests visibles son débiles
- **Qué:** la ÚNICA variante de dos-modelos con soporte 2026 (plan-then-code tiene signo invertido en 3 mediciones). No viola la línea juez-LLM: no selecciona candidatos, repara — pariente del repair dirigido ya desplegado en loop; el juez de ejecución sigue decidiendo.
- **Ganancia esperada honesta:** el set duro se parece a MBPP+ (specs magras) → esperar +2-5pp, NO el +9.8pp de HumanEval+ (specs ricas). Presupuesto máx +2 llamadas (1 crítica 4B ~corta + 1 regen 3B).
- **Gate:** N=40 tasks_hard_v2 vs pipeline BoN actual completo (no vs 3B pelado — el stepwise ya captura la mayor parte del planear, +22pp G2R medido), McNemar, disparo condicionado a "tests visibles pasan débil / sin señal". Comparar también latencia (+2 llamadas es real en el i3).
- **Integración:** extensión del repair dirigido del loop; se dispara DESPUÉS del juez de ejecución, nunca en su lugar; el router por eje no se toca.

## 2) Descartes de plano (1 línea c/u)
- **Plan-then-code 4B→3B:** signo invertido en 3 mediciones 2026 (−2.4pp, −3.65pp, CoT>Self-Planning); el gap 4B↔3B es demasiado chico y el stepwise ya da el plan interno.
- **Speculative Thinking (intervención mid-decode):** ping-pong de KV entre servers = misma física que mató draft/EAGLE3 en el i3 (línea cerrada).
- **CollabCoder framework completo:** multi-agente 2-5 iteraciones, caro en i3; la decisión plan-vs-código ya la cubre el árbitro cero-LLM (24/24 medido).
- **`-np>1` slots paralelos:** divide el ctx en silencio (16k→4k/slot) y batchear en 2 cores es 0.464× medido acá.
- **`--context-shift`:** default OFF de b9391 es correcto; regresiones upstream activas; el ctx-guard propio ya lo cubre determinísticamente.
- **GBNF a código libre:** −26/−63pp si constriñe razonamiento + sampling ~6× más lento con vocab 151k; mantener solo el bloque estructurado (ya cosechado).
- **Dynamic Cheatsheet / AWM con el 3B como curador:** GPT-4o-mini (≫3B) ya degrada curando memoria; solo curación determinista (absorbida en #3).
- **PRM/reward parcial para el abort:** PRM generativo prohibido con medición; el sustituto cero-LLM es #4.
- **BEST-Route literal (proxy-RM 300M):** el juez de ejecución ya es mejor señal que un reward-model para código; la parte útil colapsa en #2.
- **Exemplar retrieval en eje razonamiento:** ~0pp vs random medido (GSM8K); router→4B 92.5% ya lo resuelve.

## 3) Advertencias de honestidad (descuentos obligatorios)
1. **Oracle leak:** HumanEval 97.6 con BM25 sobre soluciones = copia literal; los settings "gold" (+17-62pp) concatenan la solución del propio problema. Banda transferible real: +3-8pp. Dedup banco-vs-set-duro-oculto es condición dura del gate #3.
2. **Baselines derrochadores:** los −83%/7.9× de la familia SC-adaptativa son vs N=40; con N de prod 3-5 el ahorro absoluto se comprime mucho — medir vs el N real, no el del paper.
3. **Benchmark-dependencia del review:** +9.8pp es HumanEval+ (specs ricas); el set duro ≈ MBPP+ → pre-registrar el número chico (+2.3pp) como expectativa.
4. **Consumidores frontier:** los headline de memoria/skills (+51% WebArena, 10→99% Game of 24) son con GPT-4o/Gemini-2.5-Pro; nadie publicó nada de esto con un 3B en CPU — expectativa modesta + kill rápido si el N=40 no lo muestra.
5. **Dificultad es model-specific:** entrenar los predictores de #2 con telemetría propia por miembro, jamás con etiquetas humanas o de otro modelo.
6. **192 registros es poco:** CV estricta + calibración; un predictor descalibrado convierte ahorro en pérdida de accuracy silenciosa; seguir acumulando ledger.
7. **KV y evals:** el KV reusado cambia logits (flip de ítems medido acá) → todo gate con `cache_prompt=false`; nunca A/B con cache mezclado; los exemplars correlacionan los candidatos BoN → A/B siempre sobre el pipeline completo.
8. **Fuentes contaminadas:** la discussion #20574 de llama.cpp es AI slop (flags inventados; el "93% TTFT" NO citable); BEST-Route mide drops sobre reward-model, no pass@1 de ejecución; "Knowing When to Quit" (2604.18419) devolvió relleno — descartado.
9. **Ausencia informativa:** cero papers miden exemplar retrieval en LiveCodeBench — toda la literatura reporta en benchmarks donde el pool puede contener el problema mismo.

**Sinergia de infraestructura:** #2 y #3 comparten el mismo wiring pendiente (embedder 0.6B + índice sobre el ledger) — hacerlo una vez, gatearlo dos veces por separado. Orden sugerido de ejecución: #1 (2h, destraba riesgo) → #2 offline → #3 → #4 → #5.