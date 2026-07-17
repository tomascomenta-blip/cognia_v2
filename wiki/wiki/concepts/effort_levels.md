---
title: Effort Levels — /esfuerzo v2
type: concept
tags: [esfuerzo, effort, knobs, modalidad]
updated: 2026-07-16
---

# Effort Levels (/esfuerzo v2)

→ [[index]]

## Que es

`cognia/effort_levels.py` — fuente UNICA de verdad de cuanto esfuerzo gastar.
Cuatro niveles (`bajo`/`medio`/`alto`/`maximo`, default `medio`), cada uno un
dict plano de knobs. v2 (2026-07-15) agrego los knobs de MODALIDAD que
consume [[entities/hybrid_router]]:

```
colonia         bool   etapas multi-modelo reactivas permitidas
superorganismo  bool   etapa 4 permitida (si la dificultad cruza su umbral)
delegacion_max  int    profundidad de sub-agentes (0 en bajo, 3 en maximo)
bon_max         int    techo best-of-N en generar_codigo (3 en bajo)
umbral_shift    float  corre el eje de dificultad (+0.15 bajo, -0.20 maximo)
pasos_factor    float  multiplica el presupuesto de pasos del loop /hacer
```

Mas los knobs v1: max_tokens, alternativas, profundidad, verificaciones,
reintentos, subtareas_max.

## Semantica

- `bajo`: sin colonia ni superorganismo, sin delegacion — todo mono/agente.
- `medio`: comportamiento identico a la cascada calibrada previa
  (umbral_shift=0.0; a esfuerzo medio el hibrido reproduce el sistema de hoy).
- `alto`/`maximo`: las etapas caras entran ANTES (umbral corrido a la
  izquierda), mas pasos y delegacion.

El nivel persiste en `~/.cognia_config.json` (clave "esfuerzo"); el comando
`/esfuerzo` muestra knobs y modalidades del nivel activo.

## Links

- [[entities/hybrid_router]]
- [[concepts/ruteo_hibrido]]
