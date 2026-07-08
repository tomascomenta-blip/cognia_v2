# CLI v-next (fleet) vs CLI actual — gates y veredicto (2026-07-08)

**Pregunta**: ¿el CLI con FLEET (base Q4_K_M + experto cognia3b_v1 vivo con
hot-swap por tarea) es MEJOR que el CLI actual (base Q4_K_M + adapter tooluse
v4 estático siempre aplicado, que era la config real vía `LLAMA_LORA_PATH`)?

**Método**: mismo instrumento para ambos (`eval_g4_cli`, llama-server b9391
local, threads del deploy, greedy, suites congeladas por sha256), McNemar
pareado ítem a ítem. El baseline se midió y CONGELÓ ANTES de medir el v-next
(results_baseline_cli_actual_v4.json). Regla del programa: mejor = ninguna
regresión significativa (p<0.05 con n10>n01) y ≥1 mejora significativa.

## Resultado (N: G1=100, G2A=147, G3=20, G5=25)

| Gate | ruta v-next | CLI actual | CLI v-next | delta | p | veredicto |
|---|---|---|---|---|---|---|
| G1 general | chat → base pura | 88.0% | 88.0% | 0.0pp (n01=1,n10=1) | 1.0 | sin regresión |
| G2A ACCION | agente → experto | 87.8% | **95.2%** | **+7.5pp** (n01=13,n10=2) | **0.0074** | **MEJORA sig.** |
| G3 identidad | router → experto | 0.0% | **85.0%** | **+85.0pp** (n01=17,n10=0) | **~0** | **MEJORA sig.** |
| G5 español | chat → base pura | 56.0% | 56.0% | 0.0pp (n01=0,n10=0) | 1.0 | sin regresión |

**VEREDICTO: v-next MEJOR — 2 mejoras significativas, 0 regresiones.**

## Composición del v-next (por qué el fleet gana sin pagar el costo del adapter)

- El experto cognia3b_v1 regresiona G1 −8pp si está SIEMPRE puesto (kernel
  E2-FINAL, p=0.039). El fleet lo activa SOLO donde ayuda:
  - tareas de agente (`_run_agent_task`): G2A 20.4%→95.2% vs base pelada.
  - turnos de identidad en chat (router léxico `fleet_router`, cobertura
    20/20 sobre la suite G3, 0 falsos positivos en el set de control).
  - chat general y `/largo`: base pura → G1/G5 idénticos al mejor caso.
- G3 en deploy da 85% (17/20) vs 100% del kernel: dilución Q4_K_M del delta
  LoRA (mismo fenómeno medido con tooluse v4). El ítem CLI-nivel es
  router(20/20) × experto(17/20).
- Hallazgos de implementación (medidos, no asumidos):
  1. `--lora-init-without-apply` del b9391 deja el adapter en scale 1.0 al
     arrancar → `_force_base_scales()` postea ceros explícito.
  2. Tras un POST /lora-adapters el KV cache es inválido y llama.cpp no lo
     invalida → la 1ª request post-swap va con `cache_prompt=false`
     (`_consume_lora_dirty` en las 3 rutas de generación).
  3. Un server ADOPTADO no garantiza el fleet del manifiesto → match por
     basename o fleet OFF con warning.

## Config del deploy

- `model_shards/qwen-coder-3b-q4/adapters.json` (junto al GGUF, local):
  `{"adapters": [{"name": "accion", "file": "cognia3b_v1_f16.gguf"}]}`
- `LLAMA_LORA_PATH` (User scope) BORRADA 2026-07-08: apuntaba al v4 estático;
  con ella seteada el fleet se desactiva (modo estático histórico).
- Adapter GGUF regenerable: `convert_lora_to_gguf.py` b9391 sobre
  `cognia_v3/training/cognia3b/results_e2final/adapters/cognia3b_v1`.

## Evidencia

- results_baseline_cli_actual_v4.json (baseline congelado, 16.7 min)
- results_g4_e5_cognia3b_v1.json (experto G1+G2A, G4 PASA vs kernel)
- results_vnext_chat_base.json (base pura G1+G5)
- results_vnext_identidad_experto.json (experto G3)
- scripts/e2e_fleet_smoke.py → 8/8 checks con server real
- Pendiente conocido: E2-FINAL-v2 (Kaggle) puede producir un candidato único
  sin regresión G1; si pasa, reemplaza al v1 como experto (mismo pipeline).
