# PLAN — Cognia Creativo (misión /manager 2026-06-13)

> Mapa de decisión VERIFICADO por workflow de inventario (6 exploradores + síntesis,
> 7 agentes, ~526k tokens). Cada veredicto tiene evidencia de call-site real.
> Regla del repo: verificar que corre de verdad antes de construir encima.

## Paquete VIVO
`cognia/` es el real. El REPL arranca en `cognia/__main__.py:416` → `cognia/cli.py:19`
→ `cognia/cognia.py` (1999 líneas). Backend de inferencia = **ShatteringOrchestrator /
llama-server (GGUF)**, instancia compartida en `cognia.py:301-308` (`self._orchestrator`),
que adopta el server corriendo una sola vez (`_try_load_llama` con guard `_llama_checked`).
`cognia_v3/core/cognia_v3.py` (3609 líneas) es ZOMBIE: solo lo importan módulos internos de
v3 y tests, NUNCA el REPL. OJO: el paquete vivo `cognia/` depende de DOS clases que viven en
`cognia_v3/core`: `ReasoningPlanner` (config.py:32) y `CuriosityEngine` (config.py:40).

## RIESGO #1 (verificado) — backend Ollama hardcodeado en los generadores
El backend vivo es llama-server/GGUF. Pero varios módulos generadores llaman **Ollama
hardcodeado** (`http://localhost:11434`, `llama3.2`), que NO corre → timeout → None →
silenciado por `except: pass`. Resultado: ese pipeline es un **NO-OP silencioso**.
- `cognia/reasoning/hypothesis.py:124` — OK: orchestrator PRIMARIO, Ollama solo fallback.
- `cognia/program_creator/generator.py:19-21` — MAL: Ollama PRIMARIO (lab muerto).
- `cognia/research_engine/researcher.py:21-22` — MAL: Ollama hardcodeado.
- `self_architect.generate_module_code:2406` — MAL: Ollama hardcodeado.

`orchestrator.infer(prompt, max_tokens=)` devuelve `InferResult.text`. **NO expone
`temperature`** → para generación divergente hay que threadearla (default None = compat).

## Las 8 piezas del GOAL — veredicto

| # | Pieza | Veredicto | Base | Esf |
|---|-------|-----------|------|-----|
| 1 | Generación de hipótesis (3-10, plausibilidad, pruebas, refinamiento) | REESCRIBIR | `cognia/reasoning/hypothesis.py` (VIVO, pero 1 hipótesis/par, plausibilidad=coseno) | L |
| 2 | Analogías transversales (problema→dominio→solución→mapeo) | CONSTRUIR | ninguna (AnalogyEngine de v3 es ZOMBIE Levenshtein) | L |
| 3 | Transferencia de conocimiento (principio abstracto A→B) | CONSTRUIR | ninguna | L |
| 4 | Modo explorador 70/30 | CONSTRUIR | señales vivas: `get_curiosity_score`, collapse_guard | M |
| 5 | Laboratorio de experimentación | REUSAR | `cognia/program_creator/` (sandbox+evaluator VIVOS; generador Ollama-muerto) | M |
| 6 | Detector de repetición | REESCRIBIR | `cognia_v3/core/model_collapse_guard.py` (VIVO, detecta labels no soluciones) | M |
| 7 | Motor de abstracción (concreto→abstracto→resolver→traducir) | CONSTRUIR | ninguna | L |
| 8 | Autoevaluación de novedad (novedad×factibilidad×impacto) | REESCRIBIR | `cognia_v3/core/self_architect.py` (VIVO, infra scoring/ranking/meta-learning) | M |

## Orden de construcción (por ROI + dependencias)
0. **FUNDACIÓN (transversal)**: helper `creative_generate(orchestrator, prompt, temperature,
   max_tokens)` que rutea al backend vivo + threadear `temperature` en `orchestrator.infer`.
   Desbloquea 1/2/3/5/7. Migrar los generadores Ollama→orchestrator.
1. Pieza (1) hipótesis multi (3-10 + plausibilidad por LLM, prompt libre). Entrada del pipeline.
2. Pieza (5) laboratorio: revivir program_creator (migrar backend + generalizar a validar hipótesis).
3. Pieza (8) novedad×factibilidad×impacto: reescribir scoring de self_architect.
4. Pieza (6) detector de repetición: patrones de solución + forzar alternativas.
5. Pieza (4) explorador 70/30: asignador epsilon-greedy que consume señales de 6 y 8.
6. Piezas (7)+(2)+(3): subsistema compartido de "mapeo abstracto" (lo más caro, último).

## Zombies
- REVIVIR: `cognia/reasoning/cognitive_loop.py` (780 líneas, 0 call sites pero TESTEADO:
  test_cognitive_loop.py 16 + test_deliberation_loop.py 5). Maquinaria generate→world-model
  →critique→verify→replan: base natural del refinamiento iterativo de pieza (1).
- REVIVIR PARCIAL: pipeline de `cognia_v3/core/curiosity_engine.py` (run_cycle, QuestionGenerator).
- BORRAR: `register_routes_additional_modules` + 5 clases ZOMBIE en cognia_modules_adicionales.py.
- BORRAR bloque muerto: `language_engine.py:982-993` (hipótesis interna, guarda siempre False).

## Quick wins
- Migrar `program_creator/generator.py` al orchestrator → revive el único lab real.
- Fan-out de pieza 1: quitar el `break` tras la 1ª hipótesis (`cognia.py:992`) + loop de N.
- `self_architect.test_proposal` + `benchmark_code.py:859 run_benchmark` como motor de validación.
- Conectar `get_curiosity_score` (cognia.py:463) + `get_collapse_report` (cognia.py:660) como
  señales del asignador de budget (pieza 4) — el cableado de lectura ya existe.

## Verificación obligatoria por pieza
NO solo pytest: correr el CLI/modelo real y mostrar output (hipótesis/analogías de verdad).
Gatear por budget (i3 2 cores, techo ~8 tok/s): fan-out de 3-10 + refinamiento + lab puede
ser lento; reusar el gating de ReasoningPlanner.
