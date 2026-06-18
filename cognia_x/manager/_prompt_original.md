# Prompt fundacional original (literal) — Cognia-X

> Transcripción literal del prompt entregado por el dueño el 2026-06-17. Histórico.
> NO modificar. La versión operativa mejorada vive en `00_protocolo_investigacion.md`.

---

## Misión

Dentro del proyecto Cognia, crea un subproyecto completamente independiente llamado Cognia-X.
Cognia-X NO es una modificación de Cognia. Cognia-X es un laboratorio experimental destinado a
responder una pregunta: "Si hoy tuviéramos que rediseñar una inteligencia artificial desde cero
absoluto utilizando todo el conocimiento moderno disponible, ¿qué construiríamos?"

El objetivo NO es crear otra copia de un Transformer ni otro LLM tradicional. El objetivo es
investigar rigurosamente qué componentes actuales siguen siendo óptimos, cuáles pueden mejorarse
y cuáles deben ser reemplazados.

## Principio fundamental

No aceptes ninguna arquitectura por autoridad. Ni Transformers. Ni RNN. Ni Mamba. Ni RWKV. Ni
MoE. Ni sistemas cognitivos existentes. Todo debe justificar su existencia mediante evidencia.
Si una pieza demuestra ser óptima, puede mantenerse. Si una pieza demuestra ser un cuello de
botella, debe proponerse una alternativa.

## Regla de investigación

Antes de implementar cualquier componente: 1. Investiga. 2. Formula hipótesis. 3. Busca
evidencia a favor. 4. Busca evidencia en contra. 5. Intenta refutar la hipótesis. 6. Diseña
experimentos. 7. Ejecuta pruebas. 8. Analiza resultados. 9. Documenta conclusiones. No
implementes por intuición.

## Fuentes de inspiración permitidas

Neurociencia, ciencia cognitiva, aprendizaje humano, arquitecturas de IA modernas, sistemas
distribuidos, teoría de la información, teoría de control, aprendizaje por refuerzo, memoria
biológica, computación eficiente, sistemas evolutivos. Pero no copies. Extrae principios.

## Prioridades (orden estricto)

1. Eficiencia computacional. 2. Aprendizaje continuo. 3. Adaptabilidad. 4. Creatividad. 5.
Razonamiento. 6. Escalabilidad futura. Si una mejora aumenta inteligencia pero destruye
eficiencia, debe justificarse rigurosamente.

## Hardware objetivo

CPU de portátil. La arquitectura debe diseñarse pensando primero en CPU. GPU y clústeres son
optimizaciones futuras.

## Aprendizaje continuo

Cada instancia aprende localmente; el conocimiento útil puede fusionarse; el modelo principal
puede evolucionar; el aprendizaje resistente al olvido catastrófico. Investiga múltiples
estrategias antes de elegir una.

## Auto-mejora

No implementes auto-modificación completa al inicio. Nivel 1: observación. Nivel 2:
recomendaciones. Nivel 3: herramientas propias. Nivel 4: módulos modificables. Nivel 5:
rediseño controlado. Cada nivel debe demostrar estabilidad antes de avanzar.

## Investigación agresiva

Asume que muchas creencias actuales pueden estar equivocadas. Preguntas obligatorias: ¿Por qué
existen los embeddings? ¿Son realmente necesarios? ¿Puede existir otra representación? ¿Por qué
usamos atención? ¿Es la mejor solución? ¿Qué parte consume más recursos? ¿Qué componente limita
la escalabilidad? ¿Qué haría una arquitectura diseñada específicamente para CPU? ¿Qué podemos
aprender del cerebro humano? ¿Qué NO debemos copiar del cerebro humano?

## Restricciones

Prohibido: sustituir el proyecto por un modelo existente; declarar una solución sin evidencia;
considerar terminada una investigación sin pruebas; aceptar afirmaciones por consenso. Permitido:
reutilizar matemáticas, principios, ideas; reimplementar componentes desde cero; desechar
componentes existentes.

## Sistema de documentación

Carpeta /manager con: paper.md, roadmap.md, research_log.md, architecture.md, experiments.md,
assumptions.md, hypotheses.md, future_work.md, decision_log.md. paper.md funciona como paper
científico vivo. Nunca eliminar información histórica, solo añadir revisiones.

## Contexto persistente

Asume contexto limitado en futuras sesiones: resume decisiones, mantén estados de avance,
documenta razonamientos, guarda resultados reproducibles.

## Criterio de éxito

El éxito NO es terminar rápido. El éxito es producir evidencia convincente de que una
arquitectura propuesta es más eficiente, aprende mejor, consume menos recursos, o demuestra
principios superiores. Si una técnica actual sigue siendo óptima, documenta por qué. Si hay una
alternativa mejor, demuéstrala con experimentos reproducibles.

## Resolución de bloqueos de investigación

Cuando un problema parezca imposible/ambiguo/complejo: NO te detengas, NO concluyas que no hay
solución, NO aceptes la arquitectura actual por defecto. Reformula: (1) Reducir complejidad
("¿cuál es la versión más pequeña?"). (2) Buscar analogías (naturaleza, biología, humanos,
ingeniería, logística, economía, juegos, evolución, sistemas sociales, procesos cotidianos).
(3) Resolver el problema cotidiano primero. (4) Readaptar extrayendo el principio. (5)
Optimización iterativa (eficiencia, simplicidad, robustez, escalabilidad). (6) Pensamiento de
primeros principios (¿por qué existe? ¿qué resolvía? ¿sigue existiendo? ¿hay algo más simple?).
(7) Generar tres alternativas (conservadora, moderada, radical) y evaluarlas. (8) Persistencia:
documentar el fracaso, explicar por qué falló, registrar lo aprendido, generar nuevas hipótesis.

Principio central: si no encuentras solución, reduce el problema; si sigue difícil, busca
analogía; si sigue difícil, resuelve una versión cotidiana; si sigue difícil, divide otra vez.
La investigación termina únicamente cuando exista evidencia suficiente, no cuando el problema
parezca complicado.
