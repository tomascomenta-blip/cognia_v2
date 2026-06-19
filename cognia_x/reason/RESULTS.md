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

---

## CYCLE 16 — SACAR LA MULETA: rutear desde el TEXTO, no desde la etiqueta de tipo

**Esto RETIRA la muleta de CYCLE 12–15.** En todos esos ciclos al router le PASABAN el `problem["type"]`
como label (routeaba sobre la etiqueta). Razonar de verdad es DARSE CUENTA qué clase de problema tenés
enfrente leyendo el enunciado. CYCLE 16 saca la muleta: el router solo ve `problem["text"]` (el string que
ya producen los generadores) y debe INFERIR cómo razonar.

### Mecanismo (concreto, stdlib, sin tocar CYCLE 12–15)
- **`text_router.features(text)`**: extrae señales BARATAS del texto CRUDO — flags de palabras clave
  ("propina", "$ por g", "viaje/tarjeta", "km/h", "descuento/oferta", "stock/por día", "supera/límite",
  "envío"), presencia de `%`/`$`, formato de elección binaria, y un bucket discreto del conteo de números.
  **Recibe SOLO el texto; jamás `type` ni `answer`.**
- **`signature(text)`**: discretiza esas señales en una TUPLA de flags (la "firma" del problema). Problemas
  del mismo tipo caen en la misma firma sin que nadie diga el tipo.
- **`TextRouter`**: el MISMO bandit de CYCLE 12 (epsilon-greedy + verificador real) pero indexado por la
  FIRMA inferida del texto en vez del tipo. Reusa `Router` tal cual (la firma actúa como "tipo" interno) y
  premia con `is_correct` (la realidad, no la etiqueta). Así DESCUBRE la estructura de tipos desde el texto.
- **Opt-in total**: `Router` (routea por tipo), `chains.py`, `problems.py` NO cambian. **CYCLE 12–15 corren
  byte-a-byte iguales** (verificado: 12 toca 1.000; 13 escalación 1.000 en el tipo nuevo; 15 brecha ~0.136).

### Resultados — accuracy HELD-OUT (FULL: train=4000, held-out=2000, semillas disjuntas)
| estrategia | EXACTO (CYCLE 12) | GRADUADO (bonus, CYCLE 15) |
|---|---:|---:|
| mejor cadena FIJA | 0.793 (`backwards`) | 0.402 (`stepwise`) |
| router de TIPO (le DAN la etiqueta) — referencia superior | 1.000 | 0.738 |
| **router de TEXTO (infiere del enunciado)** | **1.000** | **0.738** |
| **BRECHA (router-TIPO − router-TEXTO)** | **0.000** | **0.000** |
| ALINEACIÓN firma->tipo (pureza) | 1.000 (4 firmas) | 1.000 (4 firmas) |

(Smoke da exactamente lo mismo: brecha 0.000, pureza 1.000.)

**Lo que demuestra:**
1. **El router de TEXTO IGUALA al router de TIPO sin que le digan el tipo** (brecha 0.000 en ambos
   regímenes) → infirió correctamente la clase de problema desde el enunciado. La muleta no era necesaria.
2. **Le gana ampliamente a la mejor cadena fija** (1.000 vs 0.793 exacto; 0.738 vs 0.402 graduado) →
   elegir cómo razonar sigue importando, y ahora lo hace leyendo el texto.
3. **Pureza firma->tipo = 1.000 con 4 firmas**: cada tipo cae en su propia firma → recuperó la estructura
   de tipos a partir del texto, sin supervisión de tipo.
4. **Bonus graduado**: aún cuando las cadenas PATINAN (CYCLE 15), inferir desde el texto no cuesta nada
   extra (misma accuracy y misma brecha 0.000 que el router de tipo). La brecha residual al ORÁCULO sigue
   siendo el patinazo (CYCLE 15), no el ruteo.

### Auto-auditoría (el router NUNCA lee type/answer)
La ÚNICA lectura del problema para rutear es el texto:
- `TextRouter._sig`: `return self.sig_fn(problem["text"])` (`text_router.py`), y `train_one` premia con
  `is_correct(problem, pred)` (verificador real, no la etiqueta).
- `features(text)` toma un solo argumento `text`; el test `test_features_only_depend_on_text` verifica la
  firma y que dos problemas con el MISMO texto pero distinto `type`/`answer` rutean a la misma firma.
- `signature_to_type_purity` SÍ mira `type`, pero solo para EVALUAR la alineación a posteriori — el router
  nunca lo usó para decidir.

### Caveats (honestidad)
- **Brecha y pureza perfectas (0.000 / 1.000) porque los enunciados sintéticos son genuinamente
  distinguibles.** No es maquillaje: cada tipo tiene vocabulario propio ("propina" vs "$ por g" vs "km/h"
  vs "tarjeta/viaje"). Corrimos un CONTROL HONESTO (`signature_blind`: features POBRES, solo conteo de
  números + `$`/`%`, sin vocabulario) y en este lab HASTA el control crudo separa los tipos (los textos
  difieren incluso en señales gruesas) → no hay confusión que reportar acá. En un dominio con enunciados
  ambiguos/solapados la pureza caería y la brecha se abriría; el control está listo para medir eso.
- Es un clasificador por FIRMA discreta (reglas de keywords), no un encoder aprendido. El punto demostrado
  es el MECANISMO: rutear sin la etiqueta de tipo, premiado por el verificador real, recuperando la
  estructura desde el texto. No es una afirmación de robustez a paráfrasis libres ni a LLMs reales.
- Sigue siendo CPU-only, stdlib, solvers sintéticos.

### Innovación
Cierra la última muleta del pilar de meta-razonamiento (CYCLE 12–15): el router ya no necesita que le
digan QUÉ clase de problema es. Extrae features baratas del enunciado crudo, descubre la estructura de
tipos por su cuenta (firma → bandit por firma) y aprende qué cadena usar por firma con el verificador real
— igualando al router que SÍ conoce el tipo (brecha 0.000), tanto en el régimen exacto como en el graduado.

Reproducir: `python -m cognia_x.reason.run_cycle16` (full) / `--smoke` (rápido).
Test: `python -m pytest cognia_x/tests/test_cycle16_reason.py -q`. Datos: `runs/cycle16/`.

---

## CYCLE 17 — rutear desde el TEXTO cuando el texto es DURO: paráfrasis + vocabulario ambiguo

**Retira el caveat de CYCLE 16.** CYCLE 16 ruteaba desde el texto pero llegó a una brecha PERFECTA
(pureza firma->tipo 1.000) porque cada tipo sintético usaba su PROPIO vocabulario único: hasta un control
crudo separaba los tipos. Demostró el MECANISMO, no la ROBUSTEZ a paráfrasis / redacción ambigua. CYCLE 17
hace el ruteo desde texto genuinamente DURO y muestra qué sobrevive.

### Lo que se construyó (opt-in; CYCLE 12–16 corren byte-a-byte iguales)
- **`gen_paraphrased(n, seed, ambiguity=...)`** (en `problems.py`): genera los 4 tipos base con MUCHAS
  formas de superficie — 4 plantillas por tipo + sinónimos por ranura (`amigos`/`compañeros`/`comensales`,
  `propina`/`de yapa`/`de tip`, `viaje`/`boleto`/`pasaje`...) + cláusulas reordenadas. Mismos params /
  MISMA answer / MISMO type label (el label se usa SOLO para evaluar held-out, jamás para rutear).
- **Knob `ambiguity` en [0,1]**: inyecta cláusulas DISTRACTORAS con vocabulario COMPARTIDO entre tipos
  ("ojo con el presupuesto", "salí de oferta", "compará bien por kilo", "no llegues tarde"...). A más
  ambigüedad, más solapamiento de palabras + más distractores -> una firma de keywords ingenua se confunde.
- **Arm A (frágil)**: el `TextRouter` de CYCLE 16 indexado por `signature_keywords` (firma de KEYWORDS
  pura, sin los buckets numéricos que igual separaban los tipos) — la representación que la paráfrasis ataca.
- **Arm B (robusto, la contribución)**: `RobustTextRouter` en `text_router.py` — un **Naive-Bayes
  multiclase** sobre **bag-of-words** del texto crudo, aprendido ONLINE con el verificador real. Una clase
  por cadena; estima `P(palabra | esta-cadena-acierta)` contando palabras de los enunciados que la cadena
  resolvió bien (premio = `is_correct`, nunca el label); predice `argmax_c sum_w log P(w|c)` con Laplace.
  Reparte la decisión sobre TODAS las palabras (las compartidas/distractoras no discriminan) -> tolera
  paráfrasis. **Recibe SOLO `problem["text"]`** (tokens vía `bag_of_words(text)`).

### Resultados — accuracy HELD-OUT vs AMBIGÜEDAD (FULL: train=4000, test=2000, semillas disjuntas, seed 0)
| ambig | mejor FIJA | A: keyword-frágil | **B: texto-robusto** | CEILING (tipo) | pureza-A (firma->tipo) | brecha A→ceil | brecha B→ceil |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.00 | 0.783 | 0.811 | **0.872** | 1.000 | 0.842 | 0.189 | 0.128 |
| 0.25 | 0.789 | 0.819 | **0.927** | 1.000 | 0.845 | 0.181 | 0.073 |
| 0.50 | 0.793 | 0.839 | **0.986** | 1.000 | 0.821 | 0.161 | 0.014 |
| 0.75 | 0.793 | 0.811 | **0.924** | 1.000 | 0.793 | 0.189 | 0.075 |
| 1.00 | 0.796 | 0.778 | **0.917** | 1.000 | 0.768 | 0.222 | 0.083 |

**Lo que demuestra:**
1. **El keyword-router FRÁGIL (A) confunde tipos al subir la ambigüedad**: pureza firma->tipo cae
   monótona **0.842 → 0.768** (< 1.0 en TODOS los niveles, ya con paráfrasis sin distractores). Su brecha
   al ceiling se queda en 0.16–0.22 (peor en ambigüedad máxima). El "almuerzo gratis" de CYCLE 16
   (pureza 1.000) DESAPARECE cuando el texto es duro: era vocabulario único, no robustez.
2. **El texto-router ROBUSTO (B) SIGUE al ceiling mucho mejor**: accuracy 0.872–0.986, brecha al ceiling
   **0.014–0.128** (vs 0.16–0.22 de A). **B le gana a A en los 5 niveles** (+0.06 a +0.15) y la ventaja
   CRECE con la ambigüedad (en ambig 1.0: brecha B 0.083 vs A 0.222). El Naive-Bayes sobre bag-of-words
   degrada suave porque promedia sobre muchas palabras; los distractores compartidos no discriminan.
3. El **ceiling** (router de TIPO, le DAN la etiqueta) es 1.000 en todos los niveles (la answer no cambia
   con la redacción) → es una cota honesta; B casi la toca a ambigüedad media.

### Auto-auditoría (ambos routers de texto leen SOLO el texto)
- `RobustTextRouter._words`: `return bag_of_words(problem["text"])` (`text_router.py`) — ÚNICA lectura del
  problema para rutear; `train_one` premia con `is_correct(problem, pred)` (verificador real, no el label).
- `bag_of_words(text)` y `signature_keywords(text)` toman un único argumento `text` (test
  `test_feature_extractors_only_depend_on_text`: mismo texto con distinto `type`/`answer` da idéntica
  bolsa/firma → imposible que hayan leído type/answer).
- `signature_to_type_purity` SÍ mira `type`, pero solo para EVALUAR la confusión a posteriori.

### Caveats (honestidad)
- **B no es infalible**: en ~2/12 semillas (5, 7) el Naive-Bayes PATINA en el arranque (la exploración
  epsilon sesga los conteos tempranos) y cae por debajo de A a ambigüedad alta. El patrón DOMINANTE
  (10/12 semillas) es B ≫ A por +0.06..+0.17. El test de regresión usa la semilla canónica (0); el barrido
  de 12 semillas está documentado acá y reproducible. No se maquilló el número: es degradación honesta.
- **A no colapsa en accuracy aunque la pureza caiga**: con firmas impuras, su bandit por firma todavía
  elige la cadena MAYORITARIA de cada firma, que acierta seguido → su accuracy baja poco aunque la
  pureza (su capacidad de DISTINGUIR tipos) sí se derrumbe. El daño honesto se ve en la pureza y en la
  brecha al ceiling, no solo en la accuracy cruda.
- Sigue siendo CPU-only, stdlib, solvers sintéticos y 4 tipos. No es una afirmación sobre LLMs reales ni
  paráfrasis en lenguaje natural abierto; es una demostración controlada de que un clasificador de palabras
  aprendido tolera la ambigüedad que rompe a las keywords exactas.

### Innovación
Cierra el caveat de paráfrasis de CYCLE 16: el ruteo desde texto ya no es un almuerzo gratis. Bajo
paráfrasis + vocabulario ambiguo, la firma de keywords exactas confunde tipos (pureza 1.000 → ~0.77),
mientras un Naive-Bayes sobre bag-of-words aprendido online con el verificador real degrada con gracia y
sigue al techo de "si supiera el tipo" — la robustez al fin se GANA, no se regala.

Reproducir: `python -m cognia_x.reason.run_cycle17` (full) / `--smoke` (rápido).
Test: `python -m pytest cognia_x/tests/test_cycle17_reason.py -q`. Datos: `runs/cycle17/`.

---

## CYCLE 19 — el char-LM ENTRENADO de verdad como ENCODER del router (primera vez que el pilar toca el modelo real)

### Qué pregunta
Todo el pilar de meta-razonamiento (CYCLE 12–18) ruteó desde features HECHAS A MANO: keywords (16),
bag-of-words Naive-Bayes (17). El caveat de pie de página de TODO el pilar: nunca tocó el MODELO real.
La frontera declarada (reason/README.md, manager/future_work.md): usar un ENCODER APRENDIDO de verdad.
CYCLE 19 lo ataca: usa el char-LM híbrido de CYCLE 7 (6.3M params, entrenado sobre LIBROS en/es — dominio
AJENO a estos problemas de cuentas) como ENCODER del enunciado, y lo compara honesto contra keywords (A) y
Naive-Bayes (B) sobre HELD-OUT parafraseado, a 3 niveles de ambigüedad.

Cómo (concreto):
- `forward_features(idx)` en hybrid.py expone los estados ocultos finales (post-`norm_f`, PRE-`lm_head`)
  sin tocar `forward()`/`generate()` → ningún ciclo previo cambia.
- `lm_embed(model, text)`: corre los BYTES del texto por el char-LM y devuelve `[mean-pool ‖ last-token]`
  de esos estados → vector fijo de **512 = 2·d_model** (d_model=256). no_grad, CPU, determinista.
- `LMRouter` (lm_router.py): clasificador **nearest-class-mean ONLINE** sobre los embeddings. Las clases
  latentes se descubren solas; el bandit de CYCLE 12 se indexa por la CLASE predicha y aprende qué cadena
  usar, premiado SOLO por el verificador real. Lee SOLO `problem["text"]` (vía `lm_embed`).
- **WHITENING (clave honesta):** los embeddings crudos del char-LM tienen una componente común enorme
  (coseno medio ~0.79 entre textos cualesquiera) que ahoga la señal de tipo → SIN whitening el NCM colapsa
  a 1 clase (pureza = 0.25 = azar). Estandarizamos por dimensión (z-score con stats marginales del train;
  NO miran el tipo) → la estructura de TIPO domina el coseno (off-diag pasa a span −0.56..0.99) y los tipos
  se separan. Es lo que deja ver lo que el modelo REALMENTE sabe del texto.

### Resultado REAL (FULL: train=1200/test=600 por nivel, semillas disjuntas)
| ambig | FIJA | A:keyword | B:NaiveBayes | **C:LM-embed** | CEILING(tipo) | pureza-A | **pureza-C** |
|------:|-----:|----------:|-------------:|---------------:|--------------:|---------:|-------------:|
| 0.00  | 0.787 | 0.718    | 0.928        | **0.750**      | 1.000         | 0.845    | **0.750**    |
| 0.50  | 0.787 | 0.762    | 0.930        | **0.787**      | 1.000         | 0.840    | **0.732**    |
| 1.00  | 0.798 | 0.687    | 0.952        | **0.787**      | 1.000         | 0.777    | **0.608**    |

(azar-de-cadena ~0.58 en los tres niveles; LM = 4→5→11 clases latentes.)

### Veredicto HONESTO: el encoder real AYUDA A MEDIAS — recupera estructura y le gana a keywords, pero NO le gana al Naive-Bayes ni a la mejor cadena fija
- **SÍ recupera estructura.** La representación del char-LM separa los tipos MUY por encima del azar
  (pureza clase→tipo 0.75 / 0.73 / 0.61 vs 0.25 de azar) — y eso es un char-LM **fuera de dominio**, que
  nunca vio una sola plantilla de estos problemas. Que un modelo de 6.3M entrenado sobre libros codifique
  la clase de un problema de cuentas en su estado oculto es el hallazgo positivo del ciclo.
- **Le GANA a las keywords (A) en accuracy en los 3 niveles** (0.750/0.787/0.787 vs 0.718/0.762/0.687) y es
  ESTABLE bajo ambigüedad (no se derrumba como A: 0.69 a ambig máx).
- **PERO pierde con el Naive-Bayes in-domain (B)** por un margen grande (B 0.93–0.95, imbatible acá) y solo
  **EMPATA a la mejor cadena fija** (~0.79). El char-LM off-domain no le saca jugo a su representación tan
  bien como un contador de palabras barato entrenado sobre el MISMO texto. Honesto: el almuerzo del encoder
  aprendido no es gratis cuando el encoder es chico y ajeno al dominio.
- **Fragilidad off-domain bajo ambigüedad alta y poco data.** A train=400, ambig=1.0 y semilla suelta, el
  router-LM cae POR DEBAJO del azar-de-cadena (0.545 < 0.585): la representación se confunde cuando hay
  pocas muestras y máximo solapamiento. El test de regresión mide la cota estable (ambig baja, train=500):
  C > azar y pureza > 0.25 con ≥2 clases. La fragilidad a ambig alta queda DOCUMENTADA, no maquillada.

### Por qué (interpretación)
El char-LM codifica la clase del problema (lo prueba la pureza), pero su señal está mezclada con la enorme
componente común del estilo prosa que aprendió de los libros — por eso necesita whitening solo para no
colapsar, y por eso un Naive-Bayes que cuenta las palabras DISCRIMINATIVAS directamente sobre el dominio le
gana. La lección: un encoder aprendido genérico **no domina** a features baratas in-domain salvo que esté
entrenado (o fine-tuneado) cerca de la tarea. Es el primer dato real del pilar sobre "encoder aprendido vs
features a mano": el encoder real ayuda contra keywords frágiles, no contra un modelo de palabras honesto.

### Verificación
- Checkpoint carga: `d=256 layers=8 params=6,328,576`; `lm_embed` → **shape (512,)**, determinista.
- `forward()` original intacto + `forward_features()` nuevo OK; cycle16/17 `--smoke` siguen corriendo igual;
  `charlm`/`run_cycle7` importan sin cambios.
- Self-audit: el router-LM lee SOLO el texto en `LMRouter._raw_embed`:
  `return lm_embed(self.model, problem["text"], device=self.device)`.
- Tests: `pytest cognia_x/tests/test_cycle12 test_cycle16 test_cycle17 test_cycle19 -q` → **13 passed**.
- Sigue CPU-only (threads=3), 4 tipos sintéticos. No es una afirmación sobre LLMs reales: es la primera
  medición controlada de "modelo entrenado de verdad como encoder del router" en este lab.

Reproducir: `python -m cognia_x.reason.run_cycle19` (full ~4 min) / `--smoke`.
Test: `python -m pytest cognia_x/tests/test_cycle19_reason.py -q`. Datos: `runs/cycle19/`.
