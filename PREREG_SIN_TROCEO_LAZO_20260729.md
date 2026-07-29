# PREREG — Fase 3 de la sonda del ladrón: COGNIA_SIN_TROCEO en el LAZO

**Fecha:** 2026-07-29 ~15:50, sesión tarde-noche 29 (hasta las 04:30).
**Escrito ANTES de correr.** Cierra la cadena de la sonda del ladrón:
fase 1 (fork, neto −7: el TEXTO roba) → fase 2 (ablación apareada, neto +6:
el troceo REQUIRED es el ladrón principal; L-sin-troceo 17/24 = nivel
crudo) → **fase 3: ¿el fix transfiere al LAZO COMPLETO?** La lección de
fix2 es la razón de ser de esta fase: v2 (neto −5) y v3 (−4) COBRABAN en
sonda directa y morían en el lazo. La diferencia: aquéllos CAMBIABAN el
troceo; éste lo QUITA, y la evidencia de fase 2 es sobre los prompts
REALES del lazo, apareada.

## Diseño (instrumento CONGELADO: cero código nuevo)

- Runner: `scripts/b2_ab_fix2.py --var COGNIA_SIN_TROCEO` **tal cual está
  en main** (commit 5dfc99e) — el MISMO instrumento que midió v2/v3/pelada:
  los netos son directamente comparables. Salida: `b2_ab_sin_troceo/`.
- Sistema COMPLETO (`b2_sistema_real.correr_sistema`, defaults de
  producción: contrato clásico, max_rondas=1) × banco brutal, brazos
  ON (COGNIA_SIN_TROCEO=1) / OFF intercalados a nivel tarea, apareados por
  (tarea, réplica), n=6 réplicas → 48 celdas de lazo.
- Convención de infra DEL INSTRUMENTO (declarada, distinta de la sonda de
  la mañana): "sin HTML" cuenta como infra y excluye el par. Guardia
  pre-declarada abajo (asimetría) porque la espiral es text-driven y este
  instrumento la esconde.
- Backend: gpt-oss :8080, slots=1 y ctx 16384 verificados en /props ANTES
  de lanzar. Fallback Ollama neutralizado por el runner. Feromona y
  telemetría redirigidas (el runner ya lo hace).
- Humo = la PRIMERA réplica de la corrida real (8 celdas, ~25-40 min),
  vigilada: si aparece EXCEPCIÓN sistemática, backend degradado o el
  troceo no conmuta (se auditará el efecto en r1), se aborta y se
  diagnostica. El runner es el mismo binario que corrió 4 A/B previos:
  no se re-humea en directorio aparte.

## Métricas y umbrales (fijados ahora)

Primaria: **neto ON−OFF apareado por contrato original** (la del
instrumento; comparable con v2 = −5 y v3 = −4).

| lectura | veredicto pre-fijado |
|---|---|
| ≥ +4 | **CONFIRMA Y ADOPTA**: COGNIA_SIN_TROCEO pasa a DEFECTO del prompt web (con suite verde + test de defecto actualizado), sujeto a las 2 condiciones de abajo |
| +2..+3 | GRIS: extensión pre-comprometida a `--replicas 8 --reanudar` (32 pares) ANTES de leer; relectura: ≥+5 adopta, +3/+4 se reporta sin adopción, ≤+2 no cobra |
| 0..+1 | NO COBRA en el lazo (como v2/v3): la brecha replay↔lazo se convierte en LA pregunta — el lazo re-arma el prompt distinto de lo capturado, o interactúa con la visión; se diseña sonda antes de tocar nada |
| ≤ −1 | el troceo AYUDA dentro del lazo: se reporta, no se adopta, y la discrepancia con fase 2 se investiga |

Condiciones de adopción (además del umbral):
1. Ganancias de ON en ≥2 tareas (concentrado en 1 = investigar antes).
2. **Guardia de asimetría de infra:** si los pares excluidos por infra
   difieren entre brazos en >2 (p. ej. sin_html sistemático en un brazo),
   NO se adopta sin inspeccionar las celdas excluidas — la espiral es
   text-driven y la convención del instrumento la excluye del apareado.

Secundarias (se reportan, no deciden): estricto post-hoc (aprobado ∧
aprobado_heldout, computable del JSON; None de held-out = par gris);
sin_html / infra por brazo; sello_lazo; checks_ok en fallidas; tiempos por
celda; neto por tarea.

## Presupuesto

48 celdas de lazo completo × ~2-6 min ≈ **2.5-4 h**. Lanzada ~16:15,
cierre ~19:00-20:15 — holgado en la ventana (aterrizaje 04:14). Guardado
incremental + `--reanudar`; corrida DESACOPLADA + monitores (progreso y
estancamiento; presupuesto de pared: el lazo ya corre max_rondas=1 y el
juez del lazo tiene sus timeouts — el riesgo de página-que-cuelga-al-juez
existe TAMBIÉN aquí y NO está cubierto por este instrumento congelado:
si el vigía de estancamiento salta, se aplica el diagnóstico de
juez-colgado-js-bloqueante antes de culpar al backend).

## Después (si queda GPU, por orden)

1. Bloque de 24 del marco ejecución-en-el-bucle (~1 h; PREREG propio ya
   enmendado — el piloto pasó).
2. Segunda pieza de la ablación (brief-en-bold) o P4 espiral, con prereg
   nuevo.

## Revisión

1 agente adversarial SOLO del prereg (el runner está congelado y probado
en 4 A/B previos; auditar coherencia de umbrales, la guardia de infra y
la interpretación de comparabilidad). Enmiendas con fecha aquí.

## PRIMERA ENMIENDA (2026-07-29 ~16:05 — tras la revisión, ANTES de correr)

SIN BLOQUEA. La conmutación quedó VERIFICADA ejecutando en un mismo
proceso (OFF→ON→OFF revertible, sin caché ni residuo; apply_config no
pisa la var; nada la limpia a mitad de celda; con max_rondas=1 el prompt
de generación es el único con troceo que ve el LLM). Arreglos aplicados:

1. **Lectura de sensibilidad pre-declarada (cierra el hueco ≤2 de la
   guardia):** además de la primaria, se recomputa el neto del MISMO JSON
   contando "sin HTML" como aprobado=False (no infra). Si el veredicto
   cambia de banda respecto de la primaria, rige la rama MÁS CONSERVADORA.
   Dirección del sesgo analizada: sin_html en ON excluido = pro-ON (el
   peligroso); esta sensibilidad lo neutraliza sin tocar el instrumento.
2. **El veredicto que imprime el runner es LEGADO** (">=3 cobra..." — el
   umbral del prereg viejo de fix2) y NO rige: rige la tabla de este
   prereg, leída del JSON.
3. **Checklist de lanzamiento:** shell limpio de COGNIA_* residuales
   (COGNIA_MAX_RONDAS re-encendería la reparación en ambos brazos;
   COGNIA_PROMPT_FIX2 alteraría el baseline OFF), /props con slots=1 y
   ctx 16384.
4. **Deuda declarada para la adopción:** `asset_bridge.
   build_prompt_web_con_assets` trocea POR SU CUENTA y el gate no lo
   cubre (camino inerte en este A/B: sin sprites no se activa). Si la
   rama ≥+4 adopta, el defecto debe extender el gate a ese camino en el
   mismo commit.
5. Comparabilidad con v2 −5 / v3 −4: cualitativa (cobró/no-cobró, ±~2
   entre noches), no aritmética.
