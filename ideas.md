# Ideas de Arquitectura

---

## 2026-05-18 — Confidence-Gated Early Exit por Shard (CGEE)

### El problema real

El pipeline actual siempre ejecuta los 4 shards (36 capas) sin importar la complejidad de la query. Una consulta como "que hace `range()` en Python" usa el mismo compute que "diseña un sistema distribuido tolerante a fallos". Para un asistente personal, el 40-50% de queries son respuestas cortas que no necesitan las capas profundas.

### La mejora

Despues de cada shard, proyectar el ultimo token del hidden state a través del lm_head y medir la entropia del vocabulario. Si la entropia es baja (el modelo ya es confident), salir y decodificar directamente sin ejecutar los shards restantes.

```
prompt → shard 0 (capas 0-8)  → entropia < θ₀ ? → decodificar (1 shard)
                                ↓
                 shard 1 (capas 9-17)  → entropia < θ₁ ? → decodificar (2 shards)
                                ↓
                 shard 2 (capas 18-26) → entropia < θ₂ ? → decodificar (3 shards)
                                ↓
                 shard 3 (capas 27-35) → decodificar siempre (4 shards, max calidad)
```

La entropia se calcula como:

```python
logits = lm_head_weights @ hidden[-1]   # (vocab_size,), solo ultimo token
probs  = softmax(logits / temperature)
entropy = -np.sum(probs * np.log(probs + 1e-9))
# entropia baja = modelo confident = salir
```

### Por que es clean para esta arquitectura

El `lm_head` ya existe en shard 3 (~300 KB INT4). Compartirlo a los otros shards como peso de solo lectura es trivial. Los puntos de salida ya son naturales: los 4 shards se corresponden exactamente con los cuartos del modelo.

**Speedup esperado** (estimado en personal assistant workloads):

| Tipo de query | Shards usados | Reduccion de latencia |
|---|---|---|
| Preguntas factuales cortas | 1-2 | ~60-75% |
| Debugging de un error conocido | 2-3 | ~25-50% |
| Razonamiento complejo, codigo complejo | 3-4 | 0-25% |
| Promedio ponderado tipico | ~2.1 | ~47% |

### Archivos a modificar

| Archivo | Cambio |
|---|---|
| `shattering/shard_engine.py` | Agregar `early_exit_score(hidden) -> float` que proyecta por lm_head y retorna entropia |
| `shattering/orchestrator.py` | En `_token_loop`, despues de cada shard checkear `score < threshold` antes de continuar |
| `shattering/model_constants.py` | Agregar `CGEE_ENTROPY_THRESHOLDS = [3.5, 4.2, 4.8]` (uno por cada posible exit) |
| `node/inference_pipeline.py` | Exponer lm_head weights a todos los shards en modo local |

### Tradeoff principal

Requiere que los 3 shards intermedios accedan al `lm_head` (~300KB INT4). En modo local esto es inmediato. En modo swarm, el coordinator tendria que distribuir ese tensor al registrar el nodo — agrega 300KB de overhead al registro, una vez por sesion.

Los umbrales `θ₀, θ₁, θ₂` hay que calibrarlos con queries reales. Valor inicial conservador: `θ₀=3.0`, `θ₁=3.8`, `θ₂=4.5`.

---
