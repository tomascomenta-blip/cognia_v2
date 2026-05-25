---
title: Fatiga cognitiva — monitor de carga del sistema
type: concept
tags: [fatigue, monitor, cpu, memory, performance, adaptive]
updated: 2026-05-24
---

# Fatiga cognitiva

→ [[index]]

## Qué es

Variable `COGNITIVE_FATIGUE` — score 0-100 que mide la carga computacional del sistema en tiempo real. Modula el comportamiento de inferencia y retrieval según la carga.

## Archivo fuente

`cognia/fatiga_cognitiva.py`

## Rangos y estrategias

| Rango | Estado | Estrategia |
|---|---|---|
| 0-30 | Descansado | Rendimiento óptimo |
| 31-60 | Carga moderada | Eficiencia activa |
| 61-80 | Carga alta | Simplificación agresiva del razonamiento, aumenta `attention_threshold`, reduce `top_k` |
| 81-100 | Fatiga crítica | `max_steps=1`, sin temporal predictions, solo cache para embeddings |

## Métricas medidas

- Tiempo por ciclo de razonamiento (ms)
- CPU (psutil, 0-100%) — psutil opcional; si no está, estimación fija
- Memoria RSS (MB)
- Operaciones en ventana actual
- Tasa de cache hits de embeddings
- Operaciones costosas (embeddings nuevos calculados)

## Consumo propio

< 2ms por ciclo (solo aritmética + psutil). No es un bottleneck.

## Deuda activa

`FatigueMonitor` sin reset de estado — BAJO riesgo. Si el sistema entra en fatiga crítica, no hay mecanismo automático de reset; requiere reinicio.

## Links

- [[entities/episodic_fast]]
- [[sources/cognia_embedding]]
