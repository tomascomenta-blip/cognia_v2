# hypotheses.md — hipótesis + evidence ledger de Cognia-X

> Formato fijo (ver `00_protocolo_investigacion.md` §4). Toda hipótesis es falsable.
> Estado ∈ {abierta, apoyada, refutada, mixta}. Nunca borrar; revisar añadiendo.

---

### H-MEZ-1
- **Enunciado:** la atención full (O(L²)) es el cuello de botella de escalado en CPU; un
  mezclador de tiempo lineal (O(L)) la domina en coste de tiempo y memoria.
- **Predicción medible:** el mezclador lineal será ≥1× más rápido que la atención full en todo
  L≥128 y la brecha crecerá con L; la memoria del intermedio dominante de la atención crecerá
  O(L²) y la del lineal será ~constante. Se refutaría si el lineal no ganara o si la atención no
  mostrara régimen cuadrático.
- **Estado:** **apoyada (para coste)**.
- **Confianza:** alta (sobre coste); N/A sobre calidad.
- **Evidencia a favor:** exp001 — speedup 3.5×→70.3× (L 128→4096); memoria 4×→4096×; régimen
  cuadrático confirmado (×4 L → ×19.6 tiempo).
- **Evidencia en contra:** ninguna sobre coste. Caveat: exp001 no mide calidad; el sub-cuadrático
  podría perder recall (a probar en exp002).
- **Veredicto adversarial:** holds=true para la afirmación de coste, restringida a mezcla global
  no-causal con d=64. NO generaliza a "reemplazar atención" sin evidencia de calidad.
- **Experimento:** exp001 (corrido) ✅ ; exp002 (calidad) pendiente.

---

### H-MEZ-2 (derivada de exp001)
- **Enunciado:** en CPU, una asíntota mejor no basta: la implementación (vectorización, layout de
  memoria) puede invertir el orden esperado entre dos mezcladores O(L).
- **Predicción medible:** un SSM O(L) con scan en bucle Python será más lento que una atención
  lineal O(L·d²) vectorizada a longitudes moderadas.
- **Estado:** **apoyada.**
- **Confianza:** alta (en este micro-bench).
- **Evidencia a favor:** exp001 — ssm-loop 10.61 ms vs linear 6.85 ms a L=4096 pese a misma asíntota.
- **Evidencia en contra:** un scan fusionado (no Python) probablemente revierte el resultado;
  esto mide la implementación naïve, no el límite del método. → matiz importante.
- **Veredicto adversarial:** holds=true como advertencia metodológica ("no optimizar solo la
  asíntota"); NO como veredicto sobre SSM en general.
- **Experimento:** exp001 ✅.

---

> Las hipótesis H-REP-*, H-CPU-*, H-CONT-*, H-BIO-*, H-AUTO-* del ciclo-1 (workflow) se
> añadirán aquí con su evidence ledger cuando termine la síntesis. *(workflow en curso)*
