# Diagnóstico técnico: por qué una tarea larga muere en Cognia 4.26 y qué se construye encima

Fecha 2026-09-04. Fuentes: `01_almacenes.md`, `02_contexto.md`, `03_cli_observabilidad_bancos.md` (todo con archivo:línea).

## Arquitectura original (medida)

- Prompt por turno = `system` (640 tok) + 73 schemas de tools (7.603 tok, fuera de `mensajes`) + `user[0]` (bloque `<memoria>` HYDRA + índice de skills de 4.223 chars + 2 tareas previas + TAREA) + historial append-only (assistant con `reasoning_content` ENTERO y los `arguments` crudos; tools offloadeadas > 2.000 B). Coste fijo ≈ 10k tokens por petición.
- n_ctx real hoy 65.536; la cuenta es chars/4 sin tokenizer (−7 % a −22 % de error: la compactación dispara con 55–63k reales cuando cree 51,6k). El delta del turno no suma los `arguments` de los tool calls.
- Mecanismos, TODOS sustractivos: `_compactar_por_resumen` (0.8 de n_ctx; un splice; resumen de 4.000 chars con "PROXIMOS PASOS: ninguno registrado" SIEMPRE porque nadie llama `anotar_pendiente`) → `_recortar_mensajes` (muta los turnos viejos 3 por pasada en `while`, rompe el prefix cache) → `_recorte_de_emergencia` al 0.92 (pop de mensajes enteros SIN volcado a disco) → 400 del server a 65.536 → tras 2 reintentos la tarea muere con el parcial.
- Se PIERDE sin copia: resultados de tools de 400–2.000 B (no offloadeados), el CoT viejo, mensajes enteros en la emergencia, y el canal de estado no se reinyecta salvo tras truncado. Governance decay medido: 0/5 restricciones sobreviven a la compactación.
- Persistencia: `chat_history` guarda turnos de chat, NO los `/hacer` explícitos; `~/.cognia_agent_state.json` se escribe al FINAL; `canal.guardar` no tiene llamadores; `estado_tarea`/`bitacora` solo con `COGNIA_HORIZONTE=1`; `checkpoints/` son de FICHEROS. Si el proceso muere a mitad de un `/hacer`: quedan ficheros y offloads sueltos, ninguna tarea, plan ni next_action.
- Memoria existente: `cognia_memory.db` (39 tablas, 20 MB; `episodic_memory` con 300 chars por tarea y vectores como JSON de texto = 45 % de la DB; ya explotó a 1,8 GB), `ContextMap` (BM25 + vectores) con tablas VACÍAS, `HierarchicalMemory` de 5 capas que nadie cablea, KG de 23.100 triples (9.620 útiles de `code_graph`, 12.507 ruido regex), embeddings MiniLM-L6 en CPU (384 d, 7–10 ms/texto, 23,6 s de carga fría, sin caché persistente). El loop lee para el prompt SOLO el bloque `<memoria>` al arrancar.
- Sin tokenizer, sin Context Builder, sin retrieval del historial propio desde el arnés, sin checkpoint de tarea, sin `next_action`, sin evento de compactación en la telemetría.

## Lo que se construye (sobre lo existente, sin duplicar)

`cognia/memoria_larga/` (contrato en `__init__.py`): almacén SQLite propio con FTS5 + vectores + relaciones + checkpoints; extracción selectiva sin modelo (importancia 1-5); dedup y contradicciones con historial (`supersedes`); retrieval híbrido con reranker configurable y explicaciones; Context Manager con presupuestos y estimación de tokens calibrada (`/tokenize` con caché, 3,71 chars/token medido); REBUILD en lugar de resumen-del-resumen (un solo splice, cache-friendly); checkpoint de tarea automático con `next_action`; recuperación tras crash (`cognia hacer --retomar`, `/hacer retomar` sin gate de horizonte, aviso al arrancar el REPL); observabilidad (`/contexto stats`, `/memoria buscar|inspeccionar|porque`, `/checkpoint lista`, evento `compactacion` en telemetría); bancos con historiales sintéticos de 100k a 10M tokens y comparación ANTES/DESPUÉS.

Reusa: `estado.canal` (L0/L1 verificado), `estado_tarea`+`bitacora` (durabilidad), `cognia_embedding` (vectores), `harness/offloading` (texto completo), `horizonte.prompt_de_ronda` (traspaso).
