# RAÍZ GROKKING — el techo visto desde abajo (2026-07-12/13)

**Corrida ROMPER EL TECHO.** Este doc es el lazo de grokking pedido por el
dueño: escribir → probar → descartar → combinar, hasta que la estructura
del problema quede transparente. Insumos: AUTOPSIA_13 (evidencia local),
RAIZ_ARBOL_HIPOTESIS (literatura 2024-2026 verificada), E-PASSK (midiendo).

## 1. La historia vieja y por qué era incompleta

Historia sostenida hasta hoy: "capacidad = cómputo; donde el 3B falla, el
7B falla; el techo es de conocimiento". Era la MEJOR lectura de los datos
de entonces (7 gates negativos la respaldaban). Pero la autopsia muestra
algo que esa historia no explica:

- Las 13 "imposibles" no producen basura — producen código *casi* correcto.
- calc y eval_arith (el mismo problema textbook) fallan con el MISMO bug
  de pila. Un evaluador de expresiones no está fuera del conocimiento de
  un coder de 4B entrenado en 2026: está fuera de su PRIMER intento.
- SPEC4 cayó con solo cambiar el contexto (few-shot). Los techos de
  conocimiento no se mueven con el contexto; los de MUESTREO sí.

## 2. El reencuadre (lo que la literatura confirma con números)

El "techo" es la composición de TRES techos distintos que se disfrazan
de uno, y solo el tercero es real:

```
techo observado (27/40)
  = techo de BÚSQUEDA   (la solución está en la distribución del modelo,
  |                      pero greedy/N-chico no la muestrea)
  |   evidencia: Monkeys 2024 (coverage log-lineal en k, 4 órdenes);
  |   Yue 2025 (el BASE alcanza al RL a k=256: la capacidad es LATENTE)
  + techo de ORÁCULO    (el juez de tests visibles autogenerados no
  |                      distingue candidatos ni cubre el borde que falla)
  |   evidencia: EvalPlus (−19/−29pp con tests 80×); verifier accuracy
  |   ~22% en suites autogeneradas; k óptimo <10 con juez débil;
  |   precedente LOCAL: el juez ya descartó al 7B correcto una vez
  + techo de CAPACIDAD  (ni con k=10.000: Gemma-2B 7% en CodeContests)
      evidencia: el muro existe, pero está MÁS LEJOS de lo que decíamos
```

La frase que condensa el grokking: **"el modelo no puede" y "no lo hemos
elicitado" son estados distintos que miden igual en pass@1.** Nuestro
27/40 mide la intersección (modelo ∩ búsqueda ∩ juez), no el modelo.

## 3. Qué se descarta (con por qué)

- ❌ Subir N plano en el BoN: con el juez actual el retorno muere antes de
  k=10 (2411.17501). Sería pagar horas de i3 para que el juez débil elija
  mal entre más candidatos.
- ❌ Más operadores de selección post-hoc "inteligentes": 26 probados sin
  ganancia held-out en ≤1.5B (jun 2026); "fix the harness first".
- ❌ Re-abrir fine-tune: Yue 2025 cierra el caso con elegancia — RL/FT
  re-pesa la distribución, no la expande. Nuestras 8 negativas eran el
  mismo teorema medido en chico.
- ❌ Juez-LLM: sigue prohibido; nada de lo de arriba lo necesita.

## 4. Qué se combina (el ataque, en orden de dependencia)

**PASO 0 (corriendo): E-PASSK** — coverage@16 de las 13 contra ocultos.
Separa por ítem: rama búsqueda (alguna muestra pasa) vs candidata a
capacidad (0/16). Decide dónde apuntar cada palanca.

**A. Endurecer el ORÁCULO (la palanca más barata, ataca las 7 spec-largo):**
   - A1. Test anchors: un test generado jamás veta al candidato que pasa
     los tests DADOS en el enunciado (parche directo al bug del deploy 7B).
   - A2. Inputs-only + clustering por ejecución: el modelo genera SOLO
     inputs (fácil); los N candidatos se EJECUTAN sobre ellos; el grupo
     mayoritario por comportamiento real gana. El error del oráculo vive
     en los outputs predichos — no predecirlos.
   - A3. Inputs distinguidores (S*): si 2+ candidatos empatan en lo
     visible, generar el input donde DIFIEREN, ejecutar ambos, y usar la
     divergencia + tests de borde para decidir. S* midió 3B 18.4→42.7 y
     7B 29.4→54.4 en LCB con esta receta a N=16.
**B. Dirigir la BÚSQUEDA (ataca los 4 parsers):**
   - B1. Repair dirigido al assert que falla (ya existe en el loop; falta
     conectarlo al caso borde del juez endurecido).
   - B2. Diversidad estructural barata: primer token forzado distinto por
     candidato (logit_bias b9391) > subir temperatura.
   - B3. Pool cross-familia (un no-Qwen del registry) — el agujero
     compartido de la distribución Qwen es de familia, no de tamaño.
**C. Lo que queda tras A+B = techo de capacidad HONESTO** (probablemente
   NEWD2-geometría y poco más). Ese sí se acepta o se paga con hardware.

## 5. Predicciones registradas (falsables, antes de ver E-PASSK)

1. E-PASSK recupera ≥4/13 con 16 muestras (rama búsqueda existe).
2. Los 4 parsers están sobre-representados entre los recuperados.
3. De las spec-largo, las que E-PASSK no recupere caerán mayormente con
   oráculo endurecido (A1-A3) + repair (B1), no con más muestras.
4. Quedarán 2-4 tareas que nada de esto toca (capacidad real).

Si (1) falla (<4), la historia vieja gana y se documenta con la misma
honestidad con la que hoy se la cuestiona.
