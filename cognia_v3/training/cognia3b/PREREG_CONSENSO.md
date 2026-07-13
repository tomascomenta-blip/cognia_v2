# PREREG — Consenso por ejecución como desempate del BoN (ataque A del techo)

**CONGELADO ANTES DE VER EL RESULTADO q35 (2026-07-13).**

## Hipótesis
El techo tiene una componente de ORÁCULO: cuando ≥2 candidatos del BoN
empatan en los tests visibles débiles, best_of_n desempata por ÍNDICE (a
ciegas). exec_consensus (S*/CodeT) desempata por MODA de comportamiento
ejecutado — sin juez-LLM. Si el pool cubre la solución pero el greedy la
pierde, el consenso la recupera. Evidencia externa: S* 3B 18.4→42.7, 7B
29.4→54.4 en LCB. Evidencia local pendiente: el seguimiento q35
(results_ataque_a_qwen35_4b.json) mide si con el coder fuerte se da el
régimen cobertura>greedy donde el consenso puede lucir (con el 3B NO se dio:
cobertura 1/13 y esa salió por greedy → delta 0).

## Precondición dura (gate de entrada, del propio q35)
Correr el gate SOLO si el q35 muestra ≥2 tareas con cobertura>0 Y greedy
fallando (el régimen donde el consenso aplica). Si el q35 replica al 3B
(cobertura casi toda por greedy), la línea se cierra ANTES de gastar más:
el consenso no tiene dónde ganar y sería 9ª negativa por diseño.

## Método del gate (si pasa la precondición)
- Suite congelada: tasks_hard_v2 N=40, tests OCULTOS.
- Generador: el path de producción (3B BoN + cascada) — el consenso se
  inserta como DESEMPATE cuando ≥2 candidatos comparten el top score de
  tests visibles.
- Brazos pareados (mismos candidatos generados, misma semilla):
  A. desempate por índice (best_of_n actual).
  B. desempate por consenso de ejecución (exec_consensus sobre los
     empatados; inputs generados por el mismo modelo; fallback a idx si no
     hay señal de consenso).
- Métrica: pass@1 contra ocultos, McNemar A vs B.

## Gates
- **CE-1 (gate)**: B > A con McNemar p<0.05 en las 40 → wiring en producción
  (flag COGNIA_EXEC_CONSENSUS, default ON solo tras e2e vivo).
- **CE-2 (guardia anti-trampa)**: 0 tareas donde B empeora a A (la trampa de
  consenso de LONG5: 6/6 idéntico y mal — el consenso NUNCA debe elegir un
  cluster que falla los tests VISIBLES ya pasados; keep-best sobre visibles).
- **CE-3 (info)**: overhead de latencia (inputs + N ejecuciones extra).

## Regla de corte
Precondición falla → cerrado sin correr el gate (documentar). Gate CE-1
falla → 1 ajuste (k de inputs, o exigir cluster ≥ mitad); segunda falla →
9ª negativa limpia, exec_consensus queda como herramienta de eval no de
prod. El consenso JAMÁS overridea un candidato que pasa MÁS tests visibles
(solo desempata EMPATES) — así CE-2 se cumple por construcción.

---

## RESOLUCIÓN PARCIAL (2026-07-13) — el probe q35 murió en 5/13, pero SPEC1 decide

El seguimiento q35 (results_ataque_a_qwen35_4b.json) alcanzó el régimen que
la precondición pedía en UNA tarea antes de que el llama-server muriera:
**SPEC1: cobertura>greedy REAL** — candidatos 1,4,5 pasan los tests ocultos,
el greedy (0) falla. Es exactamente donde el consenso debía lucir. Resultado:
**el consenso ELIGIÓ MAL** (cluster 6/6, idx 0 = el greedy incorrecto). Causa:
los inputs distinguidores que el modelo generó NO separaron los candidatos
(los 6 dieron la misma firma de comportamiento sobre esos inputs), así que
la moda incluyó a los buenos Y al malo y ganó el idx menor (el greedy malo).

Lectura honesta: el eslabón débil se MOVIÓ, no desapareció. La literatura
decía "el error del oráculo vive en los outputs predichos" y por eso el
inputs-only debía curarlo; pero acá el error vive en los INPUTS generados
(el 3B/4B no genera inputs que expongan el bug de borde de una spec larga).
Es un fallo del GENERADOR DE INPUTS, no del mecanismo de consenso.

Veredicto (con n=1, honesto): la precondición del gate NO se cumple como
esperábamos — el consenso tal-como-está no rompe el techo. Queda como
herramienta EXPERIMENTAL (exec_consensus.py, opt-in, no cableado a prod).
Reapertura condicionada: generador de inputs distinguidores más fuerte
(inputs dirigidos al borde que falla — property-based / mutación), con
nuevo prereg. Es la 9ª línea que se mide y se acota sin inflar.

El probe q35 no se reinicia (~20 min/tarea, murió el server; el dato de
SPEC1 es suficiente para esta conclusión parcial). Cierre del arco ROMPER
EL TECHO: el techo tiene banda de VARIANZA real (demostrada) pero modesta;
búsqueda+oráculo son rompibles EN TEORÍA pero las palancas probadas
(few-shot=8ª neg, consenso=9ª parcial) no las capturan con generadores
chicos; el residuo es capacidad. Honestidad mantenida punta a punta.
