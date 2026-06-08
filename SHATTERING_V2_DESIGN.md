# Shattering v2 — Inferencia Tensor-Parallel Descentralizada sobre LAN

> Documento de diseño. Producto de una sesión de grilling (8-jun-2026) que resolvió 12
> ramas de decisión. Es el contrato del rediseño del subsistema de shattering.
> Fuente de verdad de las decisiones; el progreso de implementación va en `MANAGER_LOG.md`.

## Visión en una frase
Un **cliente de IA local-first** donde un aula/lab junta sus equipos débiles en una LAN y,
vía **tensor parallelism**, corren *colectivamente* un modelo grande (14B) que ninguno aguanta
solo — bajando la latencia de **un** prompt repartiendo cada matriz entre dispositivos. Gratis
por default; con escape opcional a "tus propios modelos a tu costo".

## Para quién
Gente sin recursos para suscripción de IA ni para mantener un modelo entero localmente.
Escenario canónico: un aula/lab con varios equipos modestos y un switch gigabit.

---

## Las 12 decisiones (contrato del diseño)

| # | Decisión | Elección fija |
|---|----------|---------------|
| 1 | Topología | **LAN escalable** (no WAN ⇒ limpio con la restricción dura "sin sharding WAN síncrono") |
| 2-3 | Objetivo / técnica | Bajar latencia de **un prompt** vía **Tensor Parallelism** (grado-investigación, asumido y aceptado) |
| 4 | Heterogeneidad | **(B)** partición ponderada por capacidad → **(C)** híbrido 2D (TP-en-grupo + pipeline-entre-grupos) como objetivo |
| 5 | All-reduce | **(A)** centralizado (reusa `coordinator/`) → **(C)** recursive-doubling cuando N>8. Payload de KB ⇒ latency-bound, anillo descartado |
| 6 | Churn/fallos | heartbeat→timeout→**re-shard entre sobrevivientes**→recomputar token en curso; **seeder = respaldo** (tiene pesos completos en disco). Sin replicación (mataría la premisa de memoria), sin corrupción silenciosa. Aceptado hipo 1-3s por caída |
| 7 | North Star | **Qwen2.5-14B INT4 / 4 equipos heterogéneos / LAN-aula gigabit**; baseline a vencer = 3B single-device; **partición paramétrica** en tamaño y grado TP (escalar = config, no reescribir) |
| 8 | Modos | **Dos modos explícitos**: *Red Compartida (swarm)* y *Standalone* (tus modelos a tu costo: local TP=1 o tu API key). Mismo motor (standalone = swarm de 1). API = opt-in duro con consentimiento de salida de datos |
| 9 | Bootstrap | auto-descubrimiento (mDNS/UDP) como conveniencia + **código/QR como fallback y ancla de confianza/auth** (codifica IP+puerto+secreto, autentica membresía). Coordinador = seeder por default |
| 10 | Confianza | confianza de membresía + **sanity checks baratos siempre activos** (NaN/inf/norma por tensor → expulsión visible del culpable). Spot-recomputación = flag opcional futuro. Crypto descartada |
| 11 | Puntas | embedding+lm-head+tokenizer+sampling en el **seeder** (cabeza/cola); swarm = solo el tronco (capas transformer) en TP. lm-head → vocab-parallel solo si el profiling muestra que el seeder es cuello |
| 12 | Seeding | seeder streamea cada tajada TP al unirse + **caché en disco por hash de layout** (1ª vez ~20s gigabit, luego instantáneo). P2P reservado a pools 15+. Seeder = única fuente de verdad del modelo completo |

---

## Verdades físicas que NO se negocian
- **El eje token es secuencial** (autoregresivo) ⇒ ningún número de equipos acelera *eso*. TP solo
  acelera *dentro* de cada token (un forward pass).
- TP es una **barrera síncrona por capa** ⇒ el equipo **más lento marca el reloj** del sistema en
  cada all-reduce. Por eso (B)/(C) para heterogeneidad y por eso aula-gigabit, no café-WiFi.
- TP le gana a un solo equipo **solo cuando** cómputo-por-capa >> latencia-de-red. Aula cableada +
  CPUs débiles + 14B = la ventana donde gana. **Es frágil; no es promesa de producto, es tesis a probar.**
- "Más equipos = tu respuesta más rápida" NO es vendible en general; "más equipos = la red sirve a
  más gente / más tokens/s totales" SÍ (pipeline+batching), pero ese es el modo throughput, no (iii).

---

## Qué del Cognia actual SOBREVIVE vs se REESCRIBE
**Sobrevive:**
- `shattering/router.py` (LOGOS/TECHNE/RHETOR).
- `shattering/quantization.py` (INT4 pack/unpack per-row — compatible con TP, ver abajo).
- `shattering/model_constants.py`.
- `node/qwen2_ops.py` (`RealTransformerLayer`, `INT4Weights`) como **referencia dorada** y base de
  los kernels por-tajada.
- Kernels C (parcial), `node/nano_draft.py` (speculative).
- `coordinator/` muta de relay-en-cadena a **reductor de all-reduce centralizado**.

**Se reescribe:**
- El motor de inferencia: de pipeline-por-capas a **TP por columnas/filas**.
- El layout de pesos: re-tajado a layout-TP (column-parallel q/k/v/gate/up + row-parallel o/down),
  **2 all-reduce por capa**.
- El transporte: `relay` de hidden-en-cadena → colectivo reduce/broadcast.

## Compatibilidad INT4 ↔ Tensor Parallelism (clave, verificada)
La cuantización es **per-row (por canal de salida)**, escala `(rows,1)`. Por eso:
- **Column-parallel** (q,k,v,gate,up): se corta por **filas de salida** ⇒ cada rank toma filas
  completas con sus propias escalas → **bit-exacto**, sin re-cuantizar.
- **Row-parallel** (o_proj, down_proj): se corta por **columnas de entrada** ⇒ todos los ranks
  comparten el vector de escalas per-row (pequeño) y cada uno tiene un slice de columnas de los
  nibbles; suma parcial + all-reduce reconstruye exacto → **bit-exacto** (los puntos de corte caen
  en frontera de byte porque head_dim y dims intermedias son pares).

El "choque INT4 ↔ row-parallel" NO existe: es manejable con escala compartida.

---

## Camino de inferencia (modo swarm, North Star: 4 equipos, TP=4)
```
SEEDER:  prompt → tokeniza → embedding lookup → hidden(1, hidden_dim)
   │  por cada capa l en 0..L-1:
   ├─→ broadcast hidden a los T equipos
   │   cada equipo i: su 1/T de q/k/v (sus cabezales) → atención local
   │                  (KV-cache de SUS cabezales, MLA) → su 1/T de o_proj
   │   ALL-REDUCE (centralizado por coordinador) → hidden sumado
   │   cada equipo: su 1/T de gate/up (SwiGLU) → su 1/T de down_proj
   │   ALL-REDUCE → hidden de salida de la capa
   │   [sanity check NaN/inf/norma en cada tajada recibida]
   └─← hidden final
SEEDER:  final_norm → lm-head → sample → siguiente token → repetir
         [+ NanoDraft: draft propone K, swarm verifica en 1 pase batched]
```
Nota: en TP la atención se parte por cabezales ⇒ cada equipo guarda el **KV-cache de SUS cabezales**,
sin all-reduce extra para el cache. El MLA/LPC se vuelve per-device-per-head-subset.

---

## Reconciliación con `CLAUDE.md` (restricciones duras)
- ✅ *"Sin sharding WAN síncrono"* → es **LAN**, no WAN. Limpio.
- ✅ *"Sin PyTorch en nodos"* → all-reduce a mano en numpy+C+sockets (no `torch.distributed`/NCCL).
- ✅ *"Cero datos personales centralizados"* → swarm queda en la LAN; API solo opt-in con
  consentimiento; KV-cache per-device.
- ✅ *"Nada de mocks; cada subsistema cierra con prueba CLI real"* → cada fase cierra contra el
  modelo/forward de verdad, no pytest solo.
- ✅ *"Sin constantes hardcodeadas de modelo"* → todo desde `model_constants.py`.

---

## Orden de construcción (cada fase = prueba real con CHECK)
1. **Forward TP en-proceso** (`shattering/tensor_parallel.py`): partición de `RealTransformerLayer`
   en T tajadas + verificar que el forward TP **iguala** el forward golden (correctitud antes que red).
2. **All-reduce centralizado** sobre sockets (numpy) + sanity checks. TP=2 en 2 procesos misma máquina.
3. **2 equipos físicos** en LAN, TP=2, medir tok/s vs 3B single-device (la tesis).
4. **4 equipos**, TP=4, partición ponderada (B) + churn (re-shard al desconectar uno).
5. **Bootstrap** (código/QR + auto-discovery) + seeding con caché.
6. **Modo standalone** (TP=1 local + API opt-in) detrás del mismo motor.
7. Escalar config a 32B / pipeline-entre-grupos (C) cuando 4 equipos quede chico.

## Abiertos (marcados honestos, no resueltos en el grilling)
- **Mapeo 2D exacto:** con 4 equipos = TP=4, un solo grupo, sin pipeline. El pipeline-entre-grupos
  (C) recién aparece a 8+ equipos / 32B. Umbral exacto sin decidir.
- **Integración con memoria/Chimera** (ver memoria `chimera-cognitive-layer`): cómo el KV
  per-device-per-head convive con MLA/LPC cross-turn en swarm.
- **Lista de proveedores API** del modo standalone y UX del consentimiento de salida de datos.
- **Bug latente (no de este diseño):** `RealTransformerLayer` no suma los bias q/k/v que Qwen2.5 sí
  define (el convert script los guarda como `l{i}_{q,k,v}_b` pero el forward los ignora). Afecta al
  baseline actual, no a la equivalencia TP. Registrar y corregir aparte.
