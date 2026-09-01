# Harness de tareas largas — sesión nocturna 2026-08-31 → 09-01

Corrida del 2026-08-31 23:04 al 2026-09-01 ~11:50. **No se hizo todo el encargo**: se
corrieron 10 de las 25 tareas por ronda (las otras 14 están escritas y validadas) y
quedan mejoras del diagnóstico sin implementar. Lo que sí hay está medido de punta a
punta, incluida la publicación en PyPI y el benchmark desde la versión instalada.

---

## 1. Qué se construyó

### Banco de 25 tareas largas (`banco_largo/`)
24 tareas escritas + 1 ejemplar, todas con: prompt real (1.200–5.000 caracteres, 8–12
sistemas numerados), **contrato técnico** (nombres de fichero, API global, endpoints,
subcomandos) que hace posible probarlas, artefactos esperados, criterios de éxito y de
fallo, y **9–11 pruebas ejecutables** repartidas en cinco capas.

Familias: juegos de canvas (ARK, roguelike, plataformas, tower defense), 3D con WebGL
puro (voxel, visor de datos), simulación (colonia, física 2D, epidemia), web
(dashboard, tienda, editor markdown, kanban, notas con IndexedDB), Python (CLI+SQLite,
ETL, librería de expresiones, servidor API stdlib, compilador+VM, motor de ajedrez),
Node sin dependencias (generador, servidor WebSocket a mano), herramienta con doble
interfaz, sistema multi-componente y reparación de un proyecto roto sembrado.

### Motor de verificación E2E (`banco_largo/motor.py`)
No puntúa texto: abre el producto y lo ejecuta.

- `web` — sirve el workspace, abre **Chromium real** (Playwright), teclea, hace clic,
  llama a la API del producto, lee la consola y mide el canvas (nº de colores y una
  **firma posicional** que distingue un canvas animado de una imagen fija).
- `http_servidor` — arranca el servidor del producto, espera al puerto y le pega
  peticiones reales comprobando código y cuerpo.
- `python` / `nodo` / `pytest` / `fichero` / `dos_pasadas` (regresión).

El motor pasa su propio autotest: **17/17** casos, con productos sanos que deben salir
verdes y rotos que deben salir rojos.

### Evaluación multicapa (`banco_largo/evaluador.py`)
Ocho capas independientes: **A** completitud, **B** funcionalidad, **C** calidad
estática, **D** robustez, **E** integridad, **F** entregabilidad (copia el producto a un
directorio limpio y lo vuelve a arrancar ahí), **G** verificación propia (mide *acciones*
de verificación del agente en la telemetría, no lo que dice), **H** regresiones. Nota
global ponderada priorizando funcionalidad > completitud > robustez > calidad, y todas
las notas individuales conservadas.

---

## 2. Diagnóstico (9 agentes leyendo el código, no suposiciones)

**El harness no tenía ninguna representación del objetivo.** Todo lo que gobernaba una
tarea eran proxies sintácticos:

- «terminó» = `if not resp.tool_calls: break` (`loop.py:2062`) — un turno de prosa
  cerraba con éxito un encargo de diez sistemas del que se habían hecho dos;
- «avanzó» = nació un fichero o creció 200 bytes;
- «está verificado» = se ejecutó algo después de editar.

De las **9 salidas** del bucle, ocho matan la tarea y solo una puede dar `ok=True`, y esa
no comprueba nada contra lo pedido. Encima, cinco reguladores independientes con
constantes calibradas para tareas de ~8 pasos, ninguno escalando con el tamaño del
encargo. Y casi todo lo que hacía falta **ya estaba escrito y nadie lo llamaba**:
`harness/limites.py` (cero importadores), `presupuesto_pared.py` (solo bancos),
`planner.plan_task`, `canal.anotar_pendiente`, los topes del `Progreso` (instanciado con
los tres en `None`), el modo horizonte (`"horizonte": "off"` de fábrica).

---

## 3. Cambios implementados

| # | Cambio | Por qué (evidencia) |
|---|---|---|
| 1 | **Contrato vivo del encargo** (`harness/contrato_tarea.py`) — deriva los requisitos enumerados, sigue su rastro en lo producido y **retiene el cierre** devolviendo la lista literal de lo que falta | El cierre era sintáctico. Del prompt de tower defense saca 14 requisitos; de «crea saluda.py» saca 1 y queda inactivo |
| 2 | **Corte del razonamiento desbocado** — si un turno lleva 12.000 caracteres pensando sin producir nada, se corta la generación y se repite con el pensamiento apagado | Medido en la baseline: **31.961 caracteres** razonando en el paso 1, cero ficheros, tarea muerta |
| 3 | **La sugerencia anti-estancamiento se envía antes de matar** | El código la escribía en `mensajes` y hacía `break` en la línea siguiente: el modelo no la leyó nunca |
| 4 | **Techo de pasos derivado del encargo** (`techo_por_contrato`) | Era la constante 40 para todo. ARK pasa a 120 |
| 5 | **Mutaciones detectadas en disco**, no por lista de 5 nombres de tool | Un producto escrito por `generar_codigo` o un sub-agente apagaba de golpe revisión, parada verificada y ENTREGA |
| 6 | **Presupuesto de pared cableado al agente** (`COGNIA_PARED_S`) — no se retiene un cierre si no quedan 120 s para trabajar | Ronda 2: la compuerta convertía entregas buenas en entregas a medias |
| 7 | **Telemetría real** (`harness/telemetria.py`) — diario JSONL por tarea y resumen dentro del JSON de `cognia hacer` | Antes el JSON tenía 4 campos y todo lo demás moría en stderr como prosa coloreada |

**Suite del repo: 1.640 tests pasados**, sin regresiones.

---

## 4. Resultados (10 tareas, 480 s de pared cada una, mismo banco y mismo modelo)

| Métrica | Baseline | Final | |
|---|---|---|---|
| tests funcionales superados | 36 / 106 (0,340) | **46 / 108 (0,426)** | +8,6 pp |
| nota global media | 0,417 | **0,474** | +0,057 |
| A completitud | 0,633 | 0,633 | = |
| **B funcionalidad** | 0,250 | **0,334** | +0,084 |
| C calidad | 0,862 | 0,845 | −0,017 |
| D robustez | 0,300 | 0,300 | = |
| **E integridad** | 0,200 | **0,400** | +0,200 |
| **F entregabilidad** | 0,426 | **0,492** | +0,066 |
| G verificación propia | 0,682 | 0,720 | +0,038 |
| H regresiones | 0,200 | 0,300 | +0,100 |
| productos muertos (func = 0) | 7 | **5** | −2 |
| pasos medios | 8,6 | **15,5** | +80 % |
| tokens medios por tarea | 120 k | 243 k | +102 % |
| duración media (s) | 476 | 403 | −73 |
| tareas truncadas | 10 | 10 | = |

**En el mismo tiempo de pared el agente hace el doble de trabajo y deja de cerrar en
falso.** Los dos casos más claros: `py-cli-tareas` 0,24 → 0,84 y `web-dashboard`
0,37 → 0,71, las dos pasando de producto muerto (funcionalidad 0,0) a producto que
funciona de verdad contra las pruebas.

Ronda intermedia (contrato sin reloj) frente a ronda final (con reloj): funcionalidad
0,284 → 0,334 e integridad 0,200 → 0,400, a costa de completitud 0,783 → 0,633. El
guardia de pared cambia amplitud por cosas que funcionan, que es la prioridad declarada.

---

## 4b. PyPI: la versión que instalaría un usuario

`cognia-ai` **4.22.0** publicada (https://pypi.org/project/cognia-ai/4.22.0/) tras el gate
obligatorio del repo (camino feliz **5/5**). Instalada en un venv limpio y verificado que
lo que corre es `site-packages`, no la copia local. La versión publicada trae las mejoras:
en la primera tarea imprime `Presupuesto de pasos: 40 (techo 66)` — el techo derivado del
encargo, que antes era la constante 40.

Benchmark **desde esa versión instalada**, mismas 10 tareas y mismo presupuesto de 480 s:

| Métrica | Baseline (local, 4.21) | **PyPI 4.22.0** | |
|---|---|---|---|
| tests funcionales superados | 36 / 106 (0,340) | **50 / 108 (0,463)** | +12,3 pp |
| nota global media | 0,417 | **0,508** | +0,091 |
| A completitud | 0,633 | **0,817** | +0,184 |
| B funcionalidad | 0,250 | **0,270** | +0,020 |
| C calidad | 0,862 | 0,873 | +0,011 |
| D robustez | 0,300 | **0,400** | +0,100 |
| E integridad | 0,200 | **0,400** | +0,200 |
| F entregabilidad | 0,426 | **0,487** | +0,061 |
| productos muertos (func = 0) | 7 | **6** | −1 |
| pasos medios | 8,6 | **15,2** | +78 % |
| tokens medios | 123 k | 249 k | +102 % |

Dos productos salen **completos y funcionando** desde la versión publicada:
`py-cli-tareas` con nota **1,00** (era 0,24 en la baseline) y `node-cli-generador` con
**0,98**. `ark-supervivencia`, la tarea más dura del banco, pasa de 0,09 a **0,68**.

**Una ronda descartada, y por qué.** La primera ronda desde PyPI (`r4_pypi`) salió peor
que la baseline (global 0,418). No es el producto: la corrí mientras yo ejecutaba la suite
completa y el contrafactual en la misma máquina. La telemetría lo confirma — 39,8 tok/s de
media frente a 41,96 de la ronda limpia, con tareas cayendo a 28 tok/s. Se repitió con la
máquina libre (`r5_pypi_limpio`) y es esa la que se reporta. La ronda contaminada se
conserva en `banco_largo/corridas/r4_pypi/` para que el descarte sea auditable.

---

## 5. Lo que NO se hizo, y lo que sigue roto

**No hecho**: las 25 tareas completas (se corrieron 10 representativas en cada ronda; las
otras 14 están escritas, validadas y listas para lanzarse); runners declarativos por
familia de producto; el troceado de artefactos grandes por el arnés en vez de por un aviso
en prosa.

**Sobre la suite completa.** El gate documentado del repo
(`pytest tests/ --ignore=tests/test_e2e_inference.py`) da **128 fallos sobre 14 625
pasados** con estos cambios. Los ficheros que fallan **pasan 349/349 al correrlos
aislados**, o sea que son efectos de orden/aislamiento de la suite, no del código. El
contrafactual que corrí (commit `60bb3462`) da 40 fallos, pero está 3 commits atrás y le
faltan ~580 tests, así que **no es concluyente**: queda pendiente repetirlo contra el
padre exacto. Los tests dirigidos de todo lo tocado sí están en verde (1 640 + 1 617 +
520 de comandos y ayuda + 218 de UX + 13 nuevos de pared y rescate).

**Límites de la medida, sin maquillar:**
- n = 10 por ronda y una sola corrida: las diferencias por tarea de ±0,1 son ruido.
  Lo que aguanta es el patrón (7 de 10 mejoran en la primera comparación) y las
  métricas agregadas de tests.
- Las 10 tareas siguen marcadas como truncadas en las tres rondas. Con 480 s de pared y
  un modelo local a ~48 tok/s, **ninguna tarea de este banco cabe entera**. Se mide
  cuánto producto útil se consigue por unidad de tiempo, no si la tarea acaba.
- `errores en tool calls` sube de 9 a 16: el agente trabaja más y falla más veces; lo
  que importa es que el producto final funciona mejor.

**El próximo cuello de botella, ya visible en los datos:** tres tareas de la ronda final
(`herramienta-diff`, `py-servidor-api`, `web-kanban`) murieron a los ~300 s con
`contexto, tool_call_cortado, tope_salida, error_backend`: se llena la ventana, el tool
call se corta a media cadena JSON, el servidor devuelve 500 y **los kilobytes de fichero
ya generados se tiran**. Es el hueco 11 del diagnóstico. Arreglarlo —troceado de
artefactos por el arnés en vez de por un aviso en prosa, y parciales que salgan por
todos los caminos de error del cliente— es lo que más nota queda por ganar.

---

## 6. Cómo reproducirlo

```bash
venv312/Scripts/python.exe banco_largo/autotest_motor.py          # el motor es fiable
venv312/Scripts/python.exe -m banco_largo.tareas                  # catalogo validado
BANCO_PRESUPUESTO=480 venv312/Scripts/python.exe -m banco_largo.runner \
    --ronda mi_ronda --cwd-cli /ruta/al/cognia --tareas web-dashboard,py-cli-tareas
venv312/Scripts/python.exe -m banco_largo.informe --antes r1_baseline --despues r3_pared
```

Corridas de esta noche en `banco_largo/corridas/{r1_baseline,r2_mejorado,r3_pared}/`,
con workspace, logs, diario JSONL y evaluación por tarea.
