# Arquitectura de Disponibilidad de Shards (SAR)
## Problema: nodos offline en una red P2P de inferencia

> Estado: PROPUESTA — 2026-05-22
> Relacionado con: `coordinator/relay.py`, `coordinator/contributor.py`, `coordinator/federated_store.py`

---

## El problema concreto

Cognia distribuye los pesos del modelo entre dispositivos de usuarios.
Un dispositivo móvil tiene uptime promedio de ~50-60% (cargador, batería, uso activo).
Con 4 shards independientes y 50% de uptime por nodo:

```
P(todos online) = 0.5^4 = 6.25%
```

El sistema estaría caído el **93.75% del tiempo** sin redundancia.

---

## Solución: Tres mecanismos en capas (SAR)

### Capa 1 — Replicación adaptativa por uptime

El coordinador ya rastrea uptime por nodo (tiers en `contributor.py`).
Cada shard necesita un número mínimo de réplicas R calculado por:

```
R = ceil( log(1 - target_availability) / log(avg_downtime_rate) )
```

Ejemplos:
| Uptime promedio nodo | R para 95% disponibilidad | R para 99% disponibilidad |
|---|---|---|
| 80% | 2 réplicas | 3 réplicas |
| 60% | 3 réplicas | 4 réplicas |
| 40% | 4 réplicas | 6 réplicas |

**Implementación**: el coordinador mantiene un `shard_registry` con `{shard_id: [node_id, ...]}`.
Al registrar un nodo nuevo, el coordinador le asigna el shard con menos réplicas activas.

### Capa 2 — Warm Pool en el coordinador (fallback)

El coordinador mantiene una copia comprimida de todos los shards.
Se activa **solo cuando P(ninguna réplica disponible) > 0** para un shard dado.

- Tamaño: 4 shards × ~500MB INT4 = ~2GB en el servidor coordinador
- Velocidad: más lenta (CPU del coordinador, no distribuida) pero disponible
- Activación: automática, transparente para el cliente

Esto implementa el concepto "los shards quedan en espera" — nunca se pierden,
solo cambian de dónde se sirven.

```
Jerarquía de routing por shard:
1. Nodo primario (tier alto, uptime >80%)    → ~20ms latencia
2. Nodo secundario (tier medio, uptime >50%) → ~50ms latencia
3. Warm pool del coordinador                 → ~200ms latencia (degradado)
4. Request queue con timeout de 60s          → error si nada disponible
```

### Capa 3 — Shard Debt y migración proactiva

Cuando un nodo estuvo offline >24h con un shard único (sin otras réplicas):

1. El coordinador marca ese shard como `under_replicated`
2. Los próximos N usuarios que instalen la app son candidatos a recibir ese shard
3. La migración es gradual (el coordinador sirve el shard en fragmentos al nuevo nodo)
4. Cuando el nuevo nodo confirma el shard completo, el shard deja de estar `under_replicated`

**Alineación con el modelo económico**: nodos con alto uptime reciben prioridad
para shards de alta demanda. Nodos de bajo uptime reciben shards redundantes de menor carga.
El "pago con espacio" se pondera por `espacio × factor_uptime`.

---

## Interacción con CGEE (Early Exit)

Con la propuesta de `ideas.md` (Confidence-Gated Early Exit), las queries simples
solo necesitan shards 0-1. Si shard 2 y 3 están offline, el 40-50% de queries
siguen funcionando sin degradación.

SAR + CGEE combinados producen disponibilidad efectiva superior al 95%
incluso con uptime de nodo del 60%.

---

## Casos edge

| Situación | Comportamiento SAR |
|---|---|
| Todos los nodos de shard X offline + warm pool vacío | Error 503, mensaje al usuario |
| Nodo vuelve online después de 72h | Sus shards se re-verifican contra warm pool; si divergen, se sincroniza |
| Usuario desinstala la app | Sus shards pasan al warm pool si no hay otras réplicas activas |
| Nodo con shard único pasa a offline >24h | Coordinador inicia migración proactiva a nuevo host |

---

## Archivos a crear/modificar

| Archivo | Cambio |
|---|---|
| `coordinator/shard_registry.py` | Nuevo — registro de réplicas por shard, cálculo de R, detección de `under_replicated` |
| `coordinator/warm_pool.py` | Nuevo — caché local de shards comprimidos en el coordinador |
| `coordinator/relay.py` | Modificar routing de sesiones para consultar `shard_registry` antes de asignar nodo |
| `coordinator/contributor.py` | Agregar `uptime_7d` al perfil de nodo; ponderar asignación de shards por uptime |
| `scripts/cognia_setup.py` | Al registrar nodo, pedir el shard con menor cobertura según `shard_registry` |

---

## Orden de implementación sugerido

1. `shard_registry.py` — base de todo, sin esto nada funciona
2. Modificar `relay.py` para routing multicandidato
3. `warm_pool.py` — fallback del coordinador
4. Shard Debt en `contributor.py`
5. Integrar con CGEE cuando esté implementado

---

## Lo que NO resuelve SAR

- **Sincronización de pesos post-federated-learning**: si un nodo tiene pesos más actualizados
  que otro, las réplicas pueden divergir. Esto requiere un protocolo de versionado de shards
  separado (fuera del alcance de SAR).
- **Ataques de nodo malicioso**: un nodo podría servir pesos corruptos. Requiere
  verificación de hash antes de usar shards de nodos no confiables.
