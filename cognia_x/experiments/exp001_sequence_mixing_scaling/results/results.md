# exp001 - resultados (escalado de mezcla de secuencia en CPU)

- numpy 2.4.6 | d=64 | reps=3 | seed=1234 | cpu_count=4 | dtype=float32
- **Cruce en tiempo (linear < full):** L = 128
- Memoria = tamano analitico del tensor intermedio dominante (scores LxL vs KV dxd).

| L | full (ms) | full mem (MB) | linear (ms) | linear mem (MB) | ssm-loop (ms) | speedup lin/full | mem full/lin |
|---|---|---|---|---|---|---|---|
| 128 | 2.02 | 0.06 | 0.57 | 0.0156 | 0.62 | 3.5 | 4 |
| 256 | 2.96 | 0.25 | 0.53 | 0.0156 | 0.72 | 5.6 | 16 |
| 512 | 5.94 | 1.00 | 0.82 | 0.0156 | 1.15 | 7.2 | 64 |
| 1024 | 24.58 | 4.00 | 1.50 | 0.0156 | 2.57 | 16.4 | 256 |
| 2048 | 107.23 | 16.00 | 3.39 | 0.0156 | 6.90 | 31.6 | 1024 |
| 4096 | 481.52 | 64.00 | 6.85 | 0.0156 | 10.61 | 70.3 | 4096 |

