# VERIFICAR T4 A MANO — 5 pasos, ~4 minutos

**Qué:** sólo lo que ninguna máquina de este repo puede firmar. Todo lo demás **ya está
automatizado** (ver la lista de abajo): repetirlo a mano es gastar tus 4 minutos en lo que un
`pytest` de 19 segundos te dice mejor.

Lo que queda a ojo, y por qué:
1. **Windows Terminal no es el ConPTY del spike.** El ConPTY reproduce los modos de consola y la
   entrega de teclas, pero **no genera `CTRL_C_EVENT` en modo cocido**: la propagación real de
   SIGINT al REPL y a los procesos hijos sólo se ve en una consola de verdad.
2. **Ningún assert dice si el shimmer parpadea**, ni si el scrollback "se ve" entero.
3. **El tope real de 600 s** nunca se midió en tiempo real (siempre bajado a 1-3 s).

**Dónde:** pestaña **nueva** de Windows Terminal, en `C:\Users\usuario\Desktop\cognia_v2`.
**Sin `|` ni `>`**: un pipe no es una consola y ningún paso arranca.

Los pasos 1-4 corren `scripts\verificar_t4_manual.py`: las funciones **reales** de `cognia/cli.py`
(`_lanzar_en_fondo`, `_confirmar_accion`, `_abrir_vista_agentes`) y la vista **real**, con un
trabajo sintético en vez del modelo — **no usan :8080**. Sólo el paso 5 lo necesita, y es corto
(el :8080 es un recurso compartido).

Ordenados de mayor a menor riesgo: **si el paso 1 falla, parás y avisás.**

---

## Antes de empezar (20 s, obligatorio)

```powershell
.\venv312\Scripts\python.exe -m pytest tests\test_cli_carril_fondo.py tests\test_cli_permiso_desde_hilo.py tests\test_harness_barra_estado.py -q
```
**297 passed en ~19 s.** Si esto no está verde, no sigas: lo que estás por mirar a ojo ya está roto abajo.

---

## 1. El permiso desde el hilo, CON LA VISTA ABIERTA  ← el que decide

```powershell
.\venv312\Scripts\python.exe scripts\verificar_t4_manual.py --caso permiso --dur 20
```
Enter para arrancar → **F2 antes de los 8 s** → esperá el modal → `s` → `esc` → esperá a que diga
`La corrida termino` → `salir`.

**Tiene que pasar:** aparece un modal `PERMISO · shell` con `s = ejecutar · n / esc / enter = NO`
encima de la vista; con `s` se cierra y la **vista sigue viva**; al salir con `esc` se vuelca
`— N linea(s) que la vista habia tragado —` y entre ellas
`el hilo recibio la respuesta True en X s`, con **X < 5**. Al final, `TOTAL: PASA`.

**Medido en el ConPTY el 2026-08-18** (`scratchpad\spike_t4\e2e_manual_paso1.py`, este mismo
guión conducido por máquina): F2 abrió en **92,7 ms**, el modal subió en cuanto el hilo lo pidió,
la vista siguió viva, el volcado salió, y el veredicto dio **6/6 PASA** con `in=503 out=7` en las
tres sondas. Lo que vos agregás es **Windows Terminal**, que el ConPTY no es.

**Si NO pasa** (el modal no aparece, o aparece y la respuesta nunca vuelve): es el cuelgue M5 —
el agente queda colgado, mudo, sosteniendo una tool a medias, hasta **600 s**. **Es el criterio de
corte: se va a Plan B** (la vista como proceso aparte). No sigas, avisá.

> **Sabelo antes de tocar nada:** con un permiso en pantalla **no se puede cortar la corrida**.
> Ctrl-C en la pregunta cuenta como **"no"** (`selector.confirmar` bindea `c-c`→False), y con el
> modal arriba el `ctrl+c` de la vista **ni llega** (el ModalScreen se lo traga). Contestá primero
> (`n`/`esc`), cortá después. No es un bug que estés cazando: está medido y es el diseño de hoy.

---

## 2. Ctrl-C REAL, con un proceso hijo  ← lo único que el ConPTY no puede firmar

```powershell
.\venv312\Scripts\python.exe scripts\verificar_t4_manual.py --caso ctrlc --dur 30
```
Esperá 2-3 líneas `hijo vivo Ns` → **un solo Ctrl-C** → `salir`.

**Tiene que pasar:**
`Ctrl-C: corte pedido: N agente(s) alcanzado(s). El paso en curso termina antes de cerrar. El REPL sigue vivo.`
el trabajo cierra (`el trabajo vio el corte y cierra`) y **el proceso NO se muere**.

**Si NO pasa:** si el proceso entero se cae al shell, Ctrl-C llega como SIGINT y **mata el REPL con
trabajo vivo** → bloqueante, revertir con `COGNIA_SIN_FONDO=1` (abajo).
Si el veredicto dice `HIJO: MUERTO`, es el **límite conocido** (un Ctrl-C durante una tool mata
también su subprocess): anotalo, no bloquea.

> Por qué esto no se automatizó: el hueco del Ctrl-C entre el arranque del hilo y el prompt de
> espera está **cerrado y con test** (`TestElHuecoDelCtrlC`), pero el `KeyboardInterrupt` de ese
> test se **inyecta**, no se teclea. Esta es la única vez que la tecla es de verdad.

---

## 3. Ctrl-C dentro de la vista, y el shimmer a ojo

```powershell
.\venv312\Scripts\python.exe scripts\verificar_t4_manual.py --caso vista --dur 30
```
F2 → mirá el shimmer 10 s → **Ctrl-C** → `esc` → `salir`.

**Tiene que pasar:** una notificación amarilla `Ctrl-C / corte pedido…`; la vista **sigue abierta**
y el proceso vivo; `esc` devuelve al prompt. El shimmer ondula parejo, **sin parpadeo ni tirones**.

Mirá también el **pie**, que a partir de esta tanda tiene cinco entradas y **ninguna miente**:
`^c Cortar la corrida · esc Salir · x Interrumpir agente · ^x Cancelar corrida · ⏎ Interrumpir y decir`.
`^c` corta la corrida **del REPL, ya**; `^x` corta por el motor la corrida **pintada** y
**pregunta antes**. Son dos cosas distintas: por eso el verbo es distinto.

**Si NO pasa:** si Ctrl-C cierra la App o mata el proceso, conhost sí genera `CTRL_C_EVENT` dentro
de Textual (contra lo medido: `in_mode=512`) y hay que capturarlo con `signal`, no con `BINDINGS`.
Si el shimmer parpadea, bajá `FPS` en `cognia/tui/agentes.py`.

---

## 4. El terminal vuelve entero, y la línea a medio escribir también

```powershell
.\venv312\Scripts\python.exe scripts\verificar_t4_manual.py --caso base --dur 30
```
Escribí `hola sin enter` **sin Enter** mientras salen líneas → F2 → `esc` → `salir` → después `dir`.

**Tiene que pasar:** (a) la línea no se rompe ni se pega al texto del trabajo; (b) al salir de la
vista **el scrollback de antes sigue arriba**; (c) la línea vuelve **entera**; (d) el veredicto da
**6 PASA**, con `in`/`out` iguales antes y después (**503 / 7**) y `eco=True cursor=True`; (e) `dir`
sale con eco y con colores.

**Si NO pasa:** `in`/`out` distintos o `eco=False` → el terminal quedó roto: **VOLVER ATRÁS**.
Scrollback borrado → alguien emitió `ESC[3J` (medido: 0 en las 10 corridas del banco); mirá qué
cambió en Textual. Línea rota o perdida → falta `patch_stdout(raw=True)`.

---

## 5. El REPL de verdad (el único que necesita :8080 — usalo corto)

```powershell
.\venv312\Scripts\python.exe -m cognia
```
Mirá la barra del prompt: tiene que decir
`tab completa · ↑↓ historial · @ archivo · / comandos · f2 agentes`.
Después `/workflow decime un color; decime un numero` → a los ~5 s **F2** → `esc` → esperá el final
→ y un **Ctrl-C** en el prompt vacío.

**Tiene que pasar:** aparece el prompt de espera con reloj en vez de una pantalla congelada; F2
muestra los 2 agentes con su texto real; al terminar sale el resultado de siempre y
`corrida <run_id> · N tokens`; el Ctrl-C final dice
`linea cancelada. Ctrl-C otra vez para salir (o /salir, o Ctrl-D).` y **no cierra el REPL**
(dos Ctrl-C seguidos sí salen).

**Si NO pasa:** REPL congelado sin prompt de espera → cayó al camino inline (mirá que
`COGNIA_SIN_FONDO` no esté puesta). Resultado distinto al de siempre → corré el mismo comando con
`$env:COGNIA_SIN_FONDO="1"`, que es el brazo de control, y compará los dos textos.

---

## VOLVER ATRÁS

| qué | comando |
|---|---|
| **Apagar el carril de fondo** (todo vuelve al despacho inline de hoy: sin hilo, sin prompt de espera, sin F2 durante la corrida) | `$env:COGNIA_SIN_FONDO="1"` — permanente: `setx COGNIA_SIN_FONDO 1` |
| Volver a encenderlo | `Remove-Item Env:COGNIA_SIN_FONDO` — permanente: `setx COGNIA_SIN_FONDO ""` |
| **Terminal roto** (sin eco, cursor invisible, colores rotos) | cerrar la pestaña es lo más rápido; en el sitio: `.\venv312\Scripts\python.exe -c "import ctypes,sys;k=ctypes.windll.kernel32;k.SetConsoleMode(k.GetStdHandle(-10),503);k.SetConsoleMode(k.GetStdHandle(-11),7);sys.stdout.write('\x1b[?25h\x1b[?1049l')"` |
| Spinner que quedó apagado (el carril lo apaga y lo restaura solo) | `Remove-Item Env:COGNIA_SPINNER` |
| Sospechás del arnés, no del REPL | `.\venv312\Scripts\python.exe scripts\verificar_t4_manual.py --caso humo` → `HUMO: PASA` |

El interruptor se lee **a call-time** (`cli._sin_carril()`), así que no hay que reinstalar ni
reiniciar nada: la variable surte efecto en la corrida siguiente. Hay test de eso.

---

## Ya cubierto automáticamente — NO lo repitas a mano

| lo que antes era un paso a mano | quién lo firma ahora |
|---|---|
| Permiso con la vista **cerrada** (selector `[Si]/[No]`) | `test_cli_permiso_desde_hilo.py` + ConPTY: **111,98 ms** con `s`, **103,45 ms** con `n` |
| El permiso **rescatado** si cerrás la vista con el modal arriba | pytest (c): **262-270 ms**, el pulso de 250 ms de `_permiso_en_vista` |
| Timeout del permiso + respuesta tardía avisada | pytest (d) + ConPTY con el tope bajado a 3 s |
| El **móvil** no se queda ciego / no ensucia la pantalla alterna | `test_events_sink_tui.py` (3 tests) + ConPTY: 6 `@EV` por PIPE, **0** pintadas sobre la vista |
| Líneas que la vista se tragó, volcadas en orden y sin duplicar | `TestVolcadoDeLineasTragadas`, incluido punta a punta con la vista real |
| Teclear mientras corre → cola FIFO y acuses | `TestColaDeEntrada` (3 tests) |
| F2 **sin** corrida abre y `esc` cierra | `TestF2SinCorrida` (3 tests) + ConPTY: **93-260 ms** |
| Modos de consola 503/7 antes y después, `?1049h`=1 / `?1049l`=1 / `ESC[3J`=0 | banco del spike, **10/10 casos**, y `e2e_carril_correr.py` |
| El pie no promete un `^x` que no corta, la barra nombra F2 | `TestAtajosQueNoMienten` (5 tests), sobre lo que Textual **pinta** |
| Ctrl-C en el prompt idle: cancela la línea; dos seguidos salen | `e2e_carril_ctrlc.py` en ConPTY: **21,0 ms**, rc 0 |

---

## Lo que sigue SIN verificar (y no se puede desde acá)

- **El tope de 600 s en tiempo real.** Siempre se midió con el tope bajado a 1-3 s. El techo real
  de espera del hilo es 600 s **+ hasta 4 s** de reintentos de `_despertar_prompt`.
- **Dos permisos en vuelo**: hoy es imposible (una corrida, agente secuencial). `c.pedido` es un
  solo slot: si algún día hay dos corridas, esto se rompe.
- **`CTRL_C_EVENT` de conhost**: el paso 2 es la única prueba que existe.
- **El shimmer a ojo** y **el scrollback "se ve"**: pasos 3 y 4.
- **`README.md:165`** muestra la barra vieja, sin `f2 agentes`. Una línea, pendiente.
