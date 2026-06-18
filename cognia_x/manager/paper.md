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

### 3.2 Síntesis del ciclo-1 (en curso)
*Pendiente: integración de la investigación multi-dimensión (embeddings, atención, cuello de
botella CPU, aprendizaje continuo, inspiración biológica, auto-mejora) con verificación
adversarial. Se añadirá aquí al cerrar el workflow.*

## 4. Errores / fracasos registrados
- (ninguno aún; se registrarán con su lección — un fracaso es información, no abandono).

## 5. Conclusiones provisionales
- C1: el camino de mezcla por defecto de una arquitectura CPU-first **no** debe contener un
  término O(L²) (apoyado por exp001, confianza alta para coste).
- C2: las decisiones de reemplazo de componentes exigen evidencia de **calidad**, no solo de
  coste (principio metodológico reforzado por el alcance de exp001).

## 6. Próximos pasos
- exp002: calidad de mezcladores (recall/copia) — el contrapeso a exp001.
- Integrar síntesis del ciclo-1 → `architecture.md`.
- Derivar el primer boceto de arquitectura CPU-first defendible por evidencia.
