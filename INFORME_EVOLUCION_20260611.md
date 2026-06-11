# Informe de evolución de Cognia — Manager autónomo, 2026-06-11

> Generado por la sesión de manager autónomo. Cada afirmación de línea base está medida
> (file:line o JSON de resultados), no estimada. Las predicciones declaran su supuesto.

## 0. Resultados de ESTA sesión (medidos, actualizado 17:45)

| Qué | Resultado | Evidencia |
|---|---|---|
| FASE 1 generación larga | **HECHA**: gate E2E PASS 6000 tokens reales, 3 rondas de continuación automática | gate exit 0; commits b3f3c8d..5ea0506 |
| Comando /largo en REPL | Desplegado (hasta 5000 tokens con progreso) | commit 5a8e1b2 |
| Desktop API | cap 64 → 1024 tokens | commit a36586d |
| No-determinismo | **CAUSA RAÍZ CERRADA**: KV-cache cambia logits; cache off + seed = 3/3 idéntico | experimento MANAGER_LOG 16:50 |
| Baseline determinista | pass@1 = 8/20 = 40.0% reproducible al byte | results_code_hard_det_20260611_1701 |
| Grammar GBNF (ROI 4) | **MEDIDA Y SIN GANANCIA**: 8/20 idéntico task-por-task — los fallos son de lógica, no de formato | results_code_hard_det_grammar_20260611_1729 |
| HYDRA → prompt (ROI 5) | **VIVA**: band_router inyecta memoria en el fast-path; smoke recall real PASS ("Rust" desde DB, no historia) | commits 0f9dc30, 22a78e2 |
| Repair por edición (ROI 3) | **MEDIDO: 0 recovered** (8/20 sin cambio; mayoría search_not_found — el 3B no copia exactamente sus propias líneas). Con 4 experimentos, CONCLUSIÓN: el techo es la capacidad single-shot del 3B; ningún repair lo supera. FASE 3 → QLoRA dirigido + 7B batch + few-shot | results_code_hard_det_repair_edit_20260611_1756 |
| Robustez inesperada | La generación sobrevive al sleep de la laptop (10 h dormida a mitad de ronda, completó al despertar) | run E2E #1 |

---

## 1. Línea base medida (hechos, no suposiciones)

| Dimensión | Valor medido | Fuente |
|---|---|---|
| Decode | 8.09 tok/s @3 threads, Q4_K_M, b9391 (a batería) | MANAGER_LOG:1871 |
| Prefill | 29.3 tok/s @3t | MANAGER_LOG:1871 |
| E2E orquestador | 7.77 tok/s (overhead ~5%) | MANAGER_LOG:1894 |
| pass@1 set fácil (25 tasks) | 100% — saturado, sin poder discriminativo | results_code_baseline_20260610 |
| pass@1 set duro (20 tasks) | 40% (8/20); LONG 0/5, SPEC 1/4, ALG 4/6, DBG 3/5 | results_code_hard_mt512/1024 |
| Repair por regeneración | 0 recovered (temp 0.0 y 0.5) — DESCARTADO con datos | results_code_smoke_repair* |
| Respuesta máxima (antes de hoy) | 64 tokens (desktop API), 768 (orquestador), 1024 (CLI) | mapa 2026-06-10 |
| Respuesta máxima (hoy, FASE 1) | 4996 tokens reales en 3 rondas con continuación automática, fin natural `eos` | scripts/e2e_long_gen.py run 2026-06-11 |
| Context window | 16384 (server); sin reparto explícito prompt/generación | node/llama_backend.py:51 |
| QLoRA | pipeline Kaggle corre E2E; dataset solo kg_triples (3489 pares); deltas genéricos NEGATIVOS; +69.5pp solo en knowledge_recall | checkpoints/*/eval_compare.json |
| Memoria → prompt | 0 tokens en el fast-path del CLI; HYDRA assembled_context sin consumidor | mapa 2026-06-10 |

Hechos estructurales: el techo de respuesta era 100% literales hardcodeados (no infraestructura);
no existía motivo de parada ni continuación automática (implementados hoy, commits b3f3c8d..a36586d);
solo `temperature`+`stop` se envían al server (sin top_p/top_k/seed/grammar); nadie usa /tokenize ni /props.

---

## 2. Top 10 mejoras por ROI (impacto/esfuerzo, ordenadas)

1. **[HECHO HOY] Caps fuera + continuación automática** — desktop API 64→1024, max_tokens por
   llamada, `generate_long()` 5000 tokens. ROI infinito: 1 día de trabajo, 5-78x en longitud de respuesta.
2. **Determinismo del benchmark** — enviar `seed`, A/B con `cache_prompt:false`, verificar `GET /props`
   y persistir config del server en cada JSON. Sin esto, todo delta futuro de ±1 task (±5pp) es ruido
   (flip ALG2 ya observado a temp=0). Esfuerzo: horas. Desbloquea TODA medición posterior.
3. **Repair por edición puntual (LLM → dev_tools)** — la regeneración completa ya falló (0 recovered);
   el loop search→edit→test está operativo y verificado. Falta solo el wiring LLM→old_string/new_string
   desde el traceback. Palanca directa sobre los 12 FAIL del set duro.
4. **Grammar GBNF "solo bloque Python"** — [MEDIDA 17:29: SIN GANANCIA en este set — 8/20 idéntico;
   los fallos son de lógica/semántica, no de formato. Queda como infraestructura útil para outputs
   estructurados (SEARCH/REPLACE, JSON), no como palanca de pass@1.]
5. **Memoria al fast-path** — hoy el camino dominante lleva 0 tokens de memoria; inyectar el bloque de
   conversation_memory (≤210 tokens) o HYDRA assembled_context (~10 líneas de integración) da recall
   entre sesiones por ~2% del ctx.
6. **Presupuesto de historia por tokens (/tokenize)** — `_history[-16:]` sin cap permite que un paste
   largo desborde los 16384 o infle el prefill a minutos. Esfuerzo: horas.
7. **Re-baseline limpio + timings persistidos** — los runs duros están contaminados (pre-fix timeout 120s);
   persistir `timings` del server separa prefill de decode (hoy 5.8 "tok/s" mezcla ambos).
8. **A/B de velocidad sin código** — cargador vs batería (todo el baseline es a batería), KV q8_0
   (--cache-type-k/v), --ubatch-size, --mlock. Cada uno son minutos de medición; upside 10-25% decode.
9. **Dataset de código para QLoRA apuntado a LONG/SPEC** — no existe NINGÚN dataset de código en el repo;
   el set duro quedó discriminativo (40%) justo para medir el delta real del adapter.
10. **dev_tools alcanzables desde el planner** — template `fix_bug_in_repo` + casos en `_build_kwargs`
    (supervisor.py:198). Hoy las 4 tools están registradas pero ningún plan puede usarlas.

## 3. Top 10 mejoras revolucionarias (físicamente posibles, alto upside)

1. **Generación jerárquica con outline** (plan→secciones→relleno por sección): rompe el techo de ctx
   único; 20k-100k tokens efectivos componiendo secciones generadas con prompts frescos. Analogía: no
   se escribe un libro de corrido; se escribe el índice y luego capítulo por capítulo.
2. **Continuación con compresión incremental**: cuando prompt+generado se acerca a 16k, resumir lo ya
   generado (o usar solo el tail + outline) y seguir — generación "infinita" con ctx fijo.
3. **Modelo 7B Q4_K_M vía `LLAMA_GGUF_PATH`** (~4.5 GB): techo de calidad del 3B es el límite real de
   pass@1; en esta máquina decode caería a ~3-4 tok/s — usable para tareas batch nocturnas, no chat.
4. **Loop agéntico LLM-driven medible**: el modelo decide pattern/old_string/new_string sobre las tasks
   DBG del set duro — primer benchmark de capacidad agéntica real del 3B.
5. **Generación sintética en Kaggle GPU**: usar las 30h/semana de GPU gratis para generar dataset de
   código con un modelo grande (Qwen 32B) y destilar al 3B vía QLoRA — el pipeline Kaggle ya corre E2E.
6. **Adapters LoRA por banda con hot-swap** (LOGOS/TECHNE/RHETOR como MoE de adapters sobre el mismo
   base 3B): especialización sin duplicar el modelo.
7. **Slot persistence de llama-server (id_slot)** para KV multi-sesión real entre usuarios/tareas.
8. **ctx 24576** (KV ~864 MB con GQA, viable en 12 GB): habilita 20k tokens de respuesta en una pasada
   de continuación (hoy el límite compuesto es ~15k de generación por ventana).
9. **Auto-mejora gated**: self_architect propone parches, verifier determinista + suite los valida en
   sandbox; humano solo aprueba el merge. Las piezas existen desconectadas.
10. **Cognia como enjambre de especialistas**: 3B coder + 0.5B router/clasificador (ya hay 0.5B en
    Kaggle pipeline) — el chico filtra/etiqueta/enruta, el grande genera. En CPU, un 0.5B decodifica
    ~5x más rápido; para clasificación de intent es gratis.

## 4. Top 10 mejoras más realistas (≤1 día de esfuerzo cada una)

1. `_SERVER_TIMEOUT` 30→90s (bug real: carga fría del GGUF de 1.9 GB falló hoy el E2E al primer intento).
2. Gate del E2E: aceptar `eos` natural con total ≥95% del target (hoy falló por 4 tokens en 4996/5000).
3. Sampling params (`top_p/top_k/min_p/repeat_penalty/seed`) en los 3 payloads del backend.
4. `GET /props` al adoptar un server preexistente (hoy `_ping()` adopta cualquier server sin verificar flags).
5. Temperatura explícita en el fast-path del CLI (hoy el chat genera código a 0.7; el benchmark mide a 0.0).
6. Timeouts proporcionales en los caminos Ollama (orchestrator 90s fijo, game_manager 120s vs 2000 tokens).
7. Exponer `generate_long` en orquestador/CLI (comando `/largo` o auto si la pregunta lo amerita).
8. Reemplazar stub `query_episodic` (viola regla anti-stubs; degrada research_topic/explain_concept).
9. Confinar `escribir_archivo` del loop ReAct al workspace (hoy escribe en CUALQUIER path del disco).
10. E2E de dev_tools como test pytest re-ejecutable (fixture que reintroduce el bug en tmp_path).

## 5. Roadmap de implementación (orden de dependencias)

- **Semana 1 (medición confiable)**: realistas 1-5 + ROI 2 y 7. Sin determinismo ni timings, nada
  posterior es medible. Gate: re-run set duro limpio con seed fijo, varianza 0 entre 2 runs idénticos.
- **Semana 2 (calidad de código)**: ROI 3 (repair por edición) + ROI 4 (GBNF) + realista 7.
  Gate: pass@1 ≥50% en set duro con repair de 1 ronda.
- **Semana 3 (memoria/contexto)**: ROI 5-6 + revolucionaria 8 (ctx 24k si RAM lo permite).
  Gate: recall entre sesiones demostrado en CLI real; prompt nunca desborda ctx.
- **Semana 4 (entrenamiento)**: ROI 9 + revolucionaria 5 (dataset sintético Kaggle) → QLoRA → evaluar
  adapter contra set duro local. Gate: delta pass@1 ≥ +5pp sin regresión en generic eval.
- **Continuo**: revolucionarias 1-2 (generación jerárquica) como proyecto incremental sobre generate_long.

## 6. Roadmap de investigación (requiere experimentos, no solo código)

1. ¿cache_prompt:true explica el no-determinismo a temp=0? (A/B con cache off + seed fijo, 3 runs)
2. ¿KV q8_0 ayuda o duele en CPU 2c? (medir decode/prefill con --cache-type-k/v q8_0)
3. ¿Cuánto mejora con cargador? (repetir baseline enchufado — hoy TODO el baseline es a batería)
4. ¿GBNF degrada contenido al forzar formato? (pass@1 con/sin grammar, mismo seed)
5. ¿El 0.5B sirve de clasificador de intent/banda? (accuracy vs reglas actuales, latencia)
6. ¿Outline-conditioned mantiene coherencia a 20k tokens? (eval humano de 3 documentos largos)

## 7. Plan de pruebas end-to-end

- Cada subsistema cierra con CLI real + output mostrado (regla del repo). Ya existen: e2e_long_gen
  (generación larga), e2e_demo (dev_tools), benchmark_code (pass@1), test_e2e_inference (inferencia).
- Faltantes a crear: E2E loop ReAct con modelo real (marcado slow), E2E memoria entre sesiones
  (escribir→cerrar→recordar), E2E repair por edición sobre DBG tasks.
- Suite rápida como compuerta: `venv312 pytest tests/ --ignore=tests/test_e2e_inference.py -q`.

## 8. Riesgos principales

1. **Hardware es el techo duro**: i3-10110U 2c/4t, 12 GB, sin CUDA. Decode ~8 tok/s es techo físico
   (memory bandwidth). Mitigación: Kaggle GPU para entrenamiento, generación nocturna batch, 0.5B router.
2. **No-determinismo no resuelto** contamina toda métrica (±5pp en set de 20). Mitigación: ROI 2 primero.
3. **Sleep/suspensión de la laptop** rompe tareas largas (hoy: 10h de sleep en medio del E2E; el
   sistema sobrevivió, pero el wall-clock se destruye). Mitigación: powercfg para sesiones batch + WakeToRun.
4. **QLoRA puede empeorar** (ya pasó: -5pp genérico con dataset kg). Mitigación: eval de código local
   obligatorio antes de adoptar cualquier adapter.
5. **Regresión silenciosa de backend**: try_load() prioriza llama-cpp-python SIN tuning; instalar
   llama_cpp en venv312 degradaría velocidad en silencio. Mitigación: realista 4 (/props) + invertir orden.
6. **Seguridad agéntica**: `escribir_archivo` sin confinamiento es un riesgo real hoy (realista 9).

## 9. Métricas esperadas y predicción cuantitativa

| Métrica | Hoy | Tras roadmap (4 semanas) | Supuesto |
|---|---|---|---|
| Tokens/respuesta máx | 4996 (medido hoy) | 20000 | ctx 24k + continuación encadenada; ~45 min wall |
| Tokens/respuesta producto | 1024 | 5000 por defecto en tareas largas | generate_long en CLI/API |
| Decode tok/s | 8.09 (batería) | 8.3-9 (revisado) | cargador MEDIDO 18:20 ≈ 0 ganancia (7.4-7.6 wall ≈ mismo decode); quedan mlock, ubatch, KV q8_0 sin medir |
| pass@1 set duro | 40% | 50-60% (revisado) | GBNF medido = 0pp (descartado); palancas restantes: repair edición (A/B en curso; smoke débil), QLoRA dirigido, 7B batch |
| pass@1 con QLoRA dirigido | — | +5-10pp adicionales | dataset sintético de calidad apuntado a LONG |
| Memoria en prompt | 0 tokens | ~210-800 tokens útiles | conversation_memory + HYDRA wiring |
| Varianza benchmark | ±5pp (ruido) | ~0 (seed fijo) | ROI 2 |
| Capacidad agéntica | no medida | benchmark DBG agéntico ≥3/5 | loop LLM-driven |

**Predicción global**: con las 10 mejoras de ROI implementadas, Cognia pasa de "chat capado de 1k tokens,
40% pass@1, sin memoria en prompt" a "respuestas de 5-20k tokens, ~60% pass@1 en set duro, memoria real
entre sesiones, benchmark determinista y loop de reparación agéntico medible" — sin cambiar de hardware
y sin violar ninguna restricción del repo (sin PyTorch en nodos, sin WAN sharding, sin datos centralizados).

## 10. Autocrítica (qué podría invalidar este plan)

- ¿Y si el no-determinismo NO es cache_prompt? → el A/B lo decide en horas; si persiste, fijar
  binario+seed+slot y aceptar varianza documentada.
- ¿Y si GBNF empeora el contenido al forzar formato? → MEDIDO 17:29: ni mejora ni empeora (8/20
  idéntico); la hipótesis "fallos de formato" no sobrevivió a la medición — eran fallos de lógica.
- ¿Y si el repair por edición tampoco recupera? → MEDIDO 17:56: 0 recovered (search_not_found
  dominante). La palanca pasa, con datos, a QLoRA dirigido + 7B batch + few-shot. Idea no probada
  que queda anotada: dar al modelo el código NUMERADO por líneas y pedir "línea N → nuevo texto"
  (elimina la necesidad de copiar exacto, que es donde falla).
- ¿Y si 20k tokens nunca caben (prompt+gen > ctx)? → la generación jerárquica (revolucionaria 1) no
  depende del ctx: compone ventanas frescas; es el plan B estructural.
- ¿Sesgo de optimismo en +15-25pp de pass@1? → las bandas son independientes (SPEC formato vs DBG
  lógica), los upsides no se solapan, pero el rango bajo (55%) asume que solo una de las dos palancas rinde.
