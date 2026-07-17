---
title: Superorganismo — etapa 4, colonia por pedazos
type: entity
tags: [superorganismo, cartografia, hormigas, feromona, oraculo]
updated: 2026-07-16
---

# Superorganismo

→ [[index]]

## Que es

`cognia/agent/superorganismo.py` — etapa 4 de la cascada de generar_codigo:
colonia por PEDAZOS. Port de produccion del mecanismo v2 validado por
PREREG_SUPERORGANISMO (gate >=2/13 CRUZADO 2026-07-14: NEWX3+ALG3+SPEC3
pasan tests OCULTOS con presupuesto pass@16 cuyo baseline es 0/13).

## Mecanismo

```
CARTOGRAFIA (qwen3_4b)   descompone el enunciado en helpers con contrato +
                         extrae SPEC-ASSERTS literales. Si el razonador no
                         logra oraculo decente, el CODER extrae los suyos y
                         se usa la UNION (refuerzo-coder).
HORMIGAS (qwen35_4b)     cada helper se resuelve contra su micro-oraculo,
                         evaluado sobre el ACUMULADO (recursion mutua ok).
ENSAMBLE + FEROMONA      la funcion principal usa los helpers verificados;
                         cada fallo deja rastro que el siguiente intento
                         debe evitar. Keep-best por #asserts pasados.
```

## Lecciones incorporadas

- Oraculo INFIEL = anti-solucion (SPEC1, NEWX4) → filtro DETERMINISTA de
  contradicciones (mismo input, outputs distintos ⇒ ambos asserts fuera).
- Piezas verificadas NO garantizan el ensamble (NEWX2/NEWD2): el veredicto
  final es SIEMPRE el oraculo del caller, jamas la palabra de esta etapa.
- LEY empirica: spec-visible-100% ⇔ PASS oculto (cero falsos positivos en
  la corrida 13/13).

## Activacion

Miembro MAS caro de la colonia (2 modelos 4B lazy + hasta budget
generaciones). Dispara solo con permiso del perfil hibrido en tarea dura
donde las etapas 1-3 no confirmaron; `COGNIA_SUPERORGANISMO` env manda.
Fallos → None (nunca rompe la tool).

## Links

- [[concepts/colonia]]
- [[entities/hybrid_router]]
