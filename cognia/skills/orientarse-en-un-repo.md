---
name: orientarse-en-un-repo
description: Ayuda a entender la estructura y las dependencias de un proyecto desconocido. Usar cuando el usuario quiera navegar o entender un nuevo repositorio de código.
---

# orientarse-en-un-repo

Descubre la estructura del proyecto y navega solo en lo necesario.

## Como proceder
1. Genera un mapa del proyecto: usa el comando `/mapa-codigo` para obtener una visión general de las clases y funciones.
2. Analiza el mapa: lee la salida de `/mapa-codigo` para entender las principales dependencias y relaciones entre los componentes.
3. Identifica el punto de entrada: busca la función principal o el archivo de entrada típico (como `main.py`, `app.py`, etc.) usando `buscar`.
4. Abre el punto de entrada: usa `leer_archivo` para ver el contenido del archivo identificado.
5. Navega a través de las dependencias: usa `buscar` y `leer_archivo` para explorar las funciones y clases que se llaman desde el punto de entrada.
6. Repite el proceso: sigue navegando a través de las dependencias hasta que comprendas la estructura principal del proyecto.

## Reglas
- No abras archivos aleatoriamente: siempre navega a través de las dependencias identificadas.
- Usa `/mapa-codigo` al principio para tener una visión general.
- No te extiendas en archivos que no sean relevantes para la funcionalidad principal.
- Anota las partes importantes con `anotar` para referenciarlas más tarde.
