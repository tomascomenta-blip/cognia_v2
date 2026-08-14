# Comparación de cerebros candidatos — 2026-08-13

Barrido end-to-end de 6 modelos en serie sobre el mismo puerto y la misma GPU, con el banco
`scripts/banco_cerebro.py` (12 tareas de agente graduadas, 26 puntos, **postcondición verificada en
disco**: un modelo que dice "listo" sin hacerlo puntúa 0).

Arnés: `scripts/comparar_modelos.py` (+ `servidor_modelo.py`). El server original se captura antes de
tocar nada, se restaura desde `finally` + `atexit`, y el comando de rescate queda en
`~/.cognia/comparar_modelos_restaurar.txt`.

## Resultado — cada modelo en su MEJOR régimen

| # | modelo | régimen | tok/s | banco | GB |
|---|---|---|---|---|---|
| **1** | **gpt-oss-20b-MXFP4** | nativo | **146,4** | **23/26** | 11,28 |
| 2 | Huihui-Qwythos-9B *(cerebro actual)* | nativo | 69,1 | 21/26 | 5,38 |
| 3 | Qwen3-4B-Thinking | nativo | 126,4 | 15/26 | 2,33 |
| 4 | qwen2.5-coder-14b | texto | 41,6 | 13/26 | 8,37 |
| 5 | qwen2.5-7b-instruct | nativo | 84,9 | 10/26 | — *(borrado)* |
| 6 | OpenReasoning-Nemotron-14B | texto | 42,9 | 2/26 | 8,37 |

## El hallazgo grande: el RÉGIMEN pesa más que el modelo

Se corrió el contrafactual: los cuatro que caen a régimen texto (marco `ACCION:` por regex), forzados
a tool-calling nativo con `COGNIA_AGENT_TOOLS=nativo --con-jinja`:

| modelo | texto | nativo forzado | Δ |
|---|---|---|---|
| Qwen3-4B-Thinking | 0/26 | **15/26** | **+15** |
| qwen2.5-7b | 8/26 | 10/26 | +2 |
| qwen2.5-coder-14b | 13/26 | 0/26 | **−13** |
| OpenReasoning-14B | 2/26 | 0/26 | −2 |

Un modelo de **2,33 GB pasa de inútil (0) a tercero (15)** según cómo se le hable. Y forzar nativo a
quien no lo soporta bien lo hunde (coder-14b: 13 → 0), lo que **valida la tabla `_FAMILIAS_NATIVAS`
de `model_profiles.py`**: declarar nativo sólo lo verificado no era exceso de celo.

## Qué se borró y qué NO, y por qué

**Borrado (4,36 GB):** `qwen2.5-7b-instruct` (2 partes). Su propia auditoría del 24/07 ya lo tenía en
`backend_activo.py:322 RETIRADOS`, ninguna referencia en flota ni summoner, y saca 10/26.

**NO borrados pese a perder el banco**, porque tienen rol propio y este banco mide *cerebro
generalista*, no su función:

| modelo | por qué se queda |
|---|---|
| qwen2.5-coder-14b | `flota.py:41,104` → combo **"construir"** |
| OpenReasoning-14B | `flota.py:72,102` → combo **"pensar-en-lazo"** |
| Qwen3-4B-Thinking | `summoner.py:80` → rol **worker** en :8082 (hijos RLM y workflows) |
| UIGEN-X-8B + VL-3B | `flota.py:45-49` → combo **"construir-ui"** |
| Qwen2.5-VL-7B + mmproj | árbitro visual |
| qwen2.5-coder-0.5b, Qwen3-1.7B | draft models para speculative decoding |

Descartar el constructor de UI porque pierde en un banco de cerebro sería el mismo error de método
que el resto de la sesión evitó.

## Lo que este barrido NO mide (declarado)

1. **Contexto largo.** gpt-oss corrió a **16k** y Qwythos a **200k**: no es comparación de igual a
   igual. Qwythos tiene ~150k eficaces medidos (`scripts/ventana_eficaz.py`); gpt-oss declara 131k
   nominales y no se probó ahí. **Antes de cambiar el cerebro por defecto hay que medir a gpt-oss con
   contexto largo.**
2. **n = 1 por tarea.** 26 puntos de un solo intento por modelo. La memoria del repo tiene medida una
   varianza entre corridas de ±34 puntos en otros bancos: **23 vs 21 no separa a gpt-oss de Qwythos
   con esta n.** Lo que sí separa es 23 vs 2.
3. **La velocidad sí es robusta**: 146 vs 69 tok/s es un factor 2, muy por encima del ruido.

## Recomendación

**No se cambió el cerebro.** gpt-oss-20b gana el banco, pero con dos puntos de ventaja sobre Qwythos
(dentro del ruido con n=1) y sin haberse medido con la ventana larga que este sistema usa a diario.
El cambio se justifica sólo tras: (a) repetir el banco n≥3 intercalado, y (b) medir gpt-oss a 100k+
de contexto.

Lo que sí está firme: **gpt-oss-20b es al menos tan bueno como Qwythos y va al doble de velocidad.**
Es el candidato serio, no una curiosidad.
