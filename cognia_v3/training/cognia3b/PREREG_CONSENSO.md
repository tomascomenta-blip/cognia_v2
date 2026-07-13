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
