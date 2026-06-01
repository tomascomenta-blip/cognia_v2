# Cognia — Visión del Proyecto

> Documento de visión estratégica. Fuente de verdad para decisiones de arquitectura.
> Última actualización: 2026-05-22

---

## Qué es Cognia

Cognia es una red de inferencia de IA distribuida y P2P donde los usuarios no pagan
con dinero sino con recursos de su dispositivo.

---

## Modelo económico

- El usuario instala Cognia y recibe acceso a IA a cambio de alojar una parte del modelo
  (uno o más shards) en su dispositivo.
- **No descarga el modelo completo** — el coordinador migra los shards necesarios
  desde máquinas que ya los tienen (como BitTorrent para pesos de modelo).
- Si el usuario desinstala, sus shards no se pierden: quedan en espera en el warm pool
  del coordinador hasta que un nuevo usuario los adopte.
- El "pago" es espacio × factor de uptime — mayor disponibilidad = mejor tier = más acceso.

### Niveles de acceso

| Tier | Contribución | Acceso |
|---|---|---|
| Free (250M parámetros efectivos) | Alojar shards con límite de uso | Ilimitado dentro del límite del modelo |
| Full (500M+ parámetros) | Alojar shards con alta disponibilidad | Completamente ilimitado |
| API externa | Espacio en dispositivo (no dinero) | Como Gemini/Grok pero pagado con recursos |

---

## Capacidades del sistema

### 1. Inferencia distribuida
El modelo está fragmentado en shards distribuidos entre usuarios.
La inferencia sigue este flujo:

```
prompt
  → clasifica qué MoEs son necesarios (router)
  → busca los shards correspondientes en el swarm (coordinador)
  → usa los fragmentos necesarios (descuantiza temporalmente)
  → revisa memorias episódicas del usuario
  → genera respuesta en tokens (streaming)
  → articula la respuesta en lenguaje natural
  → guarda memoria si se le pide o lo considera relevante
```

### 2. Aprendizaje continuo
- **Federated learning**: el modelo aprende de las interacciones de todos los usuarios
  sin que los datos personales salgan del dispositivo (ELC — Edge LoRA Consolidation).
- **Investigación autónoma**: durante ciclos de sueño, Cognia investiga temas relevantes
  y consolida memorias episódicas.
- **Consolidación de memorias**: sueño de 6 fases para reforzar conocimiento a largo plazo.

### 3. Evolución del modelo
- Cuando el modelo base se vuelva insuficiente para las necesidades de los usuarios,
  se migra a modelos más grandes.
- La migración es gradual: los shards del modelo anterior se reemplazan por shards
  del nuevo modelo a medida que los usuarios actualizan.
- El modelo nunca "se reinicia" — la memoria episódica y los adapters LoRA persisten
  a través de cambios de arquitectura base.

### 4. API externa
- La misma red P2P expone una API usable para aplicaciones web (como Gemini/Grok),
  pero en vez de pago monetario, el desarrollador aporta espacio/cómputo.
- Tier 250M: límite de requests pero sin costo monetario.
- Tier 500M+: ilimitado con mayor contribución de recursos.

---

## Restricciones de diseño no negociables

1. **Sin centralización de datos personales** — memorias y adapters viven en el dispositivo.
2. **Sin descarga del modelo completo** — shards migran P2P entre dispositivos.
3. **Sin PyTorch en el nodo** — numpy puro para máxima portabilidad (Android, IoT).
4. **Privacidad por diseño** — federated learning, no centralización de pesos personales.
5. **El coordinador es un árbitro, no un servidor de inferencia** — la inferencia es distribuida.

---

## Estado actual vs visión

| Componente | Estado hoy | Visión |
|---|---|---|
| Inferencia local | ~1.26 tok/s medido (hot decode, FP32 DynQuant) | 3-6 tok/s — lm_head bottleneck 250ms |
| Sharding | 4 shards en 1 máquina | N shards en N dispositivos con SAR |
| Disponibilidad | Sin redundancia | SAR: replicación adaptativa + warm pool |
| Federated learning | Implementado (ELC, FedAvg) | Activo en producción con usuarios reales |
| API externa | No implementada | Fase futura |
| Modelo base | Qwen2.5-Coder-3B INT4 | Escala a modelos más grandes según demanda |

---

## Documento relacionados

- `ROADMAP.md` — estado de fases de desarrollo
- `RESEARCH.md` — propuestas técnicas de innovación
- `planes/shard_availability_architecture.md` — SAR: solución al problema de nodos offline
- `planes/fase_A_B_C_D_inferencia_rapida.md` — optimización de inferencia
- `ideas.md` — CGEE (early exit por confianza)
