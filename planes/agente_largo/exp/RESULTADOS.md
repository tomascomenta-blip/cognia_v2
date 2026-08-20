# M4 — E0 y E1: los experimentos que hacen defendible (o no) el MVP TX/LIBRO

Corridos el **2026-08-19** contra el backend real (`:8080`, Qwythos-9B Q4_K, `n_ctx` 200.192).
Scripts: `e0.py`, `e0_tabla.py`, `e1.py`. Salidas crudas: `e0_out.json`, `e1_out.json`.
Puerta en el CLI: **`/tx exp`** (`/tx exp e1`, `/tx exp e0 --tabla`, `/tx exp e0 --correr`).

---

## 0. VEREDICTO EN OCHO LÍNEAS

1. **E1 PASA con el listón exacto: detección 1,000 (60/60) y 0 falsos positivos (0/60).**
2. **E0 dispara el KILL pre-registrado de la ESPEC 15.5: B5 (TX) ≈ B4 (contrato verbatim).**
   Neto apareado en la primaria: **+0,000 en 4 de 4 corridas**.
3. Y TX es **peor** que B4 en la única secundaria que mide trabajo hecho: demandas
   satisfechas **−0,250** (pierde 3 de 4), pagando **7.394 tokens** y **44,2 s** de maquinaria.
4. **Ratio de maquinaria de TX: 22,5 %.** El objetivo de la ESPEC es ≤7 % y la alarma 15 %.
5. Lo que E0 **sí** mata sin discusión es el **antipatrón RESUMEN**: recall **0,000** en 4/4,
   pierde el objetivo en el ciclo 11 en 4/4, y encima cuesta 7.815 tokens.
6. El **status quo ANCHO de Cognia NO está roto** a esta escala: recall 1,000 en 4/4, y el
   recorte de `loop._recortar_mensajes` nunca dejó desbordar la ventana (`truncados_izq = 0`).
7. **PERO**: E0 aquí es una maqueta de 18 ciclos (~33 min), la primaria es un *proxy*, y en toda
   la corrida **no se corrompió nada** — así que E0 no ha puesto a prueba para qué sirve la
   maquinaria. Lo que la maquinaria hace, lo mide E1, y B4 no tiene nada equivalente.
8. **Recomendación honesta: no desplegar B5 como está.** Entregar B4 (reset + contrato verbatim,
   coste cero) y conservar de TX **sólo la parte que E1 demuestra que mide algo**: los gates.

---

## 1. Los dos bugs que aparecieron al cablear E0 (y que la suite no veía)

Los dos son del mismo tipo — el vacío silencioso — y los dos **estaban en verde con 137 tests
pasando**. Los cazó correr el brazo TX contra el modelo de verdad, no el pytest.

| # | Dónde | Qué hacía | Cómo se veía desde fuera |
|---|---|---|---|
| 1 | `cognia/tx/driver.py::responder_por_defecto` | leía `r.content`, y `RespuestaChat` **no tiene** ese atributo; el `getattr(..., "")` devolvía `""` **siempre** | Q 0/3 y G2 "respuesta VACÍA" en **todo** commit → todo reset caía a MODO ANCHO |
| 2 | `cognia/tx/commit.py::_enunciado` | no **pedía** los trazadores, y G2 se mide justo sobre esa respuesta (ESPEC 6.5) | Q 3/3 **y aun así** G2 0/4 → mismo ANCHO perpetuo, por otro camino |

Medido antes del arreglo: 2 de 2 commits `ANCHO` con `Q 3/3` y `trz 0/4`.
Medido después: **12 de 12 commits `HECHO`, Q 3/3 y trazadores completos en las 4 corridas.**
Regresión en `tests/test_tx_m4.py` (6 tests).

---

## 2. E1 — LA MUTACIÓN DEL GATE

### 2.1 Diseño

n = **12 tareas TX reales** (`driver.iniciar` → LIBRO en disco → gates de producción), con la
forma variada a propósito: 2–6 restricciones, 2–6 trazadores, 1–4 artefactos con **sha medido del
disco**. Por tarea: **5 controles sanos** (G1, G2, G3, G4, G6 sobre el libro intacto) y
**5 mutaciones**. M1–M3 corren por la **ruta enviada** — `driver.mutar()`, que es literalmente lo
que ejecuta `/tx mutar` en el REPL.

### 2.2 Resultado

```
gate mutacion                     via                              n  deteccion   discrimina
G1   restriccion borrada          driver.mutar (/tx mutar)        12      1.000        1.000
G1p  parafrasis fiel              e1.mut_parafrasis               12      1.000        1.000
G2   digito de trazador cambiado  driver.mutar (/tx mutar)        12      1.000        1.000
G3   sha falseado                 driver.mutar (/tx mutar)        12      1.000        1.000
G6   ciclo mudo                   e1.mut_ciclo_mudo               12      1.000        1.000

TASA DE DETECCION GLOBAL : 1.000   (liston pre-registrado 1,000)
DISCRIMINACION           : 1.000
FALSOS POSITIVOS         : 0/60 = 0.000
coste de /tx mutar       : 2,5 ms de media
```

`discrimina` = el gate aprueba la versión **sana** *y* suspende la mutada. Un gate que abortase
siempre también mediría detección 1,000 y no serviría para nada; por eso las dos mitades.

### 2.3 Ejemplo de una tarea (la #0), con los detalles reales

| Mutación | Qué se tocó | Lo que dijo el gate |
|---|---|---|
| restricción borrada (G1) | quitó `P-R01` de la banda P | `sha P d6efe1a02df2ca (esperado 3de9b96ff86a24)` |
| **paráfrasis fiel (G1)** | `P-R01` reescrito con el mismo sentido | `sha P f5a6432e1d76d0 (esperado 3de9b96ff86a24)` |
| dígito de trazador (G2) | `TRZ-DBA2EF → TRZ-DBA2E0` **en la respuesta** | `trazadores en la respuesta 1/2 (perdidos: TRZ-DBA2EF)` |
| sha falseado (G3) | `A-00: 45b3944fd636ca → 00000000000000` | `artefactos 0/1 | sha cambio: A-00 …` |
| ciclo mudo (G6) | quitados los 2 eventos `medido` del ciclo | `0 evento(s) medido(s) en el ciclo 1` |
| **controles sanos** | nada | G1 ✓, G2 2/2 ✓, G3 1/1 ✓, G4 0 contradicciones ✓, G6 2 medidos ✓ |

**La paráfrasis fiel es la mutación que importa.** Contra un borrado acierta cualquier gate que
cuente filas. El modo de fallo real de este sistema no es que la restricción desaparezca: es que
un resumidor la reescriba *«igual pero mejor»* — y ahí la cascada de resúmenes midió recall 0,083
sin que nadie emitiera un error. G1 compara **bytes**, así que aborta también ahí.

### 2.4 Lo que E1 NO demuestra (dicho aquí)

- **`/tx mutar` sólo trae 3 de las 4 mutaciones de la ESPEC 15.5.** La cuarta —*inyectar un ciclo
  mudo*— la implementa `e1.py` por fuera. **Es un hueco del producto**, no del experimento: el
  drill que el dueño teclea no ejerce G6.
- El **control sano de G2** usa una respuesta sintética (los trazadores verbatim), no una respuesta
  de modelo. La tasa de falsos positivos de G2 **contra un modelo real** la mide E0: 12 commits,
  12 veces G2 verde, 0 falsos positivos.
- E1 corrompe **la proyección**, no el disco ni el proceso. No dice nada de corrupción concurrente.

---

## 3. E0 — EL BRAZO NULO

### 3.1 Diseño, declarado ANTES

- **Primaria:** `recall_restricciones@N` = fracción de las 6 restricciones cuyo **código exacto y
  aleatorio** (`[kxxxxx]`, no inferible) aparece **literalmente en la respuesta del modelo** tras N
  ciclos. Se mide sobre lo que escribe el modelo, jamás sobre la proyección (ESPEC 6.5 / P0-4).
- **Secundarias:** demandas satisfechas (*tareas completadas*), ciclos hasta la pérdida del
  objetivo, tokens y segundos de maquinaria, tokens de trabajo, segundos de pared.
- **N = 18 ciclos, n = 4 corridas por brazo, 6 brazos, INTERCALADOS** (el orden rota en cada
  corrida) y **PAREADOS**: los 6 brazos de una corrida comparten semilla, así que ven la misma
  tarea, las mismas restricciones y las mismas observaciones. Sólo los netos apareados cuentan.
- **Demandas:** en los ciclos 4, 8, 13 y 17 la consigna es una pregunta cuya respuesta **la dicta
  una restricción** y se corrige por substring exacto. Un brazo que perdió la restricción no la
  puede contestar por sentido común. Es la mitigación del *techo del diseñador de exámenes*.

**Los seis brazos:**

| Brazo | Qué es |
|---|---|
| `SIN-MEMORIA` | B0, **el azar**: sesión limpia cada ciclo, sólo el objetivo en una línea |
| `ANCHO-200k` | ventana entera sin recorte (la tarea cabe holgada). Aísla la **dilución** |
| `ANCHO-2k5` | el **status quo de Cognia**: `loop._recortar_mensajes` **importado**, + truncado por la izquierda si aun así no cabe. **Ojo con la etiqueta: el `n_ctx` que corrió es 1.800**, no 2.500 — el nombre quedó del primer tanteo y el valor real está en `w_ctx` del JSON |
| `RESUMEN` | B1, **el antipatrón**: el LLM resume el historial entero (contrato incluido) y el resumen se vuelve a resumir |
| `CONTRATO` | B4, **EL BRAZO A BATIR**: reset cada 5 ciclos re-emitiendo P verbatim. Cero LIBRO, cero gates, cero Q |
| `TX` | B5: LIBRO + proyección + commit 2PC + G1..G6 + Q1..Q3 en sesión fresca |

### 3.2 La PRIMARIA, corrida a corrida

| Brazo | c0 | c1 | c2 | c3 | media |
|---|---|---|---|---|---|
| SIN-MEMORIA | 0,000 | 0,000 | 0,000 | 0,000 | **0,000** |
| RESUMEN | 0,000 | 0,000 | 0,000 | 0,000 | **0,000** |
| ANCHO-200k | 1,000 | 1,000 | 1,000 | 1,000 | **1,000** |
| ANCHO-2k5 | 1,000 | 1,000 | 1,000 | 1,000 | **1,000** |
| CONTRATO | 1,000 | 1,000 | 1,000 | 1,000 | **1,000** |
| TX | 1,000 | 1,000 | 1,000 | 1,000 | **1,000** |

**El suelo está medido.** `SIN-MEMORIA` saca 0,000 de recall y **0 de 16 demandas**: el examen no
se aprueba adivinando, y el 1,000 de los demás brazos significa algo.

### 3.3 NETOS APAREADOS intra-corrida — la evidencia

**Primaria (TX − rival), n = 4:**

| Contra | media | rango | gana / empata / pierde |
|---|---|---|---|
| SIN-MEMORIA | **+1,000** | [+1,000, +1,000] | 4 / 0 / 0 |
| RESUMEN | **+1,000** | [+1,000, +1,000] | 4 / 0 / 0 |
| ANCHO-200k | **+0,000** | [0, 0] | 0 / **4** / 0 |
| ANCHO-2k5 | **+0,000** | [0, 0] | 0 / **4** / 0 |
| **CONTRATO (B4)** | **+0,000** | [0, 0] | 0 / **4** / 0 |

**Demandas satisfechas (TX − rival), n = 4:**

| Contra | media | rango | gana / empata / pierde |
|---|---|---|---|
| SIN-MEMORIA | +0,750 | [+0,500, +1,000] | 4 / 0 / 0 |
| RESUMEN | +0,500 | [+0,250, +0,750] | 4 / 0 / 0 |
| ANCHO-200k | +0,125 | [0, +0,250] | 2 / 2 / 0 |
| ANCHO-2k5 | −0,125 | [−0,500, 0] | 0 / 3 / 1 |
| **CONTRATO (B4)** | **−0,250** | [−0,500, 0] | **0 / 1 / 3** |

**Coste (TX − rival), n = 4:**

| Contra | tokens de maquinaria | segundos de maquinaria | segundos de pared |
|---|---|---|---|
| CONTRATO | **+7.394** (pierde 4/4) | **+44,2 s** (pierde 4/4) | **+99,0 s** (pierde 4/4) |
| ANCHO-200k | +7.394 | +44,2 s | +106,9 s |
| RESUMEN | −420 (2/4) | +18,7 s | +15,1 s |

### 3.4 Medias por brazo (orientación; la evidencia es 3.3)

| Brazo | recall | demandas | objetivo vivo | maq. tok | maq. s | **ratio maq.** | trabajo tok | pared s | ventana máx |
|---|---|---|---|---|---|---|---|---|---|
| SIN-MEMORIA | 0,000 | 0,000 | 1,000 | 0 | 0,0 | 0,0 % | 21.069 | 149 | 63 |
| ANCHO-200k | 1,000 | 0,625 | 1,000 | 0 | 0,0 | 0,0 % | 91.038 | 90 | 3.643 |
| ANCHO-2k5 | 1,000 | 0,875 | 1,000 | 0 | 0,0 | 0,0 % | 56.817 | 99 | 1.464 |
| RESUMEN | 0,000 | 0,250 | 0,250 | 7.815 | 25,4 | 14,0 % | 43.936 | 182 | 1.399 |
| CONTRATO | 1,000 | **1,000** | 1,000 | **0** | **0,0** | **0,0 %** | 31.908 | 98 | 1.010 |
| TX | 1,000 | 0,750 | 1,000 | 7.394 | 44,2 | **22,5 %** | 56.493 | 197 | 1.546 |

### 3.5 Ciclo en que se pierde el objetivo

| Brazo | c0 | c1 | c2 | c3 |
|---|---|---|---|---|
| RESUMEN | **11** | **11** | **11** | **11** |
| todos los demás | — | — | — | — |

Cuatro corridas independientes, el mismo ciclo. No es ruido: es la segunda compactación.

### 3.6 Instrumento (mirado ANTES de atribuirle nada al modelo)

```
SIN-MEMORIA finish={'stop': 91, 'length': 4}   reintentos_por_corte=3  cortes_no_recuperados=1
ANCHO-200k  finish={'stop': 92}                reintentos_por_corte=0  cortes_no_recuperados=0
ANCHO-2k5   finish={'stop': 92}                reintentos_por_corte=0  truncados_izq=0
RESUMEN     finish={'stop': 99, 'length': 5}   reintentos_por_corte=4  cortes_no_recuperados=1
CONTRATO    finish={'stop': 92}                reintentos_por_corte=0  cortes_no_recuperados=0
TX          finish={'stop':104, 'length': 3}   reintentos_por_corte=3  cortes_no_recuperados=0
            commits = 12 x HECHO
```

Dos filas (`RESUMEN c1`, `SIN-MEMORIA c2`) quedaron con la sonda de la primaria cortada aun tras el
reintento y van **marcadas**. Las dos son de brazos que sacan 0,000 en las cuatro corridas,
incluidas las no cortadas, así que no cambian nada — pero se dicen.

---

## 4. LA PRIMERA CORRIDA DE E0 FUE BASURA, Y POR QUÉ (`e0_out_v1_cortado.json`)

La primera pasada dio **TX 0,500 en c1 y 0,000 en c3**. No era memoria: era el **tope de tokens de
la sonda** (900). La respuesta de c1 se cortó literalmente a mitad de la cuarta restricción
(`"R-04 [ka10`) y la de c3 volvió **vacía entera**, con el razonador comiéndose el presupuesto.
Las dos con `finish_reason=length`.

> *«`finish_reason` y `usage` se miran ANTES de atribuir nada al modelo»* y *«un flaky es un bug
> del instrumento hasta que se demuestre lo contrario»*. Aplicadas, cambiaron el resultado de
> «TX pierde recall» a «mi sonda medía el tope de tokens».

**Arreglo del instrumento:** presupuestos a 700 (turno) / 2.500 (sonda y Q), **un reintento
automático con el doble** cuando `finish_reason == 'length'` (contado y cobrado al cubo que toca),
y **la fila se marca inválida** si aun así se corta. La corrida v1 se conserva como evidencia.

**No es una réplica fallida:** v1 y v2 no son el mismo instrumento, así que v1 no se promedia con
nada. Se guarda para que se vea el fallo.

---

## 5. QUÉ SIGNIFICA ESTO

### 5.1 El KILL, aplicado tal como estaba escrito

La ESPEC 15.5 lo dejó pre-registrado:

> **E0** — *«Si B5 ≈ B4 (diferencia apareada no significativa), se entrega B4 y se tira todo lo
> demás.»*

Medido: **la diferencia apareada en la primaria es exactamente 0,000 en 4 de 4 corridas**, y en la
secundaria de trabajo hecho TX va **por detrás** (−0,250, pierde 3 de 4). Pagando 7.394 tokens,
44,2 s de maquinaria y el doble de tiempo de pared. **El KILL dispara.**

Y hay un segundo listón, de la ESPEC 15.2, que TX tampoco pasa: **`ratio_maquinaria` objetivo
≤7 %, alarma 15 %. Medido: 22,5 %.**

### 5.2 Pero E0 no ha probado para qué existe la maquinaria

Tres cosas que hay que decir antes de tirar nada:

1. **En toda la corrida no se corrompió nada.** `tasa_de_abort = 0/12`. La propia ESPEC 15.2 dice
   que **un 0 perpetuo es AVERÍA, no salud** — aquí es la señal de que la tarea sintética nunca
   ejerció los gates. Lo que la maquinaria hace lo mide **E1**, y ahí saca 1,000 con 0 falsos
   positivos. **B4 no tiene nada equivalente: no puede detectar una corrupción porque no guarda
   nada contra qué compararla.** E0 mide el caso feliz; el caso feliz no es donde vive el valor.
2. **La escala.** 18 ciclos ≈ 33 min por brazo. La propia ESPEC predice: *«por debajo de 30 min
   predigo que TX pierde (paga maquinaria sin haber acumulado degradación en el rival)»*.
   **Esa predicción se cumplió exactamente.** Extrapolar de 33 min a 4 h — y mucho menos a 3 días —
   **es una suposición, y queda marcada como tal.**
3. **La primaria es un proxy.** La primaria real de la ESPEC 15.2 es *criterios congelados sellados
   y re-verificados en limpio, por hora de pared*. Esta maqueta mide recall verbatim, que es la
   métrica en la que B4 está construido para sacar 1,000 por diseño.

### 5.3 Lo que E0 sí deja cerrado

- **El antipatrón RESUMEN está muerto y con causa.** recall 0,000 en 4/4, objetivo perdido en el
  ciclo 11 en 4/4, 1 de 4 demandas, y encima 7.815 tokens y 25,4 s de maquinaria. Es **peor que no
  tener memoria** en la primaria y **cuesta dinero**. Si el MVP existe para reemplazar algo, es
  esto.
- **El status quo de Cognia no está roto a esta escala, y se sabe por qué.** `ANCHO-2k5` mantuvo la
  ventana en 1.464 tokens contra los 3.643 del brazo sin recortar (el recorte **sí** disparó) y
  `truncados_izq = 0`: nunca desbordó. Y `loop._recortar_mensajes` **no toca por diseño el primer
  mensaje de usuario**, que es donde vive el contrato. **Hoy Cognia conserva el contrato porque el
  recorte tiene prohibido tocarlo, no por suerte.**
- **B4 (contrato verbatim) es el que hay que batir, y sigue sin ser batido.** 1,000 de recall,
  **16 de 16 demandas**, 0 tokens y 0 s de maquinaria, y la ventana más pequeña de todos los brazos
  con memoria (1.010 tokens).

### 5.4 Recomendación

**No desplegar B5 como está.** Concretamente:

1. **Entregar B4**: reset por presupuesto de pasos + re-emisión verbatim de la banda P. Es lo que
   `driver` ya sabe hacer; sobra todo lo demás para el camino feliz.
2. **Conservar los gates**, que son lo único con evidencia propia (E1: 1,000 / 0 FP, 2,5 ms). Un
   reset B4 con G1 delante cuesta microsegundos y compra exactamente lo que B4 no tiene.
3. **Poner a Q y al 2PC en revisión de coste**: 44,2 s por 18 ciclos es el 22,5 % del ciclo, tres
   veces la alarma de la propia ESPEC. Q es la partida cara (2 llamadas al modelo por reset).
4. **Tapar el hueco de `/tx mutar`**: le falta la cuarta mutación (ciclo mudo / G6).
5. **Antes de tirar TX entero, correr el E0 de verdad** — el de la ESPEC 15.5, con tareas de 4 h y
   la primaria real. Este E0 mide 33 minutos y no corrompe nada: es suficiente para decir *«a esta
   escala no aporta»*, y **no** es suficiente para decir *«no aporta»*.

---

## 6. Cómo reproducir

```
venv312\Scripts\python.exe -m pytest tests/test_tx_m4.py -q          # 6 passed, ~0,4 s
venv312\Scripts\python.exe planes/agente_largo/exp/e1.py             # ~1,4 s, sin modelo
venv312\Scripts\python.exe planes/agente_largo/exp/e0.py             # ~54 min contra :8080
venv312\Scripts\python.exe planes/agente_largo/exp/e0_tabla.py       # re-analiza sin gastar GPU
```

Desde el REPL (`venv312\Scripts\python.exe -m cognia`, con `COGNIA_TX=1` o `/tx on`):

```
/tx exp                 lista los experimentos y cuando se corrieron
/tx exp e1              corre E1 AHORA (segundos, sin modelo)
/tx exp e0 --tabla      re-imprime las tablas de la ultima corrida
/tx exp e0 --correr     corre E0 entero (~55 min de GPU)
```
