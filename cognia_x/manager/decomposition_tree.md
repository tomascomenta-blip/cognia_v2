# decomposition_tree.md — Árbol de descomposición raíz de Cognia-X (RESET v4)

> El artefacto que el prompt fundacional pedía como PRIMER paso y que no existía: la excavación
> recursiva de *"¿qué es realmente una inteligencia y por qué los enfoques actuales no llegan a la
> raíz?"*. Construido el 2026-06-24 por excavación multi-lente (6 lentes independientes) + auditoría
> adversarial por lente + síntesis, y **anclado contra el código del lab** (las lentes bajaron a los
> resultados reales y corrigieron 4 errores de fidelidad, ver §Correcciones). Conserva v1/v2/v3.
>
> Estatus de cada raíz: `convergente` (varias lentes bajan por caminos distintos = señal fuerte),
> `contestada` (lentes en conflicto), `síntoma` (degradada por la auditoría a capa intermedia).

## P0 — Marco (qué ES una inteligencia, podado a lo que sobrevivió a la auditoría)

> Una inteligencia es **un sistema auto-mantenido que, bajo recursos finitos y un mundo
> NO-estacionario, convierte experiencia escasa en competencia de predicción/control sobre
> situaciones nuevas — y para ello debe GENERAR su propio criterio de qué información importa.**

La pregunta-marco de cada lente ("¿es comprimir / predecir / adaptar / representar la raíz?") resultó,
según las 6 auditorías, un **proxy**. Detrás de los 6 árboles late un único hueco que todos rodean y
ninguno nombraba: **no existe una función de valor endógena que defina qué es "útil".**

## Las raíces (el árbol podado)

### R-VALOR — RAÍZ PRIMERA (convergente, 5/6 lentes)
**Ausencia de una teleología / función-de-valor ENDÓGENA que asigne valor a la información respecto de
un objetivo que el sistema persigue en el tiempo.**
- Baja de: predicción-compresión (utilidad exógena→endógena), adaptación-recursos (criterio aprendido
  de relevancia une R1/R3/R4/R5), agencia-causalidad (objetivo bajo intervención/shift), memoria-binding
  (rate-distortion temporal dirigido por utilidad predictiva), abstracción (Goodhart / proxy mal-alineado).
- Por qué es la raíz: comprimir es asimétrico; escribir/olvidar es selectivo; asignar cómputo exige
  saber dónde importa; consolidar exige saber qué proteger. **Todas son indefinibles sin un escalar de
  valor.** El valor de una traza = su información mutua esperada con consultas/recompensas FUTURAS.
- **No la resuelve un "verificador externo":** las 6 lentes se rescatan apelando a un examinador externo
  — el atajo que critican. El lab demostró verificador externo (exp017) ANTES del v4. **ACTUALIZACIÓN
  (corrida CYCLE 56-60): YA HAY evidencia POSITIVA de valor endógeno** — info-gain aislado del azar-activo
  con el instrumento fiel (exp042/H-V4-1b), medible por la CONFIANZA CALIBRADA del propio agente sin oráculo
  (exp043/H-V4-1c), con OLVIDO dirigido por valor en mundos no-estacionarios (exp044-045/H-V4-1d-1e), y
  PARCIALMENTE sustituyendo al verificador externo en la auto-mejora cuando el modelo está calibrado
  (exp046/H-V4-2i). Ver §Estado v4 tras la corrida 51-60.

### R-INTERVENCIÓN — convergente, fuerte  · **medida real en exp022 (CYCLE 35)**
**La estructura causal/invariante solo es identificable si la distribución generadora VARÍA — por
intervención do(X), múltiples entornos, o shift. Un corpus observacional fijo no la contiene (límite
INFORMACIONAL, no de capacidad).**
- Baja de: predicción-compresión R1, agencia RAIZ-1, adaptación R5 (no-estacionariedad).
- Corrección verificada: do(X) **NO requiere cuerpo** — un verificador-que-ejecuta ya es intervención
  (exp020 corre un lazo GRPO acción→consecuencia→update).
- **CYCLE 35 (exp022):** una política PASIVA sobre un corpus confundido queda **PLANA** bajo intervención
  por más presupuesto que reciba (flatness ~0.013); solo las políticas que INTERVIENEN cruzan a ~1.0.
  → R-INTERVENCIÓN pasa a techo **real** en el ledger.

### R-PRIOR — convergente, fuerte (la raíz mejor defendida adversarialmente)
**La inducción desde k ejemplos es sub-determinada (no-free-lunch): un prior fuerte es matemáticamente
necesario; su CALIDAD (no su forma) fija la eficiencia muestral.**
- "Programa más corto / MDL / búsqueda de programas" es UNA apuesta de diseño (incomputable, NFL), no la
  raíz. Lo irreducible: hace falta un prior fuerte y bien elegido; de dónde sale (evolución/desarrollo/
  cultura) es la rama ausente. Tensión exploración-de-estructura ↔ prior: explorar tiene costo muestral
  combinatorio que ningún sustrato evita salvo que el prior lo pode.

### R-SUSTRATO/CRÉDITO — contestada (núcleo sobrevive)
**El compromiso con asignación de crédito GLOBAL-diferenciable (backprop denso) se cuela sin
cuestionarse (supuesto colado #1 en 5/6 lentes).**
- Contestación dura (verificada como deriva): "online ⇒ local" y "backprop no puede online" se refutan
  con H-BIO-3 del lab (predictive-coding ~100× más caro en CPU). Lo que sobrevive: el sustrato
  denso-**síncrono** lo impone la ECONOMÍA DEL ENTRENAMIENTO (batch grande, compute-bound), no backprop
  per se. El falso dilema continuo-vs-discreto NO sobrevive.

### R-CAPACIDAD (techo de recall = d²) — SÍNTOMA, refutado por el propio lab
**Anclar la raíz en el techo de recall = d²/pigeonhole es citar un bound que el lab YA refutó**
(exp010: 16× el estado → +0.0003; Tipo D, suposición heredada). La raíz real debajo es R-VALOR (qué
vale la pena escribir) + el costo de optimización.

### R-COSTO-FÍSICO (bytes/token) — SÍNTOMA de régimen
Verificado (exp004/006) pero **acotado a inferencia batch-1-CPU**; a batch grande (donde se decide el
sustrato) es compute-bound (óptimo opuesto). "Landauer" estaba mal etiquetado (transporte ~pJ/bit, no
borrado). Es síntoma del lock-in económico hardware-software-incentivos.

## EL VERDADERO PRIMER PROBLEMA: R-VALOR
La ausencia de una función-de-valor **endógena** — un criterio, generado por el propio sistema
persiguiendo un objetivo en un mundo no-estacionario, de qué información merece predecirse, escribirse,
recordarse u olvidarse. Es la raíz que, resuelta, **desbloquea las demás a la vez**: cada raíz superior
es un caso de R-VALOR sin un valor que la aterrice.

> **Honestidad de confianza:** que R-VALOR sea la convergencia = confianza **ALTA** (5/6 lentes, robusto
> a auditoría). Que sea **resoluble** (que un valor endógeno sea construible y no solo otra reetiqueta de
> "meta externa") = confianza **BAJA**; es lo que el reset debe atacar empíricamente.

## Veredicto sobre la deriva (tesis previa del lab)
**"Bytes-por-token / híbrido" es un SÍNTOMA, no una raíz.** (1) Eficiencia sobre la familia conocida.
(2) Diagnosticada desde el régimen equivocado (inferencia batch-1; el sustrato se decide en
entrenamiento, compute-bound). (3) Síntoma del lock-in económico. El híbrido optimiza el transporte
dentro de un mínimo local; **no toca ninguna de las 3 raíces convergentes**. Sobrevive como restricción
de **viabilidad** (todo corre en CPU finita), NO como dirección a la raíz.

**Qué sobrevive de los 34 ciclos:** exp017 (verificador externo funciona — reinterpretado: marca dónde
está el hueco), exp001/004/006 (viabilidad CPU), exp010+C-02 (el lab ya refutó d² — honestidad
anti-Goodhart), y la **metodología research-as-code** (el activo más valioso). **Qué queda en cuestión:**
la tesis central como rumbo; toda raíz anclada en d²; las conclusiones de exp019/020 sobre reward-hack
(refutadas, citadas al revés por una lente); el rival nunca entretenido **inteligencia = control/acción**
(active inference / empowerment).

## Hipótesis v4 (backlog del reset) — ESTADO tras la corrida 51-60
- **H-V4-1 · P0** — valor endógeno (info-gain) vs predicción pasiva, bajo intervención, sin verificador
  externo. → **exp022/CYCLE 35: MIXTA** (R-INTERVENCIÓN demostrada; valor-específico no aislado).
- **H-V4-1b · P0** (hija) — aislar info-gain vs azar-activo en régimen duro. → **exp042/CYCLE 56: APOYADA.**
  El valor de info-gain se AÍSLA del de la actividad con el instrumento FIEL (post_on_cause, no accuracy, que
  saturaba y enmascaraba en exp022). La accuracy enmascaraba: ése era el bug de la MIXTA de CYCLE 35.
- **H-V4-1c · P0** (nueva) — proxy ENDÓGENO sin oráculo. → **exp043/CYCLE 57: APOYADA.** La confianza calibrada
  del agente (max posterior) rankea políticas igual que el oráculo y es confiable con la política correcta;
  el azar-activo da confianza engañosa (confiado-pero-equivocado).
- **H-V4-1d · P0** (nueva, R-VALOR×memoria) — olvido en no-estacionariedad. → **exp044/CYCLE 58: MIXTA.**
  Bajo commitment profundo + adaptación corta, el committed se atasca y el olvido FIJO adapta (parcial); sweet
  spot estabilidad-plasticidad. (Liga R-VALOR a H-V4-5.)
- **H-V4-1e · P0** (nueva) — olvido ADAPTATIVO por sorpresa. → **exp045/CYCLE 59: APOYADA.** Detección de
  cambio ENDÓGENA (olvida sólo cuando se contradice) -> trade-off estabilidad-plasticidad sin saber el punto
  de cambio. Une CYCLE 57 (sorpresa) + 58 (olvido).
- **H-V4-2 · P0** — identificabilidad causal SIN cuerpo. → cubierto por exp022 (R-INTERVENCIÓN). NOTA: el
  rótulo H-V4-2 también se usó para el ARCO de AUTO-MEJORA con verificador (CYCLE 48-55, H-V4-2*): el
  verificador (su corrección) es el motor; la guardia dedup+replay compra robustez (ruido ε*=0.50, cold-start,
  sesgo). Y **H-V4-2i/CYCLE 60: MIXTA** — la confianza endógena reemplaza PARCIALMENTE al verificador externo,
  gateada por calibración (conecta el arco de auto-mejora con R-VALOR).
- **H-V4-3 · P1** — calidad del prior > forma: equivarianza correcta iguala a MDL a fracción del costo. (ABIERTA.)
- **H-V4-4 · P1** — limpieza de deriva: techo de recall es de optimización (currículo mueve el plateau). (ABIERTA.)
- **H-V4-5 · P1** — escribir≡olvidar (rate-distortion dirigido por valor). → **PARCIAL (CYCLE 58-59):** el
  olvido dirigido por valor/sorpresa es necesario para adaptarse en no-estacionariedad; falta la ablación que
  ate explícitamente la memoria a R-VALOR (quitar la utilidad mata la ventaja).
- **H-V4-6 · P2** — limpieza: reward-hack no es la barrera temida (exp019/020 refutadas). (Reconfirmado por
  exp041/CYCLE 55: el sesgo sembrado no deriva runaway; la guardia defiende.)

## Correcciones de fidelidad que la auditoría cazó contra el código (no inventar, verificar)
1. El techo de recall = d² estaba refutado por exp010 (16× estado → +0.0003); citarlo como raíz es deriva.
2. "No hay do() en el repo" es FALSO: exp020 corre un lazo GRPO acción→consecuencia→update.
3. La lente agencia citó exp019/020 (REFUTADAS) como si confirmaran el reward-hack.
4. "Backprop es la patología / local es la cura" contradice H-BIO-3 (predictive-coding ~100× más caro en CPU).

## Las 6 lentes (entradas de excavación)
predicción-compresión · adaptación-bajo-recursos-finitos · agencia/causalidad/objetivos ·
física/termodinámica/eficiencia · abstracción/generalización-muestra-eficiente ·
memoria/representación/binding/tiempo. Detalle adversarial por lente: ver `research_log.md` (CYCLE 35) y
el journal del workflow `cogniax-v4-decomposition-tree`.

## Estado v4 tras la corrida 51-60 (síntesis — actualiza el thesis)
La corrida produjo DOS arcos verificados (10 ciclos, todos por las compuertas del engine, verify_no_loss=OK):

**ARCO VERIFICADOR-REAL (51-55) — el verificador externo y su robustez.** El lazo de auto-mejora con un
verificador chequeable REAL (sandbox que ejecuta la salida, no el oráculo aritmético) es robusto, y la GUARDIA
(dedup de verificados + replay limpio de la verdad) es el mecanismo central de robustez: generaliza del oráculo
exacto al verificador real (51), bootstrapea un base débil 0.08→0.93 (52), tolera ruido falso-positivo hasta
ε*=0.50 (53), ruido×cold-start coexisten (54), y defiende contra sesgo SISTEMÁTICO del verificador (55, MIXTA:
daño por pin no runaway). TESIS: el VERIFICADOR (su corrección) es el lever de 1ra clase; el tipo de oráculo no
importa; la guardia compra robustez.

**SUB-ARCO R-VALOR (56-59) — el lazo de valor ENDÓGENO (la RAÍZ PRIMERA), AHORA con evidencia POSITIVA.**
Primera demostración del lab de un valor endógeno (no un verificador externo): info-gain construye un modelo más
causal que la mera actividad, AISLADO con el instrumento fiel post_on_cause (56); el agente puede MEDIR ese
valor por su PROPIA confianza calibrada sin oráculo (57); el olvido dirigido por valor es necesario para
adaptarse en mundos NO-estacionarios (58), y el olvido ADAPTATIVO por sorpresa detecta el cambio sin supervisión
(59). El lazo de R-VALOR queda cerrado endógenamente: el sistema juzga QUÉ información vale (confianza calibrada)
y CUÁNDO dejó de valer (sorpresa → olvido), sin oráculo ni aviso externo. Esto MUEVE R-VALOR de "convergente
pero resoluble = confianza BAJA" (estado del reset) a "**resoluble con evidencia positiva en juguete = confianza
MEDIA**" (sigue pendiente la escala y un mundo no-de-juguete).

**UNIFICACIÓN (60) — los dos arcos se tocan por la CALIBRACIÓN.** La confianza endógena (R-VALOR) reemplaza
PARCIALMENTE al verificador externo del lazo de auto-mejora (arco 51-55), GATEADA por la calibración: usable
cuando el modelo está calibrado, peligrosa (refuerza errores confiados) cuando no. Confirma el CYCLE 57 en el
sustrato de auto-mejora.

**Qué queda (próximas raíces/hipótesis):** H-V4-3 (calidad del prior > forma) y H-V4-4 (techo de recall es de
optimización) siguen ABIERTAS. H-V4-5 (escribir≡olvidar) tiene evidencia PARCIAL (falta la ablación que ate la
memoria a R-VALOR). Escala: todo es en juguete (bayesiano numpy + HybridLM tiny); falta un mundo no-de-juguete y
un verificador de código real (gated por la capacidad del modelo tiny). Gating EXPLÍCITO por calibración
estimada (usar el filtro endógeno sólo donde es confiable) es el siguiente paso natural de la unificación.

## Estado v4 tras la corrida 61-66 (addendum — arco UNIFICACIÓN/gating + arco R-VALOR x MEMORIA)
Continúa la corrida 51-60. Otros 6 ciclos (61-66), todos por las compuertas del engine (verify_no_loss=OK), tests verdes.

**UNIFICACIÓN/gating (60-62):** la confianza endógena reemplaza PARCIALMENTE al verificador externo del lazo de
auto-mejora, GATEADA por la calibración (60, H-V4-2i MIXTA); el agente puede DECIDIR cuándo confiar en su
auto-consistencia estimando su calibración con un probe (62, H-V4-2j MIXTA: robusto/no-colapsa, pero la
estimación es ruidosa). (61 = consolidación.)

**Arco R-VALOR x MEMORIA (58·63-66) — el valor de QUÉ recordar/olvidar, todo de señales ENDÓGENAS:**
- 58 (H-V4-1d MIXTA): el olvido dirigido por valor adapta a UN cambio de causa donde el committed se atasca.
- 59 (H-V4-1e APOYADA): el olvido ADAPTATIVO por sorpresa detecta el cambio sin supervisión (óptimo para un cambio AISLADO).
- 63 (H-V4-1f APOYADA): en no-estacionariedad RECURRENTE el committed se atasca PROGRESIVAMENTE; el óptimo de
  olvido DEPENDE del régimen (constante para recurrente, surprise-gated para aislado).
- 64 (H-V4-1g MIXTA): el META-olvido (estima la tasa de cambio de su sorpresa y modula el decay) adapta en
  dirección correcta pero NO iguala el óptimo de cada régimen (asimétrico).
- 65 (H-V4-1h REFUTADA): un piso constante + sorpresa NO cierra el caveat -> el trade-off estabilidad-plasticidad
  es FUNDAMENTAL para un controlador que sólo modula la TASA de olvido.
- 66 (H-V4-1i APOYADA, CIERRE): un SELECTOR de ESTRATEGIA (clasifica el régimen de su sorpresa y CONMUTA
  committear<->olvidar-fuerte, decisión DISCRETA) alcanza el ÓPTIMO en ambos regímenes, lo que la modulación de
  tasa no pudo. El valor endógeno elige la ESTRATEGIA de memoria (modo), no la intensidad.

**TESIS del arco memoria:** R-VALOR no sólo decide QUÉ información vale y CUÁNDO deja de valer, sino CÓMO
recordar/olvidar -- y eso es una decisión de ESTRATEGIA (committear vs olvidar-fuerte) seleccionada del propio
régimen de no-estacionariedad, estimado de la sorpresa endógena. Liga R-VALOR (raíz primera) con MEMORIA
(escribir≡olvidar, H-V4-5): la confianza calibrada (qué vale) + la sorpresa (cuándo/cómo olvidar) son las dos
señales endógenas del lazo de valor.

**Estado de las hipótesis v4 (tras 51-66):**
- APOYADAS: H-V4-1b (info-gain aislado), H-V4-1c (confianza calibrada), H-V4-1e (olvido adaptativo), H-V4-1i
  (selector de estrategia), H-V4-2d (verificador real generaliza), H-V4-2e (bootstrap base débil), H-V4-2f
  (tolera ruido), H-V4-2g (ruido x cold-start).
- MIXTAS: H-V4-1d (olvido un cambio), H-V4-1f (recurrente), H-V4-1g (meta-olvido), H-V4-2h (sesgo verificador),
  H-V4-2i (auto-consistencia gateada), H-V4-2j (gate explícito).
- REFUTADA: H-V4-1h (piso constante + sorpresa).
- DIFERIDA: H-V4-4 (recall = optimización; el recall a d=32 está en piso de aprendibilidad, necesita miles de
  steps; retomar con currículo escalonado + más cómputo).
- ABIERTAS: H-V4-3 (calidad del prior), H-V4-5 (escribir≡olvidar -- con evidencia PARCIAL del arco memoria).

## VEREDICTO DE LA CORRIDA 51-70 (síntesis global — el thesis v4 sustancialmente validado en juguete)
20 ciclos verificados (todos por las compuertas del engine, verify_no_loss=OK, tests verdes). El reset v4 puso a
R-VALOR como raíz primera con confianza ALTA en que es la convergencia pero BAJA en que sea RESOLUBLE. La corrida
ataca esa duda y la mueve a confianza MEDIA, mostrando además que R-VALOR ATERRIZA las demás raíces:

- **R-VALOR es resoluble (evidencia POSITIVA, juguete):** el valor endógeno (info-gain) se AÍSLA de la mera
  actividad con el instrumento fiel (56), es MEDIBLE por la confianza calibrada del propio agente sin oráculo
  (57), y la sorpresa (su contracara) dirige el olvido en mundos no-estacionarios (58-66). Antes el lab sólo
  tenía verificador EXTERNO (exp017); ahora hay valor ENDÓGENO.
- **R-VALOR aterriza la MEMORIA:** escribir≡olvidar es rate-distortion dirigido por valor (70, H-V4-5: ablar el
  valor colapsa la ventaja de la memoria a aleatoria); el QUÉ/CUÁNDO/CÓMO recordar se decide del valor/sorpresa
  endógenos (selector de estrategia, 66).
- **R-VALOR aterriza el VERIFICADOR:** el arco verificador-real (51-55) muestra que la auto-mejora es robusta con
  un verificador chequeable real (ruido, cold-start, sesgo) vía la guardia dedup+replay; y la confianza endógena
  REEMPLAZA PARCIALMENTE al verificador externo gateada por calibración (60-62) -- el verificador es un caso de
  valor (señal de corrección).
- **R-VALOR aterriza el PRIOR:** la calidad/corrección del prior fija la eficiencia muestral (69, H-V4-3); un buen
  prior es valor a priori sobre qué estructura importa (un prior falso hunde).
- **R-INTERVENCIÓN confirmada** (exp022/CYCLE 35): la pasiva queda plana bajo intervención; sólo las políticas
  activas identifican.

**Lo que NO se resolvió (honesto):** la ESCALA (todo es bayesiano numpy + HybridLM tiny; falta un mundo
no-de-juguete y modelos más ricos). H-V4-4 (techo de recall = optimización) quedó DIFERIDA (el recall a d=32 está
en piso de aprendibilidad, necesita miles de steps). El selector de 3 estrategias (1j) es MIXTA (clasificar el
régimen intermedio es difícil). El olvido por modulación de TASA tiene un techo (1h REFUTADA: el trade-off
estabilidad-plasticidad es fundamental; hay que elegir la ESTRATEGIA, no el ritmo).

**Tesis final:** R-VALOR es la raíz que aterriza la inteligencia bajo recursos finitos: un escalar de valor
endógeno (estimable de info-gain/confianza/sorpresa, sin oráculo) define qué predecir, qué escribir/olvidar, cómo
recordar, qué verificar y qué prior elegir. La corrida lo demuestra en juguete; la frontera es la escala.

## Addendum — arco "R-VALOR bajo realismo" (CYCLE 72+): quitar las muletas de juguete una por una
La corrida 51-71 validó el thesis v4 en juguete CON oráculos/valores perfectos. Este arco ataca la debilidad
honesta #1 (todo es juguete con oráculo) removiendo las muletas de a una y midiendo si la tesis sobrevive.

- **CYCLE 72 — H-V4-5b APOYADA (abre el arco).** Ataca el caveat #1 del techo de CYCLE 70 (el valor se daba
  PERFECTO + selección estática). En una memoria ONLINE (m=10/n=50, stream T=3000), un agente que NO conoce el
  valor y lo ESTIMA de la frecuencia observada (LFU = valor endógeno) recupera **99%** de la ventaja del oráculo
  (0.508) sobre random (0.219), y le gana a recency/LRU value-free (0.370) por +0.135; anti_value (0.088) < random.
  => R-VALOR×memoria NO necesita oráculo de valor en régimen estacionario; la frecuencia observada es un valor
  endógeno que aterriza la memoria online (conecta con info-gain/confianza de CYCLE 56-57). Caveat real: el régimen
  es ESTACIONARIO (LFU≈óptimo es clásico ahí); la frontera es la NO-estacionariedad, donde la frecuencia-de-toda-
  la-historia es un valor sesgado y hace falta olvido (CYCLE 58-66). Cota 'real' en el ledger. Test 5/5.

**Próximas hijas del arco (backlog):** (73) atar el estimador de valor a la NO-estacionariedad (frecuencia con
ventana/decay adaptativo, combinada con el olvido por sorpresa de CYCLE 59 / el selector de estrategia de CYCLE
66); (74+) subir de frecuencia pura a valores endógenos más ricos (info-gain/confianza) y a un downstream con
estructura/correlación en las consultas (no IID). El North Star del arco: mostrar que las piezas del thesis v4
sobreviven al quitar los oráculos perfectos, acercándose a un mundo menos de juguete.

- **CYCLE 73 — H-V4-5c APOYADA (hija del 72; ata el estimador de valor con el OLVIDO).** El caveat del 72 era el
  régimen ESTACIONARIO. Aquí la popularidad CAMBIA (re-permuta item->valor cada fase, recurrente cf. CYCLE 63).
  CROSSOVER: estacionario lfu_full=0.511 (~oracle) gana, lfu_decay=0.443 paga el costo de olvidar; no-estacionario
  lfu_full DEGRADA a 0.341 (cae hacia random 0.191), lfu_decay (frecuencia con decay=0.97) recupera 74% de la
  ventaja del oráculo (0.516) -> 0.430, +0.090 sobre full, +0.051 sobre recency value-free (0.379). => el estimador
  de valor endógeno DEBE olvidar (descontar) para rastrear valor no-estacionario; R-VALOR (qué vale) y OLVIDO
  (cuándo dejó de valer) son la MISMA señal en dos tiempos -> unifica CYCLE 72 con el arco 58-66. Caveat: decay FIJO
  (óptimo depende de la tasa de cambio); LRU competitiva bajo cambio fuerte. Cota 'real'; D-V4-35; test 4/4.

- **CYCLE 74 — H-V4-5d APOYADA (CIERRA el sub-arco 72-73-74; muleta 'decay fijo' del 73).** Un meta-SELECTOR
  full<->decay gateado por el hit-rate reciente de cada experto (endógeno, EMA de sus propios aciertos, sin oráculo
  ni aviso de régimen) logra NO-REGRET: ESTAC selector=0.507 iguala a full=0.511 (usa decay 6%); NO-ESTAC
  selector=0.425 iguala a decay=0.430 (usa decay 88%, supera a full=0.341). Ningún decay FIJO es el mejor en ambos;
  el selector sí. => el estimador de valor elige QUÉ vale (frecuencia, 72), CUÁNDO dejó de valer y a qué RITMO
  olvidar (selector, 74), todo endógeno. Replica el selector de estrategia (CYCLE 66) sobre el estimador de valor.
  Caveat: selecciona (no mejora; hereda el techo del oráculo); sólo 2 expertos; frecuencia pura. Cota 'real'; D-V4-36;
  test 4/4. SUB-ARCO R-VALOR-estimador (72-73-74) CERRADO: R-VALOR × OLVIDO cerrado endógenamente sin hiperparámetro.

- **CYCLE 75 — H-V4-5e APOYADA (capstone CONCEPTUAL del arco realismo).** El VALOR != FRECUENCIA. Separando
  frecuencia f_i de costo-de-fallar c_i (valor v=f×c): COST_VARYING (v!=f) value_est (estima costo acumulado) 0.636
  recupera 99% del oráculo (0.639), lfu_freq (sólo frecuencia) 0.489 deja 0.150 sobre la mesa (señal equivocada:
  guarda lo frecuente-barato, falla lo raro-caro); COST_UNIFORM (v~f) value_est 0.502 ~ lfu 0.502 (la ventaja la
  DRIVE la divergencia). => R-VALOR es task-definido; estimar la frecuencia (proxy) falla cuando el valor diverge.
  Rebate "esto es sólo LFU": LFU óptimo SÓLO si valor=frecuencia. El agente aprende valor de sus CONSECUENCIAS ->
  liga memoria con R-INTERVENCIÓN (CYCLE 40-48). Cota 'real'; D-V4-37; test 4/4. Capstone del arco realismo 72-75.

- **CYCLE 76 — H-V4-5f APOYADA (hija del 75; MATIZA R-INTERVENCIÓN sobre la memoria).** Cuando cachear un item CIEGA
  a su costo (revelado sólo al FALLAR), el valor task-definido igual se aprende: value_miss=0.634 recupera 99% del
  oráculo e IGUALA a value_full=0.634 (observación gateada NO rompe el aprendizaje bajo estacionariedad), vence a
  lfu=0.490; value_explore=0.572 RESTA (la exploración extra no hace falta). Mecanismo: el agente observa el costo de
  lo que NO cachea (su contrafáctico) + cold-start observa todo una vez. MATIZ HONESTO: niega "aprender valor exige
  intervenir" en estacionario; R-INTERVENCIÓN sobre la memoria aparece SÓLO con costos NO-estacionarios de lo
  cacheado-no-observado (próxima hija: combinar CYCLE 73 + 76). Cota 'real'; D-V4-38; test 4/4.

- **CYCLE 77 — H-V4-5g REFUTADA (informativa; complementa el 76).** ¿Bajo drift de costos + obs gateada, intervenir
  (re-sondar) se vuelve necesario? DOS hallazgos: (A) el PROBLEMA es REAL -- DRIFT value_miss=0.561 pierde 0.051 vs
  value_full=0.613 (en ESTAC miss=full=0.653: la ceguera al drift de lo cacheado existe sólo con drift). (B) PERO la
  intervención naive (re-sondar sacrificando 1 slot fijo) NO paga: value_explore=0.532 < value_miss bajo drift
  (recupera ~0% del gap) y cuesta -0.065 sin drift. => REFUTADA el mecanismo, real el problema. La intervención sobre
  la memoria, si paga, debe ser CHEAP/TARGETED (sorpresa-gateada, reusar CYCLE 59), no un slot fijo. NO se sobre-vende
  R-INTERVENCIÓN sobre la memoria. Cota 'real'; D-V4-39; test 4/4. Próxima hija: intervención sorpresa-gateada.

- **CYCLE 78 — H-V4-5h REFUTADA (CIERRA el sub-tema memoria con null firme).** ¿Intervención BARATA sorpresa-gateada
  (re-sondar ocasional, no slot fijo)? La barata VENCE al slot fijo del 77 (DRIFT surprise=0.545>explore=0.532; ESTAC
  0.618>0.588) PERO no supera al baseline PASIVO (DRIFT surprise<miss=0.561; ESTAC surprise<miss=0.653 por falsos
  positivos). El gap de obs bajo drift (0.051) es muy chico para que CUALQUIER intervención lo recupere. => en la
  cache con obs gateada, la observación PASIVA del contrafáctico es ROBUSTA aun con drift; intervenir NO paga, ni
  barato. Los efectos fuertes de R-INTERVENCIÓN viven en el aprendizaje causal ACTIVO (exp022), no aquí. Cota 'real';
  D-V4-40; test 4/4. **SUB-TEMA MEMORIA SATURADO (72-78) -> PIVOTE** (valor más rico / rama control-empowerment).

## Addendum — rama R-CONTROL abierta y acotada bajo R-VALOR (CYCLE 79+)
La corrida 51-78 trabajó R-VALOR (predicción/memoria). El árbol marcaba "inteligencia=control/acción (empowerment)"
como la rama CONTESTADA / faltante más grande, y CYCLE 38/39 la habían aceptado sin test adversarial. CYCLE 79 abre
y acota la rama:

- **CYCLE 79 — H-V4-6a MIXTA (abre R-CONTROL).** Test adversarial de empowerment-como-valor (valor=ctrl×rel, sweep de
  correlación control↔relevancia). El empowerment recupera el óptimo cuando control≈valor (rho=1: 1.000, = exp024/025)
  pero degrada MONÓTONO al desalinearse (rho=0: 0.724; -0.5: 0.565), malgastando en lo controlable-inútil (simétrico a
  la predicción en lo predecible-inútil). NO colapsa a random porque la controlabilidad ES un componente multiplicativo
  del valor. => el empowerment es la MARGINAL-de-controlabilidad de R-VALOR, NO un valor universal: ni control ni
  predicción puro es el valor; el general es R-VALOR (referido al objetivo). Resuelve el rival CONTESTADO bajo R-VALOR
  (empowerment es un COMPONENTE, no reemplazo). Cota 'real'; D-V4-41; test 4/4. Próximo: empowerment estimado online.

- **CYCLE 80 — H-V4-6b APOYADA (capstone CONSTRUCTIVO del par R-CONTROL 79-80).** R-VALOR se RECONSTRUYE de dos
  marginales ENDÓGENAS. El agente estima controlabilidad (empowerment, de consecuencias) Y relevancia (de recompensa)
  con S muestras y las COMBINA. En rho=0 (control ⊥ relevancia): rvalue_est (ctrl_est × rel_est) = 0.984 vence a cada
  marginal sola (empowerment 0.709, relevance 0.729) por +0.255 y recupera 98% del oráculo; converge con muestras
  [0.686→0.984]. => R-VALOR (referido al objetivo) se CONSTRUYE combinando dos estimadores endógenos baratos, SIN
  oráculo; empowerment y predicción/relevancia son sus DOS marginales. Cierra el par R-CONTROL: 79 acotó, 80
  reconstruye. El valor se construye de la experiencia, no se postula. Cota 'real'; D-V4-42; test 4/4.

> PAR R-CONTROL (79-80) CERRADO: el empowerment es la marginal-de-controlabilidad de R-VALOR (79, acota el rival
> contestado), y R-VALOR se reconstruye como el PRODUCTO de las marginales endógenas control × relevancia (80,
> constructivo). Resuelve la rama CONTESTADA del árbol bajo R-VALOR: control y predicción no son rivales de R-VALOR
> sino sus dos marginales. Frontera: lazo real acción-consecuencia/recompensa; valor no-factorizable; escala.

- **CYCLE 81 — H-V4-6c APOYADA (UNIFICA verificador + R-VALOR).** El VERIFICADOR de auto-mejora (48-55) es la
  marginal-de-RELEVANCIA de R-VALOR. Con la relevancia provista por un verificador ruidoso (error ε), rvalue_verifier
  (ctrl × verificador) en ε=0 reconstruye el óptimo (1.000) y vence a empowerment (0.387, control solo) por +0.613
  (enorme: con p_rel=0.3 el control solo capta poco), tolera el ruido del verificador hasta ε*=0.30, y degrada con
  gracia al control en ε=0.5. => act-and-verify (R-INTERVENCIÓN + verificador) estima IMPLÍCITAMENTE R-VALOR = control
  × verificador-relevancia, sin oráculo. UNE TRES arcos (R-INTERVENCIÓN + verificador 48-55 + R-VALOR 79-80). Cota
  'real'; D-V4-43; test 4/4. La auto-mejora verificada ES asignación por R-VALOR estimado.
