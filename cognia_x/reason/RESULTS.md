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
