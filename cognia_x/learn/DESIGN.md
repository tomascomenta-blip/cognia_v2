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

## Mecanismo creativo (ir más allá): curiosidad por sorpresa + ancla de Fisher
- **Aprender solo lo SORPRENDENTE.** `forward()` ya da la pérdida por-byte; se aplica gradiente solo
  donde la sorpresa supera `EMA + k·sigma` (poniendo `target=-100` en lo no-sorprendente). Concentra
  el escaso presupuesto de CPU en el ~10% novedoso y **no arrastra** los pesos en el 90% redundante
  (de donde venía casi todo el daño a lo viejo).
- **Ancla de Fisher gratis.** Adam ya calcula `exp_avg_sq` ≈ diagonal de Fisher; se usa como peso de
  una penalización `λ·F·(θ−θ_viejo)²`: lo importante para lo viejo se vuelve **rígido**, lo trivial
  **plástico**. Previene el olvido en cada paso, no post-hoc.

## El loop (Nivel 1) y la demostración
`cognia_x/learn/continual.py` (gate) + `run_cycle8.py` (demo). Montaje: base sabe inglés+español;
aprende inglés nuevo (examinado cross-book en un libro inglés hermano). Aprender inglés ayuda al
inglés viejo pero **daña el español** → el gate AGREGADO acepta (ciego), el **POR-DOMINIO lo atrapa**,
y **+replay** aprende sin olvidar. Objetivo científico: **dar vuelta `H-SELF-2`** mostrando que un
gate NO-circular + por-dominio sí reduce la deriva.

> Honestidad: una corrida valida el **mecanismo** (detección + rollback), no garantiza ausencia de
> olvido a escala; los umbrales (k·sigma, cuotas, λ) hay que calibrarlos empíricamente (multi-seed).
