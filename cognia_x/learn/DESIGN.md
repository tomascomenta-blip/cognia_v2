# CYCLE 8 — Aprender e investigar por sí misma (diseño)

Cómo enseñamos a la IA híbrida de Cognia-X a **aprender texto nuevo sin olvidar lo viejo**, con
las soluciones a los 3 problemas derivadas por el método del lab: **transformación a problema
cotidiano** (analogía / reducción / everyday / primeros principios). Refinado por una revisión
adversarial (workflow de 5 lentes) que encontró fallos reales en la primera versión.

## La metáfora unificadora: el estudiante diligente

Los 3 problemas caen al MISMO principio cotidiano:

> Un buen estudiante **aprende de fuentes reales**, **repasa lo viejo**, y lo evalúa un
> **examinador independiente con preguntas no vistas, materia por materia** — y solo "aprueba" cada
> lección si pasa **sin bajar en ninguna materia anterior**.

## Los 3 problemas → cotidiano → mecanismo

### 1. Olvido catastrófico (aprender lo nuevo borra lo viejo)
**Cotidiano:** estudiar el cap. 2 y olvidar el cap. 1. Y peor: que tu *promedio* del boletín no baje
aunque saques 2 en historia, porque el 10 en lo nuevo lo tapa.
**Mecanismos:**
- **Compuerta POR-DOMINIO (no agregada).** El examinador toma cada materia vieja por separado; el
  do-no-harm exige que **ningún** dominio empeore (peor-caso, no promedio). *Esto es crítico: el gate
  agregado es CIEGO — el repo ya lo marcó `H-SELF-2 ❌false` "porque el evaluador era circular/no
  cubría la población dañada". Aquí el examinador es held-out cross-book REAL y por-dominio.*
- **Replay (repasar).** Mientras aprende lo nuevo, intercala un buffer de texto VIEJO real. Versión
  fuerte: **estratificado** (cuota igual por dominio, no proporcional) para proteger las
  sub-distribuciones raras (acentos, dígitos) que el muestreo uniforme deja caer.
- **Congelar el tronco / adapter (opcional, el más robusto).** Aprender lo nuevo solo en un adapter
  de rango bajo (LoRA) dejando el tronco congelado → el conocimiento viejo es **físicamente
  inmutable**: no hay que *detectar* el daño porque no puede ocurrir. (Compatible con la regla del
  repo: FedAvg/adapters solo sobre LoRA.)

### 2. Ley de Goodhart (la métrica se engaña)
**Cotidiano:** memorizar el solucionario en vez de entender; o un profe que se autoexamina con sus
propias preguntas y "siempre aprueba".
**Mecanismos:**
- **Examinador EXTERNO con material no visto.** Held-out **cross-book**: para saber si aprendió
  inglés-Frankenstein se le toma inglés-Drácula (otro libro del mismo dominio), no las últimas
  páginas de Frankenstein que ya leyó. Así "aprender" = generalizar, no memorizar.
- **Banda de incertidumbre (no un epsilon mágico).** El umbral se calibra contra el **ruido del
  propio examinador** (sigma medido con varios submuestreos): se exige mejora `> k·sigma`, no
  `> 0.001`. 5.1 vs 5.0 puede ser azar.
- **Concordancia de métricas (futuro).** Además de la pérdida, un check conductual (copy/recall
  exact-match) que el optimizador no minimiza directo. Aceptar solo si **ambas** concuerdan.

### 3. Colapso del modelo (entrenarse con su propia salida)
**Cotidiano:** fotocopia de una fotocopia; estudiar de tus propios apuntes mal copiados.
**Mecanismos (para el Nivel 2 "investigar sola"):**
- **Anclar a datos REALES.** El buffer de entrenamiento es texto real externo; el examinador es
  **siempre 100% real** (invariante de código). Si lo sintético empuja a la fotocopia, el val real
  sube y el rollback lo revierte solo.
- **Ledger de procedencia + cuota.** Cada trozo lleva `origin∈{real,syn}` y `generación g`; cuota
  dura `≤15% sintético`, y **nunca aprender nieto de sintético** (`g≤1`). "Nunca fotocopiar la
  fotocopia" como invariante de datos, no buena intención.
- **Verificar ANTES de aprender.** Lo auto-generado solo es elegible si pasa un verificador
  *chequeable contra la realidad*: si es código → sandbox + oracle (regla del repo: scan estático +
  sandbox con timeout; `cognia_v3/core/sandbox_tester.py`); si es texto → redundancia en ≥2 fuentes
  reales; filtro de degeneración (KL del histograma de bytes + gzip dentro de rango del corpus real).

## Mecanismo creativo (ir más allá): curiosidad por sorpresa — PROBADO y REFUTADO ❌
**Hipótesis:** aplicar gradiente solo a los bytes SORPRENDENTES (mayor pérdida = novedad) concentra
el presupuesto en lo nuevo y arrastra menos los pesos viejos → menos olvido a igual coste.
**Resultado (CYCLE 9, `run_cycle9.py`, smoke d=128):** REFUTADO. Las 3 variantes (top-k de pérdida,
banda 50-95, banda 70-97) dan **gain NEGATIVO** en el dominio nuevo (-0.11 a -0.42 vs naive +0.15) y
NO reducen el olvido del español. **Causa (primeros principios):** en un byte-LM la pérdida por-byte
NO separa "novedad generalizable" de "ruido/contexto"; entrenar un subconjunto de posiciones da un
gradiente más débil y sesgado → peor generalización. La supervisión DENSA aprende mejor. *Un fracaso
es información: la curiosidad-por-pérdida-cruda no sirve para este modelo.*

## Mecanismo creativo #2: CONGELAR EL TRONCO DE RECALL — PROBADO y FUNCIONA ✅ (modesto)
**Idea (cotidiano):** escribir lo nuevo en una hoja aparte sin tachar el cuaderno. Se congelan las
partes caras de RECORDAR (embeddings atados + capas de ATENCIÓN softmax = recall exacto) y se aprende
lo nuevo SOLO en las capas LINEALES + MLP plásticas. El conocimiento viejo del tronco congelado queda
protegido por construcción. (`freeze_recall_trunk` en continual.py.)
**Resultado (CYCLE 9, smoke d=128):** reduce el olvido del español **~25%** (+0.80 vs naive +1.06)
conservando **~94% del aprendizaje nuevo** (+0.143 vs +0.152). Mecanismo real, **parameter-free** y
**complementario al replay**. Modesto pero positivo — contrasta con la sorpresa (refutada).

**Pendiente (no probado):** ancla de Fisher/EWC-light y adapters LoRA (olvido imposible por
construcción, rollback = descartar adapter). La solución más fuerte validada es **gate por-dominio +
replay** (reduce el olvido 15× en el smoke); **congelar-tronco** la complementa sin coste de params.

## El loop (Nivel 1) y la demostración
`cognia_x/learn/continual.py` (gate) + `run_cycle8.py` (demo). Montaje: base sabe inglés+español;
aprende inglés nuevo (examinado cross-book en un libro inglés hermano). Aprender inglés ayuda al
inglés viejo pero **daña el español** → el gate AGREGADO acepta (ciego), el **POR-DOMINIO lo atrapa**,
y **+replay** aprende sin olvidar. Objetivo científico: **dar vuelta `H-SELF-2`** mostrando que un
gate NO-circular + por-dominio sí reduce la deriva.

> Honestidad: una corrida valida el **mecanismo** (detección + rollback), no garantiza ausencia de
> olvido a escala; los umbrales (k·sigma, cuotas, λ) hay que calibrarlos empíricamente (multi-seed).
