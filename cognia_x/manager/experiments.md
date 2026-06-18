# experiments.md — fichas de experimentos de Cognia-X

> Cada experimento: objetivo, hipótesis ligada, método, cómo correr, resultado real,
> amenazas a la validez, conclusión. Reproducible (semilla + entorno declarado).

---

## exp001 — Escalado del coste de mezcla de secuencia en CPU  ✅ CORRIDO

- **Estado:** completo (2026-06-17).
- **Hipótesis:** [[H-MEZ-1]] — la atención full O(L²) es el cuello de botella de escalado en
  CPU frente a un mezclador de tiempo lineal O(L).
- **Pregunta del meta-prompt:** "¿Qué parte consume más recursos?"
- **Código:** `cognia_x/experiments/exp001_sequence_mixing_scaling/run.py`
- **Cómo correr:**
  `.\venv312\Scripts\python.exe cognia_x\experiments\exp001_sequence_mixing_scaling\run.py`
- **Método:** batch=1, d=64, float32, L ∈ {128…4096}, reps=3 + warmup. Tres mezcladores:
  (A) atención full softmax; (B) atención lineal (feature map elu+1, estado KV d×d); (C) SSM
  diagonal con scan en bucle Python. Tiempo = wall-clock medio. Memoria = tamaño analítico del
  tensor intermedio dominante (numpy no es fiable bajo `tracemalloc`).
- **Métrica:** ms/forward y MB del intermedio dominante; speedup y ratio de memoria.

### Resultado (ver tabla completa en `research_log.md` y `results/results.md`)
- Cruce en tiempo: **L=128** (lineal ya gana). Speedup lineal/full: 3.5× (L=128) → **70.3×** (L=4096).
- Memoria: full crece O(L²) (0.06→64 MB); lineal constante (0.0156 MB) → 4096× menos a L=4096.
- SSM-loop (O(L) teórico) **pierde** contra lineal vectorizado → factor constante domina en CPU.

### Amenazas a la validez (honestidad)
- Mide **coste**, no **calidad**: no dice nada de exactitud/recall/ICL. ⚠️ central.
- (A) y (B) son versiones **globales no-causales**; en decodificación autoregresiva causal el
  perfil cambia (KV-cache para A, estado recurrente para B/C). Pendiente exp003.
- numpy usa BLAS multihilo; los tiempos absolutos dependen de la máquina, pero las **tendencias**
  (cuadrático vs lineal) son robustas a la plataforma.
- d=64 fijo; el término O(L·d²) de la atención lineal podría importar con d grande. Pendiente barrido en d.

### Conclusión
H-MEZ-1 **apoyada para coste** (confianza alta). No habilita aún la decisión de reemplazo: falta
exp002 (calidad). El hallazgo accionable inmediato: cualquier arquitectura CPU-first debe evitar
el término O(L²) en el camino de mezcla por defecto.

---

## exp002 — Calidad de mezcladores: recall/copia controlada  ⏳ DISEÑO

- **Estado:** diseñado, pendiente de correr.
- **Hipótesis:** los mezcladores sub-cuadráticos pierden exactitud en recall asociativo/copia
  exacta frente a la atención full (el contrapeso a exp001).
- **Método propuesto:** tarea sintética tipo *induction head* / copia de secuencia y *associative
  recall* (clave→valor) con longitudes crecientes; comparar accuracy de full vs lineal vs SSM
  (entrenando heads pequeños en CPU con torch-cpu, o evaluando capacidad de copia analíticamente).
- **Métrica:** accuracy de recuperación vs L; punto donde el sub-cuadrático se degrada.
- **Por qué importa:** decide si "reemplazar atención" es viable o si hace falta un **híbrido**
  (mayoría de capas lineales + pocas de atención full para recall exacto, à la Jamba/Griffin).

> Fichas adicionales del ciclo-1 (workflow) se añadirán aquí tras la síntesis.
