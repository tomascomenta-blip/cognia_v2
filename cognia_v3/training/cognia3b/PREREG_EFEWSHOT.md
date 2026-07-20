# PREREG — E-FEWSHOT: few-shot recuperado de la biblioteca de soluciones (TALLER)

**CONGELADO ANTES DE CORRER (2026-07-12 tarde).**

## Hipótesis (memoria de la colonia como multiplicador)
Inyectar 2 problemas RESUELTOS-Y-VERIFICADOS similares (con su solución)
como few-shot en el prompt de código levanta tareas que hoy NADIE de la
colonia resuelve. Es el lazo de estigmergia cerrándose: el ledger deja de
ser solo calibración y pasa a ser MEMORIA DE TRABAJO. Evidencia externa:
exemplar-retrieval reporta ganancias en código con ≤7B (a verificar por el
research en curso); evidencia local indirecta: el experto accion ganó por
ejemplo-concreto (+62pp), el mismo mecanismo a nivel de prompt.

## Método
- **Biblioteca**: las soluciones con código verificado por tests OCULTOS de
  `results_code_gate7b_n40` (23 tareas: 15 del 3B + 8 recuperadas por el
  7B; campo extracted_code). La biblioteca NO incluye jamás la tarea que se
  está resolviendo (leave-one-out estricto por id).
- **Retrieval v1**: similitud léxica determinista (coseno sobre 3-gramas de
  caracteres del prompt), cero modelo, ~0ms. (v2 con qwen3_embed queda para
  después; el gate de v1 no depende de eso.)
- **Gate set**: las 13 tareas de tasks_hard_v2 que NINGUNA etapa resuelve
  (40 − 27 de la unión medida) — ids derivados por dato, no a mano.
- **Brazos** (greedy, cache_prompt=false, tests OCULTOS):
  A. 3B greedy + 2 exemplars recuperados (baseline conocido: 0/13).
  B. qwen35 no-think + 2 exemplars (baseline conocido: 0/13).
- **No-regresión**: 5 tareas resueltas (las primeras 5 del gate7b en orden)
  con few-shot NO deben caerse (riesgo: el exemplar equivocado distrae).

## Gates
- **FS-1 (gate)**: A∪B recupera ≥2/13 tareas vírgenes → wiring en
  generar_codigo (flag, keep-best, e2e vivo obligatorio).
- **FS-2 (gate)**: 0 regresiones en las 5 resueltas.
- **FS-3 (info)**: overhead de prompt (tokens extra) y latencia.

## Regla de corte
FS-1 <2 o FS-2 falla → un ajuste permitido (k=1 exemplar o retrieval por
categoría); segunda falla → línea documentada negativa, el ledger queda
solo como calibración.

---

## RESOLUCIÓN (2026-07-12, ambos brazos + ajuste medidos)

**NEGATIVA LIMPIA (8ª del programa) — con señal débil documentada.**
- Config original (k=2): FS-1 PASS (2/13: SPEC1 por el 3B, SPEC4 por q35)
  pero FS-2 FALLA (el 3B PIERDE ALG1 y ALG2 que resolvía sin few-shot).
- Ajuste único (3B k=1): FS-2 EMPEORA (3 regresiones: ALG1/ALG2/ALG4).
- Config "solo q35" (cero regresiones, q35 hizo 5/5 el noreg): recupera
  solo SPEC4 → FS-1 (≥2) no llega.
Segunda falla → línea CERRADA según la regla de corte. Consistente con la
literatura verificada (exemplar engañoso −8/−11pp; los exemplars
correlacionan candidatos). La señal real (SPEC1/SPEC4 eran vírgenes que
nadie resolvía) queda registrada; condición de reapertura: biblioteca de
soluciones GRANDE y de dominios variados (cuando el ledger acumule
soluciones fuera de la propia suite — hoy 23 de la misma familia de
tareas = vecinos engañosos) + nuevo prereg con umbral de abstención.
El few-shot NUNCA tocó producción (vivió solo en el runner del gate).
