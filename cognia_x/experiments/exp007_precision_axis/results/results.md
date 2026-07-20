# exp007 - resultados (eje de precision: bytes/peso vs throughput, GEMV)

- numpy 2.4.6 | reps=20 | seed=7 | cpu_count=4 | op = y = W @ x (GEMV)
- Hipotesis (D-009/H-BIT-1 caveat): en numpy puro, int8 naive NO acelera vs float32 BLAS;
  el ahorro de int8 es de MEMORIA (4x almacenamiento), no de computo.

## Tiempos por camino y ratio vs float32 (ratio>1 = mas rapido, <1 = mas lento)
| n | float32 BLAS (ms) | int8 naive (ms) | ratio int8 | dequant+f32 (ms) | ratio dequant |
|---|---|---|---|---|---|
| 2048 | 0.9248 | 8.4513 | x0.109 | 13.7082 | x0.067 |
| 4096 | 4.2212 | 34.8795 | x0.121 | 58.4700 | x0.072 |

## Memoria de W: float32 vs int8 (ahorro de ALMACENAMIENTO real)
| n | float32 (MB) | int8 (MB) | ahorro |
|---|---|---|---|
| 2048 | 16.78 | 4.19 | x4 |
| 4096 | 67.11 | 16.78 | x4 |

## Lectura
- int8 naive vs float32: si el ratio < 1, NO acelero (confirma el caveat: el ahorro de bytes no compra computo en numpy puro).
- dequant+float32: usa BLAS pero paga el unpack int8->float; el ratio dice si almacenar int8 y descomprimir da speedup neto.
- El ahorro 4x es de MEMORIA/almacenamiento, no de FLOPs: requiere kernels dedicados (T-MAC, bitnet.cpp) para volverse throughput.

