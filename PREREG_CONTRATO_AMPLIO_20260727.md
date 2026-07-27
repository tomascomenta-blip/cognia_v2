# PRE-REGISTRO — Contrato interno AMPLIO (dirección CodeRM)

**Escrito el 2026-07-27 ~06:20, ANTES de implementar la plantilla nueva y de
generar ningún contrato.** Sesión diurna 27; continúa la prioridad #3 de
META_MODELO_GRANDE.md.

## El "antes", ya medido (cero GPU, cruce de JSONs en disco)

Cruce sello interno del lazo vs examen del banco sobre TODOS los runs en
disco que registran ambos (n=196):

| corpus | n | FP (interno aprueba ∧ banco reprueba) | FN (interno reprueba ∧ banco aprueba) |
|---|---|---|---|
| banco fácil (basefix/bonfix/escalada/primgen/bestsofar/restaurada) | 144 | 6/19 = **32%** | 62/125 = **50%** |
| banco brutal fixprompt (n=24) | 24 | 3/6 = **50%** | 9/18 = **50%** |
| banco brutal pelada/triangula | 24 | 4/5 = 80% (pre-fix) | 1/19 = 5% |

**Lectura:** en composicionales el sello interno está al nivel del azar
contra el examen real. El lazo repara guiado por esa señal.

## Hipótesis y mecanismo

La plantilla actual (`_PLANTILLA_CONTRATO`) limita a **"COMO MUCHO 8
PASOS"**; los contratos del banco brutal tienen 14-24 pasos y los bugs
composicionales aparecen en el paso 10+. CodeRM (arXiv:2501.01054): pasar de
1 a 16 aserciones da +5-8 pp, y los modelos chicos se benefician más.

**Cambio:** plantilla `amplio` seleccionable por parámetro (la clásica queda
intacta hasta el veredicto): 10-16 pasos, cada regla de la idea con al menos
un check, secuencias largas para reglas de historia (cascada, topes, undo),
al menos un check de estado inicial y uno NEGATIVO (lo que NO debe pasar).
Guardas anti-invención de literales intactas. max_tokens 12000 (la respuesta
crece; margen 2-3× — [[presupuesto-tokens-razonamiento]]).

## Medición (pre-registrada)

Corpus: las páginas de la sonda del prompt de hoy (b2_sonda_prompt, 48
páginas con veredicto del banco ya en disco; si la GPU no da, el subconjunto
de los brazos `crudo` y `full`, 24 páginas, balanceado por construcción).
Por página: generar contrato CLÁSICO y AMPLIO (mismo pensador, mismo
effort=low, mismo server), juzgar la página con cada uno, comparar contra el
veredicto del banco ya registrado.

| veredicto | condición |
|---|---|
| **PASA** | FP_amplio < FP_clasico y FN_amplio ≤ FN_clasico + 10 pts |
| **GRIS** | FP baja pero FN sube > 10 pts (examen más duro que acusa sanos) |
| **KILL** | FP_amplio ≥ FP_clasico |

Si PASA: `amplio` pasa a ser el modo del lazo y la serie n≥6 del sistema
(cuando corra) hereda el cambio DECLARÁNDOLO (no se mezcla con el fix del
prompt en la misma serie sin decirlo).

Caveats declarados: (a) el corpus son páginas DIRECTAS (sin lazo), no
productos del lazo — mide calidad del examen, no el efecto en el lazo;
(b) n≈24-48 páginas por estilo es direccional; (c) los contratos se generan
con el inventario del DOM de cada página, como en producción.
