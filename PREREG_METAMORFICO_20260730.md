# PREREG — Verificación METAMÓRFICA: señal sin examen escrito a mano

**Fecha:** 2026-07-30 ~16:00, sesión tarde-noche 30→31. **Escrito ANTES de
implementar el instrumento y ANTES de mirar una sola página.**

## Por qué esta vía, y por qué ahora

Dos hallazgos de esta semana convergen en el mismo punto:

1. **El techo que se alcanzó primero es el del DISEÑADOR de exámenes**
   (PREREG_CABECERA_NUEVA): 9 tareas escritas para romper al sistema, 6 en
   4/4 a la primera y ninguna en 0/4. Subir dificultad dentro del molde
   "tarea web verificable por ejecución" no mide progreso.
2. **El cuello es FABRICAR SEÑAL para tareas nuevas.** El 8/8 del goal se
   apoya en un selector que es un examen escrito A MANO por tarea. Las 7
   vías de señal autogenerada están muertas (6 KILL) o moderadas (+2/+3).

La instrucción que sale de (1) es *cambiar de dominio o de tipo de
verificación*. Esta vía elige **cambiar el tipo de verificación**, porque
ataca los dos problemas a la vez: es un instrumento nuevo Y no exige un
examen por tarea.

### El argumento mecánico (no es una corazonada)

Las 7 vías muertas comparten **un mismo rasgo estructural**: un LLM emite
el examen, y el modo de fallo MEDIDO es siempre el mismo — **inventa
valores que el enunciado no fija** (medido: los inventos viven en los
VALORES de los checks, no en los selectores; palanca de los selectores 7%).

**Una relación metamórfica no tiene valores.** Es una relación entre dos
ejecuciones de la MISMA página: *añadir un ítem y luego quitarlo devuelve
el estado anterior* es comprobable sin saber el precio, sin saber el
nombre del ítem y sin haber leído el enunciado. Por construcción, el modo
de fallo que mató a las 7 vías **no puede ocurrir aquí**: no hay valor
esperado que inventar.

Referencia externa del método: el testing metamórfico existe precisamente
para el "problema del oráculo" — probar sistemas cuyo resultado correcto
no se conoce de antemano. Es exactamente nuestro problema, con otro
nombre.

## Qué se construye

`scripts/b2_metamorfico.py`: un juez que, dada una página HTML **y nada
más** (sin enunciado, sin contrato, sin LLM):

1. **Descubre** las acciones disponibles leyendo el DOM (botones, inputs,
   selects, checkboxes) — emparejamiento por léxico fijo, escrito una vez.
2. **Instancia** las relaciones del catálogo que apliquen.
3. **Ejecuta** cada relación con Playwright y compara SNAPSHOTS de estado.
4. Emite APROBADO / REPROBADO / NO_CONCLUYENTE con la lista de relaciones
   violadas.

### El catálogo de relaciones (genérico, escrito UNA VEZ para todas las tareas)

| id | relación | forma |
|---|---|---|
| **R1 INVERSA** | una acción y su inversa devuelven el estado previo | `S₀ →A→ S₁ →A⁻¹→ S₂`, exige `S₂ = S₀` |
| **R2 IDEMPOTENCIA** | repetir una acción de selección/filtro no cambia más | `S₀ →A→ S₁ →A→ S₂`, exige `S₂ = S₁` |
| **R3 RESET** | reset/limpiar lleva al estado inicial exacto | `S₀ →(A,B,C)→ →reset→ S₃`, exige `S₃ = S₀` |
| **R4 DETERMINISMO** | la misma secuencia desde cero da el mismo estado | dos cargas independientes, exige igualdad |
| **R5 CONMUTATIVIDAD** | dos acciones independientes en cualquier orden | `A;B` vs `B;A`, exige igualdad |
| **R6 MONOTONÍA** | filtrar nunca aumenta las filas visibles | `visibles(post) ≤ visibles(pre)` |

Pares inversos por léxico fijo: añadir/quitar · agregar/eliminar · +/− ·
sumar/restar · marcar/desmarcar · abrir/cerrar · mostrar/ocultar ·
undo/redo (deshacer/rehacer) · iniciar/pausar · incrementar/decrementar.

### El SNAPSHOT

Estado = para cada nodo visible: `(ruta-de-selector, texto normalizado,
value, checked, disabled, clases)`. Función pura y comparable por
igualdad. Se normaliza lo volátil declarado de antemano: espacios,
`id` autogenerados, y el foco.

## La trampa que este diseño tiene que evitar, y cómo (anti-vacuidad)

**Una página muerta pasa R1 trivialmente**: si el botón no hace nada,
`S₁ = S₀` y por tanto `S₂ = S₀`. Es la vacuidad que ya nos mordió una vez
(7/24 contratos aprobaban con 0 críticos) y que ya costó un descarte en
producción. Regla pre-fijada:

> **Toda relación exige que la acción directa CAMBIE el snapshot.** Si
> tras aplicar `A` el snapshot es idéntico, la relación NO cuenta como
> aprobada: la página se marca **REPROBADA por inactividad**.

Y la cobertura se reporta siempre: nº de relaciones instanciadas por
página. Una página con **0 relaciones instanciables es NO_CONCLUYENTE**,
se cuenta aparte y **no entra** en el cálculo de aciertos (contarla como
acierto o como fallo sería fabricar el número en cualquiera de los dos
sentidos).

**Páginas con animación propia** (temporizador, serpiente): el snapshot
cambia sin que nadie actúe. Se detectan midiendo el snapshot dos veces sin
tocar nada; si difiere, la página se marca ANIMADA, sus relaciones
sensibles a estabilidad se desactivan y **se cuenta cuántas son**. Ese
número es parte del resultado, no una nota al pie.

## El riesgo REAL de esta vía, nombrado antes de medir

**Una relación genérica puede ser FALSA para el enunciado.** El caso puro
ya está en nuestro banco: `undo_redo` exige que **la rama rehacible se
invalide** — o sea, el enunciado prohíbe deliberadamente que undo/redo sea
una inversa limpia. Una página CORRECTA violaría R1.

Por eso la **métrica primaria es el FP** (acusar a páginas sanas), que es
justo el modo de fallo que ya mató al modo `amplio` del contrato (FN 75%
por acusar en masa). Si las relaciones genéricas no son universales, esta
vía muere, y muere por su propio umbral.

Y por eso hay **split de calibración/medición** (abajo): retirar una
relación después de ver que produce FP es calibrar el instrumento — pero
solo es legítimo si el número final se mide en tareas que no se usaron
para calibrar. Es el mismo procedimiento que se usó con la cabecera.

## Corpus y SPLIT (pre-registrado)

Ground truth = **veredicto estricto ya conocido** de cada página
congelada (contrato original ∧ held-out a mano). Cero GPU: las páginas ya
existen y los veredictos ya están firmados.

- **CALIBRACIÓN** (se puede mirar, se puede retirar relaciones):
  páginas de los bancos **fácil y brutal**.
- **MEDICIÓN** (se mira UNA vez, con el catálogo ya congelado):
  páginas del banco **DURO** (64 del goal, r1+r2) y de la **CABECERA**
  (36). El catálogo se congela con un commit ANTES de correr la medición,
  y el hash del commit se anota aquí.

El split es **por tarea**, no por página: ninguna tarea aparece en los dos
lados.

*(El inventario exacto de páginas y clases por lado se anota abajo, en
CORPUS MEDIDO, antes de correr nada.)*

## Métricas y umbrales — FASE 1 (viabilidad)

Sobre el lado de MEDICIÓN, con el catálogo congelado:

| métrica | definición |
|---|---|
| **FP** (primaria) | fracción de páginas ESTRICTAMENTE APROBADAS que el metamórfico reprueba |
| **FN** | fracción de páginas ESTRICTAMENTE REPROBADAS que el metamórfico aprueba |
| cobertura | relaciones instanciadas por página (mediana y mínimo) |
| NO_CONCLUYENTE | nº de páginas sin relaciones instanciables |

Línea base contra la que se compara (ya medida en este repo, misma familia
de números): **contrato ciego autogenerado — FP 32-50%, FN ~50%** (n=196).

| resultado | veredicto |
|---|---|
| **FP ≤ 15% y FN ≤ 35%** | **VIVE** — primera señal autogenerada mejor que todo lo probado; pasa a FASE 2 |
| FP ≤ 15% y FN 36-60% | **GRIS** — señal débil pero no dañina; pasa a FASE 2 solo si además nunca elige peor que s1 |
| **FP > 15%** | **KILL** — las relaciones genéricas no son universales (el modo de fallo que ya mató al contrato amplio) |
| **FN > 60%** | **KILL** — indistinguible del azar |

**Auditoría obligatoria antes de firmar** (heredada del procedimiento que
cazó 3 FN míos en el brutal): se abren a mano **TODOS los FP** y se
clasifica cada uno en

- **(a) relación no universal** → la relación es falsa para ese enunciado;
  se declara y, si viene del lado de calibración, se retira del catálogo;
- **(b) fallo REAL que el contrato a mano dejó pasar** → sería **señal
  nueva**, y el resultado más valioso posible de esta sesión: el examen a
  mano tendría un agujero que el instrumento genérico ve.

Sin esa auditoría el número no se firma.

## Métricas y umbrales — FASE 2 (valor), solo si FASE 1 no muere

El metamórfico se usa como **SELECTOR del BoN** sobre las corridas
congeladas del goal (r1 y r2, 8 tareas × 4 muestras cada una), puntuando
cada muestra por relaciones violadas y eligiendo la mejor.

| referencia (ya medida) | número |
|---|---|
| control s1 (sin BoN) | 7/8 en ambas corridas |
| MODO con selector a mano | 8/8 en ambas corridas, pérdida 0 |
| techo pass@4 | 8/8 en ambas corridas |

| resultado del selector metamórfico | veredicto |
|---|---|
| **8/8 en r1 y r2** | el goal deja de depender de un examen a mano: **"8/8 en lo que le eches"** |
| 7/8 (empata al control) | no aporta: el BoN sin señal ya da 7/8 |
| ≤6/8 | **DAÑINO**: elige peor que no elegir |

Se reporta también la **pérdida del selector** (techo − modo) y la
asimetría (cuántas veces rescata vs cuántas veces estropea), que es la
secundaria que ya se usó con el consenso.

## Lo que este diseño NO puede demostrar (dicho antes, no después)

- **No prueba corrección general.** Una página puede cumplir las seis
  relaciones y ser basura respecto al enunciado. El metamórfico es una
  condición NECESARIA, no suficiente. Si vive, su uso natural es como
  **filtro** dentro del BoN, no como juez final.
- **El ground truth y el instrumento comparten Playwright**, así que
  comparten los fallos de infraestructura (páginas con JS bloqueante). La
  independencia que se reclama es de **contenido** (el metamórfico no lee
  el enunciado), no de tecnología. Todo juzgado bajo presupuesto de pared
  de 300 s; el desborde cae como infra, no como veredicto.
- **El corpus está desbalanceado** hacia páginas aprobadas (el sistema
  aprueba ~92% en el duro). El FN se estima con pocas páginas reprobadas y
  su intervalo es ancho: se reporta el n por clase junto al porcentaje,
  siempre, y con menos de 20 reprobadas el FN se declara **direccional**.

## Presupuesto

Implementación ~1.5 h (sin GPU). Humo sobre 4-8 páginas ~10 min.
Medición completa: CPU/Playwright, ~1-2 h, **cero GPU**. FASE 2 reusa las
mismas ejecuciones. Aterrizaje 06:44; si el reloj corta, se reporta el
PARCIAL con el n alcanzado y se declara como tal.

## CORPUS MEDIDO

*(se rellena antes de correr, con el inventario real)*

## RESULTADO

*(se rellena después; nada de esto se toca retroactivamente)*
