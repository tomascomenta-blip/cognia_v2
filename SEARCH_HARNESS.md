# El harness de búsqueda de Cognia

*Escrito el 2026-08-15, tras investigar el harness de Perplexity y —sobre todo— leer el código
propio. Documento vivo: lo que aquí está MEDIDO lleva su número; lo que no, lo dice.*

## Por qué existe

El pipeline de investigación de la casa leía **3 páginas × 2000 chars** con este comentario en
el código: *"sin comerse la ventana de 8k del modelo"*. Era verdad cuando se escribió. El
cerebro de hoy sirve **1.048.576 tokens**.

Y el fan-out devolvía `None` cuando una consulta reventaba — indistinguible de *"corrió bien y
no encontró nada"*.

## La diferencia de fondo con Perplexity

Perplexity ahorra contexto porque los tokens le cuestan **dinero**. Aquí cuestan **segundos**:

| contexto | prefill (medido) | pared con ~500 tok de salida |
|---|---|---|
| 4k | 5 s | ~15 s |
| 32k | 40 s | ~50 s |
| 128k | 160 s | ~2,8 min |
| 1M | 2.061 s | ~35 min |

Eso invierte una decisión central. Perplexity hace `extract_many` por página **en paralelo**
porque tiene inferencia paralela; aquí **un solo slot serializa**, así que 40 llamadas de 4k
pagan el mismo prefill que 1 llamada de 160k **más** 40 generaciones y 40 arranques. **La
llamada ancha es la barata.** Lo que se pierde —el aislamiento de error por página— se tapa
exigiendo una fila por `pagina_id` y contando los que faltan.

## Las piezas

| módulo | qué hace | métrica |
|---|---|---|
| `search/fanout.py` | envelope `{spec, ok, valor, error}`, orden de entrada, cero reintentos en la primitiva | **fallos reconstruibles: 0% → 100%** (leído del archivo) |
| `search/prefiltro.py` | canonicalización, dedupe, tope 3/dominio, agregadores, extensiones | **7 candidatos → 4 extracciones (−43%)** con motivo por descarte |
| `search/contexto.py` | presupuesto en **segundos de pared** → tokens, modos estrecho/medio/ancho | coste declarado antes de pagarlo |
| `search/evidencia.py` | la cita tiene que estar **literal** en su página (sin juez) | tasa de citas fabricadas |
| `search/confianza.py` | grado + razones + acción, y su propio ECE/Brier | calibración (pendiente de correr) |
| `search/responder.py` | el bucle *responder o investigar* | — |
| `knowledge/navegador.extraer_muchas` | HTTP concurrente + **un** Chromium reusado | **40 páginas en 1,7 s** |

## Cómo se mide (y qué NO se ha medido todavía)

- `scripts/b5_banco_busqueda.py` — banco **offline y determinista** (http.server local) con la
  aguja sembrada más abajo de donde corta el brazo estrecho. Cuatro brazos **intercalados por
  ítem** y **dos nulos**: `estrecho` (el pipeline de hoy, 3×2000 exactos) y `ciego` (sin
  páginas: por si el modelo lo sabe de memoria).
  *Smoke corrido:* estrecho 0/2 y ciego 0/2 — lo predicho, la aguja a 6.000 chars no entra en
  2.000. **La corrida completa (ancho vs estrecho) NO está hecha**: se abortó porque el e2e
  usaba el mismo slot de GPU y la contención infló el brazo ciego a 29,8 s (cuesta 1 s).
- `scripts/b6_calibracion_confianza.py` — ECE/Brier/sobreconfianza con las dos mitades
  (positivos y **negativos**: preguntar por un equipo que no existe). **No corrido.** Hasta
  entonces, los pesos de `confianza.py` son una **hipótesis declarada**, no una medición.

## Lo que NO se copió de Perplexity, y por qué

- **Search-as-Code** (que el modelo escriba Python que arma su propio pipeline): su control
  plane es un modelo frontera y su sandbox tiene red. Aquí el `program_creator` prohíbe la red
  en el sandbox por diseño y el cerebro es un 30B-A3B. La versión local es **plan-como-dato**
  validado por esquema.
- **Cross-encoder de reranking**: quedan ~1,8 GB de VRAM con el cerebro cargado, y el bug
  abierto de llama.cpp #16407 devuelve rankings basura **sin lanzar error** para BGE/Qwen3/MXBAI.
  Si entra, va en CPU y con verificación previa contra un orden de referencia.
- **Concurrencia 12** en el fan-out: el límite aquí no es el dinero, es el **baneo** de ddgs. 5.

---

## RESULTADO DEL BANCO (2026-08-15, server sano, sin contención)

5 ítems, 4 brazos **intercalados por ítem**, dos nulos, aguja a >6.000 chars de profundidad:

| brazo | acierto | seg/ítem | tok/ítem | aciertos/min |
|---|---|---|---|---|
| ciego (sin páginas) | **0/5** | 1,0 | 67 | 0 |
| estrecho (3×2000 = el pipeline de hoy) | **0/5** | 2,2 | 1.752 | 0 |
| medio (12 páginas × 9.000) | **5/5** | 27,6 | 28.281 | **2,18** |
| ancho (40 páginas × 14.000) | **5/5** | 152,2 | 146.529 | 0,39 |

**Lo que dice.** El pipeline actual saca 0/5 y el modo medio 5/5: colapso contra perfecto, muy por
encima de cualquier MDE razonable con n=5. El brazo ciego a 0/5 descarta que el modelo lo supiera
de memoria. **Y ancho NO le gana a medio**: mismo acierto por 5,5× de pared. Más contexto no es
mejor por serlo — el máximo de la curva acierto/segundo está en medio, y ese es ahora el default.

**Lo que NO dice, y hay que decirlo:**
- **Satura por arriba.** Con medio en 5/5 el banco no puede distinguir medio de ancho. Para eso
  haría falta subir la dificultad (aguja más profunda que 9.000 chars, o multi-hop entre páginas).
- **La aguja está siempre en la posición 3** del contexto, así que el ancho se mide en su mejor
  caso (lo señaló la revisión adversarial y no se corrigió: queda para la próxima versión del banco).
- El acierto es **subcadena** del código hexadecimal, y el contexto lleva varios códigos válidos de
  otras páginas: un acierto por casualidad es improbable pero no imposible.
- Mide **localización dentro de páginas ya descargadas**. No mide la calidad del buscador ni la del
  ranking, que es donde Perplexity tiene su foso real.

## CORRECCIÓN (misma noche): la conclusión de arriba era un artefacto del banco

La revisión adversarial había señalado que **la aguja estaba siempre en la posición 3** del
contexto, así que el brazo ancho nunca tenía que buscar de verdad. Se corrigió (posición sorteada
con semilla derivada del ítem, reproducible; `--aguja-fija` recupera el banco viejo) y se volvió a
medir:

| brazo | aguja fija (posición 3) | **aguja en posición sorteada** | seg/ítem |
|---|---|---|---|
| estrecho | 0/5 | **0/5** | 2,4 |
| medio | 5/5 | **2/5** | 27,5 |
| ancho | 5/5 | **5/5** | 152,2 |

**"Ancho no le gana a medio" era falso**: sólo era cierto cuando el ranking ponía la página buena
arriba. Con la aguja en las posiciones 22, 6, 38, 3 y 22, medio acierta exactamente los dos casos
en que cae dentro de sus 12 páginas. El banco viejo medía un ranking PERFECTO; el nuevo, uno
ALEATORIO. El ranking real de Cognia (léxico, sin reranker) está entre los dos.

**Lo que se hace con eso** (`search/responder.py`): no elegir a ciegas, sino **arrancar en medio y
escalar a ancho sólo cuando medio dice que no encontró**. Un no-encontrado es barato de detectar
(`encontrado=false`) y es justo la señal de que faltaba contexto. Coste esperado con este banco:
~119 s/ítem para 5/5, contra 152 s de ancho puro — y 27,5 s cuando el ranking acierta. Se escala
UNA vez: si con 40 páginas tampoco está, insistir es pagar 152 s para repetir el mismo "no".
