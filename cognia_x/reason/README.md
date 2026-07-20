# `cognia_x/reason/` — Pilar 5: Razonamiento

> La IA **prueba distintas cadenas de razonamiento, ve cuál le da mejores resultados** (verificándolo
> dentro del sistema o **preguntándole al usuario**) y **aprende a elegir**. Problemas de
> investigación → situaciones cotidianas → código. Construido sobre el principio que cierra todo el
> lab: *solo cuenta lo que sobrevive a un examinador NO circular.*

## La idea en una línea
Un **router de meta-razonamiento aprendido online, anclado a un verificador real**. No es best-of-N
por instancia ni self-consistency: aprende QUÉ estrategia de razonamiento desplegar según el problema,
**generaliza** a problemas nuevos, escala a **preguntarle al usuario bajo presupuesto**, **compone**
cadenas multi-paso, e **infiere la clase de problema desde el texto** — todo decidido por un
examinador que no se puede engañar con confianza propia (anti-Goodhart).

## Las situaciones cotidianas (con verificador computable)
Dividir una cuenta con propina · qué paquete sale más barato por kilo · cuántos viajes entran en un
presupuesto con tarifa fija · si llego a tiempo · (compuestos) cuántos packs del más barato puedo
comprar · si cada parte de la cuenta entra en el límite de cada uno.

## Las cadenas (estrategias de razonamiento)
`direct` (intuición de un tiro, y **fanfarrón**: confianza ~0.95 aunque se equivoque) · `stepwise`
(paso a paso) · `backwards` (hacia atrás desde la restricción) · `unit_rate` (normaliza por unidad) ·
`decision` (estima y decide). Cada una es competente en SU tipo y con error característico fuera de
él → **elegir bien la estrategia importa** (ninguna domina).

## El arco (CYCLE 12-21)
| CYCLE | módulo | qué agrega | resultado honesto (held-out) |
|---|---|---|---|
| 12 | `run_cycle12.py` | elegir cadena por tipo; anti-Goodhart; preguntar bajo presupuesto | verifier **1.000** vs mejor fija 0.793; circular 0.432 |
| 13 | `run_cycle13.py` | oráculo RUIDOSO + tipo NO visto (escala = pregunta) | robust-aggregate 1.000 vs blind 0.56 @ruido0.4; OOD 0.68→1.0 |
| 14 | `composer.py`, `run_cycle14.py` | **componer** cadenas multi-paso | cadena sola ~0.196; composer descubre el programa → 1.000 |
| 15 | `run_cycle15.py` | competencia **GRADUADA** (rompe el techo perfecto) | oracle **~0.89 (<1.0)**; router ~0.76; brecha ~0.13 |

### Sub-arco de ruteo por TEXTO (16→21): inferir la clase desde el enunciado, sin la muleta del tipo
| CYCLE | módulo | qué agrega | resultado honesto (held-out) |
|---|---|---|---|
| 16 | `text_router.py`, `run_cycle16.py` | inferir la clase desde el **TEXTO** (sin la etiqueta) | router-texto = router-tipo (enunciados separables: almuerzo gratis) |
| 17 | `run_cycle17.py` | **paráfrasis** + vocabulario solapado (texto no-trivial) | keyword-frágil pureza 0.84→0.77; Naive-Bayes (B) es el baseline a vencer |
| 19 | `lm_router.py`, `run_cycle19.py` | encoder char-LM **OFF-DOMAIN** (libros, CYCLE 7) | recupera estructura, le gana a keyword, **pierde contra B** |
| 20 | `run_cycle20.py` | encoder **IN-DOMAIN unsupervised** | le gana a B en texto limpio (1.000 vs 0.92), pierde bajo ruido |
| 21 | `supervised_router.py`, `run_cycle21.py` | **CAPSTONE**: encoder SUPERVISADO por el verificador | **E le gana a B en TODOS los niveles** y alcanza el ceiling |

**Conclusión del sub-arco:** un encoder aprendido NO le gana al bag-of-words por ser "neuronal" o
"in-domain" — le gana UNA VEZ que recibe la MISMA señal del verificador que el bag-of-words ya tenía.
La representación rica solo paga cuando el verificador la alinea a la tarea. (Respuesta literal a
"evaluá el resultado dentro del sistema".)

## El hilo conductor: anti-Goodhart
En cada cycle, si la IA aprendiera por su PROPIA confianza (señal circular) el fanfarrón `direct`
secuestra la política y la accuracy se desploma. El **examinador real** (no circular) lo desenmascara.
Es la lección de H-SELF-2 (aprendizaje continuo) aplicada a la *selección de razonamiento*.

## Honestidad (qué NO es)
Solvers deterministas/sintéticos, 4-7 tipos, CPU + stdlib. Demuestra el **MECANISMO** de "ve cuál le
da mejores resultados", no es un claim sobre LLMs reales ni escala. CYCLE 15 retiró el caveat del
techo perfecto (oracle<1.0, brecha real). CYCLE 17 reportó degradación honesta (el Naive-Bayes patina
en cold-start en ~2/12 semillas). El "preguntar al usuario" usa el ground-truth como oráculo perfecto.

## Reproducir
```
venv312\Scripts\python.exe -m cognia_x.reason.run_cycle12   # ... 13 14 15 16 17 19 20 21
venv312\Scripts\python.exe -m cognia_x.reason.run_cycle12 --smoke   # rápido (12-17 instantáneos; 19-21 cargan/entrenan el char-LM)
venv312\Scripts\python.exe -m pytest cognia_x/tests/ -k reason -q   # ~21 passed
```
Resultados detallados: `RESULTS.md`. Datos por corrida: `cognia_x/runs/cycleNN/summary.json`.

## Frontier (ver `manager/future_work.md`)
Full fine-tune del encoder (no solo la cabeza supervisada) · envolver el LM real (no solvers de
juguete) sobre una tarea con señal para un modelo chico · verificador real (sandbox/fuentes) en vez
de oráculo perfecto · componer cadenas de largo >2 con sub-metas (planificación).
