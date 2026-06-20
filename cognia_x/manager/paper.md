# Cognia-X — Paper científico vivo

> Documento vivo. Se añade, no se borra. Registra preguntas, hipótesis, evidencia, resultados,
> errores, conclusiones y próximos pasos.

## Título de trabajo
**Rediseño de una IA desde primeros principios para CPU: ¿qué componentes sobreviven a la
evidencia?**

## Abstract (v0.1, 2026-06-17)
Cognia-X investiga, componente por componente, qué piezas de las arquitecturas modernas de IA
están justificadas por evidencia bajo una restricción dura: **eficiencia en CPU de portátil, sin
GPU**. No se acepta ninguna arquitectura por autoridad. Cada componente (representación de
entrada, mezcla de secuencia, mecanismo de cómputo, aprendizaje continuo, inspiración biológica,
auto-mejora) se somete a hipótesis falsables y experimentos reproducibles. Primer resultado
empírico (exp001): el coste de la atención full escala cuadrático en tiempo y memoria en CPU,
mientras un mezclador de tiempo lineal lo domina hasta 70× a L=4096 — pero esto mide coste, no
calidad, y por tanto **no** justifica aún reemplazar la atención.

## 1. Pregunta raíz
Si rediseñáramos una IA desde cero con el conocimiento moderno, ¿qué construiríamos, y por qué,
con evidencia? Prioridad #1: eficiencia computacional. Objetivo de hardware: CPU.

## 2. Método
Ciclo de investigación de 9 pasos (ver `00_protocolo_investigacion.md` §2): investigar →
hipótesis falsable → evidencia a favor/en contra → refutación adversarial → experimento
CPU-feasible → ejecución reproducible → análisis → conclusión documentada. Cada afirmación lleva
confianza y fuentes.

## 3. Resultados
### 3.1 exp001 — coste de mezcla de secuencia (2026-06-17)
La atención full entra en régimen cuadrático ~L≥512 (tiempo y memoria). Un mezclador lineal es
3.5×→70.3× más rápido (L 128→4096) con memoria intermedia constante (4096× menos a L=4096). Un
SSM O(L) implementado con bucle Python pierde contra el lineal vectorizado: la asíntota no basta
en CPU. **Alcance:** mide coste, no calidad. → `experiments.md` exp001, `hypotheses.md` H-MEZ-1/2.

### 3.2 exp002 — capacidad de recall asociativo (2026-06-17)
Contrapeso a exp001. Sonda training-free: almacenar N pares clave→valor y medir recall. La
atención full mantiene accuracy ~1.0 en todo N; la atención lineal se degrada con capacidad
**d²/32** (32→32, 64→128, 128→512), es decir, su recall escala con el **tamaño del estado**, no
con d. → trade-off **coste↔capacidad** medido. → `experiments.md` exp002, `hypotheses.md` H-MEZ-3.

### 3.3 Síntesis del ciclo-1 (workflow de 13 agentes, 2026-06-17)
Barrido de 6 dimensiones con evidencia web + verificación adversarial (24 hipótesis, 13 holds=true /
11 holds=false). **Tesis:** una IA CPU-first se diseña para minimizar **bytes movidos por token**
(decode memory-bandwidth-bound), no FLOPs. De ahí: backbone **híbrido** estado-fijo + atención
sliding-window (3:1-4:1, Gemma-3 verificado); representación **BPE vocab moderado parity-aware**
(no byte-puro ni BLT a 1-3B); **Q4 base + ternario como apuesta** (BitNet NO demostrado superior a
Q4 de igual calidad); aprendizaje continuo **RAG document-level + LoRA + fusión intra-cuenca**
(kNN-LM/token descartado); agregación federada **avg(B@A)/FedEx-LoRA** (FedAvg ingenuo es
INEXACTO — bug real en `federated_store.py` de Cognia); biología = tomar **principios**
(esparsidad, memoria=cómputo) NO **implementación** (SNN/FF/predictive-coding cuestan más);
auto-mejora **solo con evaluador verificable + gate + rollback**. Confianza **alta en direcciones,
media en constantes** (no medidas en el CPU objetivo → E1-E5). Detalle: `architecture.md`,
`hypotheses.md`, `decision_log.md`.

**Cross-validación:** mi exp002 (recall ∝ d², empírico) reproduce el resultado teórico de la
literatura (Jelassi "Repeat After Me" ICML'24) que el workflow recuperó por una vía independiente.

## 4. Errores / fracasos registrados
- (ninguno aún; se registrarán con su lección — un fracaso es información, no abandono).

## 5. Conclusiones provisionales
- C1: el camino de mezcla por defecto de una arquitectura CPU-first **no** debe contener un
  término O(L²) (apoyado por exp001, confianza alta para coste).
- C2: las decisiones de reemplazo de componentes exigen evidencia de **calidad**, no solo de
  coste (principio metodológico reforzado por el alcance de exp001).
- C3: existe un **trade-off coste↔capacidad** medido en la mezcla de secuencia (exp001+exp002):
  el lineal es barato pero su recall está acotado por el tamaño de su estado (d²); la atención
  full es cara pero con recall ~ilimitado en N. Conclusión de diseño provisional: **ni reemplazar
  ni mantener — combinar** (híbrido). No se acepta por autoridad: se probará (H-MEZ-4).

## 6. Próximos pasos
- ✅ exp002 (calidad/recall) corrido — confirma el trade-off.
- exp003: validar A-001 (CPU memory-bandwidth-bound) + diseñar el experimento del híbrido (H-MEZ-4).
- Integrar síntesis del ciclo-1 → `architecture.md`.
- Derivar el primer boceto de arquitectura CPU-first defendible por evidencia.

---

## 7. Hallazgos CYCLE 22-29 (recall + aprendizaje continuo Nivel 2)

### 7.1 Techo de recall del mezclador de estado fijo — ESTRUCTURAL (CYCLE 22-28)
La línea H-CEIL convergió: el plateau de recall (~0.18) del mezclador lineal entrenado a d≤48 es robusto a
**6 levers no-atención** (ancho exp010; forma del kernel Taylor + mimetic init exp011; profundidad +
escala-d + optimizador exp012) Y la atención pura lo cruza (exp013: 0.95) donde el lineal no. → el techo es
**estructural** (pigeonhole sobre el estado fijo); el remedio del recall a carga alta es **arquitectónico**
(la atención del híbrido), no de tuning (D-CEIL-1/4). Matiz honesto: el híbrido naive es FRÁGIL — a d chico
las capas lineales bottleneckean (exp014/015, H-HYB), no recupera robustamente (caveat a D-007). Incluyó una
autocorrección de diagnóstico (CYCLE 26 'under-training' → CYCLE 27 refutó: era estructural).

### 7.2 Auto-mejora verificada (STaR) — el verificador es el motor (CYCLE 29, F-LEARN-2)
**H-LEARN-1 (apoyada):** en una tarea VERIFICABLE (suma byte-level, oráculo chequeable), entrenar SOLO con
las auto-generaciones VERIFICADO-CORRECTAS produce auto-mejora; el control decisivo (random_matched: mismo
N_keep + mismos pasos, subconjunto ALEATORIO) aísla que el motor es la **señal de corrección** del oráculo,
no el volumen ni el filtrado-per-se. exp016 (d=64, test held-out disjunto, n=4): verified ÚNICO brazo con
ganancia neta sobre base (+0.110) en los 4 seeds; gap verified−random media +0.126 (t-pareado=3.22, p<0.05;
win 15/16). **Avanza CYCLE 11** (de PREVENIR colapso a HABILITAR auto-mejora en tarea verificable). Caveats:
efecto modesto (+0.11), escala tiny, requiere oráculo chequeable. Verificado adversarialmente (workflow 4 lentes).

### 7.3 Método (meta)
Ambas líneas pasaron por el Investigation Engine (compuertas DoD, ledger, ceiling, verify_no_loss) y por
verificación adversarial multi-agente (workflows). El proceso CORRIGIÓ sobre-afirmaciones del propio agente
(narrativa falsa de 'colapso', estadística inflada, un margen perverso) — la evidencia decide, no la intuición.

### 7.4 Robustez de la auto-mejora al ruido del verificador (CYCLE 30, H-LEARN-2)
**H-LEARN-2 (apoyada):** la auto-mejora verificada DECAE al subir el ruido de falso-positivo del verificador (acepta incorrectas). exp017 (dosis-respuesta, volumen+pasos FIJOS → sólo varía la contaminación, n=3): net-sobre-base de verified por ε(FP-rate) = {0:+0.116, 0.15:+0.074, 0.3:+0.056, 0.5:+0.001, 1:−0.001}, decaimiento monótono (caída ε0→ε1=0.117 > 2σ), sobrevive hasta ε*≈0.15, colapsa a naive por ε≥0.5. Como el volumen es fijo, esto CONFIRMA CAUSALMENTE que el verificador (su corrección) es el motor de H-LEARN-1 (degradar la corrección degrada la mejora, graduado) — cierra una objeción a H-LEARN-1. Robusto a la métrica (final-round y media-rondas coinciden); ε=0 reproduce exp016. Implicación (D-LEARN-2): un verificador real necesita FP-rate < ε* para habilitar auto-mejora — la CALIDAD del verificador es un lever de primera clase.

### 7.5 Auto-mejora con un VERIFICADOR CHEQUEABLE REAL (CYCLE 31, H-LEARN-3)
**H-LEARN-3 (núcleo, apoyada):** la auto-mejora verificada generaliza de un oráculo de forma cerrada
(exp016/017) a un VERIFICADOR CHEQUEABLE REAL — un sandbox que EJECUTA la expresión generada por el modelo
(intérprete propio, allowlist, sin eval(); regla #9). exp018 (síntesis de expresiones "N="->"a op b", test
held-out DISJUNTO M=90, n=3): verified sube real_acc +0.230 sobre base (0.437) en los 3 seeds (strong 0.667,
weak 0.672) y supera a naive_all (0.358, que CAE = colapso sin filtro) por >2σ; robusto a la métrica. El
verificador es el motor incluso cuando EJECUTA la salida (no solo cuando conoce la respuesta). Sub-claim
(reward-hacking de un verificador débil, Amodei 2016): NO observado a esta escala (verified_weak ~= strong,
degenerate=0) — el loop no-RL no descubrió el echo; honesto. Con H-LEARN-1/2, F-LEARN-2 cierra un arco: el
VERIFICADOR (existencia, FP-rate < ε*, ejecución real) es el lever central de la auto-mejora segura.

### 7.6 El reward-hack NO emerge en STaR-imitación (CYCLE 32, H-LEARN-4)
**H-LEARN-4 (refutada con insight):** un verificador real DÉBIL NO se reward-hackea en un loop STaR de
IMITACIÓN, aun SEMBRANDO el atajo (echo del target) en el repertorio y con temperatura alta. exp019 (n=3):
weak degenerate(final)=0.085 ≈ strong=0.004 (el echo no domina, sin snowball). RAZÓN (refina Amodei 2016): la
imitación COPIA las auto-generaciones aceptadas (mayormente honestas), no MAXIMIZA la aceptación como RL → no
caza el atajo más barato; el reward-hack es patología de RL-maximización, no inherente a un verificador débil
bajo imitación. Matiz: el verificador FUERTE igual es muy superior (real_acc 0.745 vs weak 0.474, +0.27;
degenerate menor) y naive_all (sin filtro) degrada → la fuerza del verificador importa para la competencia.
Con H-LEARN-1/2/3, F-LEARN-2 cierra un arco maduro: el VERIFICADOR es el lever central de la auto-mejora segura.
