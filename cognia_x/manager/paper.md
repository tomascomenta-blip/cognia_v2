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
