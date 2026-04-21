# COGNIA v3 — Guía de Arquitectura y Migración

## 1. Qué hay de nuevo en v3

| Módulo | Descripción | Análogo cognitivo |
|--------|-------------|-------------------|
| `KnowledgeGraph` | Grafo simbólico con relaciones tipadas (networkx + SQLite) | Corteza prefrontal — conocimiento explícito |
| `InferenceEngine` | Encadenamiento hacia adelante, herencia de propiedades | Razonamiento deductivo |
| `GoalSystem` | Objetivos cognitivos internos con prioridades dinámicas | Sistema de motivación / dopamina |
| `TemporalMemory` | Secuencias A→B→C, predicción contextual | Cerebelo + hipocampo — memoria procedimental |
| `AttentionSystem` | Score ponderado: semántica + emoción + recencia + frecuencia | Corteza parietal — atención selectiva |
| `ConceptCompressor` | Clustering de embeddings → abstracción conceptual | Consolidación cortical |
| `GraphEpisodicBridge` | Integración automática episodios → grafo | Transferencia hipocampo → corteza |

---

## 2. Migración v2 → v3

### Completamente retrocompatible

La migración es **cero downtime**:

```bash
# Opción A: usar la BD existente de v2
cp cognia_v2/cognia_memory.db cognia_v3/cognia_memory.db
python cognia_v3.py
# Las tablas nuevas se crean automáticamente, las v2 no se tocan
```

```bash
# Opción B: instalación fresca
pip install -r requirements.txt
python cognia_v3.py
```

### Cambios en la BD

Solo se **agregan** tablas nuevas. Las tablas v2 no se modifican:

```sql
-- NUEVAS en v3:
knowledge_graph      -- relaciones simbólicas
temporal_sequences   -- secuencias A→B→C
goal_system          -- objetivos cognitivos
inference_rules      -- reglas de inferencia almacenadas
```

---

## 3. Arquitectura cognitiva completa

```
INPUT TEXTO
    │
    ▼
[PerceptionModule]
 ┌─ Embeddings (cacheados, LRU-512)
 └─ Análisis emocional
    │
    ▼
[WorkingMemory]  ← 12 slots, buffer RAM
    │
    ▼
[AttentionSystem] ← NUEVO v3
 ┌─ score = 0.40×semántica + 0.25×emoción + 0.20×recencia + 0.15×frecuencia
 └─ Descarta memorias bajo umbral (ahorra cómputo)
    │
    ▼
[EpisodicMemory]
 ┌─ Recuperación semántica top-K
 └─ Reactivación de memorias olvidadas
    │
    ▼
[SemanticMemory + SpreadingActivation]
    │
    ▼
[KnowledgeGraph]  ← NUEVO v3
 ┌─ Hechos sobre el concepto
 └─ Jerarquía is_a
    │
    ▼
[InferenceEngine]  ← NUEVO v3
 ┌─ Encadenamiento transitivo
 └─ Herencia de propiedades
    │
    ▼
[TemporalMemory]  ← NUEVO v3
 └─ Predicción: ¿qué viene después?
    │
    ▼
  RESPUESTA

═══════════════════════════════
CICLO DE SUEÑO (comando: dormir)
═══════════════════════════════

[ConsolidationModule]
 └─ Episodios → Conceptos semánticos

[ConceptCompressor]  ← NUEVO v3
 └─ Clustering embeddings → Abstracción

[GraphEpisodicBridge]  ← NUEVO v3
 └─ Episodios → Triples en knowledge graph

[ForgettingModule]
 └─ Decaimiento con protección emocional

[GoalSystem]  ← NUEVO v3
 └─ Generación automática de objetivos
```

---

## 4. Comandos nuevos en v3

```
grafo <concepto>            — Ver el knowledge graph de un concepto
hecho <subj> | <pred> | <obj> — Agregar hecho al grafo manualmente
objetivos                   — Ver objetivos cognitivos activos
predecir <concepto>         — Ver predicciones temporales
inferir <concepto>          — Ver inferencias derivadas sobre concepto
```

### Relaciones del knowledge graph

| Relación | Significado | Ejemplo |
|----------|-------------|---------|
| `is_a` | Jerarquía taxonómica | `perro is_a mamífero` |
| `part_of` | Composición | `rueda part_of auto` |
| `causes` | Causalidad | `lluvia causes inundación` |
| `capable_of` | Capacidades | `perro capable_of ladrar` |
| `has_property` | Atributos | `oro has_property brillante` |
| `related_to` | Relación semántica general | `jazz related_to música` |
| `opposite_of` | Antónimos | `calor opposite_of frío` |
| `used_for` | Propósito | `martillo used_for clavar` |
| `located_in` | Ubicación | `parís located_in francia` |

### Ejemplo de sesión de aprendizaje

```
Cognia v3> aprender el perro es un mamífero | perro
✅ Aprendido: 'perro'
   🕸️  Grafo: +3 relaciones [perro→is_a→mamífero; ...]

Cognia v3> hecho perro | capable_of | ladrar
✅ Relación agregada: perro --capable_of--> ladrar

Cognia v3> hecho mamífero | capable_of | respirar
✅ Relación agregada: mamífero --capable_of--> respirar

Cognia v3> inferir perro
💡 Inferencias sobre 'perro':
  [transitivity] perro is_a mamífero + mamífero is_a animal → perro is_a animal (conf: 75%)
  Propiedades heredadas:
  ↳ perro capable_of respirar (de mamífero, conf: 70%)
```

---

## 5. Eficiencia energética

### Estrategias implementadas

| Estrategia | Ahorro estimado |
|------------|----------------|
| Cache LRU de embeddings (512 slots) | 40-60% menos cómputo de embeddings |
| AttentionSystem filtra antes del recall | 30-50% menos comparaciones vectoriales |
| Grafo lazy-loaded en memoria | RAM solo cuando se necesita |
| Spreading activation limitada (depth=2) | Cómputo O(k²) en vez de O(n) |
| Consolidación en batch (sleep) | Sin overhead por interacción |
| Sin modelos externos ni APIs | 0W de red + GPU externa |

### Consumo estimado

| Componente | Consumo estimado |
|------------|-----------------|
| sentence-transformers (MiniLM) | ~1-3W (CPU) |
| SQLite I/O | ~0.1W |
| networkx graph ops | ~0.1W |
| Resto Python | ~0.5W |
| **Total estimado** | **~2-5W en CPU moderno** |

Con GPU integrada (edge AI): similar, la inferencia de MiniLM es muy ligera.

---

## 6. Efectividad cognitiva estimada (v2 vs v3)

| Capacidad | v2 | v3 |
|-----------|----|----|
| Memoria episódica | ✅ | ✅ |
| Memoria semántica | ✅ | ✅ |
| Atención selectiva | ⚠️ básica | ✅ ponderada |
| Razonamiento simbólico | ❌ | ✅ inferencia transitiva |
| Conocimiento estructurado | ⚠️ world_model plano | ✅ KG con jerarquías |
| Predicción temporal | ❌ | ✅ secuencias A→B→C |
| Abstracción conceptual | ⚠️ consolidación básica | ✅ + clustering activo |
| Motivación interna | ❌ | ✅ goal system |
| Eficiencia energética | ⚠️ sin cache | ✅ LRU + atención |
| **Score estimado** | **65/100** | **82-87/100** |

---

## 7. Hoja de ruta hacia v4 (para alcanzar 90+)

Para superar 87/100 se recomiendan:

1. **Razonamiento analógico**: mapear estructuras entre dominios distintos
2. **Meta-learning**: aprender a aprender (ajustar parámetros de atención automáticamente)
3. **Memoria autobiográfica narrativa**: conectar episodios en historias coherentes
4. **Teoría de la mente lite**: modelar el conocimiento de otros agentes
5. **Comunicación multi-turno**: mantener diálogos coherentes >5 turnos

Ninguno requiere LLMs gigantes — todos son realizables con arquitecturas simbólico-neurales ligeras.
