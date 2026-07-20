# GLM-INDEX — índice agregado congelado de la colonia vs GLM 5.2

**Congelado 2026-07-12 (corrida COLONIA→CASI-GRANDE).** Mide el "qué tan
cerca estamos" con UN número honesto y reproducible. Regla: cada eje usa su
suite congelada existente (sha en sus preregs); la referencia GLM 5.2 solo
donde fue MEDIDA en este repo (duelo 2026-07-03, gate 7B 2026-07-10); los
ejes sin referencia se reportan aparte y NO entran al headline.

## Ejes con referencia GLM 5.2 medida (headline)

| eje | suite | colonia HOY (medido) | GLM 5.2 (medido) | ratio |
|---|---|---|---|---|
| tool-calling agente | G2A ×147 | 99.3 (adapter accion) | 86 (duelo 2026-07-03: 3B andamiado 86 vs GLM ref) | **≥1.0 (capado 100)** |
| diseño/arquitectura | duelo diseño | 96.1 | 93.7 | **≥1.0 (capado 100)** |
| código duro RAW | tasks_hard_v2 ×40 ocultos | 37.5 (3B) / 57.5 (cascada) | ~50 | **115 → capado 100** |
| código duro prod e2e | set H01-H05 + X1-X3 | 7/8 (best_of_n) | no medido pareado directo | (fuera del headline) |

**Headline v1 (media de ratios capados a 100): los 3 ejes con referencia
dan ~100 — PERO es engañoso solo: los ejes donde GLM 5.2 aplasta (contexto
largo, conocimiento abierto, generación libre larga, multimodal, robustez
multi-turno) NO tienen suite congelada acá.** Por eso el índice separa:

## Ejes sin referencia GLM (se reportan absolutos; el techo declarado es GLM≈95-100 en c/u)

| eje | suite | colonia HOY | nota honesta |
|---|---|---|---|
| razonamiento | G2R ×N | 82 (stepwise v2) | GLM est. ≥95 → ratio ~0.85 |
| español | G5 (fix instrumento) | 72 | resto = contenido/capacidad |
| estructurado JSON | diag_json ×72 | 98.6 (GBNF) | formato resuelto por construcción |
| identidad | G3 ×20 | 100 (3B y 4B) | eje propio, GLM no aplica |
| math competencia | (SIN SUITE — crear si E3 avanza) | — | VibeThinker AIME25 74.4 de card |
| generación libre larga / conocimiento abierto / ctx>16k | SIN SUITE | — | **aquí vive el grueso de la brecha real; sin suite no se maquilla: se declara ~20-30/100** |

## El número honesto compuesto (v1, mismo criterio que la respuesta al dueño)

- Nicho del producto (ejes tabla 1 + G2R/G5/JSON): **~75-80/100**.
- Aspectos GENERALES (ponderando los ejes sin suite donde la brecha es de
  capacidad cruda): **~35/100**.
- Meta de esta corrida: mover el compuesto midiendo ANTES/DESPUÉS con las
  MISMAS suites: código duro RAW (E1), código duro prod, G2R (E3 vote),
  math (nueva suite si E3 pasa). Todo delta se reporta pareado.

## Protocolo de re-medición (post-estrategias)

1. E1: results_e1_qwen35_hard.json (RAW ×40) vs 15/40 del 3B.
2. E2: BoN cross-family vs BoN 3B-only, mismas 40, pareado McNemar.
3. E3: majority-vote inter-familia en G2R vs stepwise v2 (82), pareado.
4. e2e: batería 17/17 + camino feliz 5/5 (sin regresión = gate duro).

---

## DESPUÉS (2026-07-12, corrida COLONIA→CASI-GRANDE ejecutada)

| eje | antes | después | evidencia |
|---|---|---|---|
| código duro (techo de la colonia, ocultos) | 57.5% (cascada 2 etapas) | **67.5%** (27/40, cascada 3 etapas c/Qwen3.5) | unión medida + etapa 3 desplegada + e2e DBG1 PASA ocultos |
| razonamiento G2R-40 | 82 (3B+stepwise) | **92.5** (ruteo→qwen3_4b crudo, McNemar p≈0.0000) | audit + wiring + live check (Beto=10) |
| español G5 | 72 | 72 (sin cambio: qwen35 92% n.s. p=0.125, 17.7 s/ítem) | decisión honesta documentada |
| vs ref GLM 5.2 código duro (~50%) | 115% capado | **135% capado** | mismo protocolo del gate 7B |

**Compuesto honesto actualizado**: nicho del producto ~**82/100** (razonamiento
saltó, código duro subió el techo); aspectos GENERALES ~**38/100** — el grueso
de la brecha sigue en capacidad cruda (conocimiento abierto, generación libre
larga, ctx>16k) que ninguna orquestación de ≤7B compra. El delta de la corrida
es real y medido: +10pp de techo en código duro, +10.5pp en razonamiento.

---

## v3 (2026-07-12 tarde, corrida TALLER SÚPER EFICIENTE)

Sin cambio en los números de capacidad (el techo del set duro sigue en
27/40): la corrida pagó en EFICIENCIA e HIGIENE, no en pp:
- `--cache-ram` 8192→1024 MiB por server (riesgo de swap/OOM latente con
  3-4 servers coexistiendo, verificado contra el binario pineado).
- Telemetría descontaminada (los unit tests escribían registros falsos al
  ledger de calibración; no-op bajo pytest + limpieza con backup).
- E-FEWSHOT: 8ª negativa limpia (el few-shot de biblioteca propia REGRESA
  al 3B; señal débil SPEC1/SPEC4 registrada con condición de reapertura).
- Presupuesto adaptativo: DIFERIDO por datos insuficientes (27 filas
  reales; el turno nocturno debe acumular tráfico antes de calibrar).
