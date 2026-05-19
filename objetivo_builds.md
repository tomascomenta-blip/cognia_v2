# objetivo_builds.md — Versiones de Cognia y su relacion con el objetivo final

---

## Objetivo final (sintesis)

Cognia es un sistema de IA distribuido, privado y descentralizado que corre en los
dispositivos de sus propios usuarios. No depende de servidores centrales para inferencia.
Su capacidad crece cuanto mas personas lo usan — no porque centralice datos, sino porque
distribuye mejor el computo y agrega gradientes anónimos via aprendizaje federado.

Cada usuario tiene su propia memoria episodica local. Los datos nunca salen del dispositivo.
El acceso es gratuito e ilimitado para quien contribuye con recursos (disco, computo,
disponibilidad). La economia de contribucion reemplaza las suscripciones.

Horizonte: AGI descentralizada — un sistema que aprende sin supervision continua,
investiga por iniciativa propia, se auto-expande donde lo necesita, y se vuelve mas
capaz cuanto mas diversa sea la red que lo sostiene.

---

## Mapa de versiones

### Pre-release — Infraestructura base del swarm (2026-05-04 a 2026-05-05)

**Que resuelve:** La arquitectura de fragmentacion (Shattering) no existia.
El modelo corria como un proceso monolitico local.

**Que se construyo:**
- Arquitectura shard: el modelo se parte en 4 fragmentos que residen en distintos nodos
- Coordinador WebSocket que orquesta el flujo de activaciones entre nodos
- Router global que clasifica prompts en tres dominios (LOGOS / TECHNE / RHETOR)
- Orchestrator local con modos local / distributed / auto
- Correcciones criticas: ciclo de sueno roto, respuestas sociales con NameError,
  race conditions en VectorCache y FragmentManager

**Relacion con el objetivo:** Es el nucleo del proyecto. Sin shattering no hay
distribucion; sin distribucion no hay privacidad estructural ni economia de contribucion.

---

### Fases 1-6 — Estabilidad, seguridad y rendimiento (ROADMAP Phases 1-6)

**Que resuelve:** El swarm era inestable y explotable. No habia tests. La inferencia
bloqueaba el event loop. Los indices de memoria se reconstruian N veces por ciclo de sueno.

**Que se construyo:**
- Circuit breaker para Ollama (3 fallos → 60s cooldown)
- Rate limiting en todos los endpoints del coordinador
- CORS restringido a localhost
- Sleep no bloqueante (async con run_in_executor)
- Consolidacion O(N log N) via multiplicacion matricial (BLAS)
- 144 tests automatizados + CI en GitHub Actions
- Docker, Prometheus, FAISS como mejoras opcionales

**Relacion con el objetivo:** Un sistema distribuido inestable no puede ser el nucleo
de una red de usuarios. Esta fase hace que el swarm sea digno de production.

---

### v0.7.0 — SRDN: Sparse-Recursive Distillation Network (Phase 7)

**Que resuelve:** El modelo corria en modo simulacion con pesos sinteticos.
La arquitectura interna no era lo suficientemente eficiente para dispositivos de consumo.

**Que se construyo:**
- NPQ (Neural Precision Quantization): INT8 para shards criticos, ternario 1.58-bit para shards factuales
- RST (Recursive Shared Transformers): K pasadas iterativas con inyeccion de contexto (alpha=0.1)
- MLA (Multi-Head Latent Attention): KV cache comprimido a d_c=512, 50% menos memoria
- Micro-MoE: 16 expertos agrupados por dominio (logos 0-4, techne 5-9, rhetor 10-15), top_k=2
- Pipeline de destilacion: Ollama como teacher, episodios gold del usuario como datos de entrenamiento

**Relacion con el objetivo:** El objetivo requiere que el modelo corra en dispositivos
de consumo (Android <= 1.5 GB RAM, PC <= 4 GB). La cuantizacion dinamica y el MoE
especializado son los mecanismos que hacen eso posible sin sacrificar capacidad.

---

### v0.8.0 — Commercial Release: primer instalador y hardening (Phase 8)

**Que resuelve:** Instalar Cognia requeria 8+ pasos manuales sin guia. La UI exponia
terminologia interna. La DB no estaba cifrada. No habia endpoints de datos del usuario.

**Que se construyo:**
- `install.ps1` / `install.sh` — instaladores en un comando
- `cognia_doctor.py` — diagnostico del entorno
- `cognia/ux/messages.py` — todos los strings de UI centralizados en lenguaje de usuario
- `migrate_db_encrypt.py` — cifrado AES-256-GCM opcional de la memoria episodica
- Endpoints GDPR: `GET /api/user/data/export` y `DELETE /api/user/data`
- `electron-builder.config.js` + scripts de build — instaladores NSIS (Windows), DMG (macOS), AppImage (Linux)
- Docs: INSTALL.md, PRIVACY.md, TROUBLESHOOTING.md, SECURITY.md

**Relacion con el objetivo:** Sin instalador accesible no hay usuarios. Sin privacidad
garantizada (cifrado, GDPR) no hay confianza. Esta version cierra la brecha entre
arquitectura correcta y producto usable.

---

### v0.9.0 — Security Hardening pre-public (Phase 9)

**Que resuelve:** Superficies de ataque concretas antes de la exposicion publica.

**Que se construyo:**
- SQL injection en `emotion_filter` → queries parametrizadas
- XSS en renderer Electron → DOM API (elimina innerHTML con datos de API)
- CORS wildcard → origenes explicitos
- Prompt injection en hipotesis → delimitadores estructurales en el prompt
- SSRF en OLLAMA_URL → validacion a localhost/127.0.0.1 unicamente
- Rate limiting de feedback: ventana de 60s, maximo 10 llamadas
- 20 tests de seguridad nuevos

**Relacion con el objetivo:** Privacidad por diseno requiere que el sistema no sea
explotable desde adentro. Un atacante que inyecta prompts puede contaminar la memoria
episodica de un usuario — el activo mas valioso del sistema.

---

### v1.0.0-beta.1 — Beta publica (Phases 10-11)

**Que resuelve:** Nuevos usuarios no sabian que instalar, que habia fallado, ni como reportar problemas.
No habia forma de distribuir binarios actualizables.

**Que se construyo:**
- Deteccion de Ollama con instrucciones accionables (no solo "error")
- Modal de consentimiento de privacidad en first-run
- Boton de feedback → GitHub Issues
- Auto-update via electron-updater + GitHub Releases
- Release CI: GitHub Actions construye .exe y .AppImage en cada tag `v*`

**Relacion con el objetivo:** El objetivo de red descentralizada requiere usuarios reales.
Esta version es el primer punto de entrada para la comunidad externa.

---

### v1.1.0 — Production Hardening (Phase 12)

**Que resuelve:** Decisiones pendientes de fases anteriores que generaban riesgo en produccion.

**Que se construyo:**
- MLA KV-cache TTL eviction: sesiones inactivas >1h se purgan automaticamente
- Nivel de log WARNING en modo packaged (elimina ruido interno en la app del usuario)
- Warning explicito de aislamiento single-user en endpoint de borrado de datos
- Pinning de dependencias opcionales (torch>=2.1.0, transformers>=4.40.0)

**Relacion con el objetivo:** Deployments de larga duracion (nodos contribuyendo al swarm
por dias) necesitan que el proceso no acumule memoria indefinidamente.

---

### v1.2.0 — Real Distributed Inference: Qwen2.5-Coder-3B INT4 (Phase 13)

**Que resuelve:** El sistema corria en modo simulacion con pesos sinteticos.
No habia inferencia real distribuida.

**Que se construyo:**
- Cuantizacion INT4 nibble-packed per-row symmetric (50% mas compacto que INT8)
- Constantes de arquitectura Qwen2.5-Coder-3B: 36 capas, hidden=2048, n_heads=16, n_kv_heads=8, vocab=151936
- Forward pass Qwen2 en numpy puro: RMSNorm, RoPE, GQA, SwiGLU — sin PyTorch
- Template ChatML, EOS tokens de Qwen, pipeline de generacion autoregressiva
- Script de conversion HF → shards INT4 (.npz)
- Manifest de 4 shards para Qwen2.5-Coder-3B-Instruct INT4

**Relacion con el objetivo:** Esta es la transicion de prototipo a sistema real.
Sin pesos reales no hay inferencia; sin inferencia distribuida no hay swarm; sin swarm
no hay economia de contribucion ni descentralizacion.

---

### v1.3.0 — Federated Learning (Phase 14)

**Que resuelve:** El aprendizaje era estrictamente local. Los nodos no compartian
inteligencia entre si, lo que contradice el objetivo de red que mejora colectivamente.

**Que se construyo:**
- `FederatedStore`: motor FedAvg ponderado por tier (basic=0.5, standard=1.0, premium=3.0)
- Tres endpoints en el coordinador: `POST /contribute`, `GET /global`, `GET /stats (admin)`
- Ciclo ELC en sleep: entrena adapter LoRA local → agrega ruido gaussiano (sigma=0.01) → envia al coordinador → descarga adapter global → aplica en inferencia
- MIN_CONTRIBUTORS=2 antes de la primera agregacion (un nodo no puede definir el modelo global)
- Sin PyTorch: stdlib urllib.request + numpy

**Relacion con el objetivo:** Este es el mecanismo central del crecimiento colectivo.
Los datos del usuario nunca salen del dispositivo; solo viajan deltas de parametros con
ruido gaussiano. La red aprende de la diversidad de sus usuarios sin ver ninguno
individualmente.

---

### v1.4.0 — Emotion Wheel (Phase 15)

**Que resuelve:** El ciclo de sueno no tenia procesamiento emocional. Las emociones
de alta intensidad se acumulaban sin regulacion, afectando la recuperacion de memorias.

**Que se construyo:**
- `EmotionWheelProcessor`: modelo Plutchik con 8 emociones primarias
- Deteccion de desequilibrio: emocion dominante >35% con opuesta <10%
- Modulacion de importancia: factor 1.08 (anti-olvido positivo) o 0.92 (anti-rumiacion negativa)
- Integrado como PASO 8 del ciclo de sueno — falla silenciosa, no bloquea el ciclo

**Relacion con el objetivo:** La inteligencia sin regulacion emocional tiende a
bucles de rumiacion. Este modulo hace que la memoria episodica sea mas robusta:
episodios de alta carga emocional negativa pierden peso gradualmente en vez de
contaminar indefinidamente la recuperacion de contexto.

---

### v1.5.0 — Dynamic Quantization (Phase 16)

**Que resuelve:** La cuantizacion INT4 era estatica. Cada llamada a linear() requeria
dequantizacion completa aunque el peso se usara repetidamente.

**Que se construyo:**
- `DynamicWeights`: wrapper de INT4Weights que trackea accesos y cachea en RAM
  - <5 accesos: INT4 puro (sin cache)
  - 5-14 accesos: cache INT8 en RAM
  - 15-29 accesos: cache FP16
  - >= 30 accesos: cache FP32 (matmul directo, maximo rendimiento)
- Auto-decay tras 300s de inactividad: regresa a INT4 para liberar RAM
- `PrecisionManager`: registry de DynamicWeights por capa; `decay_all()` desde el ciclo de sueno
- Thread-safe via RLock; matmul corre fuera del lock

**Relacion con el objetivo:** El objetivo documenta exactamente esta precision dinamica
(INT4 → INT8 → INT16 → INT32 segun uso). Esta fase implementa lo que el vision document
describe como principio fundamental de eficiencia energetica.

---

### v1.6.0 — Contribution Economy: enforcement real (Phase 17)

**Que resuelve:** El sistema economico de tiers existia en la BD pero no tenia
enforcement. Cualquier nodo podia acceder a cualquier modelo independientemente de su tier.

**Que se construyo:**
- `SlidingWindowLimiter`: ventana deslizante de 60s por node_id (no por IP)
- Progresion de tiers:
  - basic: solo qwen-coder-3b-q4, 10 RPM
  - standard: todos los modelos + shattering, 30 RPM
  - premium: sin restriccion de modelo, 100 RPM
- Enforcement en `/api/shattering/infer`: verifica `allowed_models` (403) y RPM (429)
- Admin y modo dev (COORDINATOR_KEY no seteado) bypass ambos checks

**Relacion con el objetivo:** La economia de contribucion es el mecanismo que reemplaza
las suscripciones. Sin enforcement real, el tier es decorativo. Esta version cierra el
circuito: contribucion → tier → acceso prioritario.

---

### v1.7.0 — Sandbox real: AST analysis + runtime guard (Phase 18)

**Que resuelve:** El sandbox de codigo generado por IA usaba validacion por regex.
El regex es bypasseable con split de strings, encoding o imports dinamicos.

**Que se construyo:**
- `_SandboxVisitor` (AST NodeVisitor): detecta `import X`, `from X import`,
  `__import__()`, `importlib.import_module()`, y acceso a attrs peligrosos de `os`
- Runtime guard: cada archivo temporal se prefija con un override de `builtins.__import__`
  que bloquea modulos en tiempo de ejecucion (cubre `exec("import socket")` y similares)
- `BLOCKED_MODULES` y `BLOCKED_OS_ATTRS` como frozensets — fuente unica para ambas capas

**Relacion con el objetivo:** El objetivo incluye ejecucion de codigo generado durante
el ciclo de sueno. Sin sandbox real, un usuario malintencionado (o un bug en el modelo)
puede ejecutar codigo arbitrario en el host.

---

### v1.8.0 — ARA: Adaptive Rank Amplification (Phase 19)

**Que resuelve:** Los adapters LoRA del ELC tenian rango fijo (r=4). Cuando el
adapter saturaba (loss plateau), no tenia forma de ganar capacidad adicional.

**Que se construyo:**
- `is_saturated(loss_history)`: detecta plateau con varianza/media < 2% y loss > 0.05
- `expand_lora_weights(A, B, n_new)`: inicializa nuevas filas de A ortogonales al espacio
  actual (proyeccion al espacio nulo via QR), columnas de B en cero; MAX_RANK=8
- `train()` en `local_adapter.py`: detecta saturacion, expande si corresponde, hace
  epochs//3 de fine-tuning con el rank expandido
- FedAvg variable-rank: el coordinador acepta ranks 4-8, rellena con ceros al rank maximo
  del batch antes de promediar

**Relacion con el objetivo:** El objetivo describe auto-expansion de parametros donde
el modelo detecta necesidad y propone crecimiento controlado. ARA es la implementacion
concreta a nivel de adapter: el sistema crece donde lo necesita, en el dispositivo del
usuario, y la expansion exitosa se propaga via federated learning.

---

### En desarrollo — Mobile + Installer con wizard de setup

**Mobile (Expo React Native, SDK 54):**

Resuelve la ausencia de punto de acceso movil. Cognia era unicamente web o desktop.
La app movil no requiere servidor: conversaciones en SQLite local (expo-sqlite v16),
sin dependencia de la red para almacenamiento. Configurable con URL del servidor
Cognia para inferencia cuando hay conexion.

**Desktop installer con wizard de setup (desktop-v1.1.x):**

Resuelve la friccion de primer uso. El wizard en 3 clics:
1. Bienvenida
2. Eleccion de modo: local (descarga los 4 shards, ~1.2 GB) o swarm (registra el nodo
   con el coordinador, descarga solo el shard asignado, ~300 MB)
3. Instalacion automatica con progreso visual por fase

En modo swarm: el setup llama `POST /api/node/register` al coordinador, recibe el
shard asignado, escribe `COGNIA_NODE_ID` y `COGNIA_NODE_SHARD` en `.env` para
persistencia entre reinicios, y descarga unicamente ese shard. Esto implementa
el principio de migracion de shards — cada nodo aloja una parte, no una copia completa.

**Relacion con el objetivo:** El objetivo requiere que cualquier persona con un dispositivo
moderno pueda acceder sin pasos complejos. El wizard reduce la instalacion de 8+ pasos
manuales a un doble clic. El modo swarm del wizard conecta directamente con la
descentralizacion: cada nuevo usuario que instala en modo swarm contribuye capacidad
de computo a la red en lugar de duplicar el modelo completo en su disco.

---

## Que falta para el objetivo final

| Componente | Estado | Siguiente paso |
|---|---|---|
| Inferencia distribuida real en swarm | Implementada en v1.2.0; requiere multiples nodos con pesos reales | Prueba con 2+ nodos en red local |
| Aprendizaje federado en produccion | FedAvg implementado; requiere MIN_CONTRIBUTORS=2 | Suficiente con 2 usuarios reales contribuyendo |
| Cuantizacion dinamica verificada | Implementada en v1.5.0; no hay benchmarks reales sin pesos | Ejecutar con shards reales descargados |
| Auto-expansion (ARA) en red | Implementado localmente; FedAvg acepta ranks variables | Verificar con nodos en distintos ranks |
| Android | No iniciado | Requiere llama.cpp via NDK o puerto del forward numpy |
| Descentralizacion del coordinador | El coordinador es un punto unico de fallo | Arquitectura P2P o coordinadores redundantes |
| Certificados de code signing | electron-builder listo; certificados no comprados | Comprar Apple Developer ID + EV cert Windows |
| CuriosityEngine integrada en sueno | Existe en cognia core; no integrada en el ciclo de sueno completo | Conectar en _sleep_sync() como PASO 9 |

---

## Proximos horizontes tecnicos

**Routing semantico sobre embeddings.** El router actual asigna sub-modelo por conteo de keywords, lo que produce falsos negativos en prompts donde el dominio se expresa con vocabulario no anticipado. El siguiente paso es reemplazarlo con similitud coseno entre el embedding del prompt y centroides de dominio precalculados, usando el mismo VectorCache que ya existe en `episodic_fast.py`. Esto no requiere dependencias nuevas — solo calcular tres vectores centroide en el primer arranque y actualizar con cada nueva sesion. El impacto directo es en la calidad del routing para usuarios no anglofonos y para prompts tecnicos en idiomas distintos al ingles.

**Latent Persistence Cache (LPC) como alternativa al contexto regenerado.** En cada token generado, el pipeline recalcula el hidden state desde cero para el token nuevo, asumiendo que el KV cache esta en el nodo remoto. El problema es que en modo local y en modo swarm sin estado persistente, ese cache no existe entre llamadas. LPC propone cachear el hidden state comprimido del ultimo shard al final de cada generacion, indexado por session_id, y reinyectarlo como sesgo residual en la siguiente llamada del mismo usuario. Esto aproxima continuidad de contexto sin transmitir el historial completo de tokens por la red, lo cual seria imposible con la latencia actual del swarm. La implementacion reutiliza `CompressedKVCache` en `mla.py` con una clave de lookup por session.

**Depth Up-Scaling (DUS) para crecer sin reentrenamiento.** La tecnica SOLAR de Upstage demostro que se pueden fusionar capas de modelos del mismo tipo (interpolacion lineal de pesos) para producir un modelo mas profundo sin entrenamiento completo. Aplicado a los shards de Cognia: un nodo con mas RAM disponible podria recibir dos shards adyacentes y fusionarlos en un shard de 18 capas en lugar de 9, ganando representaciones mas ricas sin alterar el protocolo de red. El script de fusion seria un post-proceso sobre los .npz existentes, con alpha configurable para controlar el grado de interpolacion. Esto abre un camino concreto hacia modelos mas grandes en la red sin requerir entrenamiento distribuido.

**Federated Knowledge Distillation como evolucion de FedAvg.** El FedAvg actual promedia directamente los deltas LoRA de los nodos contribuyentes, lo que asume que todos los adapters viven en el mismo espacio de representacion. Cuando los ranks difieren (ARA permite r=4 a r=8), el promedio introduce ruido estructural. Una alternativa mas solida es que cada nodo contribuya no sus pesos LoRA sino un conjunto de representaciones intermedias (hidden states sobre prompts anonimos de benchmark), y el coordinador distile un adapter global que replique esas representaciones. Esto desacopla la estructura interna del adapter de la semantica que se quiere agregar, hace el proceso robusto a ranks heterogeneos, y reduce el riesgo de memorizar patrones especificos de un nodo individual.
