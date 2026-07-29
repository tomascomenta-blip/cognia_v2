# PREREG — QA más fuerte: ¿otro pensador rompe el techo del contrato interno?

**Fecha:** 2026-07-28, sesión nocturna 28→29. **Escrito ANTES de correr.**
**Vía que prueba:** la única alternativa viva que dejaron los tres KILL del
contrato autogenerado (memoria contrato-interno-al-azar): "held-out A MANO
**o un modelo más fuerte para el rol QA**". Los held-outs a mano ya existen
(brutal + fácil); esto mide la mitad "modelo más fuerte".

## Hipótesis y prior

- El techo medido es del PENSADOR (gpt-oss-20b): conserva sus propias
  invenciones aunque un filtro se las señale (FN 15/19; aciertos 8–10/24 en
  el corpus de la sonda; 3 KILL convergentes de prompt-engineering).
- Candidato QA: **OpenReasoning-Nemotron-14B** (Q4_K_M, ya instalado;
  especializado en razonamiento — el rol QA es razonar consecuencias, no
  escribir HTML). NO se toca el prompt: mismo modo `clasico`, mismo
  `b2_ab_contrato.py`, solo cambia el modelo servido en :8080.

## Diseño (corpus CONGELADO, cero generación de páginas)

- Corpus: las 24 páginas de b2_sonda_prompt con veredicto del banco ya
  registrado (19 aprobadas / 5 reprobadas — el FP se mide /5, límite
  conocido). Las mismas ejes que nocturna 27: FP, FN, aciertos /24.
- **Bloque G (control de deriva, primero, sin swap):** con gpt-oss-20b aún
  servido tras la corrida BoN, `b2_ab_contrato.py --modos clasico
  --etiqueta gposs_ctrl28`. Re-mide el baseline ESTA noche.
- **Bloque N:** swap a Nemotron (`servir_modelo.py --modelo OpenReasoning`),
  humo de 1 página (¿el JSON del contrato se extrae del output con
  razonamiento?; arreglos de plomería de parseo están permitidos y se
  documentan — no tocan el camino de gpt-oss), luego `--modos clasico
  --etiqueta nemotron14b` sobre el corpus completo.
- Bloques secuenciales (no se pueden servir dos 14B a la vez): la lectura
  usa umbrales ABSOLUTOS + el control G para acotar deriva, no una resta
  G−N pura (gate-e2e-flaky).

## Umbrales (fijados ahora)

| lectura | condición | veredicto |
|---|---|---|
| control G | aciertos fuera de [5,13]/24 | DERIVA ALTA: todo lo demás solo direccional |
| Nemotron | aciertos ≥ 17/24 ∧ FN ≤ 5/19 ∧ FP ≤ 2/5 | SEÑAL ÚTIL (vía QA-fuerte VIVA) |
| Nemotron | FN ≤ 4/19 ∧ FP ≤ 1/5 | PASA FUERTE: candidato a selector de BoN |
| Nemotron | aciertos ≤ 13/24 ∨ FN ≥ 8/19 | KILL: el techo no era solo del pensador chico |
| medio | resto | GRIS: se reporta, sin adopción |

- El juez (Playwright) es el mismo binario/commit en ambos bloques; el commit
  se registra en la config de cada corrida.
- Si SEÑAL ÚTIL y queda reloj: stretch direccional pre-declarado — generar
  contratos Nemotron para un subconjunto (~24) de las muestras GUARDADAS de
  la corrida BoN de esta noche y medir cuánto del techo A captura un selector
  Nemotron (sin GPU de páginas; solo contratos + replay). Sin umbral de
  adopción: alimenta el diseño del selector de producción de la próxima
  sesión.
- Nada de este prereg adopta código de producción esta noche (los arreglos
  de plomería del extractor sí se commitean: son bugs, con test).

## PRIMERA ENMIENDA (2026-07-28 ~21:05 — ANTES del bloque N)

Los humos de Nemotron (3 páginas: kanban, hoja, carrito) fallaron los tres,
por tres vías distintas: bucle de repetición a temp 0.2 (documentado del
linaje Qwen; knob `COGNIA_TEMP_CONTRATO=0.6` añadido — la decodificación de
la TARJETA del modelo es parte de "cambiar el modelo", el prompt no se
tocó), un parse "Extra data" (extractor endurecido con raw_decode + test), y
DOS contratos sin ningún paso crítico (el descarte por vacuidad de
producción los tira — eso no es plomería, es el modelo no marcando
criticidad).

Para no gastar ~2 h en un KILL casi seguro ni matarlo con 3 humos post-hoc:

1. **PILOTO DE FUTILIDAD pre-registrado** sobre 6 páginas FRESCAS (una por
   tarea × primeras réplicas del corpus, sin contar los 3 humos): si menos
   de 3/6 contratos son USABLES (parsean ∧ ≥1 crítico ∧ sobreviven el
   descarte), el bloque N completo NO se corre y Nemotron se declara
   **KILL DE APTITUD** como QA drop-in (no sabe emitir el artefacto, con
   dos reintentos por página como en el runner).
2. **Candidato B pre-declarado:** qwen2.5-coder-14b (mismo protocolo
   completo: humo, piloto de futilidad, bloque, mismos umbrales del prereg).
   Racional: el rol exige JSON disciplinado + consecuencias del enunciado;
   un instruct no-razonador puede ser mejor QA que un razonador que no
   sigue el esquema.
3. El control G del día (FN 15/19, dentro de [5,13] aciertos) sigue siendo
   el ancla de deriva para cualquier candidato de esta noche.

## RESULTADO DEL CANDIDATO B — coder-14b (2026-07-28 22:05)

Piloto: **6/6 usables** (5-8 s/contrato, críticos bien marcados — la aptitud
de emisión no era el problema). Bloque completo (24 páginas, M3:
sin-contrato=reprueba): **aciertos 10/24, FN 14/19, FP 0/5 → KILL por los
umbrales pre-fijados** (aciertos ≤13 ∧ FN ≥8). Control G de la misma noche:
gpt-oss aciertos 8/24, FN 15/19 — indistinguibles.

**Lectura conjunta (el CUARTO clavo):** dos pensadores de familias distintas
(razonador MoE 20B, coder denso 14B) producen el MISMO perfil de FN con el
mismo marco. La enfermedad no es el modelo: es el MARCO — un contrato ciego
generado desde idea+inventario inventa expectativas que condenan páginas
sanas, lo genere quien lo genere. La vía "QA más fuerte drop-in" queda
CERRADA con dos KILL; fabricar señal para tareas nuevas exige OTRO marco
(p. ej. verificación conductual cruzada entre muestras del propio BoN, o
held-outs con ejecución en el bucle) — diseño para la próxima sesión, no un
tercer modelo con el mismo prompt.

## RESULTADO DEL PILOTO NEMOTRON (2026-07-28 21:45)

**0/6 usables → KILL DE APTITUD** (piloto_qa_nemotron14b.json, 2 intentos
por página, temp 0.6 de su tarjeta, extractor ya endurecido). El modelo no
sabe emitir el artefacto: o el JSON no cierra (degenera aun a 0.6) o no
marca ningún paso crítico (contrato vacuo, descartado por producción). El
bloque N completo NO se corre (puerta de futilidad). Matiz honesto: esto
mata a Nemotron como QA **drop-in con el prompt actual**, no la idea
"QA más fuerte" — el candidato B sigue el protocolo.
