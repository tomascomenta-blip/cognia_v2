# exp008 — Cierre de H-MEZ-4 (eje recall): el híbrido recupera lo que el lineal pierde

**Estado:** cerrado (corrida principal, profundidad 4). Refuerzo a profundidad 6 (mayoría-lineal)
en curso. PyTorch CPU (i3-10110U, venv312, 3 hilos).

## Resultado principal (profundidad 4, d=64, h=4, n_queries=16, warmup=400, lr=1e-3)

Tarea MQAR: pares (clave→valor) + consultas; accuracy de recall en las consultas. **Azar = 1/n_vals
= 0.0625.** 3 configs a IGUAL tamaño (201k params), solo cambia el mixer (attn_every):
- `atencion_pura` (ae=1): 4 capas de atención.
- `hibrido_3to1` (ae=2): `[lin, attn, lin, attn]` — 2 lineales + 2 atención.
- `lineal_puro` (ae=0): 4 capas de atención lineal (estado fijo).

| n_pairs | atención | híbrido | lineal | lectura |
|--------:|---------:|--------:|-------:|---------|
| 4 | 0.999 | 0.991 | 0.988 | bajo capacidad: **las 3 resuelven** |
| 8 | 1.000 | 0.998 | **0.255** | el **lineal SATURA y falla**; el híbrido lo recupera |

**Trayectorias (np=8):** la atención cruza la transición de fase en el paso ~1200 (0.25→1.00); el
híbrido en ~4800 (más lento, el circuito de inducción se forma a través de las capas lineales
intercaladas); el **lineal queda plano en ~0.25 los 12000 pasos** (loss clavada en 1.8 — nunca
cruza). A np=4 las 3 cruzan (lineal en ~5400 pasos).

## Interpretación — H-MEZ-4 (eje recall) CERRADO end-to-end

1. **Control positivo válido:** la atención resuelve ambas dificultades (0.999, 1.000). (La corrida
   nocturna previa fallaba el control por SUB-RECURSOS — receta mala: sin warmup, h=8, n_queries=1.
   Con warmup + h=4 + supervisión densa cruza np=8 en 1200 pasos.)
2. **El lineal satura:** resuelve np=4 (0.988) pero FALLA np=8 (0.255). Su estado fijo no alcanza
   para 8 asociaciones — la predicción de exp002 (recall acotado por el estado), ahora **entrenada
   end-to-end**, no solo training-free. (La capacidad del lineal multi-cabeza entrenado satura entre
   np=4 y 8 — más bajo que el d²/32 idealizado de exp002; el feature-map ELU+1 multi-cabeza es más
   débil que la memoria de producto externo idealizada.)
3. **El híbrido RECUPERA el recall:** 0.991 (np=4) y 0.998 (np=8) — sigue a la **atención**, NO al
   lineal. Las 2 capas de atención (entre las 4) recuperan exactamente el recall que el stack lineal
   pierde al saturar. **Esto es H-MEZ-4.**

Junto con exp005 (coste: el híbrido cuesta ~12-15% del full a L grande), H-MEZ-4 queda cerrado en
sus **dos ejes**: recupera el recall (este exp) a una fracción del coste (exp005).

## Hallazgo secundario: el recall necesita ≥2 capas de atención

A **profundidad 2**, el híbrido mínimo `[lin, attn]` (1 sola atención) FALLA (acc 0.524 a np=2),
igual que el lineal puro (0.532), mientras la atención pura `[attn, attn]` resuelve (0.998). El
circuito de inducción (cabeza de token-previo ∘ cabeza de inducción) exige **dos** operaciones de
atención compuestas; una sola capa de atención sobre una lineal no lo completa. → el ratio/ubicación
de las capas de atención importa, no solo tenerlas. (Por eso el cierre se hace a profundidad ≥4.)

## Caveats (honestidad)

- **Semilla única** (seed=0). Falta repetir con varias semillas para barras de error.
- El híbrido de la corrida principal es **2:2 (50% atención)**, no el 3:1 "mayoría lineal" de D-007.
  Prueba el MECANISMO (2 capas de atención recuperan recall); el refuerzo a profundidad 6
  (`[lin,lin,attn,lin,lin,attn]`, 33% atención) verifica la versión mayoría-lineal — ver abajo.
- Modelo chico (201k params), tarea sintética. El resultado es sobre el MECANISMO de recall, no una
  afirmación de escala.

## Refuerzo (profundidad 6, mayoría-lineal 33% atención) — EN CURSO
`[lin,lin,attn,lin,lin,attn]` a np=8,16: ¿la versión mayoría-lineal también recupera el recall?
Se completará al terminar.

## Reproducir
```
.\venv312\Scripts\python.exe -m cognia_x.experiments.exp008_recall_control.run \
  --pairs 4,8 --d_model 64 --n_heads 4 --n_layers 4 --n_queries 16 --warmup 400 \
  --lr 1e-3 --steps 12000 --min_steps 8000 --early_stop 0.99 --hybrid_ae 2
```
Artefactos: `results_depth4.json`, `run_depth4.log`.
