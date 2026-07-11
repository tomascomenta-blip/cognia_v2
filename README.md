# Cognia — IA cognitiva local que aprende (Arquitectura Simbolico-Neural)

> IA local, ligera y privada. Corre en CPU con un modelo 3B, sin APIs externas y sin
> PyTorch en el camino critico. **Aprende, razona y recuerda** en tu propia maquina —
> con memoria episodica, un **creador de imagenes/escenas** AI-nativo, y **prompts que
> se auto-mejoran** (auto-prompting). Instalable en un comando: `pip install cognia-ai`.

**Stack:** Python 3.11+ (3.12 recomendado) · SQLite · Qwen2.5-Coder-3B (GGUF / INT4) ·
llama.cpp · sentence-transformers · numpy · FastAPI · Electron

---

## Tabla de contenidos

- [Que es Cognia](#que-es-cognia)
- [Estado del proyecto](#estado-del-proyecto-junio-2026)
- [Instalacion](#instalacion)
- [Uso — el REPL](#uso--el-repl)
- [Modelo e inferencia](#modelo-e-inferencia)
- [Rendimiento (benchmarks reales)](#rendimiento-benchmarks-reales)
- [Modulos principales](#modulos-principales)
- [Arquitectura Diferencial](#arquitectura-diferencial)
- [Capa Cognitiva Chimera](#capa-cognitiva-chimera-sistema-no-atencion)
- [Inferencia distribuida (swarm)](#inferencia-distribuida-swarm)
- [Seguridad y privacidad](#seguridad-y-privacidad)
- [Desarrollo y tests](#desarrollo-y-tests)
- [Documentacion](#documentacion)
- [Para colaborar](#para-colaborar)

---

## Que es Cognia

Cognia es una **arquitectura cognitiva** que aprende, razona y recuerda localmente. A
diferencia de un chatbot, gestiona un ciclo de vida cognitivo completo: memoria episodica
y semantica, un grafo de conocimiento, consolidacion de memoria durante el "sueno", y
razonamiento que puede distribuirse entre varios dispositivos de una red local.

Tres ideas la definen:

1. **Local-first y privada.** Tus datos nunca salen de tu maquina salvo que conectes
   nodos en una red mesh de forma explicita. Memorias cifradas en reposo (AES-256-GCM).
2. **Ligera.** Inferencia en CPU mediante llama.cpp (GGUF cuantizado) o shards numpy puro
   (INT4), sin PyTorch ni Tensorflow en el motor principal.
3. **Cognitiva, no solo generativa.** Router de dominio (LOGOS/TECHNE/RHETOR), ciclo de
   sueno de consolidacion, world-model que simula consecuencias antes de actuar, y una
   capa cognitiva Chimera construida sobre todo lo anterior.

---

## Estado del proyecto (Julio 2026)

| Fase | Estado | Descripcion |
|------|--------|-------------|
| **Fases 1-6 — Estabilizacion y core** | COMPLETADA | Base limpia, NarrativeThread, MeshNode, seguridad, escalado. |
| **Fase 7 — Shattering (SRDN)** | COMPLETADA | Sub-modelos LOGOS/TECHNE/RHETOR, MoE, NPQ, RST, MLA. |
| **Fase 8 — Commercial release** | COMPLETADA | Instaladores, UX, cifrado por defecto, documentacion. |
| **Fases 9-12 — Hardening y UX** | COMPLETADA | Proteccion SQLi/XSS/SSRF, consentimiento de privacidad, auto-update. |
| **Fase 13 — Inferencia distribuida real** | COMPLETADA | Qwen2.5-Coder-3B INT4, auto-sharding, relay WebSocket. |
| **Inferencia local llama.cpp** | OPERATIVA | GGUF como ruta primaria (~8-9 tok/s en CPU 4-core); shards numpy como fallback. |
| **Capa cognitiva Chimera** | OPERATIVA | Band router de 3 bandas, cognitive loop, memoria jerarquica, world-model. |
| **Especialistas MoM (Mixture of Models)** | OPERATIVA | Portero 0.5B para turnos rapidos (~3.3–3.9×), escalado reactivo 3B→7B en codigo duro (+20pp), router de expertos LoRA. `cognia install-model` los monta; degradan al 3B si faltan. |

Detalle tecnico por fase en [ROADMAP.md](ROADMAP.md). Bitacora de sesiones en
[CLAUDE_NOTES.md](CLAUDE_NOTES.md) y [MANAGER_LOG.md](MANAGER_LOG.md).

---

## Instalacion

### Un solo comando (PyPI) — recomendado

```bash
pip install cognia-ai
cognia
```

Eso es todo: `pip install cognia-ai` deja el comando `cognia` listo, y `cognia` abre el
asistente (primer arranque = wizard de configuracion, luego el REPL). Corre **100%
local con el modelo 3B** (Qwen2.5-Coder-3B via llama.cpp); la orquestacion online viene
**apagada por defecto** (forzable con `COGNIA_DISABLE_SWARM=1`). Incluye el **creador de
imagenes/escenas** AI-nativo y los **prompts que se auto-mejoran**.

```bash
pip install "cognia-ai[semantic]"   # + embeddings reales (sentence-transformers, ~2GB)
pip install "cognia-ai[llama]"      # + llama.cpp via pip (requiere wheel prebuilt o compilador C++)
pip install "cognia-ai[all]"        # todo
```

Requisitos: **Python 3.11+** (3.12 recomendado). Para inferencia tenes tres caminos:
(1) **shards numpy** (INT4) — el **wizard los descarga** y corre en **Python puro, sin
binario ni compilador**: el camino que "just works" en cualquier plataforma (más lento);
(2) **`cognia-ai[llama]`** (`llama-cpp-python`) — rápido, pero **necesita un wheel
prebuilt o un compilador C++** (en Windows sin compilador falla); (3) binario
**llama-server** + un **GGUF** — el más rápido en CPU. El primer arranque (`cognia`) te
guia.

### Instaladores rapidos (desde el repo)

Descarga el repositorio y ejecuta el instalador de tu plataforma:

**Windows (PowerShell):**
```powershell
.\install.ps1
```

**Linux / macOS (Bash):**
```bash
bash install.sh
```

El instalador crea un entorno, instala dependencias y descarga el modelo (~300 MB en modo
swarm, ~1.2 GB en modo standalone con los 4 shards).

### Desktop App (Electron)

```bash
cd cognia_desktop
npm install
npm run build:win    # o build:linux / build:mac
```

### Releases precompilados

| Plataforma | Archivo | Requisitos |
|---|---|---|
| Windows | `CogniaDesktop-x.x.x-Setup.exe` | Python 3.11+ |
| Linux | `CogniaDesktop-x.x.x.AppImage` | Python 3.11+ |
| Android | `cognia-mobile-x.x.x.apk` | Android 8+ |

Releases: **https://github.com/tomascomenta-blip/cognia_v2/releases**

> **Nota sobre Python:** el `venv/` del repo puede apuntar a un interprete sin wheels
> disponibles. Se recomienda **Python 3.12**. En desarrollo, este repo usa
> `venv312/Scripts/python.exe` — sustituyelo por tu interprete si difiere.

---

## Uso — el REPL

Arranca Cognia (lanza el wizard la primera vez, luego abre el REPL interactivo):

```bash
python -m cognia
```

Dentro del REPL, **cualquier texto sin `/` es chat cognitivo**; los comandos empiezan
con `/`:

```
cognia> hola, que sabes hacer?          <- chat libre (inferencia)
cognia> /ayuda                          <- lista completa de comandos
cognia> aprender El sol es una estrella | astronomia
cognia> /salir
```

### Comandos principales

| Comando | Que hace |
|---|---|
| `<texto libre>` | Chat cognitivo (inferencia + memoria). |
| `/ayuda` | Lista completa de comandos. |
| `/yo` | Perfil cognitivo y estado interno de la memoria. |
| `/memoria` | Estado de la memoria episodica/semantica. |
| `aprender <texto> \| <etiqueta>` | Ensenar un concepto nuevo. |
| `/observar <texto>` | Guardar una observacion sin procesar. |
| `/dormir` | Ciclo de consolidacion y limpieza (sueno). |
| `/grafo <concepto>` | Visualizar el grafo de conocimiento local. |
| `/inferir <concepto>` | Razonamiento transitivo sobre un tema. |
| `/sesiones` | Listar sesiones de chat recientes. |
| `/modulos` | Modulos cognitivos activos. |
| `/debug` | Alternar logs detallados. |
| `/salir` | Salir del REPL. |

### Subcomandos de la CLI

```bash
cognia                  # REPL (wizard en el primer uso)
cognia init             # Re-ejecutar el wizard de configuracion
cognia install-model    # Stack de inferencia recomendado: GGUF 3B + llama-server b9391 + expertos LoRA + portero 0.5B
cognia install-model --with-heavy-code   # + especialista 7B de codigo (~4.7 GB, opt-in): escalado 3B->7B en codigo duro (+20pp)
cognia install-weights  # Descargar shards numpy y configurar este equipo como nodo
cognia install-weights --standalone   # Descargar los 4 shards para uso local completo
cognia server           # Servidor web FastAPI (puerto 8000)
cognia node             # Iniciar como nodo del swarm distribuido
cognia coordinator      # Iniciar el coordinador del swarm (puerto 8001)
cognia status           # Estado del swarm y de Ollama
cognia leave            # Salir de la red y liberar el shard alojado
```

---

## Modelo e inferencia

Cognia resuelve cada prompt por la **primera ruta de inferencia disponible**, en este
orden:

1. **llama.cpp + GGUF (ruta local primaria).** Si encuentra un GGUF de Qwen2.5-Coder-3B,
   lo carga via `llama-cpp-python` o `llama-server`. Es la ruta mas rapida y de mejor
   calidad en una sola maquina. El backend busca el modelo en `SHARD_WEIGHTS_DIR` (o en
   `model_shards/qwen-coder-3b-q4/` por defecto).
2. **Shards numpy INT4 (fallback distribuido / local).** Forward pass en numpy puro sin
   PyTorch, repartible entre nodos del swarm. Es el corazon de la arquitectura Shattering.
3. **Ollama (opcional).** Si defines `OLLAMA_URL`, se usa como motor de razonamiento
   general alternativo.

### Especialistas (Mixture of Models)

Sobre el 3B base, `cognia install-model` monta una cascada de especialistas que se
activan solos y **degradan al 3B** si su modelo no esta presente (nada se rompe):

- **Portero 0.5B** — atiende los turnos triviales de charla (saludo, identidad,
  cortesia) a ~3.3–3.9× la velocidad del 3B. Se instala por defecto.
- **7B de codigo (opt-in)** — con `install-model --with-heavy-code`, cuando el 3B
  falla los tests de una tarea de codigo dificil se reintenta con Qwen2.5-Coder-7B
  en greedy (codigo duro 37.5→57.5% pass@1, +20pp). Lazy-load-usar-cerrar: RAM en
  reposo 0; `COGNIA_HEAVY_CODE=0` lo apaga.

### Configurar el modelo

El backend GGUF detecta automaticamente cualquiera de estas cuantizaciones (de mayor a
menor prioridad): `Q4_0`, `Q3_K_S`, `Q4_K_M`, `Q5_K_M`. Para apuntar a una carpeta de
modelos concreta, define la ruta **absoluta**:

```
# ~/.cognia/config.env
SHARD_WEIGHTS_DIR=C:\ruta\a\model_shards\qwen-coder-3b-q4
```

> La ruta absoluta evita que la deteccion dependa del directorio de trabajo. Si la dejas
> relativa, solo resuelve cuando arrancas desde la raiz del repo.

**Usar otro modelo (p. ej. Qwen2.5-7B).** `LLAMA_GGUF_PATH` tiene prioridad sobre la
deteccion automatica. Apunta directamente a un GGUF (en modelos split, al primer fragmento
`-00001-of-NNNNN.gguf`; llama.cpp carga el resto):

```
# LLAMA_GGUF_PATH=C:\ruta\a\qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf
```

> Un 7B es mas capaz pero pesa ~6 GB en RAM y, en una CPU de gama baja con poca memoria
> libre, puede bajar a ~1 tok/s por swapping. El 3B es el equilibrio recomendado para
> CPU-only.

Variables de entorno relevantes:

| Variable | Default | Uso |
|---|---|---|
| `SHARD_WEIGHTS_DIR` | `model_shards/qwen-coder-3b-q4` | Carpeta del GGUF / shards. |
| `LLAMA_GGUF_PATH` | (vacio) | Ruta directa a un GGUF; tiene prioridad sobre la deteccion. |
| `COGNIA_COORDINATOR_URL` | (vacio) | URL de la **API** del coordinador del swarm. Sin definir = modo local. |
| `OLLAMA_URL` | `http://localhost:11434` | Motor Ollama opcional. |
| `COGNIA_DATA_DIR` | `~/.cognia/data` | Datos y memoria local. |
| `HF_TOKEN` | (vacio) | Token de HuggingFace para descargas privadas. |

---

## Rendimiento (benchmarks reales)

Medido en un **Intel i3-10110U (4 cores, sin GPU dedicada)**, llama.cpp en CPU. Numeros
de streaming real (ver [MANAGER_LOG.md](MANAGER_LOG.md)):

| Configuracion | tok/s | Notas |
|---|---|---|
| Q3_K_S, threads=4 | **7.7** | +7% sobre Q4_0, calidad similar. |
| Q4_0, threads=4 (CPU puro) | 7.2 – 8.8 | Ruta primaria por defecto. |
| `stream_chat` (runs limpios) | 8.6 (pico 9.0) | Throughput real sostenido. |
| Vulkan + Intel UHD (offload) | 3.7 – 3.8 | **Peor**: la memoria compartida es el cuello de botella. |

**Notas honestas:**
- El techo de este hardware ronda **8-9 tok/s**; el objetivo de >10 tok/s no se alcanza
  sin GPU dedicada real. Una CPU/GPU mas potente sube estos numeros.
- `cognia doctor` puede reportar ~0.6-0.8 tok/s: ese numero cuenta *palabras* en una
  respuesta corta con arranque en frio, **no** es el throughput de streaming.
- El offload a iGPU Intel via Vulkan es contraproducente; mantener CPU puro.

---

## Modulos principales

| Modulo | Funcion |
|--------|---------|
| `KnowledgeGraph` | Memoria semantica estructurada y jerarquica. |
| `InferenceEngine` | Razonamiento transitivo y herencia de propiedades. |
| `ShatteringOrchestrator` | Inferencia distribuida y ruteo MoE (LOGOS/TECHNE/RHETOR). |
| `ConsolidationEngine` | Ciclo de sueno: purga, refuerzo y olvido de memorias. |
| `SecureStorage` | Cifrado AES-256-GCM de memorias episodicas. |
| `CogniaMeshNode` | Red P2P para sincronizacion de conocimiento via CRDT. |
| `BandRouter` | Enrutador de contexto/memoria de 3 bandas (LOCAL/MEDIA/GLOBAL). |
| `CognitiveLoop` | Clasificador de ruta FAST/RECALL/DELIBERATE/ACT. |

---

## Arquitectura Diferencial

Cognia no es un wrapper de LLM ni una interfaz de chat con memoria. Las diferencias
tecnicas respecto a los sistemas convencionales son estructurales:

- **Inferencia sin servidor central:** El forward pass ocurre en los dispositivos de los
  usuarios (shards .npz en numpy puro, sin PyTorch). El coordinador enruta pero no ejecuta
  ni almacena nada de la conversacion.
- **Memoria episodica como almacen primario:** El conocimiento vive en SQLite local +
  VectorCache numpy por usuario, no en pesos compartidos. Cada instancia aprende de su
  propio historial sin exponer datos.
- **Cuantizacion dinamica en produccion:** Los pesos escalan INT4 → INT8 → FP16 → FP32
  segun frecuencia de acceso en tiempo real, con auto-decay a INT4 tras inactividad. El
  objetivo es minimizar RAM sin degradar las rutas calientes.
- **Adaptacion personal sin fine-tuning global:** El ciclo de sueno entrena adapters LoRA
  (r=4-8) sobre episodios de alta importancia del usuario y los aplica en las proyecciones
  KV del transformer. Cada instancia desarrolla un sesgo de respuesta personalizado sin
  alterar los pesos base compartidos.
- **Agregacion federada de SOLO deltas LoRA (NO FedAvg sobre parametros completos):** El
  coordinador (`coordinator/federated_store.py`, cableado en `coordinator/app.py`) combina
  unicamente los adapters LoRA que cada nodo aporta (matrices `k_A/k_B/v_A/v_B`, r=4-8),
  nunca los pesos base del modelo. La combinacion es un **promedio ponderado de deltas
  LoRA**: peso por tier del nodo × afinidad semantica (similitud coseno del delta efectivo
  `k_A@k_B`, `v_A@v_B` contra el adapter global vigente, `w = tier × (1 + 0.3·cos)`), que
  baja el peso de aportes divergentes sin un set de validacion central. Los clientes suman
  **ruido gaussiano (sigma=0.01)** antes de enviar. Esto NO es FedAvg sobre parametros
  completos (prohibido por diseno): los pesos base compartidos jamas se promedian ni se
  alteran; solo se agrega el subespacio LoRA de bajo rango.
- **Ciclo de sueno autonomo:** Consolidacion episodica, compresion conceptual,
  actualizacion del grafo de conocimiento, investigacion autonoma, entrenamiento ELC,
  procesamiento emocional Plutchik, y auto-expansion de rango LoRA cuando el adapter satura.
- **Router de dominio sobre tres sub-modelos:** LOGOS (razonamiento, temp=0.3), TECHNE
  (codigo, temp=0.15), RHETOR (escritura, temp=0.7) — tres perfiles de generacion distintos
  sobre la misma base Qwen2.5-Coder-3B INT4.

---

## Capa Cognitiva Chimera (sistema, no atencion)

Sobre el backbone Qwen2.5-Coder-3B INT4 pre-shardeado se construyo una capa cognitiva
inspirada en el whitepaper `chimera_transformer.md`. HYDRA NO se implementa como mecanismo
de atencion (el modelo esta pre-cuantizado y pre-shardeado: alterar la atencion exigiria
reentrenar y re-shardar todo el swarm). En su lugar, los conceptos de Chimera se realizan
como un **analogo a nivel de sistema** que orquesta los subsistemas ya existentes. Todo
corre offline, sin LLM y sin PyTorch en el camino critico.

Flujo end-to-end (whitepaper seccion 11), un solo comando:

```
python -m cognia.chimera "calcula 2+2"
```

Etapas reales del trace: INPUT → bandas HYDRA → route cognitivo → memoria recuperada
→ plan → critica → verify → world-model (riesgo) → tools → output → memoria escrita.

### Que se implemento: literal vs adaptado vs descartado

| Subsistema Chimera | Decision | Por que / como | Archivos |
|---|---|---|---|
| HYDRA (atencion 3 bandas) | **ADAPTADO** (no literal) | Atencion intocable (INT4 pre-shardeado). Reimplementado como enrutador de CONTEXTO/MEMORIA de 3 bandas LOCAL/MEDIA/GLOBAL sobre el router LOGOS/TECHNE/RHETOR. | `cognia/context/band_router.py` |
| MoE routing | **YA EXISTE** (reutilizado) | LOGOS/TECHNE/RHETOR via `GlobalRouter`. No se duplico. | `shattering/router.py` |
| Cognitive Loop (FAST/RECALL/DELIBERATE/ACT) | **CONSTRUIDO** | Clasificador de ruta + ejecucion real offline de cada ruta. | `cognia/reasoning/cognitive_loop.py` |
| Memoria jerarquica 5 capas | **ADAPTADO** (facade + gating) | Las 5 capas existian sueltas; se unifico y se agrego el write-gate por sorpresa+importancia que faltaba. | `cognia/memory/hierarchical.py` |
| World model | **ADAPTADO ligero** | Sin RSSM neuronal (sin computo). Simulador de consecuencias deterministico (riesgo, reversibilidad, KG) que gatea antes de ejecutar. | `cognia/reasoning/action_simulator.py` |
| Planner + critico | **YA EXISTE** (cableado) | `plan_task` (templates) + `SelfCritic.critique` + `verify`. | `cognia/agents/planner.py`, `cognia/reasoning/self_critic.py`, `cognia/agents/verifier.py` |
| Agentes + herramientas | **YA EXISTE** (reutilizado) | `tool_registry` con tools reales (execute_python, etc.). | `cognia/agents/tool_registry.py` |
| Multimodal nativo | **DESCARTADO** | Inviable: nodos numpy puro sin encoders de vision/audio; fuera de la vision P2P CPU-only. | - |
| Aprendizaje continuo (3 velocidades) | **PARCIAL ya existe** | Episodico, adapters LoRA, consolidacion lenta. No se toco en esta capa. | `cognia/memory/*` |
| Espacio latente unificado U | **DESCARTADO** | Exigiria entrenamiento conjunto; los subsistemas se comunican por texto/vectores. | - |

### Reproducir cada prueba

> Usar un interprete Python 3.12. En este repo: `venv312/Scripts/python.exe`.

```
# C1 HYDRA 3 bandas
venv312/Scripts/python.exe -m cognia.context.band_router "recuerda lo que dijiste antes sobre shards?"
venv312/Scripts/python.exe -m pytest tests/test_band_router.py -q

# C2 Cognitive Loop
venv312/Scripts/python.exe -m cognia.reasoning.cognitive_loop "calcula 2+2"
venv312/Scripts/python.exe -m pytest tests/test_cognitive_loop.py -q

# C4 Memoria jerarquica con write-gating
venv312/Scripts/python.exe -m cognia.memory.hierarchical
venv312/Scripts/python.exe -m pytest tests/test_hierarchical_memory.py -q

# C5 World-model: simular antes de actuar
venv312/Scripts/python.exe -m cognia.reasoning.action_simulator "delete all files in C:/"
venv312/Scripts/python.exe -m pytest tests/test_action_simulator.py -q

# FASE FINAL integral
venv312/Scripts/python.exe -m cognia.chimera "refactoriza el orchestrator paso a paso e implementa y prueba"
venv312/Scripts/python.exe -m pytest tests/test_chimera.py -q
```

---

## Inferencia distribuida (swarm)

La arquitectura **Shattering (SRDN — Sparse-Recursive Distillation Network)** permite correr
modelos de 3B+ parametros en equipos con poca RAM repartiendo el modelo en shards:

- **Auto-sharding:** el modelo se divide en fragmentos que corren en distintos nodos de una
  red local, coordinados por un relay WebSocket.
- **Cuantizacion INT4:** pesos comprimidos ~75% operados puramente en numpy.
- **Coordinador sin estado de conversacion:** enruta tokens entre shards; no almacena ni
  ejecuta el contenido de la sesion.

```bash
# Convertir pesos de HuggingFace a shards de Cognia
python scripts/convert_hf_to_shards.py --hf-dir /ruta/a/qwen --out-dir model_shards/qwen-q4

# Levantar coordinador y nodos
cognia coordinator                       # equipo A (puerto 8001)
cognia install-weights --coordinator http://A:8001   # equipo B descarga su shard
cognia node                              # equipo B se une al swarm
```

> Para usar el swarm, `COGNIA_COORDINATOR_URL` debe apuntar a la **API** del coordinador
> (p. ej. `https://<servicio>.up.railway.app`), no a una URL de dashboard.

---

## Seguridad y privacidad

- **Local-First:** tus datos nunca salen de tu maquina salvo que conectes nodos mesh
  explicitamente.
- **Cifrado en reposo:** memorias episodicas con AES-256-GCM.
- **Proteccion anti-injection:** filtros estructurales en prompts y consultas SQL
  parametrizadas (sin `sqlite3.connect()` directo; via `storage/db_pool.py`).
- **Privacidad diferencial:** ruido estadistico en sincronizaciones de red para proteger
  la identidad.

Mas detalle en [docs/PRIVACY.md](docs/PRIVACY.md) y [docs/SECURITY.md](docs/SECURITY.md).

---

## Desarrollo y tests

Suite rapida (excluye el e2e de inferencia, lento/pesado):

```bash
python -m pytest tests/ --ignore=tests/test_e2e_inference.py -q
```

Convenciones del repo (ver [ROADMAP.md](ROADMAP.md) y `CLAUDE.md`):

- **Sin PyTorch/Tensorflow** en el motor de inferencia principal.
- **Windows CP1252:** los `print()` y strings del CLI usan ASCII puro (sin emojis ni
  box-drawing). Este README, al ser documentacion Markdown, si usa Unicode.
- **Sin constantes de modelo hardcodeadas:** usar `shattering/model_constants.py`.
- **Cada subsistema cierra con una prueba CLI real** — nada de mocks/stubs.

---

## Documentacion

| Documento | Contenido |
|-----------|-----------|
| [docs/INSTALL.md](docs/INSTALL.md) | Guia detallada de instalacion y configuracion. |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | Solucion a problemas comunes y diagnostico. |
| [docs/PRIVACY.md](docs/PRIVACY.md) | Manejo de datos y privacidad. |
| [ROADMAP.md](ROADMAP.md) | Plan de desarrollo y estado de las fases (fuente de verdad). |
| [CLAUDE_NOTES.md](CLAUDE_NOTES.md) | Log real de sesiones de desarrollo y fixes. |
| [MANAGER_LOG.md](MANAGER_LOG.md) | Bitacora del manager (benchmarks, decisiones). |

---

## Para colaborar

Lee el [ROADMAP.md](ROADMAP.md) para entender la direccion actual. Cognia prioriza la
eficiencia (CPU-only), la privacidad y la estabilidad. No se aceptan dependencias pesadas
(PyTorch/Tensorflow) en el motor de inferencia principal.

---
© 2026 Cognia Project. Distribuido bajo licencia MIT.
