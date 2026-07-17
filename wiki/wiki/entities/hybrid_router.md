---
title: Hybrid Router — perfil de corrida por dificultad
type: entity
tags: [hybrid, routing, dificultad, esfuerzo, colonia, superorganismo]
updated: 2026-07-16
---

# Hybrid Router

→ [[index]]

## Que es

`cognia/agent/hybrid_router.py` — decide CUANTO sistema despertar por tarea.
La dificultad estimada de la TAREA (cero LLM) + el nivel [[concepts/effort_levels]]
activo arman un PERFIL de permisos/umbrales:

```
mono                          d < 0.12  respuesta directa / loop 1-2 pasos
agente                        default   loop ReAct con tools, 1 modelo
agente+colonia                d >= 0.30 (+umbral_shift) etapas multi-modelo permitidas
agente+colonia+superorganismo d >= 0.55 (+umbral_shift) etapa 4 permitida
```

Las modalidades se COMBINAN (no son rigidas). El perfil da el PERMISO;
el gasto sigue siendo REACTIVO — una etapa cara solo corre si lo barato
fallo sus tests ([[concepts/colonia]]).

## Estimador de dificultad

`estimate_task_difficulty(task)` = max(dificultad de codigo calibrada de
`cognia/agent/model_router.py`, senal general multi-paso: encadenamiento
"y luego" + variedad de verbos de accion + archivos mencionados + longitud).
max() garantiza que nada que hoy es duro deja de serlo.

## Quien lo consume

- loop `/hacer` (pasos_factor, delegacion_max)
- `generar_codigo` (permisos 7B/q35/superorganismo, bon_max, umbral_pesado)
- fast-path de chat (permiso razonador_4b)

## Kill-switch

`COGNIA_HIBRIDO=0` → perfil legacy (colonia siempre permitida,
superorganismo solo por env). Bajo pytest NO se lee el config del usuario
(higiene del instrumento; el nivel se pasa explicito en tests).

## Links

- [[concepts/ruteo_hibrido]]
- [[concepts/effort_levels]]
- [[concepts/colonia]]
- [[entities/superorganismo]]
