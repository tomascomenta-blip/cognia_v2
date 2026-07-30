# PREREG — Cabecera nueva: el banco DURO se saturó, hace falta terreno que discrimine

**Fecha:** 2026-07-30 ~06:35. **Escrito ANTES de redactar las tareas.**

## El dato que lo motiva (medido hoy, no supuesto)

Sobre las 64 muestras del goal (2 corridas, juez triple):

| | |
|---|---|
| pass@1 por muestra | **92%** (59/64) — META registraba 83% |
| tareas al 100% | **5 de 8** (descuento, form_cruzado, temporizador, tres_en_raya, undo_redo) |
| única que discrimina | tabla_compuesta 62% |
| techo pass@4 | 8/8 en las dos corridas |

**El banco duro ya no mide progreso.** Es el mismo diagnóstico que META
hizo del banco de 6 tareas ("está SATURADO, no sirve para medir avance") y
la misma consecuencia: **sin cabecera no hay progreso medible**. El 8/8 del
goal sigue siendo válido y replicado, pero hay que decir en voz alta que
mide un banco que el sistema actual ya domina.

## Qué se construye

**5 tareas nuevas** en `b1_tareas_cabecera.json`, con contrato a mano cada
una. El principio de dificultad no es la longitud sino la **interacción
entre mecánicas**: en el banco duro las reglas se componen (3-5 requisitos);
aquí las reglas **se afectan entre sí**, de modo que implementar cada una
por separado no basta.

Candidatas (enunciado preciso con selectores obligatorios, verificable por
ejecución):

1. **editor_undo_buscar** — textarea + buscar/reemplazar-todo + undo/redo:
   el undo debe deshacer un reemplazo masivo como UNA acción.
2. **carrito_cupones** — stock + cupón porcentual + envío gratis por
   umbral, donde el umbral se evalúa sobre el subtotal YA descontado (las
   tres reglas se afectan).
3. **calendario_conflictos** — eventos con inicio/fin que se rechazan si
   solapan, y mover un evento REVALIDA los conflictos.
4. **parser_parentesis** — precedencia + paréntesis anidados + unario
   negativo (más duro que `precedencia`, que no tiene paréntesis).
5. **ascensor** — cola de peticiones servida por dirección (tipo SCAN), no
   FIFO: el orden de servicio depende del sentido actual.

## Criterio de aceptación del banco (PRE-REGISTRADO, y esto es lo que
impide hacer trampa)

Cada tarea se mide con **n=4 muestras del sistema** (mismo modo que el
goal) y entra al banco según su pass@1:

| pass@1 de la tarea | decisión |
|---|---|
| **1/4 – 3/4 (25-75%)** | **ENTRA**: discrimina, que es para lo que existe |
| 4/4 | SATURADA: no entra como está; se anota y, si se endurece, se re-mide y se declara la versión |
| 0/4 | fuera de alcance por ahora: se anota y NO se usa para medir progreso hasta saber si es techo real o enunciado ambiguo |

- **El banco se calibra ANTES de usarlo para medir nada.** Ajustar tareas
  después de ver cómo le va al sistema en una medición de progreso sería
  fabricar el resultado; ajustarlas ahora, contra un criterio escrito
  antes, es calibrar el instrumento.
- Objetivo declarado: **≥3 tareas en la banda que discrimina**. Con menos,
  la cabecera no sirve y se dice.
- Contratos a mano con la regla de siempre: cada check crítico es
  consecuencia lógica del enunciado sobre selectores que el enunciado
  declara obligatorios; nada de valores que el enunciado no fija.

## Presupuesto

Redacción de tareas y contratos ~1.5 h (sin GPU). Calibración: 5 tareas ×
4 muestras ≈ 50-70 min de GPU. Cierre estimado ~10:00, con el aterrizaje a
las 12:14.

## RESULTADO (2026-07-30 ~08:30 — 20/20 muestras, 0 infra)

**CABECERA INSUFICIENTE por el criterio pre-registrado: solo 2 de 5 tareas
discriminan (se exigían ≥3).**

| tarea | pass@1 | decisión |
|---|---|---|
| editor_undo_buscar | **4/4** | SATURADA |
| calendario_conflictos | **4/4** | SATURADA |
| parser_parentesis | **4/4** | SATURADA |
| carrito_cupones | 3/4 | ENTRA |
| ascensor | 3/4 | ENTRA |

**El dato que importa más que el veredicto:** tres tareas diseñadas
explícitamente para romper al sistema —undo atómico de un reemplazo masivo,
solapamientos con el borde que toca (el `>=` en vez de `>`), paréntesis
anidados con precedencia— salen **4/4 a la primera**. Y **ninguna cae en
0/4**: cero evidencia de techo de capacidad en este dominio.

**Lectura honesta, que reencuadra el goal:** el 8/8 del banco duro no era
el resultado de un banco fácil por accidente. **El sistema está por encima
del nivel de dificultad que yo sé expresar en una tarea web verificable por
ejecución.** Diseñé cinco tareas para superarlo y superó tres sin
despeinarse. Esto refuerza, desde otro ángulo, la conclusión de inversión
que la semana viene repitiendo: **no falta capacidad, falta señal.**

**Hipótesis de diseño que sale de los datos (falsable, para la próxima
tanda):** las dos que discriminan comparten una propiedad que las tres
saturadas no tienen — exigen **un invariante GLOBAL que se re-evalúa
cuando cambia otra cosa** (el umbral de envío que depende del descuento; el
sentido de marcha que determina el orden de servicio). Las tres saturadas
son transformaciones más locales, por complejas que parezcan. Si la
hipótesis es buena, una tanda escrita alrededor de "invariante global
re-evaluado" debería caer en la banda que discrimina.

Las 2 tareas que entran quedan en `b1_tareas_cabecera.json` como semilla;
el banco NO se usa para medir progreso hasta tener ≥3.

## SEGUNDA TANDA — la hipótesis del "invariante global" NO se sostiene (2026-07-30 ~07:35)

Se escribieron 4 tareas construidas ALREDEDOR del invariante que la
primera tanda señalaba (`b1_tareas_cabecera2.json`) y se calibraron con el
mismo criterio:

| tarea | pass@1 | |
|---|---|---|
| presupuesto_reparto | **4/4** | SATURADA |
| carrito_packs | **4/4** | SATURADA |
| inventario_reservas | 2/4 | entra… pero por AMBIGÜEDAD MÍA (ver abajo) |
| turnos_capacidad | 2/4 | entra… pero por AMBIGÜEDAD MÍA |

**Las dos tareas limpias salen 4/4, así que la hipótesis queda
DESCARTADA.** `presupuesto_reparto` (un cambio que rompe la suma REVIERTE
al valor anterior) y `carrito_packs` (el precio depende del mínimo entre
dos cantidades, así que quitar un pan DESHACE un pack y la leche pasa a
cobrarse suelta) son exactamente el invariante-global-re-evaluado que
predije que discriminaría. El sistema las resuelve a la primera, 4 de 4.

**Y las dos que "discriminaban" no lo hacían por dificultad:** al abrir las
páginas se vio que los productos PRECARGAN ejemplos (reservas, grupos) y
**mi enunciado nunca exigió que la lista empezara vacía** — el `#disponible`
y la `#ocupacion` eran correctos para SU estado inicial. Ambigüedad del
enunciado, no del sistema. Corregido el ENUNCIADO (no el contrato) y
re-calibrado; el número que vale es el de la re-calibración.

**El balance de la mañana, dicho sin adornos: 9 tareas nuevas escritas
para romper al sistema, 7 saturadas a la primera y 2 que solo fallaban por
un defecto de redacción mío.** La conclusión ya no es sobre el banco:

> **No sé diseñar una tarea web verificable por ejecución que este sistema
> no resuelva.** El techo que se alcanzó primero no es el del sistema: es
> el del diseñador de exámenes.

Consecuencia para el goal: medir progreso aquí exige **cambiar de dominio o
de tipo de verificación**, no subir la dificultad dentro del mismo molde.
Y refuerza por tercera vía la conclusión de inversión de la semana: **no
falta capacidad, falta señal.**

## Lo que NO se hace aquí

No se re-mide el goal contra el banco nuevo en esta sesión: primero hay que
saber si el banco discrimina. Un "MODO x/5" sobre un banco sin calibrar no
significaría nada.
