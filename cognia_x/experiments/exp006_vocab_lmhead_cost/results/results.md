# exp006 - coste lm_head(V) vs bloque transformer + memoria embed/head

- numpy 2.4.6 | reps=20 | seed=7 | d=2048 | n_layers=24 | cpu_count=4
- 1 bloque (6 GEMVs): 13.2377 ms | 7.60 GFLOP/s

## (A) coste lm_head = Eout @ h (GEMV O(V*d))
| V | time (ms) | GFLOP/s | lm_head/bloque | lm_head / n_layers bloques |
|---|---|---|---|---|
| 8192 | 3.9939 | 8.40 | x0.302 | 1.26% |
| 16384 | 8.0146 | 8.37 | x0.605 | 2.52% |
| 32768 | 16.4758 | 8.15 | x1.245 | 5.19% |
| 65536 | 32.2823 | 8.32 | x2.439 | 10.16% |

## (C) embedding de ENTRADA (lookup de 1 fila)
- V=65536 | lookup = 0.001190 ms | el lm_head al mismo V es ~27128x mas caro -> lookup trivial.

## (D) cruce lm_head vs bloque (extrapolacion lineal en V)
- pendiente: 492.5890 ns/fila de vocab (medida en V=65536)
- lm_head iguala **1 bloque** a V ~= 26,874
- lm_head iguala **24 bloques** a V ~= 644,968

## (E) memoria: params embed+head y fraccion del modelo (analitico)
- backbone = n_layers*12*d^2 = 1,207,959,552 params
| V | embed+head tied (M) | % tied | embed+head untied (M) | % untied | total tied (M) |
|---|---|---|---|---|---|
| 8192 | 16.8 | 1.37% | 33.6 | 2.70% | 1225 |
| 32768 | 67.1 | 5.26% | 134.2 | 10.00% | 1275 |
| 65536 | 134.2 | 10.00% | 268.4 | 18.18% | 1342 |
| 131072 | 268.4 | 18.18% | 536.9 | 30.77% | 1476 |
| 256000 | 524.3 | 30.27% | 1048.6 | 46.47% | 1732 |

