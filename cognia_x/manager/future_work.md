# future_work.md — direcciones futuras de Cognia-X

> Cola de ideas e investigaciones. No es compromiso; es memoria de lo que vale la pena explorar.

## Experimentos cercanos (E1-E5 del ciclo-1, priorizados por impacto/coste)
- ✅ **exp001** coste de mezcla; ✅ **exp002** capacidad de recall (corridos).
- **exp003 = E3** (P0, **siguiente**) — demostrar que el FedAvg ingenuo de LoRA es inexacto:
  ‖avg(B@A) − avg(B)·avg(A)‖_F > 0 y crece con la heterogeneidad. numpy puro, 100% CPU, definitivo.
  Valida H-CF-2; impacto directo en `coordinator/federated_store.py` de Cognia.
- **exp004 = E1** (P0) — roofline CPU: tok/s de un GGUF en Q8/Q4/Q2 variando hilos 1-4; confirmar
  bandwidth-bound (aplanamiento por hilos <30%, tok/s ∝ 1/bytes-por-peso). Requiere llama.cpp.
- **exp005 = E2** (P1) — SWA vs atención full: tok/s(L) 256→32K + RAM de KV-cache + ΔPPL. Valida
  H-SEQ-3. Requiere un GGUF con sliding-window (Gemma-3 / Mistral-SWA).
- **E4** — RAG document-level vs LoRA vs kNN-LM/token para 100 hechos nuevos (valida H-CF-3).
- **E5** — peso real de embedding+lm_head en el GGUF y ahorro de cuantizarlos (valida H-REP-4).

## Direcciones de arquitectura (a confirmar con evidencia)
- Mezcla de secuencia híbrida (mayoría lineal + pocas capas de atención para recall exacto).
- Representación sin tabla de embeddings gigante (byte-level / parches por entropía).
- Aprendizaje continuo por fusión de adapters (model merging) con control de olvido.
- Cómputo entero/ternario como primitiva base en vez de matmul densa float.

## Metodología
- Automatizar el "evidence ledger" (script que valida que cada hipótesis tenga predicción +
  evidencia + experimento antes de marcarla apoyada).
- Suite de micro-benchmarks reproducibles como gate de regresión de eficiencia.

> Se ampliará con los `open_questions` del ciclo-1 (workflow).

## [2026-06-19] Frontier siguiente: Nivel 2 — "INVESTIGAR por sí misma" (tras CYCLE 8/10)
El aprendizaje continuo Nivel 1 está validado (CYCLE 8: aprende sin olvidar, gate por-dominio + replay;
CYCLE 10: loop como proceso sobre una secuencia). Lo que falta para "investigar sola":
- **Nivel 2 — verificar-antes-de-aprender** (anti-colapso): la IA propone/genera; solo aprende lo
  que pasa un verificador chequeable contra la realidad (código→sandbox+oracle, `cognia_v3/core/
  sandbox_tester.py`; texto→redundancia en ≥2 fuentes reales + filtro de degeneración KL/gzip).
  Ledger de procedencia (origin∈{real,syn}, generación g≤1, cuota ≤15% sintético). Examinador
  SIEMPRE 100% real (invariante). exp009_collapse_guard: 2 brazos (colapso vs guard) — ver workflow.
- **Robustez del gate:** multi-seed (calibrar k·σ, eps), held-out rotativo + committee (anti-Goodhart),
  canarios de sub-distribución (acentos/dígitos), snapshot del optimizer para loops largos.
- **Mecanismos anti-olvido restantes:** Fisher/EWC-light (leer exp_avg_sq de Adam) y adapters LoRA
  con tronco congelado (olvido imposible por construcción). Congelar-tronco ya da -25% (CYCLE 9).
- **Resolver el learned=False a base-fuerte:** aprender una obra del mismo idioma no transfiere
  cross-book; probar dominios genuinamente nuevos (otro idioma, código) o examinador intra-dominio.

## [2026-06-19] Tras PILAR 5 (Razonamiento, CYCLE 12-17): el frontier real
El mecanismo de meta-razonamiento (probar cadenas, quedarse con la que el verificador real aprueba,
elegir por tipo/texto, componer, bajo ruido/OOD, en escala graduada) está validado SOBRE SOLVERS
sintéticos. Lo que falta para que sea razonamiento "de verdad":
- **Envolver el LM real (no solvers de juguete).** Hoy las "cadenas" son procedimientos hand-coded.
  El paso honesto: que las cadenas sean prompts/estrategias del char-LM (o del backend GGUF) sobre
  una tarea que el modelo SÍ pueda intentar, y que el router aprenda cuál funciona. El char-LM (779k,
  byte-level) NO hace aritmética de enunciados → o se sube de escala el modelo, o se elige una tarea
  donde un modelo chico tenga señal (p.ej. transformaciones de texto verificables).
- **Verificador real, no oráculo perfecto.** El "preguntar al usuario" usa hoy el ground-truth como
  oráculo. Reemplazar por (a) verificadores chequeables (código→sandbox, hechos→≥2 fuentes) y (b) un
  usuario simulado ruidoso/caro real (CYCLE 13 ya modeló el ruido; falta el costo asimétrico).
- **Paráfrasis natural, no plantillas.** CYCLE 17 usó plantillas+sinónimos; el NB bag-of-words es
  frágil a paráfrasis genuina. Encoder aprendido (no keyword) o el propio LM como clasificador de tipo.
- **Componer cadenas de largo >2 y descubrir sub-metas** (planificación), no solo secuencias fijas.

## [2026-06-19] CYCLE 24 — H-CEIL-3 REFUTADA (kernel Taylor + mimetic init no levantan el plateau)
exp011 (d=24, n_heads=1, n_pairs=16, seed0, steps=3000 step-parity) **refutó** [[H-CEIL-3]]: ni la
FORMA del kernel (Taylor 2do orden) ni la INIT mimética suben el recall sobre el baseline ELU+1.
Números: elu_base=**0.173**, taylor=**0.160** (Δ−0.013, por debajo), elu_matched(dim 336)=0.181 (+0.008
ruido), mimetic=0.183 (+0.0098, < umbral 0.02). taylor_vs_matched=−0.021 (Taylor bajo su size-matched →
el control de TAMAÑO aísla forma de tamaño: no falta estado). Junto con exp010 (ancho), el plateau
~0.18 a d=24 es robusto a **ancho, forma e init** → el cuello NO es del feature-map. Decisión: **D-CEIL-3**
(descartar forma+init a esta escala; redirigir a profundidad/escala/optimizador o atención del híbrido).

## [2026-06-19] Siguiente experimento — H-CEIL-4: profundidad/escala/optimizador o atención (tras CYCLE 24)
La triple refutación (ancho exp010, forma+init exp011) afila la pregunta → **[[H-CEIL-4]]** (`abierta`):
el cuello del recall lineal entrenado a d=24 es de **profundidad/escala/optimizador** o requiere la
**capa de atención** del híbrido (un mezclador de estado fijo a d=24 no llega). Experimentos propuestos:
- **exp012 (propuesto)** — a `n_pairs=16`, seed0, steps step-parity: barrer (a) **profundidad** (4→8→12
  capas lineales), (b) **d** (24→48→96, donde exp009 vio al híbrido separar a d=48), (c) **optimizador/LR**
  (Okpekpe & Orvieto arXiv:2508.19029: la brecha es de optimización — LR alto, schedule). Predicción:
  alguno cruza ~0.18 donde el lineal puro a d=24 satura. **Refutado si** ninguno.
- **exp013 (propuesto)** — el **híbrido mínimo**: lineal puro a d=24 (0.173) vs lineal+1 capa de atención.
  Si la atención cruza el plateau donde el lineal no puede, confirma D-CEIL-1 end-to-end a esta escala
  (la atención es necesaria para el recall a carga alta; el estado fijo solo no basta).
- 100% CPU, modelos tiny, reproducible — mismo molde acotado que exp009/exp010/exp011. Cuidado de coste:
  el barrido de d/profundidad y la atención son baratos; NO repetir el kernel Taylor (dim 325, ~5× lento).

## [2026-06-19] CYCLE 25 — la línea H-CEIL CONVERGE: el techo de recall es ESTRUCTURAL
exp012 (lineal PURO, d≤48) **refutó** la cláusula lineal de [[H-CEIL-4]]: ni profundidad (L8=0.181), ni
escala-d (d48=0.183), ni optimizador (LR 3×=0.176) suben el lineal puro sobre ~0.18. Junto con exp010
(ancho) y exp011 (forma+init), el plateau es robusto a **SEIS levers no-atención** → el techo del
mezclador de estado fijo es **ESTRUCTURAL** (techo `real`: pigeonhole sobre el estado, exp002). H-CEIL-4
**mixta**: la rama "requiere atención" gana por eliminación + CYCLE 6. **Decisión D-CEIL-4** (cerrar la
línea de tuning del lineal; el remedio es la atención del híbrido, D-CEIL-1). Backlog de asumidos → 0.

### Lo que cierra y lo que queda de la línea de recall
- **CERRADO:** afinar el mezclador lineal de estado fijo para recall (6 levers refutados). El recall a
  carga alta = atención (híbrido). El eje COSTE↔RECALL del híbrido está medido (exp005 + CYCLE 6).
- **Confirmación opcional (exp013):** lineal puro d=24 (0.173) vs lineal+≥2 capas de atención a d=24
  como control positivo end-to-end a ESTA escala (CYCLE 6 lo mostró a otra; baratísimo, sin Taylor).
  No es bloqueante — la conclusión estructural ya está sólida.

### Pivote: el siguiente frente por PRIORIDAD (la directiva v3 §1)
Cerrado el eje de eficiencia/recall (prioridad #1), el frente abierto de mayor prioridad es **#2
Aprendizaje continuo → F-LEARN-2 (Nivel 2: verificar-antes-de-aprender, anti-colapso)**:
- La IA propone/genera; SOLO aprende lo que pasa un **verificador chequeable contra la realidad**
  (código→sandbox+oráculo; texto→redundancia ≥2 fuentes + filtro de degeneración KL/gzip). Examinador
  100% real (invariante). Ledger de procedencia (origin∈{real,syn}, generación g, cuota ≤15% sintético).
- Nivel 1 ya validado (CYCLE 8/10: aprende sin olvido con gate por-dominio + replay + congelar-tronco).
  Nivel 2 es el salto a "investigar/aprender sola sin colapsar". exp candidato: collapse_guard (2 brazos:
  colapso vs guard) — ya esbozado en un future_work previo.
- Alternativa de menor prioridad pero barata: F-REASON-REAL (envolver el LM real en el router de
  meta-razonamiento) — el pilar 5 está validado solo sobre solvers sintéticos.

## [2026-06-20] CYCLE 26 — control positivo CONFIRMADO: línea de recall CERRADA
exp013: atención pura = **0.882** cruza el plateau ~0.18 (6 levers lineales refutados) a la MISMA escala →
el remedio del recall es ARQUITECTÓNICO, confirmado directamente (no solo por eliminación). D-CEIL-5.
- **Matiz (H-HYB-1, abierta, menor):** el híbrido 50/50 quedó under-trained a 3000 steps (ASCENDIENTE, no
  plateau). El híbrido CAN (CYCLE 6: 0.99) pero optimiza más lento a d chico. Follow-up barato: híbrido a
  d=24 con más steps / más proporción de atención (¿cierra la brecha con la atención pura?).
- **Línea H-CEIL (CYCLE 22-26): CERRADA.** Techo del estado fijo = estructural (refutación de 6 levers +
  control positivo). El siguiente frente MAYOR por prioridad (directiva v3 §1) sigue siendo **#2 F-LEARN-2**
  (aprendizaje continuo Nivel 2: verificar-antes-de-aprender, anti-colapso).

## [2026-06-20] CYCLE 27 — H-HYB-1 REFUTADA + corrección del "línea cerrada" de CYCLE 26
exp014 (híbrido a d=24, 10000 steps): hibrido_h4=0.186 (PLATEÓ, no under-training) vs atencion pura=0.948.
**H-HYB-1 refutada**: el híbrido interleaved a d=24 NO recupera recall — las capas lineales bottleneckean.
Corrige mi diagnóstico de under-training de CYCLE 26 (autocorrección honesta). ACOTA H-MEZ-4 (d-dependiente).
- **Corrección del cierre:** la conclusión central se mantiene (atención=remedio, lineal=estructural), PERO
  la línea de recall NO está tan "cerrada": **[[H-HYB-2]]** queda abierta — ¿por qué el híbrido falla a d=24
  pero funciona a d=64 (CYCLE 6)? Suspectos: d (capacidad lineal), arreglo (atención-primero), ratio.
- **Siguiente experimento (exp015 propuesto, barato):** barrer d (24→48→64) y arreglo (atención-primero vs
  lineal-primero) del híbrido a n_pairs=16 → encontrar el umbral de d donde el híbrido recupera recall, o
  mostrar que el arreglo lineal-primero es el cuello. Cierra H-HYB-2 y completa de verdad la línea de recall.
- El pivote a #2 F-LEARN-2 sigue disponible, pero H-HYB-2 es el cabo honesto que falta de la línea de recall.

## [2026-06-20] CYCLE 28 — H-HYB-2 REFUTADA (no es d); sub-línea del híbrido PAUSADA
exp015 (barrido de d del híbrido a np=16): d24=0.189, d48=0.253, d64=0.190 — NO recupera a ningún d, no
monótono. **H-HYB-2 refutada**: el cuello del híbrido es ARREGLO (lineal-primero) y/o CARGA (np), no d
(reconcilia con CYCLE 6 a np=8). Caveat FUERTE a D-007: el híbrido naive es frágil para recall; la atención
pura es el remedio robusto. Genera **[[H-HYB-3]]** (arreglo/carga).
- **PAUSA (D-HYB-2):** la sub-línea H-HYB-1→2→3 está en rendimientos decrecientes. Consolido la línea de
  recall (sólida: lineal=estructural + atención=remedio + híbrido-frágil documentado). H-HYB-3 queda para
  retomar con orientación del dueño.
- **Frente mayor abierto (prioridad #2):** **F-LEARN-2** — aprendizaje continuo Nivel 2 (verificar-antes-de-
  aprender, anti-colapso). Es el siguiente salto sustantivo del proyecto; se beneficia de orientación sobre
  el enfoque (tarea/verificador) antes de invertir varios ciclos.
- Si se retoma el híbrido (H-HYB-3): exp016 = híbrido atención-primero vs lineal-primero a d=48, np=16
  (¿es el arreglo?) + un punto a np=8 (¿es la carga?). Barato, decisivo.

## [2026-06-20] CYCLE 29 — F-LEARN-2 abierto: AUTO-MEJORA VERIFICADA funciona (H-LEARN-1 apoyada)
exp016 (suma byte-level, n=4): verified (auto-generaciones verificado-correctas) es el ÚNICO brazo con
ganancia neta sobre base (+0.110) en los 4 seeds; gana al control decisivo random_matched (t-pareado=3.22,
p<0.05) → la CORRECCIÓN del oráculo es el motor (STaR), no el volumen ni el filtrado. Avanza CYCLE 11
(prevención→habilitación). Verificado adversarialmente (4 lentes) + n=4.
- **Siguiente (F-LEARN-2 continúa):** (a) tarea verificable MÁS DURA / mayor escala (¿el efecto crece o el
  modelo satura?); (b) verificador RUIDOSO/PARCIAL (oráculo imperfecto) — ¿hasta qué ruido del verificador
  sobrevive la auto-mejora? (puente hacia tareas no-aritméticas); (c) verificador chequeable real (código→
  sandbox `cognia_v3/core/sandbox_tester.py`; hechos→redundancia ≥2 fuentes) en vez del oráculo aritmético;
  (d) cuota de sintético + ledger de procedencia (origin/generación) para loops largos sin deriva.
- **Cabos previos abiertos (menores):** H-HYB-3 (arreglo/carga del híbrido, pausado). 

## [2026-06-20] CYCLE 30 — H-LEARN-2 APOYADA: la auto-mejora tolera ruido del verificador hasta ε*≈0.15
exp017 (dosis-respuesta, volumen FIJO): net-sobre-base de verified decae monótono con el FP-rate del
verificador ({0:+0.116 … 1:−0.001}); ε*=0.15. Confirma causalmente que el verificador es el motor (D-LEARN-2:
su calidad es lever de 1ra clase). Robusto a la métrica; ε=0 reproduce exp016.
- **Siguiente (F-LEARN-2 continúa):** reemplazar el oráculo aritmético por un **verificador chequeable REAL**:
  (a) código → sandbox+tests (`cognia_v3/core/sandbox_tester.py` como referencia, reimplementar cognia_x-native);
  (b) hechos → redundancia ≥2 fuentes. ¿La auto-mejora sobrevive con un verificador real (cuyo FP-rate efectivo
  hay que medir contra ε*≈0.15)? + cuota de sintético + ledger de procedencia (origin/generación) para loops largos.
- Cabos previos: H-HYB-3 (arreglo/carga del híbrido, pausado); F-REASON-REAL (envolver el LM real en el router).

## [2026-06-20] CYCLE 31 — H-LEARN-3 (núcleo) APOYADA: auto-mejora con VERIFICADOR REAL (sandbox)
exp018 (síntesis de expresiones, sandbox ejecutor, M=90, n=3): verified +0.230 sobre base (los 3 seeds), >>
naive_all (que CAE) por >2σ -> la auto-mejora generaliza del oráculo a un verificador chequeable REAL.
Reward-hack NO observado (loop no-RL no descubrió el echo). D-LEARN-3.
- **F-LEARN-2 arco fuerte:** H-LEARN-1 (funciona) + H-LEARN-2 (robustez al ruido, ε*) + H-LEARN-3 (verificador real).
- **Siguiente:** (a) combinar H-LEARN-2+3: ruido en el verificador REAL (tests parciales) -> ¿emerge el hack
  con un loop más agresivo (RL-lite/temperatura alta)? (b) cuota de sintético + ledger de procedencia para
  loops largos; (c) verificador de CÓDIGO real (subprocess+tests con timeout).
- Cabos previos: H-HYB-3 (híbrido, pausado); F-REASON-REAL (LM real en el router).
