# decision_log.md — decisiones de Cognia-X (con fecha y razón)

> Append-only. Cada decisión: qué, por qué, evidencia, reversibilidad.

## D-001 (2026-06-17) — Cognia-X es un laboratorio independiente
- **Decisión:** vivir en `cognia_x/`, sin reutilizar el pipeline de Cognia ni heredar su
  arquitectura.
- **Razón:** la misión exige rediseñar desde cero sin sesgo de la implementación existente.
- **Reversible:** sí (es una carpeta aislada).

## D-002 (2026-06-17) — Eficiencia computacional es la métrica primaria
- **Decisión:** toda propuesta se evalúa primero por coste (tiempo/memoria/ancho de banda) en CPU.
- **Razón:** prioridad #1 del meta-prompt; el hardware objetivo es CPU sin GPU.
- **Reversible:** sí, pero requeriría justificación rigurosa con números.

## D-003 (2026-06-17) — Trabajo en rama `cognia-x`
- **Decisión:** aislar el subproyecto en su propia rama; no commitear los cambios preexistentes
  no relacionados del working tree (.gitignore, build/*).
- **Razón:** higiene de git; mantener el experimento separado.
- **Reversible:** sí.

## D-004 (2026-06-17) — Medir coste antes que calidad, y no confundirlos
- **Decisión:** exp001 mide coste; la decisión de reemplazar un componente requiere además
  evidencia de calidad (exp002+). No declarar "reemplazar atención" con solo exp001.
- **Razón:** honestidad de alcance; evitar conclusiones sobre-extendidas.
- **Reversible:** N/A (principio metodológico).

## D-005 (2026-06-17) — Híbrido como dirección líder de mezcla de secuencia (a confirmar)
- **Decisión:** perseguir la arquitectura de mezcla **híbrida** (mayoría lineal + pocas capas de
  atención full) como hipótesis de diseño principal — NO como decisión cerrada; requiere su
  experimento (H-MEZ-4).
- **Razón:** exp001 (lineal 70× más barato) + exp002 (full con recall ~ilimitado vs lineal
  acotado por estado d²) muestran un trade-off coste↔capacidad; el híbrido es la combinación que
  la evidencia sugiere, alineada con la literatura (Jamba, Griffin, Based).
- **Reversible:** sí; se abandona si exp003+ refuta H-MEZ-4.

> Decisiones de arquitectura por componente (síntesis del ciclo-1) se añadirán aquí al cerrar
> el workflow.
