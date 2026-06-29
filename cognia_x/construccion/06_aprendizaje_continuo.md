# 06 — Aprendizaje continuo (RAG doc-level + LoRA r≤16 + fusión intra-cuenca + router de bandas + FedEx-LoRA)

> **Propósito.** Especificar la **triple capa** de aprendizaje continuo de Cognia-X, diseñada por
> evidencia para tener **cero olvido por construcción** en la capa barata y **olvido acotado** en las
> caras: (a) **RAG a nivel de DOCUMENTO** (1 recuperación/consulta, base congelada) para inyectar
> hechos nuevos sin tocar pesos; (b) **LoRA de rango bajo** (r≤16) por dominio como regularizador
> implícito; (c) **fusión de adapters dentro de la misma cuenca** + **router de 3 bandas**
> (LOCAL / MEDIA / GLOBAL) sobre el routing de dominios existente. Define además la **agregación
> federada CORRECTA** (FedEx-LoRA / `avg(B@A)`, **NUNCA** FedAvg ingenuo `avg(B)@avg(A)`), anclada en
> el bug REAL que ya existe en `coordinator/federated_store.py` y que **exp003 midió** (error
> 0.4%→66% con heterogeneidad). Cierra con el gate **G3/E4** (A/B RAG vs LoRA vs kNN-LM) y un DoD
> verificable: **inyectar N hechos nuevos sin olvido medible**.

> **Anclaje de fuentes (verificado HOY con Read/Grep, no asumido):**
> - Decisión de arquitectura: `cognia_x/manager/architecture.md §4` (triple capa) **y `§5`** (agregación
>   federada exacta vs ingenua; señala el bug de `federated_store.py` Pass 3).
> - Evidencia experimental propia: `cognia_x/experiments/exp003_fedavg_lora_inexactness/` (H-CF-2,
>   `run.py` + `results/results.md`: error relativo Frobenius y colapso de rango K·r→r, medidos).
> - Bug REAL a corregir: `coordinator/federated_store.py` (Pass 3, líneas 316-329, acumula
>   `k_A,k_B,v_A,v_B` por separado). Constantes reales: `_RANK_MAX=8`, `_HIDDEN_DIM=2048`,
>   `_KV_PROJ_OUT=256`, `SEMANTIC_WEIGHT_ALPHA=0.3`, `MAX_BLOB_BYTES=512_000`, ruido DP `sigma=0.01`.
> - Infra reusable que corre: `cognia_v3/memory/cognia_embedding.py` (`LazyEmbeddingModel`
>   all-MiniLM-L6-v2 384-dim, `text_to_vector_fast`, `BoundedLRUCache`, fallback n-gramas en
>   bajo-recurso), `cognia_v3/memory/conversation_memory.py` (`ContextSelector`, coseno en RAM, diseño
>   CPU 2-core), `storage/db_pool.py` (`db_connect_pooled` / `get_pool(path).get()` — regla "sin
>   `sqlite3.connect` directo"), `cognia_v3/training/qlora_trainer.py` (`LoraConfig`,
>   `target_modules=["q_proj","v_proj","k_proj","o_proj"]`, Kaggle pipeline
>   `cognia_v3/training/kaggle/train_qlora_kaggle.py`), `shattering/model_constants.py`
>   (`QWEN25_CODER_3B`, `DOMAIN_EXPERT_CLUSTERS` logos/techne/rhetor).
> - Gobernanza: `00_READINESS.md §4 G3` (gate E4 RAG vs LoRA vs kNN-LM; "sin exp propio, apoyado en
>   literatura").

---

## 1. Propósito y alcance

### 1.1 Qué resuelve
Cognia-X debe **adquirir conocimiento nuevo después del entrenamiento** (hechos del usuario, código de
su repo, documentación de un dominio) **sin degradar lo que ya sabía** (catastrophic forgetting). La
tesis del lab (`architecture.md §4`, confianza **alta en dirección, media en constantes**) es que no
hay UNA solución sino una **jerarquía de costo↔permanencia**:

| Capa | Mecanismo | Qué cuesta | Olvido | Permanencia |
|---|---|---|---|---|
| (a) RAG doc-level | recuperar + inyectar en contexto, base **congelada** | banda en prefill (~35% TTFT, doc-level — *citado, NO medido en el i3*) | **cero por construcción** | mientras esté en el índice |
| (b) LoRA r≤16 | adapter de bajo rango por dominio | entrenamiento (Kaggle GPU) + 1 carga de adapter | **bajo** (regularizador; "olvida menos pero aprende menos") | persistente en el adapter |
| (c) Fusión + router de bandas | task-arithmetic/TIES intra-cuenca + enrutado LOCAL/MEDIA/GLOBAL | fusión offline + 1 selección de banda/consulta | depende de la cuenca | persistente, compartible |

La regla de asignación: **un hecho aislado → RAG**; **una habilidad/estilo de dominio → LoRA**;
**varios adapters del mismo dominio que conviene unificar → fusión intra-cuenca**.

### 1.2 Qué NO cubre (se delega)
- El **verificador de hechos** (`FactVerifier`, redundancia ≥2 fuentes) que decide si un documento
  recuperado es confiable → **plano 04 §FactVerifier**. Aquí el RAG **provee** el índice; el verificador
  **consume**.
- El **lazo de auto-mejora STaR** que genera los datos con que se entrenan los adapters → **plano 05**.
  Aquí se define **cómo persistir** lo aprendido, no cómo generarlo.
- El **entrenamiento QLoRA en sí** (recetas, hiperparámetros, dataset) → ya existe
  `qlora_trainer.py` + plano 03 (entrenamiento/datos). Aquí se define el **formato del adapter**, su
  **rango**, y su **ciclo de vida** (fusión + federación).
- El **backbone** que ejecuta la inferencia con el adapter cargado → plano 02.

### 1.3 Alcance honesto (PROBADO / ASUMIDO / PENDIENTE)
- **PROBADO (propio):** la **inexactitud del FedAvg ingenuo** de adapters (exp003, álgebra + medición:
  error 0.43%→65.7% según heterogeneidad; rango exacto K·r=32 vs ingenuo r=8). Confianza **alta en la
  EXISTENCIA/dirección** del error (`avg(B)@avg(A) ≠ avg(B@A)` es álgebra, no estadística, y el colapso
  de rango a `r` es exacto); las **magnitudes** de la tabla (0.43%→66%) son **medidas sobre datos
  sintéticos** (m=n=256, K=4, heterogeneidad gaussiana, trials=20, seed=11) → la **escala** con
  adapters reales puede diferir; lo que NO depende de los datos es el signo/dirección.
- **ASUMIDO (literatura, sin exp propio):** "RAG ≥ fine-tune en hechos nuevos con cero olvido"
  (Ovadia 2024), "LoRA olvida menos pero aprende menos" (Biderman TMLR'24), "fusión segura sólo dentro
  de una cuenca" (Model Soups), "olvido = interferencia de gradientes en subespacio de bajo rango"
  (arXiv:2510.09181). Confianza **media**. **El gate G3/E4 (§5) los re-mide en Cognia.**
- **PENDIENTE (no construido):** el índice RAG doc-level real, el router de 3 bandas como subsistema,
  la fusión task-arithmetic/TIES, y la **corrección del bug de `federated_store.py`**. SCALE = 0%.

---

## 2. Estado de partida (qué existe y corre hoy)

| Pieza | Existe | Corre | Cita |
|---|---|---|---|
| Embeddings CPU (all-MiniLM-L6-v2, 384-dim, lazy+batch+LRU) | Sí | Sí | `cognia_v3/memory/cognia_embedding.py` (`LazyEmbeddingModel.get`, `text_to_vector_fast`, `BoundedLRUCache`) |
| Fallback n-gramas en modo bajo-recurso (sin descargar modelo) | Sí | Sí | `cognia_embedding.py` (devuelve `None` → capa superior usa n-gramas) |
| Selección de contexto por coseno en RAM (patrón doc-level) | Sí | Sí | `cognia_v3/memory/conversation_memory.py` (`ContextSelector`, coseno O(N) en RAM, N≤MAX_TURNS) |
| Pool SQLite (regla "sin `sqlite3.connect` directo") | Sí | Sí | `storage/db_pool.py` (`db_connect_pooled`, `get_pool(path).get()`) |
| Entrenador QLoRA (PEFT) con `target_modules` q/k/v/o | Sí | Sí (Kaggle) | `cognia_v3/training/qlora_trainer.py` (`LoraConfig(r,alpha,target_modules=["q_proj","v_proj","k_proj","o_proj"],lora_dropout=0.05,task_type="CAUSAL_LM")`) |
| Pipeline de entrenamiento en Kaggle GPU | Sí | Sí | `cognia_v3/training/kaggle/train_qlora_kaggle.py` (cuenta anthuananthuan, token en `~/.kaggle`) |
| Clusters de dominio (base del router de bandas) | Sí | — | `shattering/model_constants.py:DOMAIN_EXPERT_CLUSTERS` = logos(0-4)/techne(5-9)/rhetor(10-15) |
| Almacén federado de adapters LoRA | Sí | Sí | `coordinator/federated_store.py` (`FederatedStore.add_contribution/aggregate`, SQLite BLOBs) |
| **Agregación federada CORRECTA (`avg(B@A)`)** | **No** | — | **Bug**: Pass 3 (líneas 316-329) hace `avg(B)@avg(A)`. Este plano la corrige. |
| **Índice RAG doc-level como subsistema** | **No** | — | Diseño nuevo aquí (`cognia_x/continual/rag_index.py`); reusa `cognia_embedding` + `db_pool` |
| **Router de 3 bandas (LOCAL/MEDIA/GLOBAL)** | **No** | — | Diseño nuevo aquí; se monta SOBRE el routing de dominios existente |
| **Fusión intra-cuenca (task-arithmetic/TIES)** | **No** | — | Diseño nuevo aquí (`cognia_x/continual/adapter_fusion.py`) |

**Lectura honesta.** No se parte de cero: la **infra de embeddings, el coseno-en-RAM, el pool SQLite y
el entrenador QLoRA ya corren**. Lo que falta es (a) **empaquetar** el RAG doc-level como subsistema con
índice persistente, (b) el **router de bandas**, (c) la **fusión intra-cuenca**, y (d) **arreglar la
agregación federada** que hoy es matemáticamente inexacta. El `federated_store.py` ya **reconstruye la
delta por cliente** (`_effective_delta_embed`, líneas 74-84: `k_A.T @ k_B.T`) — sólo que la usa para
coseno, **no** para la agregación. La corrección reusa esa misma reconstrucción.

### 2.1 Una trampa real ya presente en el código (no repetirla)
`federated_store.py` calcula `dk = k_A.T @ k_B.T` para el **embedding semántico** (líneas 80-81) pero en
la **agregación** (Pass 3) acumula `k_A`, `k_B`, `v_A`, `v_B` **por separado** (`acc[k] += norm_w *
padded[k]`). Es decir: **el código YA sabe reconstruir la delta exacta**, pero la tira para promediar los
factores. La corrección (§4.4) **no necesita una librería nueva**: necesita mover esa reconstrucción al
camino de agregación. Lección de diseño: *promediar adapters = promediar deltas reconstruidas, jamás
factores.*

---

## 3. Diseño detallado

### 3.1 Capa (a) — RAG a nivel de DOCUMENTO (cero olvido por construcción)

**Principio.** La base **no se toca**: los hechos nuevos viven en un índice externo y se inyectan en el
contexto en tiempo de consulta. Si no hay actualización de pesos, **no hay olvido** (Ovadia 2024;
confianza media en la magnitud, **alta** en el principio: es tautológico que pesos congelados no se
olvidan). **1 recuperación por consulta** (doc-level), **no por token**.

**Por qué doc-level y no kNN-LM por-token (DECISIÓN DURA, ya tomada).** `architecture.md §4`:
kNN-LM por-token está **DESCARTADO** — la recuperación es *memory-bound* (~35% de TTFT a nivel
documento; por-token lo multiplica por la longitud de salida). En el i3 (2c/4t, banda escasa) eso es
inviable. El A/B de §5 lo incluye **sólo como control negativo documentado**, no como candidato real.

**Componentes (`cognia_x/continual/rag_index.py`, nuevo):**

```
class RagDocIndex:
    # Persistencia: SQLite vía db_pool (NUNCA sqlite3.connect directo).
    # Tabla docs(id TEXT PK, text TEXT, source TEXT, ts REAL, embedding BLOB)
    # embedding = np.float32[384] de all-MiniLM-L6-v2 (reusa cognia_embedding).
    def add(text, source) -> doc_id          # embebe (text_to_vector_fast) + persiste
    def search(query, k=4) -> list[Doc]      # coseno top-k; 1 recuperación/consulta
    def build_context_block(query, k) -> str # arma el bloque inyectable en el prompt
    def remove(doc_id)                        # olvido EXPLÍCITO (privacidad/RGPD)
```

- **Embeddings:** reusar `LazyEmbeddingModel` + `text_to_vector_fast` de `cognia_embedding.py`
  (all-MiniLM-L6-v2, 384-dim, cache LRU acotada). En modo bajo-recurso el módulo ya devuelve fallback
  n-gramas → el RAG **degrada** pero no se cae (respeta el i3).
- **Búsqueda (CPU-first):** para N pequeño (≤ ~10⁴ docs) **coseno denso en RAM** sobre una matriz
  `np.float32[N,384]` con `np.argpartition` top-k — el mismo patrón que `ContextSelector` ya usa y que
  es O(N) sin DB en el hot path. Para N grande, índice plano por bloques (sin dependencia FAISS de
  arranque; FAISS-CPU es opción posterior, no requisito). **Confianza media** en el umbral N de cruce
  (no medido en el i3).
- **Inyección:** `build_context_block` antepone los top-k docs al prompt del backbone (plano 02),
  respetando el presupuesto de ventana. El verificador de hechos (plano 04) puede filtrar antes de
  inyectar (≥2 fuentes coincidentes).
- **Olvido explícito:** `remove(doc_id)` borra del índice. Esto da **derecho al olvido real** (RGPD) —
  algo que LoRA/fusión NO dan (un hecho fundido en pesos no se "des-aprende" sin reentrenar). Es un
  argumento fuerte a favor de RAG para datos personales.

**Coste declarado (confianza media, citado no medido en target):** ~35% de sobrecarga en TTFT a nivel
documento (`architecture.md §4`). El gate G3/E4 lo mide en el i3.

### 3.2 Capa (b) — LoRA r≤16 por dominio (regularizador implícito)

**Principio.** Para **habilidades/estilo** (no hechos sueltos): un adapter LoRA de **rango bajo r≤16**
por dominio. El bajo rango es un **regularizador implícito** — "olvida menos pero aprende menos"
(Biderman TMLR'24; confianza media). Entrenado en **Kaggle GPU** (el i3 NO entrena QLoRA: bitsandbytes
4-bit exige GPU — ver `00_READINESS §5` y restricción de hardware).

**Reuso real:** `qlora_trainer.py` ya tiene la `LoraConfig`. Decisiones concretas:
- **Rango:** `r=8` por defecto (= `_RANK_MAX=8` de `federated_store.py`, para compatibilidad con la
  federación), `r≤16` techo duro. **Razón de coherencia:** si un adapter local va a federarse, su rango
  debe respetar el cap del coordinator.
- **`target_modules`:** **DECISIÓN A FIJAR (riesgo, §6).** `qlora_trainer.py` entrena `q,k,v,o`;
  `federated_store.py` **sólo federa `k,v`** (`_KEYS=("k_A","k_B","v_A","v_B")`). Hay un **desajuste de
  contrato** entre lo que se entrena y lo que se agrega. Opciones: (i) federar también `q,o` (ampliar
  `_KEYS`), o (ii) restringir el entrenamiento federable a `k,v`. **Recomendación: (i)** — federar el
  mismo conjunto que se entrena, porque limitar a `k,v` deja capacidad sobre la mesa sin razón medida.
  Marcar como decisión de M0.
- **Un adapter por dominio:** alineado con `DOMAIN_EXPERT_CLUSTERS` (logos/techne/rhetor). Esto **no**
  es el router de bandas (§3.3); es la unidad de entrenamiento.
- **Formato de adapter:** `npz` con las llaves del contrato federado (compatible con
  `FederatedStore.add_contribution`). El export de PEFT→npz es un script de pegado (M0).

**Lo que LoRA NO debe hacer:** no es el camino para hechos volátiles del usuario (eso es RAG, por el
olvido explícito y el cero-olvido). LoRA es para **competencia estable de dominio**.

### 3.3 Capa (c) — Fusión intra-cuenca + router de 3 bandas

**3.3.1 Fusión intra-cuenca (`cognia_x/continual/adapter_fusion.py`, nuevo).**
Cuando hay **varios adapters del mismo dominio** (p.ej. tres entrenos de `techne` en datos distintos),
fundirlos en uno reduce el costo de carga/selección. **Sólo dentro de la misma cuenca de pérdida**
(Model Soups; confianza media): fundir adapters de dominios dispares (logos+rhetor) puede caer fuera de
la cuenca y degradar ambos. Métodos, de conservador a radical:
- **Conservador — promedio de deltas reconstruidas** `avg(B@A)` (la MISMA operación exacta que la
  federación correcta, §4.4): seguro pero diluye.
- **Moderado — task-arithmetic** (suma escalada de deltas): `W += Σ λ_i · ΔW_i`. Permite "sumar
  habilidades".
- **Radical — TIES-Merging** (trim + elect-sign + disjoint-merge): resuelve interferencia de signos
  entre adapters; mejor cuando hay muchos. Más complejo, **no demostrado en Cognia**.
**Regla dura:** la fusión opera sobre **deltas reconstruidas**, nunca sobre factores A/B por separado
(mismo teorema que §4). Y **sólo intra-cuenca**: el router de bandas (abajo) mantiene separadas las
cuencas dispares en vez de fundirlas a la fuerza.

**3.3.2 Router de 3 bandas LOCAL / MEDIA / GLOBAL (`cognia_x/continual/band_router.py`, nuevo).**
Es el **análogo a nivel de sistema de HYDRA** (restricción dura: HYDRA **NO** es atención de red; es un
**enrutador de contexto/memoria de 3 bandas** montado SOBRE el routing de dominios existente
logos/techne/rhetor). Las tres bandas son **horizontes de memoria**, no dominios:

| Banda | Fuente de conocimiento | Mutabilidad | Mecanismo |
|---|---|---|---|
| **LOCAL** | contexto reciente/personal de la sesión | alta, efímero | RAG doc-level hot-cache + buffer conversacional (reusa `conversation_memory`) |
| **MEDIA** | competencia de dominio del usuario/equipo | media, por-dominio | adapter(s) LoRA fundidos del dominio activo (§3.2/§3.3.1) |
| **GLOBAL** | base congelada + adapter federado global | baja, compartida | pesos base (Q4_K_M) + global adapter de `federated_store` |

El router decide, por consulta: **qué banda(s) consultar y con qué peso**. Decisión de bajo costo (1
clasificación por consulta), montada sobre el clasificador de dominio que ya existe. La señal de
**relevancia** del router puede usar **R-VALOR como heurística decisional ACOTADA** (controlabilidad ×
relevancia) — pero (honestidad, `00_READINESS §5.2`) R-VALOR es **brújula, no acelerador**, validado en
toy/oráculo, **no confirmado en el lazo real**: usarlo para ordenar/abstener, sin sobre-apoyarse.

### 3.4 Agregación federada CORRECTA — el corazón del plano (FedEx-LoRA / `avg(B@A)`)

**El teorema (PROBADO, exp003 — no es opinión, es álgebra).**
Cada cliente k aporta `ΔW_k = B_k @ A_k`. La agregación **exacta** es:
```
ΔW_exact  = mean_k(B_k @ A_k)              # rango ≤ K·r
```
La agregación **ingenua** (la que hace `federated_store.py` HOY) promedia los factores:
```
ΔW_naive  = mean_k(B_k) @ mean_k(A_k)      # rango ≤ r
```
Y `mean(B)@mean(A) ≠ mean(B@A)` **en general** (sólo iguala si los clientes son idénticos). exp003 lo
midió (numpy puro, determinista, seed=11, m=n=256, r=8, K=4):

| heterogeneidad clientes | error relativo Frobenius | rango exacto | rango ingenuo |
|---|---|---|---|
| 0.0 (idénticos) | **0.0000** (sanity) | 8 | 8 |
| 0.1 | 0.0043 | 32 | 8 |
| 0.25 | 0.0268 | 32 | 8 |
| 0.5 | 0.1008 | 32 | 8 |
| 1.0 | 0.3289 | 32 | 8 |
| 2.0 | **0.6565** | 32 | 8 |

Dos hallazgos: **(1)** el error crece con la heterogeneidad (0.4%→66%); **(2)** el ingenuo **colapsa el
rango** del adapter agregado a `r` (8) cuando el exacto retiene `K·r` (32) — **tira la diversidad de los
K clientes**. Y `architecture.md §5` añade que **bajo el ruido DP que Cognia exige (`sigma=0.01`) el
error se vuelve cuadrático** → la corrección importa MÁS, no menos, con privacidad.

**El bug REAL (a corregir).** `coordinator/federated_store.py`, Pass 3, líneas 316-329:
```
acc = {"k_A": 0, "k_B": 0, "v_A": 0, "v_B": 0}     # ceros por llave
for (row, data), w in zip(loaded, weights):
    padded = _pad_to_rank(...)
    for k in _KEYS:
        acc[k] += norm_w * padded[k]                # <-- promedia FACTORES por separado
# al reconstruir en inferencia: acc["k_B"] @ acc["k_A"] = avg(B)@avg(A) = INGENUO
```
Es **exactamente** `ΔW_naive`. Además `_pad_to_rank` alinea rangos a `max_rank` pero **no** arregla la
inexactitud (sigue promediando factores).

**La corrección.** Reemplazar Pass 3 por agregación sobre **deltas reconstruidas**, reusando la
reconstrucción que el archivo YA tiene (`_effective_delta_embed`). Tres opciones, conservador→radical:

- **Conservadora — `avg(B@A)` re-factorizada por SVD truncado (RECOMENDADA para v1).**
  ```
  for k in (k, v): ΔW_k_global = mean_k(weights_k · (B_k @ A_k))   # delta exacta, rango ≤ K·r
  U,S,Vt = svd(ΔW_global); B_glob, A_glob = factorizar(U,S,Vt, r')  # truncar a r' (≤16)
  ship npz(k_A=A_glob_k, k_B=B_glob_k, v_A=A_glob_v, v_B=B_glob_v)
  ```
  La delta global es **exacta**; la **única** aproximación es el truncado SVD a `r'`, que es
  **controlado y medible** (energía espectral retenida), a diferencia del error **no controlado** del
  FedAvg ingenuo. **Restricción de tamaño REAL:** la delta full `256×2048` en float32 son ~2 MB por
  proyección > `MAX_BLOB_BYTES=512_000` → **no se puede shippear la delta full**; el SVD truncado a
  `r'≤16` la devuelve al formato de adapter (npz pequeño) y respeta el cap. **Costo CPU:** un SVD
  `256×2048` por proyección por agregación (cada `AGGREGATE_EVERY_N=5` contribs) — barato, offline.
- **Moderada — stacking exacto estilo FedEx-LoRA (rango K·r, sin truncar).** Concatenar adapters →
  `A_glob = [A_1;…;A_K]` (rango K·r). **Exacto sin pérdida**, pero el rango **crece con K** y revienta
  `_RANK_MAX=8` y el blob de 512 KB. Viable sólo con K chico y cap de rango duro + re-SVD periódico →
  converge a la conservadora.
- **Radical — residual FedEx-LoRA puro.** Mantener un término residual de alto rango
  `W_res = avg(B@A) − B_glob@A_glob` absorbido en una corrección frozen redistribuida. En el coordinator
  **no hay un `W` base por capa donde absorber** el residual (el adapter ES el entregable), así que esta
  variante exige cambiar el contrato de despliegue (shippear residual aparte). **No recomendada para
  v1** (complejidad sin pago medido).

**Restricciones duras respetadas:**
- **FedAvg SOLO sobre adapters LoRA, NUNCA params base** (autorizado 2026-06-16). La corrección sigue
  operando sólo sobre `ΔW` de adapters.
- **Ruido DP en el CLIENTE** (`sigma=0.01` ya en `federated_store`), **cero datos personales
  centralizados**: los adapters no deben permitir reconstruir datos personales → el ruido DP se aplica
  **antes** de submitir. La corrección de agregación **no** toca esto (sigue siendo cliente-side).
- **Sin `sqlite3.connect` directo:** `federated_store.py` HOY usa `sqlite3.connect` (líneas 125,135).
  **Deuda a migrar a `db_pool`** en la misma intervención (tarea de higiene, M0).

---

## 4. Decisiones y alternativas (con evidencia)

| Decisión | Conservadora | Moderada (recomendada v1) | Radical | Evidencia |
|---|---|---|---|---|
| **Inyección de hechos** | sólo RAG doc-level + base congelada (cero olvido) | RAG + LoRA por dominio con router | fusión continua de adapters en coordinator | Ovadia 2024; Biderman TMLR'24; Model Soups; **G3/E4 lo re-mide** |
| **Recuperación** | doc-level coseno-en-RAM (N chico) | doc-level + índice plano por bloques (N grande) | índice ANN (FAISS-CPU) | kNN-LM por-token **DESCARTADO** (`architecture.md §4`, memory-bound) |
| **Rango LoRA** | r=8 (= `_RANK_MAX`) | r=8, techo r≤16 | r adaptativo (ARA) | Biderman TMLR'24 (bajo rango = regularizador) |
| **Agregación federada** | `avg(B@A)` + SVD trunc r' | (= conservadora; es la correcta) | stacking K·r / residual FedEx | **exp003** (error 0.4%→66%); `architecture.md §5`; FedEx-LoRA arXiv:2410.09432 |
| **Fusión** | promedio de deltas | task-arithmetic intra-cuenca | TIES-Merging | Model Soups; TIES (arXiv:2306.01708) |
| **Router de bandas** | 3 bandas fijas LOCAL/MEDIA/GLOBAL | + pesos aprendidos por consulta | + R-VALOR como señal de relevancia (acotado) | HYDRA = router de sistema (restricción dura); R-VALOR brújula (`00_READINESS §5.2`) |

**Nota de coherencia:** para la **agregación federada** la "conservadora" y la "recomendada" coinciden
— porque la ingenua **no es una alternativa válida** (es un bug medido), no un punto del espectro
costo/calidad. El espectro real es: *cuánto rango retener* (truncar r' vs stacking K·r).

---

## 5. Plan de validación — Gate G3 / E4 (RAG vs LoRA vs kNN-LM) + corrección federada

### 5.1 E4 — política de inyección de hechos (CPU + Kaggle)
**Objetivo (de `00_READINESS §4 G3`):** fijar con datos propios la política de inyección. Diseño:
- **Conjuntos:** `BASE` = M hechos/tareas que el modelo base YA acierta (medir `base_acc₀`); `NUEVO` =
  N hechos que NO conoce (medir `new_acc₀ ≈ 0`). Recomendado **N = M = 50** para arranque (barato).
- **Brazos:** (1) **RAG doc-level** (índice §3.1, base congelada); (2) **LoRA r=8** entrenado en los N
  hechos (Kaggle GPU); (3) **kNN-LM por-token** (control negativo: medir su TTFT y confirmar el blow-up
  memory-bound previsto); (4) **full fine-tune** (control negativo de olvido máximo).
- **Métricas por brazo:** `Δnew = new_acc − new_acc₀` (aprendizaje); `Δbase = base_acc − base_acc₀`
  (**olvido**, ≤0); **TTFT/tok-s en el i3** (costo de inferencia, llama.cpp real).
- **Predicción honesta (a confirmar, no asumir):** RAG → `Δbase ≈ 0` (cero olvido por construcción),
  `Δnew` alto si la recuperación acierta; LoRA → `Δbase` pequeño negativo, `Δnew` medio; full-FT →
  `Δnew` alto pero `Δbase` muy negativo; kNN-LM → descartado por TTFT.
- **CPU vs Kaggle:** RAG, kNN-LM y la **medición de inferencia** corren en el **i3** (llama.cpp + numpy);
  el **entrenamiento** de LoRA/full-FT va a **Kaggle GPU** (`train_qlora_kaggle.py`). El i3 sólo **evalúa**
  los adapters resultantes.

### 5.2 Validación de la corrección federada (CPU puro, determinista)
- **Reusar exp003** como **test de regresión**: tras corregir Pass 3, el `rel_error` del agregador real
  debe **bajar a ~0** en el caso heterogéneo (hoy 0.10-0.66), y el **rango efectivo** del adapter global
  debe recuperar K·r (truncado a r') en vez de colapsar a r. Test que **falla con el bug y pasa con el
  fix** (regla 5 del método).
- **Test CLI real (regla 4):** `FederatedStore(":memory:")` → `add_contribution` de K adapters
  heterogéneos → `aggregate()` → reconstruir `ΔW_global` y comparar contra `mean_k(B_k@A_k)`: error
  Frobenius < umbral (p.ej. < `1e-3` salvo el truncado SVD declarado).
- **Sanity DP:** con `sigma=0.01` cliente-side, confirmar que el error del fix se mantiene acotado
  (`architecture.md §5`: el ingenuo se vuelve cuadrático bajo DP; el fix no).

### 5.3 DoD del subsistema (verificable end-to-end)
**Inyectar N hechos nuevos sin olvido medible:** con N=50, el brazo elegido (predicción: RAG para hechos
volátiles) sube `new_acc` de ~0 a ≥ umbral acordado **con `|Δbase| ≤ 1%`** (cero olvido para RAG por
construcción; ≤1% el techo tolerado para LoRA). **El 1% es un umbral PROPUESTO, no derivado de medición**
(confianza baja en el valor exacto): con N=50, 1% ≈ 0.5 ítems → el umbral cae **por debajo de la
resolución del test**, así que E4 debe calibrarlo contra el ruido de `base_acc` (subir N, o el umbral, si
el ruido de medición lo exige). Medido con CLI real sobre el GGUF Qwen2.5-Coder-3B Q4_K_M en el i3,
mostrando el output (no sólo pytest).

---

## 6. Lo que NO está probado / riesgos

1. **G3/E4 sin exp propio (confianza media).** La triple capa se apoya en **literatura** (Ovadia 2024,
   Biderman TMLR'24, Model Soups), NO en medición propia en Cognia. El gate §5.1 lo cierra; hasta
   entonces, "RAG ≥ fine-tune en hechos nuevos" es **ASUMIDO**.
2. **Constantes RAG sin medir en el i3 (confianza media).** El ~35% de TTFT doc-level es **citado**, no
   medido en el target; el umbral N de cruce coseno-en-RAM → índice por bloques es **estimado**. M0 los
   mide.
3. **Desajuste de contrato de adapter (riesgo P1).** `qlora_trainer` entrena `q,k,v,o`;
   `federated_store` sólo federa `k,v`. Federar adapters entrenados así **pierde `q,o`** silenciosamente.
   Decisión de M0 (§3.2): ampliar `_KEYS` o restringir el entrenamiento. **Sin resolver, la federación
   degrada los adapters.**
4. **Truncado SVD reintroduce error (confianza alta en que es controlado).** La corrección
   `avg(B@A)`+SVD-r' **no es loss-less** — pierde la energía espectral fuera de las r' componentes.
   Es **controlado y medible** (a diferencia del FedAvg ingenuo), pero si la heterogeneidad real exige
   rango K·r alto, r'≤16 puede ser insuficiente → medir energía retenida y, si hace falta, subir el cap
   de rango del blob.
5. **Fusión cross-cuenca puede degradar (confianza media).** "Sólo intra-cuenca" es heurística de Model
   Soups, no garantía. Fundir logos+rhetor podría caer fuera de cuenca. Mitigación: el **router de bandas
   los mantiene separados** por defecto; la fusión es opt-in y verificada (plano 04) antes de comprometer.
6. **R-VALOR como señal del router (confianza media, NO sobre-apoyar).** El arco downstream (149-155)
   cerró del lado RANKING: R-VALOR es **brújula decisional**, validada en toy/oráculo, **no confirmada en
   el lazo real**. Usarlo para ordenar/abstener en el router, **nunca** como única señal ni como
   acelerador.
7. **Deuda técnica en `federated_store.py`:** usa `sqlite3.connect` directo (viola la regla "sin
   `sqlite3.connect`") y entra a `aggregate()` automáticamente cada `AGGREGATE_EVERY_N=5`. La corrección
   debe migrar a `db_pool` **sin** romper el auto-trigger ni el peso semántico (`SEMANTIC_WEIGHT_ALPHA=0.3`).
8. **Adapter federado/fundido → motor de inferencia (omisión de integración, riesgo P1).** El formato
   del adapter federado es `npz` propio (`k_A,k_B,v_A,v_B`, **sólo proyecciones k,v**, rango ≤8), que
   **NO es el formato GGUF-LoRA que `llama.cpp` carga** (`LLAMA_LORA_PATH`). La banda **GLOBAL** (§3.3.2)
   y la fusión asumen que el adapter resultante es *ejecutable en el i3*, pero **falta el puente de
   conversión `npz → GGUF-LoRA`** y, por el desajuste de contrato (riesgo 3), el adapter federado sólo
   lleva k,v. **Sin ese puente la federación produce adapters que no se pueden correr.** La
   deliverabilidad de la banda GLOBAL queda **NO probada** (ningún test de §7.1 ejerce inferencia real
   con un adapter federado cargado). Tarea de M0.
9. **Calidad de recuperación del RAG en el i3 (no sólo banda).** El "cero olvido" del RAG es tautológico,
   pero su utilidad depende del **recall@k del retriever**. En modo bajo-recurso `cognia_embedding` cae a
   **n-gramas** (sin all-MiniLM) → el recall puede **degradarse fuerte** justo en el target i3, y esto
   **no está medido**. **Rama de fallback (documentada, no asumida):** si E4 muestra que el RAG en el i3
   (modo n-gramas) no alcanza `Δnew` útil, la política de hechos cae a **LoRA-para-hechos** dentro del
   presupuesto `|Δbase|` — al costo de perder el olvido explícito (RGPD) y de reentrenar en Kaggle.
   (Análogo a la rama de fallback de G1 en el backbone: tener un camino maduro previsto si el preferido
   no rinde.)
10. **SCALE = 0%.** Todo el diseño está validado en toy (exp003 numpy) + infra existente que corre en
    pequeño. La transferencia a un modelo 3B real con adapters reales entrenados en Kaggle es la mayor
    incógnita (confianza media).

---

## 7. DoD + dependencias

### 7.1 Definición de Hecho (verificable, no "parece andar")
- [ ] **`cognia_x/continual/rag_index.py`** corre: `add`/`search`/`build_context_block`/`remove` con
      persistencia vía `db_pool` (NO `sqlite3.connect`), reusando `cognia_embedding`. Test CLI: indexar
      50 docs, recuperar top-4 por coseno, mostrar output real.
- [ ] **Corrección de `coordinator/federated_store.py`** (Pass 3 → `avg(B@A)` + SVD trunc r'): exp003
      reusado como **test de regresión** baja `rel_error` heterogéneo de 0.10-0.66 a ~0 (salvo truncado
      declarado) y recupera rango efectivo; test falla con el bug, pasa con el fix.
- [ ] **`cognia_x/continual/band_router.py`** decide LOCAL/MEDIA/GLOBAL por consulta, montado sobre el
      routing de dominios (`DOMAIN_EXPERT_CLUSTERS`). Test CLI: 3 consultas de bandas distintas → banda
      correcta.
- [ ] **`cognia_x/continual/adapter_fusion.py`**: fusión intra-cuenca por `avg(B@A)`/task-arithmetic,
      operando sobre deltas reconstruidas (nunca factores). Test: fundir 2 adapters `techne` y verificar
      que la delta fundida = promedio de deltas reconstruidas.
- [ ] **Puente adapter federado → inferencia (riesgo 8):** convertir un `npz` federado/fundido a un LoRA
      cargable por `llama.cpp` (`LLAMA_LORA_PATH`) y mostrar **generación real en el i3** con la banda
      GLOBAL activa. Sin esto la federación NO es ejecutable end-to-end (hoy el formato `npz` k,v no es
      GGUF-LoRA).
- [ ] **Gate G3/E4 corrido** (§5.1): tabla con `Δnew`, `Δbase`, TTFT por brazo (RAG/LoRA/kNN/full-FT);
      política de inyección **fijada por datos**.
- [ ] **DoD de negocio:** N=50 hechos nuevos inyectados, `new_acc` ↑ a umbral acordado con `|Δbase|≤1%`,
      medido con CLI real sobre Qwen2.5-Coder-3B Q4_K_M en el i3.
- [ ] **Decisión de contrato de adapter** (q,k,v,o vs k,v) tomada y documentada (riesgo 3).
- [ ] Suite de tests rápida verde: `.\venv312\Scripts\python.exe -m pytest tests/ --ignore=tests/test_e2e_inference.py -q` (reportar N passed/M failed real).

### 7.2 Dependencias
- **Bloqueantes:** plano 04 (`FactVerifier` para filtrar docs antes de inyectar), plano 02 (backbone que
  consume el bloque RAG y carga adapters), plano 03 (entrenamiento QLoRA → produce los adapters).
- **Infra que ya corre (no bloqueante, reusar):** `cognia_v3/memory/cognia_embedding.py`,
  `cognia_v3/memory/conversation_memory.py`, `storage/db_pool.py`,
  `cognia_v3/training/qlora_trainer.py` + `cognia_v3/training/kaggle/train_qlora_kaggle.py`,
  `shattering/model_constants.py`, `coordinator/federated_store.py`.
- **Hardware:** RAG/fusión/agregación/medición de inferencia → **i3 (CPU)**; entrenamiento de adapters →
  **Kaggle GPU** (cuenta anthuananthuan). El i3 **no** entrena QLoRA.
- **Restricciones duras aplicables:** FedAvg sólo sobre adapters LoRA; ruido DP en cliente; cero datos
  personales centralizados; HYDRA = router de sistema (no atención de red); sin `sqlite3.connect`
  directo; sin constantes de modelo hardcodeadas (usar `model_constants.py`); nada de mocks (cada
  subsistema cierra con prueba CLI real).
