# 🧠 COGNIA v3 — Arquitectura Cognitiva Simbólico-Neural

> IA local, ligera, sin APIs externas. Corre en CPU. Objetivo: 2–5W de consumo.

**Stack:** Python 3.x · SQLite · Ollama (llama3.2 + qwen2.5-coder) · sentence-transformers (MiniLM) · networkx

---

## Estado del proyecto (Abril 2026)

| Fase | Estado | Descripción |
|------|--------|-------------|
| ✅ **Fase 1 — Estabilización** | **COMPLETADA** | Base limpia, connection pool, CognitiveProfile, 11 fixes críticos |
| ✅ **Fase 2 — Arquitectura Cognitiva Avanzada** | **COMPLETADA** | NarrativeThread, decay diferencial, hash de VectorCache |
| ✅ **Fase 3 — Sistema Distribuido** | **COMPLETADA** | CogniaMeshNode, CRDTKnowledgeGraph, privacidad diferencial |
| ✅ **Fase 4 — Privacidad y Seguridad** | **COMPLETADA** | KeyManager (PBKDF2+AES-256-GCM), SecureEpisodicMemory, 3 capas de privacidad |
| 🔲 **Fase 5 — Escalado Dinámico** | Pendiente | ScaleManager por nivel de RAM/memoria/peers |
| 🔲 **Fase 6 — Personalización Profunda** | Pendiente | Vectores de interés, multi-usuario, StyleEngine |
| 🔲 **Fase 7 — Deployment** | Pendiente | FastAPI + React frontend + Railway/Render |
| 🔲 **Fase 8 — Monetización** | Pendiente | Tiers sin comprometer privacidad |

---

## Qué hace Cognia

Cognia es una arquitectura cognitiva que aprende de observaciones, recuerda con contexto emocional, razona sobre lo que sabe y olvida lo que no usa — todo localmente, sin enviar datos a ningún servidor.

### Módulos activos en v3

| Módulo | Archivo | Análogo cognitivo |
|--------|---------|-------------------|
| `KnowledgeGraph` | `cognia/knowledge/graph.py` | Corteza prefrontal — conocimiento explícito |
| `InferenceEngine` | `cognia/knowledge/inference.py` | Razonamiento deductivo transitivo |
| `GoalSystem` | `cognia/knowledge/goals.py` | Motivación / generación de objetivos |
| `TemporalMemory` | `cognia/knowledge/temporal.py` | Hipocampo — predicción de secuencias A→B→C |
| `AttentionSystem` | `cognia/attention.py` | Atención selectiva ponderada |
| `ConceptCompressor` | `cognia/compression.py` | Consolidación cortical por clustering |
| `NarrativeThread` | `cognia/memory/narrative.py` | Memoria autobiográfica — hilos coherentes |
| `CogniaMeshNode` | `network/mesh_node.py` | Red distribuida — replicación semántica |
| `CRDTKnowledgeGraph` | `network/crdt_graph.py` | Consistencia eventual sin coordinador |
| `CognitiveProfile` | `cognia/user_profile.py` | Pesos de atención adaptativos por usuario |
| `SelfArchitect` | `self_architect.py` | Auto-evaluación y optimización arquitectural |
| `FeedbackEngine` | `feedback_engine.py` | Aprendizaje por feedback del usuario |

### Flujo cognitivo

```
INPUT
  │
  ▼
[Perception] → embeddings + análisis emocional
  │
  ▼
[WorkingMemory] → 12 slots en RAM
  │
  ▼
[AttentionSystem] → score = 0.40×sem + 0.25×emo + 0.20×rec + 0.15×freq
  │
  ▼
[EpisodicMemory] → recuperación semántica top-K (~2ms para 7000 vectores)
  │
  ▼
[KnowledgeGraph] → hechos + jerarquías is_a
  │
  ▼
[InferenceEngine] → encadenamiento transitivo + herencia de propiedades
  │
  ▼
[TemporalMemory] → predicción: ¿qué concepto viene después?
  │
  ▼
RESPUESTA

══════════════════════════════════
CICLO DE SUEÑO (comando: dormir)
══════════════════════════════════

[ConsolidationEngine] → 6 fases: purge / weaken / consolidate / reinforce / decay / dedup
[ConceptCompressor]   → clustering de embeddings → abstracción conceptual
[GraphEpisodicBridge] → episodios → triples en knowledge graph
[ForgettingModule]    → decaimiento con protección emocional diferencial
[GoalSystem]          → generación automática de objetivos
[ResearchEngine]      → investigación autónoma sobre conceptos débiles
[ProgramCreator]      → hobby: genera y evalúa programas propios
```

---

## Instalación

```bash
git clone https://github.com/tomascomenta-blip/cognia_v2.git
cd cognia_v2
pip install -r requirements.txt

# Ollama necesario para respuestas en lenguaje natural
# https://ollama.ai
ollama pull llama3.2
ollama pull qwen2.5-coder

python -m cognia
```

**Requisitos:** Python 3.10+ · Ollama en `localhost:11434` · ~2GB RAM · no se requiere GPU

---

## Uso — Comandos disponibles

### Heredados de v2

| Comando | Descripción |
|---------|-------------|
| `observar <texto>` | Observar sin etiquetar (modo inferencia) |
| `aprender <texto> \| <label>` | Enseñar con etiqueta |
| `corregir <obs> \| <mal> \| <bien>` | Corregir un error pasado |
| `hipotesis <A> \| <B>` | Generar hipótesis entre dos conceptos |
| `yo` | Introspección: métricas de memoria y estado |
| `conceptos` | Listar todos los conceptos semánticos aprendidos |
| `dormir` | Ciclo de sueño: consolidación, compresión, olvido |
| `repasar` | Ver episodios pendientes de repaso espaciado |
| `contradicciones` | Ver contradicciones sin resolver |
| `explicar <texto>` | Autoexplicación con grafo y jerarquías |
| `olvido` | Ciclo de olvido manual |

### Nuevos en v3

| Comando | Descripción |
|---------|-------------|
| `grafo <concepto>` | Ver knowledge graph de un concepto |
| `hecho <subj> \| <pred> \| <obj>` | Agregar hecho al grafo manualmente |
| `objetivos` | Ver objetivos cognitivos activos |
| `predecir <concepto>` | Ver predicciones de secuencia temporal |
| `inferir <concepto>` | Ver inferencias derivadas sobre un concepto |
| `narrativa <texto>` | Ver hilo narrativo de episodios relacionados |

### Perfil cognitivo

| Comando | Descripción |
|---------|-------------|
| `feedback <texto>` | Ajustar pesos de atención con feedback |
| `perfil` | Ver perfil cognitivo y pesos actuales |
| `rollback` | Deshacer último cambio de perfil |
| `estilo <balanced\|concise\|detailed\|socratic>` | Cambiar estilo de respuesta |

### Sesión de ejemplo

```
Cognia v3> aprender el perro es un mamífero | perro
✅ Aprendido: 'perro'
   🕸️  Grafo: +3 relaciones [perro→is_a→mamífero; ...]

Cognia v3> hecho mamífero | capable_of | respirar
✅ Relación agregada: mamífero --capable_of--> respirar

Cognia v3> inferir perro
💡 Inferencias sobre 'perro':
  [transitivity] perro is_a mamífero + mamífero is_a animal → perro is_a animal (conf: 75%)
  Propiedades heredadas:
  ↳ perro capable_of respirar (de mamífero, conf: 70%)
```

---

## Relaciones del Knowledge Graph

| Relación | Significado | Ejemplo |
|----------|-------------|---------|
| `is_a` | Jerarquía taxonómica | `perro is_a mamífero` |
| `part_of` | Composición | `rueda part_of auto` |
| `causes` | Causalidad | `lluvia causes inundación` |
| `capable_of` | Capacidades | `perro capable_of ladrar` |
| `has_property` | Atributos | `oro has_property brillante` |
| `related_to` | Semántica general | `jazz related_to música` |
| `opposite_of` | Antónimos | `calor opposite_of frío` |
| `used_for` | Propósito | `martillo used_for clavar` |
| `located_in` | Ubicación | `París located_in Francia` |

---

## Eficiencia energética

| Estrategia | Ahorro estimado |
|------------|-----------------|
| Cache LRU de embeddings (512 slots) | 40–60% menos cómputo |
| AttentionSystem filtra antes del recall | 30–50% menos comparaciones vectoriales |
| VectorCache matricial con numpy | ~2ms para 7000 vectores |
| Connection pool SQLite | Elimina "database is locked" bajo concurrencia |
| Consolidación en batch (sleep) | Sin overhead por interacción |

**Consumo total estimado: 2–5W en CPU moderno.**

---

## Efectividad cognitiva — v2 vs v3

| Capacidad | v2 | v3 |
|-----------|----|----|
| Memoria episódica | ✅ | ✅ |
| Memoria semántica | ✅ | ✅ |
| Atención selectiva | ⚠️ básica | ✅ ponderada + adaptativa |
| Razonamiento simbólico | ❌ | ✅ inferencia transitiva |
| Conocimiento estructurado | ⚠️ plano | ✅ KG con jerarquías |
| Predicción temporal | ❌ | ✅ secuencias A→B→C |
| Abstracción conceptual | ⚠️ básica | ✅ clustering activo |
| Motivación interna | ❌ | ✅ goal system |
| Hilos narrativos | ❌ | ✅ NarrativeThread |
| Red distribuida | ❌ | ✅ CRDT Mesh |
| Perfil cognitivo por usuario | ❌ | ✅ con rollback |
| **Score estimado** | **65/100** | **85/100** |

---

## Roadmap — Próximas fases

### ✅ Fase 4 — Privacidad y Seguridad *(completada)*
`KeyManager` (PBKDF2-HMAC-SHA256 × 600k iter + AES-256-GCM o fallback XOR+HMAC) + `SecureEpisodicMemory` wrapper que cifra `observation` antes de escribir a disco y descifra en RAM al leer. El vector de embedding no se cifra (necesario para búsqueda semántica). Tres capas: Capa 1 local cifrada → Capa 2 semi-privada (peers autorizados) → Capa 3 pública anonimizada (ya implementada en `network/privacy.py`). Comandos CLI: `desbloquear <pass>`, `bloquear`, `seguridad`.

### 🔲 Fase 5 — Escalado Dinámico
`ScaleManager` detecta nivel óptimo según RAM disponible, cantidad de memorias y peers activos. Nivel 1: llama3.2:3b local. Nivel 2: llama3.2:8b + índice en disco. Nivel 3: mixtral:8x7b + federado.

### 🔲 Fase 6 — Personalización Profunda
`PersonalIndex` (índice privado de conceptos importantes, no compartido en mesh). `StyleEngine` que aprende vocabulario y nivel técnico del usuario. Multi-usuario real con `switch_user()`.

### 🔲 Fase 7 — Deployment Económico
FastAPI sobre `cognia.py` con endpoints REST + WebSocket. Frontend React en Vercel ($0). Backend en Railway (~$7/mes). Ollama corre local en el dispositivo del usuario. Dockerfile mínimo sin CUDA.

### 🔲 Fase 8 — Monetización
Cognia ($0, local completo) → Cognia+ ($5–8/mes) → Cognia Pro ($15–20/mes, API para devs). Los datos del usuario nunca son el producto. El tier gratuito nunca degrada.

---

## Estructura del repositorio

```
cognia_v2/
├── cognia/                     # Paquete principal
│   ├── cognia.py               # Clase Cognia — orquestador central
│   ├── cli.py                  # REPL interactivo
│   ├── config.py               # Feature flags (HAS_*)
│   ├── memory/                 # episodic, semantic, working, forgetting, narrative
│   ├── knowledge/              # graph, inference, temporal, goals
│   ├── reasoning/              # hypothesis, contradiction, metacognition, world_model
│   ├── research_engine/        # Investigación autónoma durante sueño
│   └── program_creator/        # Hobby: genera y evalúa programas propios
├── network/                    # Fase 3 — Red distribuida
│   ├── mesh_node.py            # CogniaMeshNode (websockets + asyncio)
│   ├── crdt_graph.py           # CRDTKnowledgeGraph (G-Set convergente)
│   └── privacy.py              # Privacidad diferencial (ε=1.0)
├── storage/
│   └── db_pool.py              # ConnectionPool SQLite
├── tools/                      # Utilidades internas (no producción)
├── cognia_embedding.py         # LazyEmbeddingModel + AsyncEmbeddingQueue
├── model_router.py             # Enrutamiento inteligente entre modelos Ollama
├── self_architect.py           # Auto-evaluación arquitectural
├── feedback_engine.py          # Aprendizaje por feedback del usuario
├── requirements.txt
├── COGNIA_ROADMAP.txt          # Specs detalladas de cada fase
└── FIXES_APLICADOS.md          # Log de los 11 fixes críticos aplicados
```

---

## Para colaborar

Ver `COGNIA_ROADMAP.txt` para specs completas de cada fase. Antes de proponer cambios: clonar y leer el código real, verificar el estado actual con `git log --oneline`, respetar las restricciones del proyecto (sin dependencias nuevas fuera de `requirements.txt`, retrocompatible con la DB existente, funcionar en Windows, Ollama en CPU).
