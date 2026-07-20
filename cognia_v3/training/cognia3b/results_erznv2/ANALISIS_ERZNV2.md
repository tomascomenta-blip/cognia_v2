# E-RZN-v2 — NO APTO: cero transferencia. LÍNEA CERRADA: razonamiento se gana por INFERENCIA, no por fine-tune

Kaggle 1×T4, 173.9 min. Generador DIFÍCIL (composición encadenada + distractores
+ orden 5 entidades + resto), banda de yield pre-registrada, receta E-GROK.

## Veredicto contra el pre-registro

| Predicción | resultado | veredicto |
|---|---|---|
| P-RZN2-2: yield en banda [15%, 65%] | **62.4%** (873/1.400, 0 colisiones) | **PASA** (el endurecimiento funcionó: 86%→62%) |
| P-RZN2-1: G2R ≥ base +10pp, p<0.05 | 57% → **57%** (0.0pp, n01=10, n10=10, p=1.0) | **FALLA — efecto CERO** |

**`APTO_FLEET: false`.**

## Lectura (dos corridas honestas → conclusión de programa)

1. v1 (fácil, yield 86%): nada que destilar → −4pp n.s.
2. v2 (difícil, yield 62%): hay cadenas correctas que destilar (873 pares),
   el modelo LAS APRENDE (loss 0.149→0.058) y aun así la suite held-out no se
   mueve UN ítem neto (n01=n10=10 = ruido puro). El CoT auto-destilado enseña
   el FORMATO de razonar sobre las plantillas propias, no la CAPACIDAD de
   razonar sobre problemas nuevos.
3. El contraste decisivo (mismo gate, mismos 100 ítems, mismo deploy):
   - STaR fine-tune (2 corridas, ~6 GPU-h): **+0pp**.
   - Andamiaje de inferencia (stepwise v2, E-INT, cero entrenamiento):
     **60→82% (+22pp, p=0.0002)**.

**DECISIÓN: la línea "experto de razonamiento por fine-tune" queda CERRADA.**
El razonamiento del 3B se escala por ANDAMIAJE (CoT dirigido por turno, BoN
con oráculo, repair dirigido) — consistente con toda la evidencia MoM del
programa (andamiaje 24→86 en tool-calling antes del adapter; el adapter pagó
en ACCION porque ahí el gap era de FORMATO/hábito, no de capacidad).
El fleet sigue con expertos donde el gap es de formato/dominio: código por
lenguaje (verificable por tests), imágenes LCD.

## Números operativos

- Generación STaR endurecida: 152.4 min para 1.400 problemas (~2× v1 por
  respuestas más largas). Train 35 steps (corpus 873, SEQ 1024). Total 173.9 min.
- Costo total de la línea E-RZN: ~5.7 GPU-h por un resultado negativo LIMPIO
  con diseño pre-registrado — barato comparado con creer que funcionaba.
