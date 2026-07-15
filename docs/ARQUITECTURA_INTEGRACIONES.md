# Arquitectura de integraciones nativas (Cognia)

**2026-07-14.** Cómo las capacidades de herramientas OSS quedaron absorbidas
como módulos propios de Cognia (mandato de integración nativa). Regla que rige
todo: *evolucionar lo existente, nunca duplicar*. Ver `INTEGRACIONES_OSS_MAPA.md`
para el cruce herramienta↔subsistema y el estado por checkpoint.

## Principio de diseño

Cada integración es una **capacidad interna** (módulo + tool del agente),
no una interfaz humana: Cognia las usa automáticamente dentro de sus tareas.
Todas se apoyan en la infraestructura existente en lugar de traer su propia:
memoria (episódica/semántica), knowledge graph, `storage/db_pool`, el fleet
de modelos locales, el registro de tools y —nuevo— el bus de eventos.

## Bus de eventos como columna vertebral (`cognia/events.py`)

Antes no existía comunicación desacoplada dentro de `cognia/` (todo por
callbacks). El bus `emit(evento, **datos)` / `subscribe(evento, cb)` conecta
los subsistemas sin acoplarlos. Puntos de emisión activos:

```
run_tool (agent/tools.py) ── "tool.ejecutada" ──┐
reminders (al disparar)   ── "recordatorio.disparado" ─┤
sentinel (cada decisión)  ── "sentinel.evaluada" ──┤
                                                    ▼
                            historial en memoria (200) + suscriptores
                            (consumidores: /analiticas, y a futuro la
                             oficina en tiempo real y un manager)
```

Un suscriptor roto jamás rompe al emisor; thread-safe (los reminders
disparan desde un hilo daemon).

## Módulos nativos (por área)

| Área | Módulo nativo | Reusa | Herramienta OSS |
|---|---|---|---|
| Seguridad pre-acción | `agent/sentinel.py` | events, ctx.confirm | Sentinel |
| Eventos internos | `events.py` | — | Agent Reach |
| Grafo de código | `knowledge/code_graph.py` | KnowledgeGraph (mismo grafo) | Graphify + CodeGraph |
| Telemetría local | `analytics/panel.py` | bon_telemetry + usage_analytics + events | Plausible |
| Conversor documentos | `converters.py` | ingest, http_get | MarkItDown |
| Calendario | `reminders/` (recurrencia) | db_pool, NotificationCenter | Cal.com |
| Cuaderno | `notebook.py` | SmartNotes + ingest + episódica | Open Notebook |
| Oficina (entrypoint) | `/oficina` en `cli.py` | oficina/ existente | — |

## Sentinel: cadena de validación pre-acción (default-ON)

```
comando de shell
      │
      ▼
 clasificar_shell ──► BLOCK (destructivo)      ──► rechazo, auditoría
      │           ──► ALLOW (dev conocido)     ──► ejecuta
      │           ──► CONFIRM (desconocido)    ──► ctx.confirm / autónomo
      ▼
 auditoría append-only (~/.cognia/sentinel_audit.jsonl) + emit(sentinel.evaluada)
```

Reemplazó la denylist pura de `ejecutar` (default-allow) por default-deny.
Kill-switch `COGNIA_SENTINEL=0` restaura el comportamiento previo.

## Grafo de código dentro del KG

`code_graph.indexar_codigo()` parsea el repo con `ast` (stdlib) y escribe
tripletas `importa/define/tiene_metodo/llama_a` en el **mismo** knowledge_graph
(source=`code_graph`), así `/kg-camino`, `get_neighbors`, etc. operan sobre el
código sin un segundo sistema. Reindexado idempotente (no toca otras fuentes).
Medido: 518 módulos, 7808 tripletas.

## Pendiente (gated, honesto)

- **Orquestador único** (LangGraph+CrewAI+Dify+Langflow): requiere unificar
  los dos registries de tools (`agent/tools.py:TOOLS` vs
  `agents/tool_registry.py`) — invasivo, exige la suite completa.
- **Voz** (Whisper/Voicebox/Pipecat): requiere descargar modelos GGML/ONNX
  (~100-500 MB) — gated a máquina libre.
- **Navegador completo** (BrowserUse+Scrapling): navegación por links y
  formularios; hoy sólo extracción limpia de una URL (`http_get`→converters).
- **Entrenamiento distribuido / Supervision / LCD MoM**: gated por GPU externa.

## Ruteo híbrido por dificultad (2026-07-15)

La cascada por dificultad que vivía dentro de `generar_codigo` (3B → 7B →
Qwen3.5 → superorganismo) subió a **nivel de sistema**
(`cognia/agent/hybrid_router.py`): la dificultad estimada de la TAREA
(cero LLM: `max(estimador de código calibrado, señal general multi-paso)`)
más el nivel `/esfuerzo` arman el **perfil de la corrida**:

```
dificultad →  <0.12      0.12-0.30    ≥umbral       ≥0.55 (medio)
modalidad     mono       agente       agente+colonia agente+colonia+superorganismo
              (1-2       (loop ReAct, (7B/q35/4B     (etapa 4: colonia por
              pasos)     1 modelo)    reactivos)      pedazos, la más cara)
```

Las modalidades **se combinan** (no son rígidas): `/esfuerzo` desplaza el eje
(`umbral_shift`: alto entra antes a colonia; máximo despierta la etapa 4 en
tarea media; bajo niega colonia/superorganismo y recorta pasos/delegación).
El perfil da el **permiso**; el gasto sigue siendo **reactivo** (una etapa
cara solo corre si lo barato falló sus tests visibles). Knobs por nivel en
`effort_levels.py` (colonia, superorganismo, delegacion_max, bon_max,
umbral_shift, pasos_factor). El chat ya era "mono" por diseño (fast-path);
el razonador 4B por turno respeta el permiso colonia.

Kill-switches (mandan sobre el perfil): `COGNIA_HIBRIDO=0` (perfil legacy),
`COGNIA_SUPERORGANISMO=1/0` (fuerza on/off), `COGNIA_RAZONA_4B=0`,
`COGNIA_HEAVY_CODE`, `COGNIA_FLEET30=0`, `COGNIA_DELIBERACION` (la mesa
redonda sigue opt-in puro: su gate midió negativo). Telemetría: cada
`generar_codigo` registra `modalidad`/`esfuerzo` en `_bon_telemetry.jsonl`.
