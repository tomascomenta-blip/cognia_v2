# PREREG — AUDIT DEL ORÁCULO (Top-1 fase A, COLONIA→CASI-GRANDE)

**CONGELADO ANTES DE CORRER (2026-07-12).**

## Hipótesis (del consolidado de investigación)
El cuello de la colonia es la SELECCIÓN/RUTEO, no la generación. Si la
unión-oráculo (por ítem, el mejor miembro acierta) supera al mejor miembro
único por ≥3pp en algún eje, un router kNN/cluster (fase B) paga. Hipótesis
nula fuerte: en CÓDIGO el techo compartido Qwen predice ~0pp de unión extra;
la decorrelación esperable está en math/razonamiento (VibeThinker: base
Qwen2.5-Math + RL distinto) y español (LFM2.5: arquitectura no-Qwen).

## Método
- Ejes y suites CONGELADAS:
  - código duro: tasks_hard_v2 ×40 RAW (columnas: 3B [ya medido 15/40],
    qwen35_4b [E1 en curso], cascada [23/40 ya medido]).
  - razonamiento: g2_razonamiento.jsonl PRIMEROS 40 ítems en orden del
    archivo (sin cherry-picking; sha en SUITES_FROZEN).
  - español: g5_espanol.jsonl completo (25).
- Miembros del audit (5): 3b (ChatML), qwen3_4b (ChatML), qwen35_4b
  (ChatML + prefill no-think, igual que E1), vibethinker15b (SE LE PERMITE
  pensar: budget 640, se le quita el bloque <think> antes del oráculo — su
  skill ES el razonamiento), lfm25_12b (ChatML).
- Protocolo: greedy, cache_prompt=false, oráculo determinista
  (suite_oracle), persistencia incremental, servers secuenciales (RAM).

## Gates (congelados)
- **AUD-1 (gate de fase B)**: unión-oráculo − mejor-único ≥ 3pp en ≥1 eje
  → se construye el router kNN (fase B) para ese eje.
- **AUD-2 (info)**: tabla de perfil de skill por miembro y eje (la
  "feromona" inicial del ledger de la colonia).
- **AUD-3 (info)**: latencia por miembro y eje (presupuesto del router).

## Regla de corte
Si AUD-1 falla en TODOS los ejes → el ruteo por contenido no paga con la
flota actual; la fase B no se construye y la colonia se queda con
léxico+dificultad (se documenta como resultado negativo útil).
