# architecture.md — arquitectura propuesta de Cognia-X (y su justificación)

> La arquitectura se construye **por evidencia**, componente a componente. Nada entra aquí sin
> una hipótesis apoyada o una decisión registrada en `decision_log.md`. Mientras un componente no
> tenga evidencia, queda marcado como **abierto**.

## Estado global: BORRADOR v0 (en construcción)

La arquitectura aún NO está decidida. Esto es el esqueleto de decisiones por componente; se
llena a medida que la evidencia llega. Una sesión nueva debe leer `hypotheses.md` y
`decision_log.md` para saber qué está cerrado.

## Componentes y estado

### 1. Representación de entrada
- **Estado:** abierto. *(síntesis del ciclo-1 pendiente)*
- Preguntas: ¿embeddings necesarios? ¿byte/char-level? ¿coste de la tabla de embeddings en
  memoria/ancho de banda?

### 2. Mezcla de secuencia (lo que reemplaza/complementa a la atención)
- **Estado:** informado por evidencia en ambos lados (coste y capacidad). Decisión: híbrido como
  dirección líder, **a confirmar con experimento** (no decidido en firme).
- **Hallazgo de coste (exp001):** el camino de mezcla por defecto **no** debe contener un término
  O(L²) en tiempo/memoria (apoyado, confianza alta). El lineal domina el coste hasta 70× a L=4096.
- **Hallazgo de capacidad (exp002):** el recall de un mezclador de estado acotado escala con el
  **tamaño de su estado** (d²/32 medido); la atención full tiene recall ~ilimitado en N. → existe
  un trade-off coste↔capacidad real.
- **Dirección de diseño (H-MEZ-4):** **híbrido** — mayoría de capas lineales (coste) + pocas de
  atención full (recall exacto). Pendiente de medir (exp003+). NO se adopta por autoridad.

### 3. Mecanismo de cómputo (precisión / sparsity)
- **Estado:** abierto. *(dimensión CPU-bottleneck del ciclo-1 pendiente)*
- Pregunta clave: ¿la inferencia en CPU es memory-bandwidth-bound? (A-001). Si sí, la
  cuantización extrema (int4/ternario) pesa más que reducir FLOPs.

### 4. Aprendizaje continuo
- **Estado:** abierto. *(dimensión aprendizaje-continuo del ciclo-1 pendiente)*
- Pregunta: aprender local + fusionar sin olvido catastrófico, viable en CPU.

### 5. Inspiración biológica (qué tomar / qué NO)
- **Estado:** abierto. *(dimensión bio del ciclo-1 pendiente)*

### 6. Auto-mejora
- **Estado:** abierto, gobernado por niveles 1→5 con gates de estabilidad
  (`00_protocolo_investigacion.md` §7).

## Principios de diseño ya adoptados (por evidencia/decisión)
- **P1 — Sin O(L²) por defecto** en el camino de mezcla (exp001).
- **P2 — Coste primero, calidad como compuerta** antes de fijar un componente (D-004).
- **P3 — La asíntota no basta:** validar el factor constante real en CPU (exp001 / A-004).
- **P4 — Recall acotado por estado:** un mezclador de estado fijo tiene recall asociativo
  limitado por el tamaño de su estado (exp002). El recall exacto ~ilimitado exige algún mecanismo
  de direccionamiento por posición (atención) o memoria externa. → diseñar a sabiendas del techo.

> La tesis de arquitectura integrada y las decisiones conservadora/moderada/radical por
> componente se escribirán aquí al cerrar el ciclo-1 (workflow).
