---
name: escribir-tests
description: Escribe tests para una funcion o modulo y verifica que pasen. Usar cuando el usuario pida tests, pruebas, cobertura o "probar" codigo.
---

# escribir-tests

Escribi tests REALES que corran, no esqueletos.

## Como proceder
1. Lee el codigo a testear con `leer_archivo`. Entende su contrato (entradas, salidas, errores).
2. Escribi el test con `escribir_archivo` en `tests/test_<nombre>.py`, estilo pytest, igualando
   el estilo de los tests vecinos del repo.
3. Cubri: el caso feliz, al menos un caso borde, y el caso de error esperado.
4. Corre los tests con la herramienta `tests` sobre el archivo nuevo.
5. Si fallan, lee el error, corregi el test (o reporta si el bug es del codigo bajo prueba) y volve a correr.

## Reglas
- Un test que no corre no cuenta. No termines hasta verlo en verde.
- Tests deterministas: nada de depender de hora real, red o orden de ejecucion.
- Cada test prueba UNA cosa y su nombre dice cual.
