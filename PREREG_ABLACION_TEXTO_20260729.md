# PREREG — Fase 2 de la sonda del ladrón: ablación del troceo REQUIRED

**Fecha:** 2026-07-29 ~07:00, sesión matinal 29. **Escrito ANTES de
implementar el runner y ANTES de correr.** Es la fase 2 condicional del
PREREG_SONDA_LAZO_20260729: el fork de fase 1 dio **neto L−C = −7** (24
pares completos, 0 infra; C gana en las 4 tareas; secundaria por contrato
original −6, misma rama) → rama pre-fijada "el TEXTO roba": ablaciones por
CONTENIDO de pieza, **troceo REQUIRED primero** (el orden de prioridad
quedó fijado en el borrador de anoche y en la 1ª enmienda).

## Pregunta

De las piezas del prompt que el lazo arma, ¿el bloque de componentes
REQUIRED (el troceo por comas que MUTILA enumeraciones: "las minas estan en
las celdas 6" / "12 y 18. Al hacer click...") explica el grueso del robo
del texto (replay 11/24 vs crudo 18/24 hoy)?

Priors: la escalera del 27 midió el troceo en −2 netas EN SONDA DIRECTA
(base vs basereq); dos fixes del troceo (v2, v3) NO cobraron en el lazo —
pero aquéllos CAMBIABAN el troceo; esta ablación lo QUITA, sobre el prompt
real capturado.

## Diseño

- **Brazos apareados sobre el MISMO prompt capturado** (los mismos 24 de la
  fase 1, misma regla de selección rep_gate=r, s=((r−1+i_tarea)%4)+1):
  - **L** = replay ÍNTEGRO (re-medido: ancla concurrente, nada contra la
    corrida de fase 1 — deriva ~20 pts/12h).
  - **L−REQ** = el MISMO prompt sin el bloque del troceo: se eliminan
    TODAS las líneas `- REQUIRED component N: ...` y la línea
    `- Implement EVERY required component above...`. La idea ÍNTEGRA (con
    su brief) permanece en la cabecera del prompt — solo desaparece la
    checklist mutilada.
- Cirugía DETERMINISTA por regex de línea, verificada sobre los 24 prompts
  ANTES de correr (conteo de líneas eliminadas por prompt ≥ 2; existencia
  del bloque en 24/24; ningún otro cambio — diff solo en esas líneas).
- Todo lo demás IDÉNTICO a fase 1 (mismo runner-base: llm_local.generar
  directo, timeout 400, juez estricto original ∧ held-out con presupuesto
  de juzgado 300 s, clasificación de fallos de la 1ª enmienda, volcado de
  crudos, intercalado a nivel tarea, guardado incremental, slots=1 y
  n_ctx verificados).
- n = 6 réplicas × 4 tareas = 24 pares, 48 generaciones.

## Métricas y umbrales (fijados ahora)

Primaria: **neto (L−REQ) − L sobre pares válidos** (estricto, apareado).

| lectura | veredicto pre-fijado |
|---|---|
| ≥ +4 | **el troceo es el ladrón principal** → fase 3: fix condicional EN producción (quitar/reformar el troceo) con A/B de confirmación EN el lazo (la lección de fix2: el fix se mide en el lazo, nunca solo en replay) |
| +2..+3 | contribuye pero no es el grueso: la siguiente pieza (brief-en-bold) hereda la prioridad; sin adopción |
| −1..+1 | **el troceo NO es el grueso** (los fixes v2/v3 no cobraron por OTRA razón); siguiente pieza |
| ≤ −2 | la checklist AYUDA pese a la mutilación — se reporta y la sonda pasa al brief |

- Si el neto estricto y el neto por contrato original caen en ramas
  distintas → GRIS (la regla de fase 1).
- Rama ≥ +4 exige ganancias en ≥2 tareas (fallos concentrados = otra
  cosa), igual que fase 1.
- <12 pares válidos = solo direccional.
- **Este veredicto NO adopta nada en producción**: dirige el fix de la
  fase 3 y su A/B en el lazo.

Secundarias (se reportan, no deciden): sin_html por brazo (¿la espiral
baja al acortar el prompt?); checks_ok en fallidas; tiempos; neto por
tarea; largo del prompt por brazo.

## Presupuesto

48 gens (~30-60 s c/u) + 96 juzgados ≈ **1.3-1.7 h** (celdas que fallan
juzgan lento). Lanzada ~07:45, cierre ~09:15-09:30 — dentro del reloj de
la sesión (aterrizaje 11:44). Si el reloj corta, `--solo-resumen` +
parcial direccional.

## Revisión

1 agente adversarial (diseño+implementación, verificaciones ejecutadas
sobre la cirugía) ANTES de encender la GPU; humo de 1 celda por brazo
(kanban) antes de la corrida completa. Enmiendas con fecha aquí.

## RESULTADO (2026-07-29 ~07:59 — corrida completa, veredicto por umbrales pre-fijados)

**Neto (L−REQ)−L = +6 → EL TROCEO REQUIRED ES EL LADRÓN PRINCIPAL del
texto.** 24 pares completos, 0 infra, 0 juez-colgado.

- L−REQ **17/24 (71%)** vs L **11/24 (46%)** — quitar el troceo recupera
  prácticamente TODO el gap hasta el crudo concurrente de fase 1 (18/24,
  75%). El ancla L reproduce exacto el 11/24 de fase 1 (misma mañana).
- Condición de reparto: ganancias netas en 2 tareas (buscaminas +5,
  carrito +2; hoja −1, kanban 0) — cumplida, CON la nota de la 1ª
  enmienda: buscaminas domina (+5 de +6) y el mecanismo es legible — su
  enunciado contiene la enumeración canónica que el troceo mutila ("las
  minas están en las celdas 6, 12 y 18" → tres componentes rotos: "…las
  celdas 6" / "12 y 18. Al hacer click…"). No es anomalía a investigar:
  es la mutilación medida haciendo exactamente el daño predicho, con
  fuerza proporcional a cuánta enumeración crítica tiene cada tarea.
- Secundaria por contrato original: +5, misma rama (sin conflicto).
- sin_html 1-1 (la espiral no distingue brazos aquí).

**Fase 3 (pre-fijada por la rama ≥+4):** fix condicional EN producción —
quitar/reformar el troceo de `_componentes_de_idea`/`_build_prompt_web` —
con **A/B de confirmación EN EL LAZO** (la lección de fix2: v2/v3
CAMBIABAN el troceo y no cobraron; esta evidencia dice QUITARLO). El A/B
en el lazo exige n≥6 por brazo intercalado (~2.5-4 h de GPU): NO cabe en
el reloj de esta sesión — el fix se implementa env-gated + prereg hoy, la
corrida es de la próxima sesión.

## PRIMERA ENMIENDA (2026-07-29 ~07:15 — tras la revisión, ANTES de correr)

Revisión SIN BLOQUEA (cirugía verificada limpia 96/96: n_fuera=11 exacto,
0 colas huérfanas, cabecera con brief intacta; apareado reproduce los 24
de fase 1 en 24/24). Arreglos aplicados y declaraciones:

1. **Extensión pre-comprometida (la lección del Monte Carlo de fase 1):**
   si el neto cae en {+2, +3} — la frontera que separa caminos de fase 3
   opuestos — la corrida se EXTIENDE a `--replicas 8` (32 pares) antes de
   leer. Relectura post-extensión: ≥ +5 → troceo ladrón principal; +3/+4
   → contribuye sustancialmente, el fix de fase 3 se diseña pero con A/B
   en el lazo obligatorio; ≤ +2 → no es el grueso, siguiente pieza.
2. **Concentración:** si ≥+4 viene concentrado en 1 tarea, investigar esa
   tarea antes de declarar (no es veredicto).
3. **Declaración de la pieza:** los componentes 8-10 del troceo contienen
   fragmentos MUTILADOS del brief; la ablación los quita también — eso ES
   parte de la pieza bajo prueba (el troceo entero), no un artefacto.
4. **sin_html:** si el neto lo domina el sin_html de un brazo, inspeccionar
   los crudos antes de dirigir la fase 3 (la espiral es señal, pero hay
   que VER qué la dispara).
5. Chequeo de cirugía endurecido (n_fuera==11 exacto + cero residuo +
   cabecera intacta; el anterior era casi-tautológico). Humo con
   `--sufijo humo` (sin sufijo, la celda de humo contaminaría la corrida
   real vía --reanudar con otra s por el filtro de --tarea).
