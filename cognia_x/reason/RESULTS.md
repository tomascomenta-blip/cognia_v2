# CYCLE 12 — La IA aprende a RAZONAR: prueba cadenas y se queda con la que funciona

Pilar 5 (Razonamiento). La IA enfrenta **problemas cotidianos** (dividir una cuenta con propina, qué
paquete sale más barato por kilo, cuántos viajes entran en un presupuesto, si llego a tiempo) y los
resuelve con **distintas cadenas de razonamiento** (estrategias). Ninguna estrategia es mejor para
todo. La IA prueba cadenas, un **examinador REAL** (o **preguntándole al usuario**) le dice cuál
acertó, y **aprende qué cadena usar según el tipo de problema** — y generaliza a problemas nuevos.

Es el mismo principio que cerró el aprendizaje continuo (CYCLE 8/11): **solo se aprende lo que
sobrevive a un examinador NO circular.** Aquí ese principio se aplica a la *selección de razonamiento*.

## Las 5 cadenas (estrategias) y su competencia por tipo (held-out)
Cada cadena es un procedimiento real con un error característico fuera de su "tipo casa":
- `direct` — intuición de un tiro (ignora la propina, ignora la tarifa fija). Rápida, falla en multi-paso.
  Es además un **fanfarrón**: reporta confianza ~0.95 SIEMPRE, aun equivocada (miscalibrada a propósito).
- `stepwise` — descomposición paso a paso (aplica propina y luego divide) → gana `split_bill`.
- `backwards` — razona hacia atrás desde la restricción (saca la tarifa fija, redondea) → gana `trips`.
- `unit_rate` — normaliza a precio por unidad → resuelve `cheaper_per_kg`.
- `decision` — estima y decide → resuelve `arrive_on_time`.

## Resultado FULL (train=4000, held-out=2000, semillas disjuntas)
| brazo | accuracy held-out | nota |
|---|---:|---|
| fija direct | 0.432 | el fanfarrón: confiado y flojo |
| fija stepwise | 0.632 | |
| **fija backwards** | **0.793** | la mejor cadena ÚNICA |
| fija unit_rate | 0.562 | |
| fija decision | 0.562 | |
| RANDOM | 0.592 | |
| **router CONFIDENCE** (circular) | **0.432** | el fanfarrón lo secuestra |
| **router VERIFIER** (examinador real) | **1.000** | aprende qué cadena por tipo |
| ORACLE (mejor por instancia) | 1.000 | cota superior |

**Lo que demuestra:**
1. **Ninguna cadena domina.** `backwards` (mejor fija, 0.793) ACIERTA cheaper/trips/arrive pero
   FALLA `split_bill` (0.19). Por eso *elegir bien la estrategia* es lo que importa.
2. **El router con examinador REAL aprende a razonar.** Aprendió el mapa tipo→cadena
   (`split_bill`→stepwise, `trips`→backwards, etc.), **supera a toda cadena fija (1.000 vs 0.793) y
   alcanza el oracle**, y **generaliza** a problemas nuevos (held-out de semillas disjuntas: no
   memorizó respuestas, aprendió qué forma de pensar aplica a cada situación).
3. **Anti-Goodhart (la lección del lab, en razonamiento).** Si la IA aprende por su PROPIA
   confianza (señal circular), el fanfarrón `direct` secuestra la política (la elige para los 4
   tipos) y la accuracy se desploma a 0.432. El examinador NO circular lo desenmascara. — mismo
   patrón que [CYCLE 8/11]: solo cuenta lo que sobrevive al examinador real.
4. **"Preguntarle al usuario" con presupuesto.** Cuando el router está genuinamente inseguro de un
   tipo (las dos mejores cadenas empatadas), consulta al usuario (oráculo) — pero bajo presupuesto.
   Curva de preguntas por bloque: **[198, 2, 0, 0, 0, 0, 0, 0, 0, 0]** — pregunta MUCHO al
   principio y deja de preguntar cuando ya aprendió, manteniendo la accuracy alta. Aprende a
   preguntar solo cuando le sirve.

## Caveats (honestidad)
- Solvers deterministas y las cadenas "casa" son exactamente correctas → oracle = 1.0 y el
  router-verifier toca un techo perfecto en esta suite sintética. Limpio para el MECANISMO, no es
  una afirmación sobre razonamiento real ruidoso.
- En `cheaper_per_kg` tanto `backwards` como `unit_rate` aciertan al 100% → el router eligió
  `backwards` por empate legítimo, no por bug. Lo demostrado es tipo→cadena-competente, no una etiqueta única.
- Semilla dominante única (problemas deterministas); sin bandas de varianza multi-seed. Existe el
  camino UCB; el run por defecto usa epsilon-greedy.
- "Preguntar al usuario" usa el verificador como oráculo perfecto; un humano real sería más ruidoso/caro.

## Innovación
No es best-of-N por instancia ni self-consistency: es un **router de meta-razonamiento aprendido
online, anclado a un examinador no circular**, que aprende *qué estrategia de razonamiento desplegar
según el tipo de problema*, generaliza a problemas nuevos, y **escala a la pregunta-al-usuario bajo
presupuesto**. Es la pieza que envolverá las cadenas del LM cuando sea más inteligente (hoy probado
sobre solvers de competencia conocida para que el resultado sea medible y limpio).

Reproducir: `python -m cognia_x.reason.run_cycle12` (full) / `--smoke` (rápido).
Test: `python -m pytest cognia_x/tests/test_cycle12_reason.py -q`. Datos: `runs/cycle12/`.

---

# CYCLE 13 — Razonar en el régimen REALISTA: el examinador a veces miente, y a veces no sabés lo que no sabés

CYCLE 12 mostró el router de meta-razonamiento en una suite determinista con **techo PERFECTO**
(oracle = 1.0, examinador siempre correcto). Su debilidad honesta. CYCLE 13 empuja el razonamiento a
dos robusteces de TODOS LOS DÍAS, **construidas sobre el mismo router, las mismas cadenas y el mismo
verificador** (se extendió, no se reescribió):

## Problema A — el usuario a veces te contesta MAL (oráculo RUIDOSO)
"Le preguntás a alguien y a veces te contesta mal." Cada vez que el router "pregunta", el veredicto es
correcto con prob `(1-p_noise)` y se FLIPEA con prob `p_noise`.
- **blind-single** (pregunta UNA vez y confía ciego): la PRIMERA respuesta por tipo FIJA la cadena
  desplegada. Si esa única respuesta fue ruidosa → aprende el mapa tipo→cadena EQUIVOCADO y no se corrige.
- **robust-aggregate** (la innovación de casa: *"preguntá a varios y quedate con lo que más se
  repite"*): K votos por cadena + acumular sobre muchos intentos. La **ley de los grandes números**
  promedia el ruido y la estimación converge a la competencia real → recupera el mapa correcto.

### Barrido de ruido — accuracy HELD-OUT (FULL: train=4000, held-out=2000, media de 15 semillas)
| p_noise | blind-single (confía ciego) | robust-aggregate (vota K=5) |
|---:|---:|---:|
| 0.00 | 0.943 | **1.000** |
| 0.20 | 0.806 | **1.000** |
| 0.40 | 0.723 | **1.000** |

**Lo que demuestra:** blind-single **se degrada monótonamente** a medida que sube el ruido (0.943 →
0.806 → 0.723: una respuesta envenenada fija una cadena equivocada para todo un tipo), mientras
robust-aggregate **se mantiene en 1.000** aunque cada respuesta individual falle hasta el 40% de las
veces. El voto mayoritario + la acumulación protegen la política aprendida (LLN).

## Problema B — un TIPO nunca visto (fuera-de-distribución: saber lo que no sabés)
Se agregó un 5º tipo NUEVO, `discount_better` (un producto a $P, oferta A = X% off vs oferta B = $Y
off → cuál ahorra más), presente **SOLO en el test, nunca en el entrenamiento**. `backwards` y
`unit_rate` lo resuelven perfecto (pasan el % a dinero real); `direct`/`stepwise`/`decision` se dejan
engañar por el número más grande (~0.68).
- **naive** (rutea confiado sin escalar): no tiene evidencia para el tipo nuevo → elige por stats
  vacías y falla seguido (**acc 0.679**).
- **escalación** (sabe que no sabe): cuando la mejor cadena de un tipo tiene poca evidencia (o las dos
  mejores empatan **cerca del azar**, no un empate competente legítimo), ESCALA = pregunta al oráculo
  y aprende, en vez de adivinar.

### Ask-rate por tipo (cuánto PREGUNTA) y accuracy en el tipo nuevo (FULL)
| tipo | ask-rate | nota |
|---|---:|---|
| familiar split_bill / cheaper_per_kg / trips / arrive | **0.000** | ya competente: no pregunta |
| **NUEVO discount_better** | **0.010** | escala ~8 veces y deja de preguntar al aprenderlo |

| router en el tipo NUEVO | accuracy |
|---|---:|
| naive (adivina) | 0.679 |
| **con escalación** | **1.000** |

**Lo que demuestra:** el router **pregunta solo en el tipo que no conoce** (ask-rate >> familiares,
que es 0) — está calibrado ("sabe lo que no sabe") — y tras unas pocas escaladas **aprende el tipo
nuevo** y lo resuelve perfecto (0.679 → 1.000). En los tipos familiares, donde ya tiene competencia,
no malgasta preguntas.

## Caveats (honestidad)
- **blind-single en p_noise=0 ya da 0.943, no 1.000:** una sola respuesta (aunque limpia) puede
  endosar una cadena empatada o sub-óptima. Es honesto: confiar en una sola respuesta es frágil aun
  sin ruido. El promedio sobre 15 semillas evita reportar una corrida con suerte (blind es estocástico).
- **robust-aggregate toca 1.000 porque las cadenas "casa" son exactamente correctas** (mismo techo
  sintético que CYCLE 12). Lo demostrado es el MECANISMO de robustez al ruido, no una afirmación sobre
  razonamiento real.
- **La ask-rate OOD absoluta es baja (0.010):** el router solo necesita ~8 escaladas para separar las
  cadenas competentes; con 800 problemas OOD eso es 1%. Lo que importa es el CONTRASTE (>> 0 familiar)
  y que la accuracy se recupere, no la magnitud.
- El umbral de empate "competente" (acc top1 < 0.75 dispara duda) es una constante de diseño; calibra
  "empate cerca del azar" vs "dos cadenas ambas buenas". Funciona para esta suite; no es universal.
- El oráculo ruidoso flipea el veredicto de forma simétrica; un humano real tendría sesgos y costos
  asimétricos.

## Innovación
Lleva el router de meta-razonamiento de CYCLE 12 al régimen donde el examinador **NO es perfecto**:
(A) robustez al ruido del oráculo vía **agregación/voto** anclada en la ley de los grandes números, y
(B) **calibración de incertidumbre OOD** ("sé que no sé" → escalo) que detecta un tipo nunca visto y
lo aprende preguntando con presupuesto. Es la misma lección no-circular del lab (solo cuenta lo que
sobrevive a un examinador real), ahora endurecida contra un examinador que a veces miente y contra
problemas que nunca viste.

Reproducir: `python -m cognia_x.reason.run_cycle13` (full) / `--smoke` (rápido).
Test: `python -m pytest cognia_x/tests/test_cycle13_reason.py -q`. Datos: `runs/cycle13/`.

# CYCLE 14 — Componer cadenas: cuando NINGUNA forma sola de pensar alcanza

CYCLE 12/13 tenían una brecha honesta: TODO problema se resolvía con UNA sola cadena (oracle = mejor
cadena por instancia). CYCLE 14 cierra el sentido literal de "cadenas de razonamiento": problemas
**COMPUESTOS** donde la respuesta necesita el OUTPUT del paso 1 como ENTRADA del paso 2, así que la IA
tiene que aprender a **ENCADENAR** estrategias en una secuencia (un pequeño "programa de razonamiento")
y DESCUBRIR la secuencia correcta probando y verificando. Construido **sobre** las cadenas y el
verificador del lab (se extendió: `gen_composed` aparte, step-chains nuevas; cycle12/13 byte-a-byte iguales).

## Los problemas compuestos (cada uno = 2 pasos, ground-truth computable)
- **afford_packs**: paso 1 = ¿qué paquete es más barato por kg? (tasa/comparación) → su precio;
  paso 2 = ¿cuántos del más barato entran en el presupuesto restando un envío fijo? (hacia atrás, floor).
- **split_then_check**: paso 1 = dividir la cuenta con propina entre N (paso-a-paso) → cuota por persona;
  paso 2 = ¿esa cuota supera un límite L? (decisión/umbral, 0/1).
- **stock_then_days**: paso 1 = consumo diario = personas × unidades/día (paso-a-paso) → consumo;
  paso 2 = ¿cuántos días enteros alcanza el stock? (hacia atrás, floor).

El **modelo de ejecución** es concreto: un programa es una tupla de step-chains; el paso 1 corre con
`intermediate=None` y produce un número; cada paso siguiente recibe ese número por un argumento y lo
CONSUME. La predicción del programa es el valor del ÚLTIMO paso. Las step-chains de paso-2
(`backwards`, `decision`) SIN intermedio no tienen de qué partir → fallan: por eso una sola op no basta.

## Resultados — accuracy HELD-OUT en tipos compuestos (FULL: train=4000, held-out=2000, programas long≤2 = 30)
| estrategia | accuracy held-out |
|---|---:|
| cadena fija de UN paso (cualquiera de las 5) | **0.196** |
| composer CONFIDENCE (circular) | 0.425 |
| **composer VERIFIER (examinador real)** | **1.000** |
| ORACLE (mejor programa por instancia) | 1.000 |

### Programas DESCUBIERTOS por el composer (VERIFIER), tipo → secuencia
| tipo compuesto | programa aprendido |
|---|---|
| afford_packs | `("unit_rate", "backwards")` |
| split_then_check | `("stepwise", "decision")` |
| stock_then_days | `("stepwise", "backwards")` |

**Lo que demuestra:**
1. **Ninguna cadena sola resuelve los compuestos** (todas ~0.196, solo aciertos accidentales) → la
   composición es NECESARIA, no un lujo.
2. El **composer aprendido DESCUBRE el programa correcto por tipo** (la tabla de arriba es exacta),
   supera a toda cadena fija y **alcanza el oráculo** (1.000) sobre problemas NUEVOS (semillas disjuntas)
   → aprendió a componer y GENERALIZA.
3. **Verificador-anclado, no circular**: el composer premiado con la CONFIANZA auto-reportada (circular)
   es secuestrado por programas con el paso fanfarrón (`step_direct`, conf ~0.95): elige `("direct",)`
   para los tres tipos y cae a **0.425**. Misma lección no-circular de CYCLE 12, ahora en el espacio de
   secuencias: solo cuenta lo que sobrevive a un examinador REAL.

## Caveats (honestidad)
- **El composer VERIFIER toca 1.000 porque el espacio long≤2 contiene EXACTAMENTE el programa correcto
  y las step-chains "casa" son exactas** (mismo techo sintético que CYCLE 12/13). Lo demostrado es el
  MECANISMO — descubrir una SECUENCIA por verificación — no una afirmación de escala. Con 30 programas
  la búsqueda es chica y la converge sin esfuerzo; el punto es el mecanismo, no el tamaño.
- **El contraste de confianza no es un secuestro perfecto a 0.000**: `step_direct` acierta por accidente
  parte de las veces (de ahí 0.425, no 0.196 ni 0.000). Igual queda MUY por debajo del verificador
  (1.000) → la dirección y la magnitud de la lección se sostienen.
- Cada compuesto tiene UN único programa perfecto en este diseño; problemas reales tendrían varios
  caminos válidos y pasos ruidosos. La búsqueda sobre secuencias largas (>2) crece exponencial y pediría
  poda/UCB — fuera de alcance acá.

## Innovación
Lleva el router de meta-razonamiento de CYCLE 12/13 a problemas que **ninguna cadena sola resuelve**:
el "brazo" del bandit pasa de una cadena a una **SECUENCIA de cadenas** (un programa), ejecutada
encadenando intermedios, y descubierta por el **verificador real**. Cierra el sentido literal de
"cadenas de razonamiento" — componer estrategias — manteniendo la regla del lab (solo cuenta lo que
sobrevive a un examinador no-circular).

Reproducir: `python -m cognia_x.reason.run_cycle14` (full) / `--smoke` (rápido).
Test: `python -m pytest cognia_x/tests/test_cycle14_reason.py -q`. Datos: `runs/cycle14/`.

---

## CYCLE 15 — ROMPER el techo perfecto: competencia GRADUADA (oráculo < 1.0, brecha honesta)

**Esto RETIRA el caveat repetido de CYCLE 12/13/14** ("mecanismo, no escala; techo sintético perfecto").
Aquellos ciclos tocaban TODOS 1.000 porque los solvers eran deterministas y exactos → oráculo=1.0 y
política=1.0. El objetivo del dueño ("ve cuál le da mejores resultados") solo tiene sentido medido en una
escala GRADUADA, no binaria-perfecta. CYCLE 15 introduce dureza real y controlable para que **ninguna
estrategia sea perfecta**, el **oráculo caiga por debajo de 1.0**, y la cercanía del router al oráculo pase
a ser un número con significado.

### Mecanismo (real y documentado, no maquillado)
- **Dificultad variable** (`gen_graded`, opt-in): cada problema trae `params["difficulty"]` ∈ [0,1] y se
  ENDURECE (`_harden`) acercando la decisión al FILO según la dureza — comparaciones casi-empatadas
  (precio por gramo, ahorro de descuentos), plazos al filo, presupuestos justo sobre un múltiplo entero de
  viajes. La verdad-base se recomputa consistente (nunca empate exacto → sigue nítida).
- **Competencia estocástica/parcial** (`graded_chain` en `chains.py`): cada cadena ACIERTA su tipo "de
  casa" con prob `COMPETENCE_HOME=0.92` (ya no 1.0) y `0.55` fuera de casa, y esa competencia BAJA con la
  dificultad (`-0.35 × difficulty`). Si no acierta, PATINA de forma realista: redondeo/estimación en
  continuos (split_bill), flip en decisiones 0/1, ±1 en conteos. El patinazo es **determinista por
  (cadena, instancia)** (semilla derivada del contenido) → oráculo, fija y router ven el MISMO mundo y la
  comparación es JUSTA. `random.Random` local, nunca el global.
- **Opt-in total**: `gen_problems`/`gen_composed` y `CHAINS` NO cambian. `Router(..., graded=True)` es nuevo
  y por defecto `False`. **CYCLE 12/13/14 corren byte-a-byte iguales** (verificado: los tres siguen en 1.000).

### Resultados — accuracy HELD-OUT GRADUADO (FULL: train=8000, held-out=4000, dificultad [0,1])
| estrategia | accuracy held-out |
|---|---:|
| mejor cadena FIJA (`stepwise`) | 0.403 |
| router CONFIDENCE (circular) | 0.307 |
| **router VERIFIER (examinador real)** | **0.746** |
| router VERIFIER + PREGUNTAR (presupuesto) | 0.802 |
| **ORACLE (mejor cadena por instancia)** | **0.887** ← *ahora < 1.000* |

**BRECHA AL ORÁCULO (oracle − router VERIFIER) = 0.141** — el número titular "qué tan bueno es el
razonamiento aprendido". (Smoke da cifras del mismo orden: oracle ~0.89, router ~0.74, gap ~0.15.)

**Lo que demuestra:**
1. **ORACLE = 0.887 < 1.000**: con dureza real, incluso la mejor cadena por instancia patina a veces →
   hay techo alcanzable real y HEADROOM. El "techo perfecto" quedó RETIRADO.
2. **La mejor cadena FIJA (0.403) queda muy por debajo del oráculo** → elegir bien sigue importando, y
   ahora con margen medible.
3. **El router VERIFIER (0.746) le gana a TODA cadena fija y se acerca al oráculo SIN alcanzarlo**
   (brecha 0.141). Rutea bien (aprende el mapa tipo→cadena de casa correcto) pero la cadena de casa
   IGUAL patina en instancias duras — de ahí la brecha honesta. No está maquillado: es lo que cae del
   setup realista.
4. **Anti-Goodhart se sostiene bajo grading**: el router CONFIDENCE (circular) lo secuestra el fanfarrón
   (`chain_direct`, conf ~0.95) y cae a 0.307 (peor que varias fijas).
5. **Preguntar bajo presupuesto cierra PARTE de la brecha** (0.746 → 0.802 hacia 0.887): el presupuesto se
   gasta SOLO en las instancias donde el router base falló, y como el patinazo es por (cadena, instancia),
   consultar otras cadenas vía el verificador real rescata varias. No cierra toda la brecha (presupuesto
   acotado) → honesto.

### Caveats (honestidad)
- La brecha del router (0.141) viene del PATINAZO, no de mal ruteo: el mapa tipo→cadena aprendido es el
  correcto; la cadena de casa simplemente no es perfecta en lo duro. Es exactamente el régimen no-trivial
  que se buscaba.
- Los números concretos dependen de los parámetros de competencia (`COMPETENCE_HOME/AWAY`,
  `DIFFICULTY_PENALTY`) — están elegidos para un régimen realista (oráculo ~0.85–0.90), no para que el
  router se vea perfecto. Mover esos parámetros mueve el oráculo y la brecha de forma predecible.
- Sigue siendo CPU-only, stdlib, solvers sintéticos: lo demostrado es el MECANISMO de medir "qué razonar
  da mejores resultados" en una escala graduada creíble, no una afirmación de escala a LLMs reales.

### Innovación
Convierte el pilar de meta-razonamiento (CYCLE 12–14) de un juguete de techo perfecto a un régimen
**creíble y graduado**: dificultad por instancia + competencia estocástica que decae con la dureza, con
patinazo determinista por (cadena, instancia) para una comparación justa. El verdicto deja de ser "todo
1.000" y pasa a una **brecha medible al oráculo** — el número honesto que responde "qué tan bueno es el
razonamiento aprendido".

Reproducir: `python -m cognia_x.reason.run_cycle15` (full) / `--smoke` (rápido).
Test: `python -m pytest cognia_x/tests/test_cycle15_reason.py -q`. Datos: `runs/cycle15/`.
