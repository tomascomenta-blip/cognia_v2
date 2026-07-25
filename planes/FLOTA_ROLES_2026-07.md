# FLOTA POR ROLES — reformulación 2026-07-24

**Pedido del dueño:** reformular todos los expertos — conservar lo que está bien,
cambiar/implementar lo que está mal — para acercar el sistema lo más posible a
**GLM 5.2**.

**Realidad física:** GLM 5.2 es un MoE de 744B (40B activos); su Q4 pesa 376 GB.
En esta máquina (RTX 5060 Ti 16GB VRAM + 31GB RAM) es inalcanzable como modelo.
Lo alcanzable es **aproximar su PERFIL** (agentic coding + razonamiento fuerte +
juicio + multimodal) con **ruteo por roles**, poniendo en cada rol el mejor
modelo de su clase que quepa (estado del arte a jul-2026, investigado hoy).
Esto extiende la decisión ya tomada en G4 ("ROLES sobre el residente, no
entrenar especialistas") de un solo residente a una flota chica de residentes
por rol.

## Auditoría (con la evidencia medida, no opiniones)

### CONSERVAR (medido bueno)
| Pieza | Rol | Evidencia |
|---|---|---|
| qwen2.5-coder-14b + draft 0.5b | CODEAR / REPARAR | draft-verify 2.4-3x medido (43.9→107-135 tok/s); todo el pipeline se midió con él |
| Qwen2.5-VL-7B | ÁRBITRO FINAL | 0 varianza en 6 corridas; techo 9.5 con pares idénticos |
| Qwen2.5-VL-3B | ÁRBITRO EN-LAZO | convive con el 14B en 16GB; fiable con compuesta lado-a-lado a alto=700 (medido) |
| SDXL+LayerDiffuse+LoRAs (pixel, pvz) + BiRefNet | IMAGINAR (mockups/sprites) | mockups de calidad profesional; sprites RGBA verificados en GPU |
| MiniCPM + LoRA tooling | HERRAMIENTAS | 0%→97% tool-match entrenado y verificado |
| Micro-expertos idea_router e idioma | RUTEO LÉXICO | pasaron sus gates pre-registrados |
| Qwen3-4B-Thinking-2507 | RAZONADOR BARATO | líder de su tamaño; ya ruteado por fleet_router |

### CAMBIAR / IMPLEMENTAR (medido malo o hueco)
| Problema medido | Cambio | Gate pre-registrado |
|---|---|---|
| **No hay pensador serio** (el hueco #1 vs GLM 5.2): el coder-14b no razona, el 4B es chico | **AÑADIR gpt-oss-20b** (MXFP4 13.7GB, cabe ENTERO en GPU, ≈o3-mini, esfuerzo low/med/high = mapea a roles) como PENSADOR solo-GPU; **AÑADIR OpenReasoning-Nemotron-14B Q4** (~9GB, destilado R1-0528 SOTA 14B) como PENSADOR-EN-LAZO (convive con VL-3B, cosa que gpt-oss NO: 13.7+3.2>16) | Smoke A/B de 5 problemas verificables: el nuevo pensador debe ganar al 14b-coder en aciertos; si empata, KILL (no se adopta) |
| **Constructor web débil** (juegos 5.0-7.0; PixelRunner 68%): el 14B no traduce visión→UI | **CABLEAR UIGEN-X-8B** (ya en disco, sin usar) como CONSTRUCTOR web vía `COGNIA_CONSTRUCTOR_URL` (call-time, patrón del crítico) | A/B: misma idea x3 con 14B vs UIGEN, juez VL-7B contra el mismo brief; UIGEN se adopta si mediana ≥ +1.0 |
| qwen2.5-7b-instruct: redundante (ni coder, ni thinking, ni VL) | **RETIRADO** (verificado: ningún módulo lo rutea; queda en disco como candidato a borrado por el dueño, 4.7GB) | n/a |
| ~~Qwen3-1.7B: retirar~~ **CORREGIDO al verificar**: es el RAZONADOR-CPU por diseño (razonador.py, thinking que un CPU aguanta) | **SE CONSERVA** con su rol real — la auditoría inicial se equivocaba; el código manda | n/a |
| Servir el combo correcto por tarea es manual y propenso a error | **scripts/servir_flota.py**: modos `construir` (coder-14b+VL-3B), `construir-ui` (UIGEN+VL-3B), `pensar` (gpt-oss-20b solo), `pensar-en-lazo` (Nemotron-14B+VL-3B), `juzgar` (VL-7B solo) | arranque verificado de cada modo |

### DESCARTADO CON DATOS (no perseguir)
- **Qwen3.6-27B denso**: benchmarks ≈ iguales al 35B-A3B pero Q4=18GB no cabe;
  Q3 15GB deja sin sitio al KV. Operativamente peor aquí.
- **Qwen3.6-35B-A3B**: el mejor razonamiento absoluto alcanzable (AIME25 92.3)
  con expertos en RAM, pero Q4=23GB sobre 31GB de RAM total del sistema deja
  ~8GB para todo lo demás — frágil. Queda ANOTADO como "pensador profundo"
  opcional (Q3=17GB), NO en la flota por defecto. Si un A/B futuro muestra que
  el techo de gpt-oss-20b no alcanza, se mide.
- **DeepSeek R2**: no existe (rumor, jul-2026). R1-Distill originales: superados
  por OpenReasoning-Nemotron con el mismo footprint.

## La flota objetivo (el "GLM 5.2 de esta máquina")

```
                    ┌─ PENSAR duro (solo)      → gpt-oss-20b (high, GPU entera)
                    ├─ PENSAR en el lazo       → OpenReasoning-Nemotron-14B + VL-3B
  fleet_router ─────┼─ RAZONAR barato          → Qwen3-4B-Thinking (como hoy)
  (+ micro-expertos)├─ CODEAR / REPARAR        → qwen2.5-coder-14b + draft 0.5b
                    ├─ CONSTRUIR UI/web        → UIGEN-X-8B (si gana su A/B)
                    ├─ HERRAMIENTAS            → MiniCPM + LoRA tooling
                    ├─ IMAGINAR (mockup/sprite)→ SDXL+LayerDiffuse (+pixel/pvz)
                    └─ ARBITRAR   en-lazo/final→ VL-3B / VL-7B
```

Regla de VRAM (16GB): en el lazo diseño-a-código conviven a lo sumo un 14B-clase
(9GB) + VL-3B (3.2GB). gpt-oss-20b y VL-7B corren SOLOS. SDXL corre SOLO
(mockups/sprites se generan en fase previa, patrón mockup_path/assets ya
implementado y testeado).

## Resultados (2026-07-24)

### A/B CONSTRUCTOR — GATE PASA, UIGEN ADOPTADO ✅
3 ideas (dashboard, landing, juego), 1 generación cruda por modelo (sin
reparaciones — aísla el constructor), juez VL-7B (2 corridas por par, mediana),
mismas ideas para ambos:

| Idea | coder-14b | UIGEN-X-8B |
|---|---|---|
| dashboard cripto | 9.5 | 8.7 |
| landing cafetería | 7.5 | 9.5 |
| **juego arcade** | **2.5** | **7.5** |
| **mediana global** | **7.5** | **8.7** |

Delta +1.2 ≥ gate (+1.0) → UIGEN es el CONSTRUCTOR web de la flota. Donde más
gana es exactamente en la debilidad medida (juegos: +5.0).

HALLAZGO operativo: UIGEN DEBE ir por el camino del constructor
(COGNIA_CONSTRUCTOR_URL, max_tokens 8000). Por el camino genérico (6000) su
bloque <think> se come el presupuesto y el fence sale truncado (1 fallo
reproducido y corregido así durante el A/B).

### SMOKE A/B RAZONADORES — gpt-oss-20b ARRASA ✅
5 problemas con respuesta exacta (pre-verificados a mano), :8080, temp 0.1:

| Modelo | Aciertos | Tiempo total |
|---|---|---|
| **gpt-oss-20b (MXFP4)** | **5/5** | **13s** |
| Qwen3-4B-Thinking-2507 | 4/5 | 95s |
| qwen2.5-coder-14b | 3/5 | 19s |

gpt-oss-20b es a la vez el MAS listo y el MAS rapido: PENSADOR por defecto
(modo `pensar` de servir_flota). El coder-14b falla justo lo que un no-pensador
falla (inclusion-exclusion, proporciones). El 4B queda como razonador barato
residente y el 1.7B como razonador-CPU. Pendiente: OpenReasoning-Nemotron-14B
(descargando) para el rol PENSADOR-EN-LAZO (gpt-oss no convive con VL-3B:
13.7+3.2 > 16GB).

## Estado de ejecución
- [x] Investigación del estado del arte (jul-2026) con fuentes
- [ ] Descarga gpt-oss-20b MXFP4 + OpenReasoning-Nemotron-14B Q4 (en curso)
- [x] COGNIA_CONSTRUCTOR_URL en generator (+ 4 tests)
- [x] A/B constructor UIGEN vs 14B (juez VL-7B) — ADOPTADO
- [ ] Smoke A/B razonadores (pendiente de descarga)
- [x] servir_flota.py (5 modos, 3 verificados arrancando: construir,
      construir-ui, juzgar) + retiros verificados contra el código
