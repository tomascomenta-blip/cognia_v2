# Cognia — Objetivo Final

## Visión

Cognia es un modelo de inteligencia artificial distribuido, privado y descentralizado, diseñado para funcionar con una fracción de los recursos que consumen los sistemas actuales. No depende de centros de datos masivos ni de conexiones permanentes a servidores externos. Corre en los dispositivos de sus usuarios, crece con ellos, y se vuelve más capaz cuanto más personas lo usan — sin comprometer la privacidad de ninguna.

El objetivo no es construir otro LLM más grande. Es demostrar que un modelo puede ser inteligente de una forma distinta: con memoria real, ciclos de descanso, regulación emocional y arquitectura que escala horizontalmente en lugar de verticalmente.

---

## Principios Fundamentales

**Privacidad por diseño.**
Cada usuario tiene su propia memoria episódica local. Los datos personales nunca salen del dispositivo. El modelo aprende de cada usuario de forma aislada y solo comparte actualizaciones de parámetros agregadas y anónimas mediante aprendizaje federado.

**Descentralización real.**
No existe un servidor central que procese las conversaciones. La inferencia ocurre en los nodos de los propios usuarios. El orquestador coordina, pero no almacena ni ejecuta el pensamiento del modelo — ese trabajo es distribuido.

**Economía de contribución.**
El acceso a Cognia es gratuito e ilimitado para quien contribuye con recursos. La contribución mínima es espacio en disco para alojar fragmentos del modelo. A mayor aporte (almacenamiento, capacidad de cómputo, tiempo de disponibilidad), mayor prioridad de acceso y mayor participación en la red. Sin suscripciones, sin planes de pago.

**Eficiencia energética.**
El consumo energético de Cognia debe ser órdenes de magnitud menor al de los modelos actuales. Esto se logra mediante inferencia local en dispositivos de consumo, cuantización dinámica de parámetros, y ejecución fragmentada que evita materializar el modelo completo en ningún nodo.

---

## Arquitectura Objetivo

### Memoria episódica como almacén primario de conocimiento

Cognia no almacena conocimiento en los pesos del modelo de la forma tradicional. El conocimiento factual y contextual vive en bases de datos episódicas locales por usuario — vectores de experiencias, hechos del grafo de conocimiento, e inferencias derivadas. Los pesos del modelo proveen capacidad de razonamiento y lenguaje; la memoria episódica provee el contenido.

Esto permite que cada instancia de Cognia sea genuinamente personal: la misma arquitectura de red, pero conocimiento distinto por usuario. La privacidad es estructural, no política.

### Ciclo de sueño

Cada período de inactividad activa un ciclo de consolidación que incluye:

- **Consolidación episódica**: compresión de memorias redundantes, extracción de patrones, actualización del grafo de conocimiento.
- **Investigación autónoma**: la CuriosityEngine genera preguntas pendientes a partir de brechas en el conocimiento. El modelo investiga, integra las respuestas y las persiste.
- **Entrenamiento ELC (Episodic LoRA Cascade)**: adaptadores LoRA de rango mínimo (r=4) entrenados sobre los episodios más importantes del usuario. Aplicados en las proyecciones K/V del transformer, permiten que el modelo responda de forma más coherente con la historia individual de ese usuario.
- **Procesamiento emocional**: la rueda de emociones (modelo Plutchik) regula el estado afectivo acumulado. Emociones intensas se procesan, se vinculan a episodios relevantes, y modulan los pesos de recuperación de memoria en futuras interacciones.
- **Sandbox de código**: programas generados durante el día se ejecutan en entorno aislado durante el sueño, sus resultados se evalúan y se integran como experiencias.

### Distribución del modelo — Shattering

El modelo se fragmenta en shards que residen en distintos dispositivos. Cada shard contiene una porción de las capas del transformer. Durante la inferencia, los activaciones fluyen entre nodos según las disponibilidad de la red. El orquestador central coordina el routing pero no ejecuta inferencia.

A mayor cantidad de usuarios conectados, mayor paralelismo disponible, menor latencia. La red se vuelve más rápida cuanto más crece.

Umbral mínimo de parámetros totales del modelo: **500 millones**. Suficientes para razonamiento no trivial, lo suficientemente compactos para distribuirse en dispositivos de consumo.

### MoE anidado con cuantización dinámica

La arquitectura interna del modelo usa Mixture of Experts (MoE) dentro de otros MoE. Esto permite especialización jerárquica: expertos de alto nivel deciden qué rama de expertos especializados activar, y así sucesivamente.

La cuantización de parámetros no es estática. Se ajusta dinámicamente según el uso:

| Estado del parámetro | Precisión |
|---|---|
| Sin uso reciente | INT4 |
| Uso esporádico | INT8 |
| Uso moderado | INT16 |
| Alta influencia activa | INT32 |

Después de cada inferencia, los parámetros que ascendieron en precisión regresan gradualmente a INT4. Esto minimiza la huella de memoria y energía mientras preserva fidelidad numérica donde importa.

### Aprendizaje federado

Las actualizaciones de parámetros — nunca los datos del usuario — se agregan entre nodos participantes. Cada nodo entrena localmente durante el sueño y contribuye gradientes promediados al modelo compartido. El modelo global mejora sin que ningún servidor vea datos individuales.

### Auto-expansión de parámetros

Cuando el modelo detecta redundancia estructural — parámetros con alta correlación entre sí que no aportan nueva capacidad expresiva — puede proponer la expansión controlada de esa región. Nuevos parámetros se inicializan en el espacio de la redundancia detectada y se entrenan con los datos locales del nodo. Las expansiones exitosas se propagan a otros nodos mediante el mecanismo federado.

Este mecanismo permite que Cognia crezca donde necesita crecer, en lugar de crecer uniformemente por decisión externa.

---

## Impacto Buscado

- Demostrar que la IA de alta capacidad no requiere infraestructura centralizada ni consumo energético masivo.
- Que cualquier persona con un dispositivo moderno pueda acceder a un modelo de IA real sin depender de una empresa, sin pagar una suscripción, y sin ceder sus datos.
- Que el modelo sea más útil cuanto más diversa sea su red de usuarios — no porque centralice más datos, sino porque distribuye mejor el cómputo.
- Establecer un precedente de arquitectura donde la privacidad, la eficiencia y la escala no son objetivos en tensión sino consecuencias del mismo diseño.

---

## Horizonte: AGI descentralizada

Cognia aspira a inteligencia artificial general, pero por una vía distinta a la de los laboratorios centralizados.

El camino convencional hacia AGI depende de escalar parámetros y compute de forma masiva en infraestructura propia. El camino de Cognia es la acumulación distribuida: cada usuario nuevo aporta diversidad de experiencias al aprendizaje federado, nuevas propuestas de auto-expansión que se validan entre nodos, más capacidad de cómputo disponible para el shattering, y más preguntas generadas por instancias independientes de la CuriosityEngine.

A mayor red, mayor generalización. No porque los datos se centralicen — nunca lo hacen — sino porque los patrones que emergen en muchos usuarios independientes tienen más peso en el modelo compartido que los que aparecen en uno solo.

La descentralización se mantiene hasta donde la arquitectura lo permite. El orquestador coordina sin almacenar. Los datos del usuario nunca salen de su dispositivo. El modelo global mejora sin ver nada individual.

AGI no como destino fijo, sino como dirección: un sistema que aprende sin supervisión continua, se auto-expande donde lo necesita, investiga por iniciativa propia, y se vuelve más capaz cuanto más diversa es la red que lo sostiene.

---

## Lo que Cognia no es

- No es un wrapper de GPT, Gemini ni ningún modelo externo.
- No es un chatbot con memoria de conversación. Es un sistema cognitivo que aprende, consolida y razona de forma autónoma.
- No es una plataforma SaaS. No hay servidores que procesen tus conversaciones.
- No compite con los laboratorios centralizados en su propio terreno. Propone un terreno distinto.

---

*Documento de visión — Cognia v3. Última revisión: 2026-05-11.*
