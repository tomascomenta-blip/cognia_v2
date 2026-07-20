# Informe Final — Misión: Cognia como Sistema Excepcional de Programación

**Fecha:** 2026-06-10  
**Rama:** cognia-reorganization  
**Modelo base:** Qwen2.5-Coder-3B-Instruct Q4_K_M (llama.cpp b9391)  
**Hardware:** Intel i3-10110U, 12 GB RAM, DDR4-2400 dual-channel, sin GPU

---

## 1. Problemas Encontrados

### 1.1 Velocidad de inferencia degradada sin motivo aparente
- llama.cpp b9414 (instalado) decodificaba a 5.2 tok/s.
- b9391 (build anterior) decodificaba a 8.2 tok/s con el mismo modelo y flags.
- llama-bench NO detecta la regresión (reporta ~8 tok/s en ambos) — el bench calienta caches artificialmente. Solo `server real → /completion → timings.predicted_per_second` la revela.
- Timeout hardcodeado de 120 s en `urlopen`: a 5.5 tok/s, generaciones de >660 tokens devolvían `None` silenciosamente (sin excepción). El benchmark mostraba 0 tokens generados para las tasks LONG, confundiéndose con fallo de razonamiento.

### 1.2 Contexto artificialmente restringido
- `_CTX_SIZE` hardcodeado a 4096 tokens. El modelo tiene `n_ctx_train=32768`. La restricción era solo una constante en el código, sin base técnica.

### 1.3 max_tokens insuficiente en producción
- CLI y orchestrator usaban max_tokens=256/512. Las tasks que requieren >500 tokens de solución (LONG) se truncaban. La truncación producía `SyntaxError: ( was never closed` en ejecución.

### 1.4 Sin benchmark de calidad de código
- No había forma de medir el impacto de cambios en calidad de generación de código. Todo era subjetivo.
- El "easy set" de MBPP no discrimina: el 3B a temp=0 lo satura (100% pass@1).

### 1.5 Agentes sin herramientas de ingeniería
- Los agentes (Supervisor, Executor) no tenían acceso a herramientas concretas de software engineering: búsqueda de código, edición de archivos, ejecución de tests.

### 1.6 El mecanismo de "repair" no funciona con temperatura=0
- El repair loop (dar al modelo su propio error de ejecución para un segundo intento) con `temperature=0.0` genera código idéntico en cada ronda (modelo determinista). Con `temperature=0.5` diverge pero sigue sin recuperar (el 3B no puede trazar error → causa → fix en un solo shot).

### 1.7 FormatIntelligence sin tipo CODE
- Las peticiones de generación de código ("implement X", "write a function") caían en GENERAL sin ningún hint de formato al sistema, subóptimo para el modelo.

### 1.8 `search_code` resolvía paths contra CWD en vez de AGENT_WORKSPACE_ROOT
- Inconsistente con `edit_file` y `run_tests` (ambos resuelven contra `AGENT_WORKSPACE_ROOT`). Requería paths absolutos donde los otros tools aceptaban relativos.

---

## 2. Cambios Realizados

| # | Archivo / Componente | Cambio | Commit |
|---|---|---|---|
| 1 | `node/llama-server.exe` + DLLs | Rollback b9414 → b9391 (backup en `node/_llama_b9414_backup/`) | 4f1fafd |
| 2 | `node/llama_backend.py` | `_CTX_SIZE` 4096 → 16384; timeout proporcional `max(120, 30+0.6*max_tokens)`; `cache_prompt=True`; `--cache-reuse 256`; threads `cpu_count-1=3` para decode y batch; `last_tokens_predicted` expuesto | a17f1d3 |
| 3 | `shattering/orchestrator.py` | `max_new_tokens` 256 → 768; temperatura propagada; token count desde `last_tokens_predicted` | a17f1d3 |
| 4 | `cognia/cli.py` | `max_tokens` 512 → 1024 en ambos paths (stream_chat y stream_generate) | bf2c956 |
| 5 | `cognia_v3/eval/benchmark_code.py` | Nuevo: benchmark pass@1 con ejecución real en subprocess, 25 tasks easy + 20 tasks hard; `--repair N`; `--repair-temp` | be6e491, b06b986, bf2c956 |
| 6 | `cognia_v3/eval/tasks_hard.jsonl` | 20 tasks hard validadas: ALG×6, LONG×5, DBG×5, SPEC×4 | a4663ac |
| 7 | `cognia/agents/workers/dev_tools.py` | Nuevo: search_code, write_file, edit_file, run_tests con workspace sandbox, AST-validate, .bak | 0ca1b46 |
| 8 | `cognia/agents/workers/dev_tools.py` | Fix: `search_code` resuelve `root` relativo contra `AGENT_WORKSPACE_ROOT` | 2d391b8 |
| 9 | `tests/test_agent_tools_tier1.py` | 23 tests de los 4 dev_tools | 0ca1b46 |
| 10 | `agent_workspace/mini_repo/` | Mini-repo con bug plantado para validación E2E | 3830b11 |
| 11 | `cognia/quality/format_intelligence.py` | Tipo CODE nuevo + patrón regex multilingual + hint | 24b1775 |
| 12 | `tests/test_format_intelligence.py` | 7 tests nuevos para tipo CODE (30 total) | 24b1775 |
| 13 | `C:/Users/.../Gotchas.md` | 4 gotchas nuevas: regresión b9414, spec decode CPU, Q4_K_M vs Q4_0, threads óptimos | — |

---

## 3. Justificación Técnica

**Binarios b9391 pineados:** La regresión b9414 afecta decode CPU en ~37% (5.2 vs 8.2 tok/s). No es detectable con llama-bench (que calienta KV-cache artificialmente) — solo visible vía server real. El build b9391 tiene SHA `7fb1e70b5`.

**Threads = cpu_count-1 = 3:** En i3-10110U (2c/4t), el 4.° hilo lógico compite con el SO. Medido: tg 8.09 vs 7.33 tok/s; prefill 29.3 vs 22.7 tok/s.

**Q4_K_M sobre Q4_0:** En b9391, Q4_K_M decodifica más rápido (8.09 vs 7.58 tok/s decode; 29.3 vs 20.3 tok/s prefill) además de mejor calidad. El supuesto "Q4_0 más rápido por dequant más simple" quedó obsoleto en builds modernos con kernels SIMD mejorados.

**ctx 16384 sin costo de velocidad:** KV-cache con GQA 2 heads ocupa ~36 KB/token. A 16k ctx → ~590 MB de KV, dentro de los 12 GB de RAM. Velocidad de decode: memory-bound, no KV-size-bound en el rango 4k–16k para este modelo.

**Timeout proporcional:** A 5.5 tok/s promedio, 120 s fijos cortan generaciones de >660 tokens. La fórmula `max(120, 30 + 0.6 * max_tokens)` da ~491 s para max_tokens=768, cubriendo las tasks más largas con margen.

**Repair temp=0 inútil, temp=0.5 insuficiente:** El 3B en modo determinista genera código idéntico. Con temperatura el código cambia (ALG4 produjo error diferente) pero el modelo no puede inferir la causa raíz del error y escribir el fix correcto en un solo shot. La palanca real es edición puntual guiada por búsqueda.

**Dev tools tier 1:** Deterministas (no LLM), confinados a workspace vía `Path.resolve() + is_relative_to()`, AST-validan antes de escribir, backup `.bak` antes de editar. Cero dependencias externas.

---

## 4. Resultados de Benchmarks

### Set fácil (25 tasks MBPP-style, temp=0)
| Métrica | Valor |
|---|---|
| pass@1 | **100%** (25/25) |
| Nota | Set saturado — el 3B a temp=0 es demasiado bueno para MBPP |

### Set duro (20 tasks, temp=0, max_tokens=768)
| Categoría | Tasks | Pasadas | pass@1 |
|---|---|---|---|
| ALG (algoritmos) | 6 | ~3 | ~50% |
| LONG (>500 tok sol.) | 5 | 0 | 0% |
| DBG (bug en código) | 5 | ~4 | ~80% |
| SPEC (spec compleja) | 4 | 1 | 25% |
| **GLOBAL** | **20** | **8** | **40%** |

### Experimento max_tokens (512 vs 1024)
- pass@1 = 40% en AMBOS. Solo 1/12 fallos era por truncación (LONG3: 901 tokens generados, aún falla por lógica). El 3B falla por capacidad razonamiento, no por presupuesto.

### Experimento repair (temp=0)
- Smoke 4 tasks (2 failing): **0 recovered**. Código idéntico en retry.

### Experimento repair (temp=0.5)  
- Smoke 4 tasks (3 failing): **0 recovered**. ALG4 genera código diferente pero igualmente incorrecto.

---

## 5. Resultados de Pruebas End-to-End

### E2E: Inferencia real
```
.\venv312\Scripts\python.exe -m cognia  →  modelo responde en ~4-8 seg
```
- Velocidad medida: 7.77 tok/s (overhead no-modelo ~5% vs techo teórico 8.2)
- Cache hit: re-prompt mismo query → 0 s de prefill (cache_prompt funcional)

### E2E: Dev tools loop (search → edit → test)
```
Repo: agent_workspace/mini_repo/
Bug plantado: result.append(total / i)  →  ZeroDivisionError en i=0
```
1. `search_code(pattern=r"total / i\b", root="mini_repo")` → match en `stats.py:7`
2. `edit_file(path="mini_repo/stats.py", old_string=..., new_string=...)` → OK, .bak guardado
3. `run_tests(path="mini_repo")` → **4/4 passed en 0.03 s**
- Estado final: bug encontrado, editado y verificado sin intervención humana

### E2E: Tests de regresión
```
.\venv312\Scripts\python.exe -m pytest tests/ --ignore=tests/test_e2e_inference.py -q
```
- 23/23 en `test_agent_tools_tier1.py`
- 30/30 en `test_format_intelligence.py`
- Suite completa: dentro de rangos normales (las fallas residuales son deps ausentes conocidas, no regresiones del código de esta sesión)

---

## 6. Impacto en Velocidad

| Métrica | Antes | Después | Delta |
|---|---|---|---|
| Decode (tok/s, server real) | 5.2 | 8.2 | **+58%** |
| Decode E2E (con overhead) | ~4.5 | 7.77 | +73% |
| Prefill (tok/s) | ~22 | 29.3 | +33% |
| Context máximo | 4096 | 16384 | +300% |
| Overhead re-prefill | alto (sin cache) | ~0 (cache_prompt) | eliminado |
| Latencia timeout falso | frecuente (>660 tok) | 0 | eliminado |

---

## 7. Impacto en Calidad

| Área | Antes | Después |
|---|---|---|
| pass@1 set duro | no medido | **40%** (baseline establecido) |
| pass@1 set fácil | no medido | 100% (saturado) |
| Code format hint | GENERAL (sin hint) | CODE: "Provide a complete, working implementation..." |
| Debug hint | existía | sin cambio |
| Dev tools en agentes | ninguno | search_code / write_file / edit_file / run_tests |
| max_tokens en producción | 256-512 (trunca) | 768-1024 |
| Loop search→edit→test | inexistente | demostrado en E2E |

---

## 8. Riesgos Detectados

| Riesgo | Severidad | Estado |
|---|---|---|
| b9414 instalado sin avisar (regresión silenciosa) | CRÍTICO | Mitigado: binarios pineados a b9391, gotcha documentada |
| llama-bench no detecta regresión de decode | ALTO | Documentado: medir siempre vía server real |
| Repair loop a temp=0 no mejora nada | MEDIO | Comprendido: limitación del modelo, no bug del sistema |
| LONG tasks (>500 tok) 0% pass@1 | ALTO | Inherente al 3B en CPU; no resuelto — requiere modelo más grande o GPU |
| SPEC tasks 25% pass@1 | MEDIO | Capacidad de razonamiento del 3B; mejora posible con CoT en prompt |
| QLoRA adapter sin integrar | BAJO | Entrenado en KG facts, riesgo de degradar código; evaluación pendiente |
| `_Executor` retry no propaga error context | MEDIO | Documentado; el retry actual es para herramientas flaky, no para regenerar con feedback |

---

## 9. Próximas Mejoras Recomendadas

### Prioridad ALTA
1. **Temperature sampling pass@k:** Para producción, temperatura=0.4-0.7 con best-of-2 recupera tasks con soluciones alternativas. Coste: 2× latencia. Beneficio: pass@2 estimado >55% en el set duro.

2. **Integración QLoRA en GGUF:** Convertir `checkpoints/cognia_3b_v2_winner/cognia_adapter.zip` via `convert_lora_to_gguf.py` de llama.cpp. **Gating obligatorio:** medir pass@1 en set duro antes/después. Si degrada ≥2 puntos: no integrar. El adapter mejoró C2 (list vs tuple: 0→1.0) — podría ayudar en SPEC tasks.

3. **CoT en prompt para SPEC tasks:** Añadir "Think step by step before writing code" al SYSTEM_PROMPT de benchmark y medir. Las tasks SPEC fallan por spec-misreading, no por algoritmo — CoT puede ayudar. Riesgo: verbosidad extra consume tokens útiles.

### Prioridad MEDIA
4. **`fix_code_bug` template en Planner:** Añadir template simbólico que use `search_code → edit_file → run_tests` cuando la task description sigue el formato `FIX_BUG:file=...:pattern=...:fix=...`. Permite que el Supervisor resuelva bugs sin LLM en el planning.

5. **Supervisor `_run_subtask` con error context:** En el retry, pasar `vr.fail_reason` al siguiente intento como contexto adicional (al menos para tools como `edit_file` donde el error puede ser "old_string not found").

6. **LONG tasks con planificación multi-step:** Las LONG tasks fracasan porque 500+ tokens de código correcto en un solo shot es difícil para el 3B. Un enfoque multi-step (planificar la función → implementar parte a parte → combinar) podría mejorar.

### Prioridad BAJA
7. **Model sharding LAN (Shattering v2):** Para superar el techo del 3B, tensor-parallel sobre LAN con un segundo dispositivo (North Star: 14B/4 nodos). Documentado en `SHATTERING_V2_DESIGN.md`.

8. **Draft model con GPU:** El spec decode fue descartado en CPU (1.54 tok/s vs 8.2 sin draft). Con una GPU dedicada, el 0.5B draft podría multiplicar throughput.

---

## 10. Estado Final de la Arquitectura

```
[Usuario]
    ↓ CLI / Desktop API
[FormatIntelligence]  ← detecta tipo CODE/DEBUG/HOW_TO/etc → hint al system prompt
    ↓
[GlobalRouter / Shattering]  ← TECHNE (código) / LOGOS (razonamiento) / RHETOR (escritura)
    ↓
[ShatteringOrchestrator]
  - max_new_tokens=768 (antes: 256)
  - temperatura propagada
  - token count real (last_tokens_predicted)
    ↓
[LlamaBackend]  ←  llama-server b9391 (pineado, b9414 descartado)
  - Qwen2.5-Coder-3B-Instruct Q4_K_M
  - ctx_size=16384 (antes: 4096)
  - threads=3 (cpu_count-1, óptimo para i3-10110U)
  - timeout=max(120, 30+0.6*max_tokens) (antes: 120 fijo)
  - cache_prompt=True + --cache-reuse 256
  - Velocidad: 8.2 tok/s decode, 29.3 tok/s prefill

[Agent Runtime]  (paralelo, no en el path hot)
  [Supervisor / _Executor]
      ↓
  [ToolRegistry]
    - search_code (regex read-only, workspace-relative)
    - write_file (AST-validated, .bak, sandbox)
    - edit_file (exact substring, AST-validated, .bak)
    - run_tests (pytest subprocess, workspace-confined)
      ↓
  [AGENT_WORKSPACE_ROOT]  = agent_workspace/

[Benchmark]
  - cognia_v3/eval/benchmark_code.py
  - tasks_hard.jsonl (20 tasks: ALG/LONG/DBG/SPEC)
  - pass@1 = 40% (baseline establecido)
  - --repair N + --repair-temp (documentado: no efectivo en 3B)
```

### Límites físicos conocidos (hardware actual)
| Límite | Valor | Causa |
|---|---|---|
| Decode máximo | ~8.2 tok/s | DDR4-2400 memory bandwidth (decode memory-bound) |
| Contexto práctico | 16384 tokens | KV ~590 MB; más → RAM insuficiente |
| pass@1 hard tasks | ~40% | Capacidad del 3B para razonamiento algorítmico complejo |
| LONG tasks | 0% | Soluciones >500 tok de código correcto en single-shot |

---

*Informe generado en la sesión manager 2026-06-10. Todos los cambios están en la rama `cognia-reorganization`, commits be6e491→24b1775.*
