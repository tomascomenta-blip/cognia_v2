# exp004 - resultados (roofline de CPU, GEMV decode batch=1)

- numpy 2.4.6 | reps=30 | seed=7 | cpu_count=4 | op = y = W @ x (GEMV)
- Memory-bound si: GFLOP/s << pico CPU, GB/s ~plano al crecer n, f32 ~2x f64.

## Barrido 1 - bytes/peso
| n | dtype | time (ms) | GFLOP/s | GB/s |
|---|---|---|---|---|
| 1024 | float64 | 0.455 | 4.61 | 18.44 |
| 1024 | float32 | 0.189 | 11.08 | 22.16 |
| 2048 | float64 | 2.144 | 3.91 | 15.65 |
| 2048 | float32 | 0.993 | 8.45 | 16.90 |
| 4096 | float64 | 7.518 | 4.46 | 17.85 |
| 4096 | float32 | 3.401 | 9.87 | 19.73 |

### Speedup f32 vs f64 (prediccion ~2x)
| n | speedup f32/f64 |
|---|---|
| 1024 | 2.40 |
| 2048 | 2.16 |
| 4096 | 2.21 |

## Barrido 2 - hilos de BLAS (n=4096, float32)
- threadpoolctl NO instalado -> medido a hilos por defecto (~4).

| hilos (defecto) | time (ms) | GB/s |
|---|---|---|
| ~4 | 4.066 | 16.50 |

