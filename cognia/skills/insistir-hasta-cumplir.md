---
name: insistir-hasta-cumplir
description: Itera sobre una tarea hasta que se cumpla la especificación verificable, sabiendo cuándo parar: si dos intentos seguidos dejan el síntoma identico, hay que dejar de parchear y buscar la causa; activa esta skill si el usuario dice "sigue intentandolo hasta que pasen los tests", "no pares hasta que funcione", o "reintenta hasta cumplir la especificacion".
---

# insistir-hasta-cumplir

Itera hasta que se cumpla la especificación o se detecte un ciclo sin progreso.

## Como proceder
1. Define la especificación verificable: usa `recordar` para guardar la condición que debe cumplirse.
2. Ejecuta la tarea: usa `ejecutar` para correr el comando o script que intenta cumplir la especificación.
3. Verifica la especificación: usa `calcular` o `leer_archivo` para comprobar si se cumplió la especificación.
4. Si se cumple, termina: usa `notas` para registrar que la tarea se completó.
5. Si no se cumple, anota el estado actual: usa `anotar` para guardar el resultado actual.
6. Repite desde el paso 2: vuelve a ejecutar la tarea y verifica nuevamente.
7. Si dos verificaciones seguidas tienen el mismo resultado, detente: usa `recordar` para comparar los resultados y `notas` para registrar que se detectó un ciclo sin progreso.

## Reglas
- Verifica la especificación después de cada ejecución.
- No termines sin verificar la especificación.
- Detente si detectas un ciclo sin progreso (dos verificaciones seguidas con el mismo resultado).
- Anota cada estado para rastrear el progreso.
