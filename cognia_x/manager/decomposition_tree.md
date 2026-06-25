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
