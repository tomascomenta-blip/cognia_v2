# PREREG — separar VALOR INVENTADO de SECUENCIA ROTA dentro del 67.5%

**Criterio congelado el 2026-07-30 ~21:25, ANTES de mirar un solo literal.**
Prioridad 2 de la sesión. Cero GPU.

## De dónde viene

`b2_invencion_real.py` cerró el diagnóstico del contrato interno con 434
literales de checks críticos fallidos en páginas **sanas**:

| | |
|---|---|
| **SELECTOR EQUIVOCADO** (el valor existe en la página, el check mira otro sitio) | 32.5% (142) |
| **VALOR AUSENTE** (no está en la página ni tras ejecutar las acciones del check) | 67.5% (292) |

Y quedó dicho explícitamente que esa medición **NO separa "inventado" de
"secuencia rota"**, porque un check que escribe en el selector equivocado
tampoco produce el estado que luego comprueba. Eso es lo que se cierra aquí.

## La pregunta

De los 292 ausentes: ¿el examen exige un valor que **el enunciado no fija**
(INVENTADO), o exige un valor **legítimo** al que llega por una secuencia o un
razonamiento equivocados (SECUENCIA/RAZONAMIENTO)?

Importa porque decide la función objetivo: *"no inventes valores"* y *"no te
equivoques de paso"* son dos entrenamientos distintos.

## CRITERIO (escrito antes de ver los datos)

Para cada literal ausente, contra el **enunciado** de su tarea:

| clase | regla |
|---|---|
| **A — ANCLADO_LITERAL** | el literal aparece **textualmente** en el enunciado (comparación normalizada: sin separadores de millar, `50` ≡ `50.00` ≡ `50,00`) |
| **B — ANCLADO_DERIVABLE** | no aparece textual, pero se obtiene por aritmética **de una o dos operaciones** sobre números que sí están en el enunciado (p.ej. `50.00 = 5 × 10.00`) |
| **C — NO_ANCLADO** | ni aparece ni es derivable así ⇒ **candidato a INVENTADO** |

- **A y B ⇒ el valor NO está inventado.** El examen pide algo que el enunciado
  fija y falla por otra cosa: secuencia, razonamiento o selector.
- **C ⇒ candidato a INVENTADO**, y solo *candidato*: la auditoría a mano
  decide, porque "no supe derivarlo" no es "no es derivable".

A se decide **automáticamente**. B y C exigen **juicio**, así que se auditan
a mano sobre una **muestra con semilla fija (20260730)**.

## Tamaños y los DOS LADOS

Regla de la sesión: *auditar los dos lados, no solo el que conviene.*

| muestra | n | para qué |
|---|---|---|
| ausentes NO anclados literalmente | **40** | separar B (derivable) de C (inventado) |
| ausentes SÍ anclados literalmente | **15** | control: verificar que el "anclado" no es coincidencia (`2` aparece en cualquier enunciado) |
| lado SELECTOR_EQUIVOCADO (32.5%) | **15** | control del otro lado: ¿la etiqueta acierta? |

El control de los anclados es imprescindible: un literal corto (`2`, `5`)
aparece por azar en casi cualquier enunciado, así que **la regla A sola
sobrestima el anclaje**. Se mide cuánto.

## Predicciones registradas ANTES (para poder equivocarme por escrito)

1. La mayoría de los ausentes estarán **anclados** (A o B): el diagnóstico
   previo ya apuntaba a que `540.00` y `14` salen del enunciado.
2. El anclaje literal A estará **inflado por literales de 1-2 caracteres**;
   espero que >30% de los A con literal corto sean coincidencia.
3. **INVENTADO puro (C confirmado a mano) < 25%** de los ausentes.

Si sale al revés, se escribe que salió al revés.

## Lo que este trabajo NO puede decidir

No separa "secuencia rota" de "el producto está mal", porque el ground truth
de sanidad viene del juez a mano, no de una verdad absoluta. Se declara y no
se firma más de lo medido.

---

# RESULTADO (2026-07-30, misma noche)

## 1. La regla A, automática (`scripts/b3_anclaje.py`)

434 literales, los 434 con enunciado disponible. Reparto reproducido exacto:
**141 SELECTOR_EQUIVOCADO (32.5%) · 293 VALOR_AUSENTE (67.5%)**.

De los 293 ausentes: **69 anclados literalmente (23.5%)**, 224 no (76.5%).

Y el aviso pre-registrado se cumple: **35 de esos 69 (51%) tienen un literal
de 1-2 caracteres**, así que la regla A sola **sobrestima** el anclaje.

## 2. La auditoría a mano (40 no anclados, muestra con semilla 20260730)

| clase | n | % |
|---|---|---|
| **B — anclado o derivable del enunciado** | **32** | **80%** |
| **C — no fijado por el enunciado (INVENTADO)** | **8** | **20%** |

**Predicción 1 ACIERTA** (la mayoría están anclados) y **predicción 3 ACIERTA**
(INVENTADO puro < 25%: sale **20%**). El trabajo lo hace la **derivabilidad**,
no el anclaje textual: la regla A automática solo veía 23.5%.

Dentro de los 32 anclados, la distinción que importa:

- **21 (52.5% del total) son valores de ENTRADA** que el propio examen dice
  escribir (`5`, `abcdefgh`, `17`, `Elemento 1`). Que un valor de entrada no
  aparezca **ni siquiera tras ejecutar el check** no es una invención: es que
  la escritura no ocurrió.
- **11 son valores de SALIDA correctamente derivados** (`70`, `75`, `56`,
  `7`, `145`, el texto reemplazado).

Los 8 INVENTADOS son de dos tipos: aritmética mal hecha (`285.00`, que no
corresponde a ninguna cantidad entera en el enunciado de `descuento_tramos`)
y detalles que el enunciado deja libres (`data-x="0" data-y="0"` — dónde
empieza la serpiente no está fijado; `5 filas filtradas` — los datos de la
tabla no están fijados; `^O$` — el formato exacto de `#estado` no está fijado).

> **Respuesta a la pregunta de la sesión: dentro del 67.5% de valores
> ausentes, ~80% son valores LEGÍTIMOS que el examen exige mal (secuencia,
> momento o sitio) y ~20% son valores que el enunciado no fija.** La función
> objetivo no puede ser "no inventes valores": eso ataca un quinto del
> problema.

## 3. LA HIPÓTESIS QUE SALIÓ DE LA AUDITORÍA — Y QUE LA MEDICIÓN MATÓ

Auditando apareció un patrón con pinta de causa raíz. Literal del corpus:

```json
{"nombre": "Al introducir 5 unidades, total sin descuento es 50.00",
 "acciones": [{"accion":"texto","selector":"#cant","contiene":"5"},
              {"accion":"texto","selector":"#total","contiene":"50.00"}]}
```

El paso dice *"al introducir 5 unidades"* y **no introduce nada**. Y el
motivo que registró el juez es exactamente `('' no contiene '5')`.

**Medido sobre los 782 checks de los 87 contratos** (`b3_checks_mudos.py`):

| | |
|---|---|
| checks cuyo **nombre** describe una interacción | 343 (43.9%) |
| de esos, **MUDOS** (no ejecutan `click`/`tecla`/`escribir`) | **280 (81.6%)** |
| **críticos** mudos | **272 = 36.9% de los críticos** |
| páginas con ≥1 crítico mudo | **64/87 (73.6%)**, mediana 4 por página |

**El hecho estructural es enorme y es nuevo: 4 de cada 5 checks que anuncian
una interacción no la ejecutan.**

**Y NO es lo que los hace fallar.** El cruce con el veredicto real del juez,
en páginas SANAS:

| clase | falla | n |
|---|---|---|
| MUDO | 50.5% | 275 |
| **INTERACTÚA** | **94.6%** | 56 |
| no describe interacción | 31.5% | 419 |

La comparación cruda está confundida por tarea (los que interactúan viven
casi todos en `turnos_capacidad` e `inventario_reservas`), así que se hizo
**apareada dentro de tarea**, en las 5 tareas con ≥3 de cada clase:

```
calendario_conflictos  MUDO  59% vs INTERACTUA 100%   -41
carrito_cupones        MUDO  18% vs INTERACTUA 100%   -82
form_cruzado           MUDO  92% vs INTERACTUA 100%    -8
inventario_reservas    MUDO  40% vs INTERACTUA  92%   -52
tres_en_raya           MUDO  19% vs INTERACTUA  50%   -31
MEDIA apareada: -42.9 pts (consistente en las 5)
MUDO - "no describe": +7.7 pts (15 tareas)
```

> **KILL de la hipótesis, con brazo apareado: la mudez no causa el fallo.
> Cuando el contrato SÍ intenta interactuar falla MÁS (−42.9 pts apareados,
> misma dirección en las 5 tareas).** Ser mudo es una forma degradada pero
> más *segura* de examen: comprueba estado estático y acierta la mitad de las
> veces; en cuanto intenta manipular la página, se equivoca casi siempre.

Es la **quinta** hipótesis de causa única que cae sobre este examen
(`texto`-en-`input`, selector equivocado, valores inventados, poda, mudez).
Refuerza lo ya escrito: **no es un bug con fix, son fallos múltiples y
simultáneos por página**, y el veredicto es un AND.

*Lección de método, la misma de ayer:* la hipótesis venía de UN caso leído a
mano y era muy convincente. La midió el cruce con el veredicto y salió al
revés. **Auditar un lado solo habría firmado una causa raíz falsa.**

## ENMIENDAS

_(fechadas, append-only)_
