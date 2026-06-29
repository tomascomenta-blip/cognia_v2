# 00 — ÍNDICE MAESTRO de los planos de construcción de Cognia-X

Esta carpeta (`cognia_x/construccion/`) contiene los **planos de construcción** de Cognia-X v1:
el conjunto de documentos a nivel experto que traducen la investigación saturada del laboratorio
(CYCLE 155) en un sistema **mínimo viable end-to-end**, CPU-first para inferencia y Kaggle GPU
para entrenamiento. El veredicto que gobierna todo es **GO CONDICIONADO**: se puede empezar a
construir, pero la construcción debe **arrancar por una fase de validación (M0)** que cierre los
supuestos load-bearing aún sin medir (kernels SSM/SWA en CPU, recall del híbrido a carga, inyección
de hechos). Están escritos **para un constructor que arranca**: cada plano detalla su subsistema, su
DoD, sus riesgos y su lugar en la secuencia de milestones, anclado en el ledger REAL del lab y no en
intuición.

---

## Orden de lectura recomendado

Leer en este orden; cada plano asume los anteriores.

1. **[00_READINESS.md](00_READINESS.md)** — *READINESS DE CONSTRUCCIÓN (GO / NO-GO honesto).*
   Por qué se decide construir ahora: los 5 criterios de readiness, el veredicto GO CONDICIONADO,
   los gates de validación M0 (G1-G3) y los caveats honestos. **Empezar aquí.**
2. **[01_arquitectura_sistema.md](01_arquitectura_sistema.md)** — *Arquitectura del sistema.*
   El flujo end-to-end (planificador → verificador → director de expertos → integrador →
   razonamiento → comunicación), los módulos y el router de 3 bandas (LOCAL / MEDIA / GLOBAL).
3. **[02_backbone_modelo.md](02_backbone_modelo.md)** — *Backbone del modelo CPU-first.*
   El sustrato híbrido (mezcla atención/lineal + GQA + SWA) y su **rama de fallback** conservadora
   (Transformer denso pequeño + KV-cache 4-bit) por si A-018 no se sostiene en CPU.
4. **[03_entrenamiento_datos.md](03_entrenamiento_datos.md)** — *Plan de entrenamiento y datos.*
   Entrenamiento en Kaggle GPU, el curriculum y el motor de datos verificados.
5. **[04_verificador.md](04_verificador.md)** — *Infraestructura de verificadores real-chequeables.*
   La pieza de 1ra clase: verificación determinista (verify débil vs fuerte, anti reward-hack);
   se construye **antes** del lazo, según el orden que el lab probó que paga.
6. **[05_lazo_automejora.md](05_lazo_automejora.md)** — *Lazo de auto-mejora verificada (STaR).*
   Generar → verificar → re-entrenar, con la **guardia de diversidad** obligatoria y el gate
   anti-colapso.
7. **[06_aprendizaje_continuo.md](06_aprendizaje_continuo.md)** — *Aprendizaje continuo.*
   Triple capa: RAG doc-level + LoRA r≤16 + fusión intra-cuenca + router de bandas + FedEx-LoRA.
8. **[07_inferencia_cuantizacion.md](07_inferencia_cuantizacion.md)** — *Stack de inferencia y
   cuantización.* llama.cpp + Q4 + KV-cache cuantizado + telemetría (numpy-free) en el i3.
9. **[08_expertos_routing.md](08_expertos_routing.md)** — *Expertos jerárquicos y coordinación.*
   Adapters LoRA por dominio, selección **por PLAN** (no token-por-token), registry, pizarra y
   protocolo director↔experto (partes PENDIENTES).
10. **[09_razonamiento_comunicacion.md](09_razonamiento_comunicacion.md)** — *Núcleos de
    razonamiento y comunicación.* Separación en dos núcleos, planificador/verificador, lazo
    plan→verify→replan, abstención calibrada, meta-razonamiento y engine de hipótesis.
11. **[10_riesgos.md](10_riesgos.md)** — *Registro de riesgos consolidado.* Todos los riesgos del
    build de Cognia-X v1 en un solo lugar, con su severidad y mitigación.
12. **[11_plan_maestro_build.md](11_plan_maestro_build.md)** — *Plan maestro de build.* La secuencia
    ejecutable: milestones M0…M6, gates G1-G3 y el orden del Apéndice A. **Terminar aquí** para
    ejecutar.

---

## Nota de verificación

Estos planos fueron **verificados adversarialmente** siguiendo el método del laboratorio
(verificación REAL antes del ledger; 3-4 agentes contrastando afirmaciones antes de registrar):
los supuestos load-bearing están anclados en el ledger vivo (`research_log.md` +
`decomposition_tree.md` + `STATUS_RVALOR`), no en docs viejas ni en intuición. **Salvo donde el
texto lo indica explícitamente**, cada afirmación está respaldada por evidencia REAL. Las
excepciones honestas están marcadas en los propios planos: constantes de confianza **MEDIA** (no
medidas end-to-end en el target — se fijan en M0 + telemetría), gates **G1-G3** abiertos, piezas
**PENDIENTES** de implementar (pizarra, comunicación-por-necesidad, jerarquía de expertos, separación
de núcleos) y SCALE al **0%** (hardware-bloqueado, transferencia a escala real con confianza MEDIA).
