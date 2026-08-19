# Evidencia cruda del tecleo real de `/mejorar` en el REPL (2026-08-19)

Copiada aca durante la revision adversarial de la ronda 2. Antes vivia solo en
el scratchpad EFIMERO de la sesion de Claude, sin ruta citada en
`MANAGER_LOG.md`: manana la afirmacion "la salida es real" dejaba de ser
comprobable, y con ella los limites 2 y 5 del informe, que se apoyan en estos
volcados. Los artefactos del A/B si se habian copiado (`scratchpad/ab_mejorador/`);
estos no.

## Ficheros

| fichero | que es |
|---|---|
| `s_texto.txt` | sesion ConPTY: dos `/mejorar <texto>` (facturas, regalo) |
| `s_auto.txt`  | sesion ConPTY: `/mejorar auto` + un mensaje normal (el enganche del Enter actua solo) |
| `s_off.txt`   | sesion ConPTY: `/mejorar off` + un mensaje normal (el REPL vuelve a lo de antes) |
| `s_reset.txt` | sesion ConPTY: vuelta del estado a `preguntar` (el default) al cerrar |
| `auto.txt`    | el intento FALLIDO que soporta el limite 5 del informe: Git Bash convirtio `/mejorar auto` en `C:/Program Files/Git/mejorar auto` y v2 leyo "auto" como automovil ("Arma un plan de mejora para mi coche"). Hace falta `MSYS_NO_PATHCONV=1` |
| `teclear_repl.py` | el arnes: pywinpty, lector en HILO (`PtyProcess.read()` BLOQUEA) y tope duro de tiempo (el spinner escupe bytes sin parar, esperar silencio no corta) |
| `limpiar.py` | quita ANSI y los repintados de prompt_toolkit para poder leer el crudo |

## Comprobacion del `off`, no impresion

    grep -c "Mejorando el prompt" s_off.txt   ->  0
    grep -c "prompt mejorado"     s_off.txt   ->  0
    grep -c "Mejorando el prompt" s_texto.txt ->  distinto de 0
    grep -c "prompt mejorado"     s_auto.txt  ->  distinto de 0

## Por que no sirve `printf ... | python -m cognia`

El enganche del Enter se apaga a proposito sin tty (`_mejora_aplica` ->
`selector.hay_tty()`), asi que por pipe el modo `auto` NUNCA se activa y el REPL
parece ignorar la funcion. Costo tres intentos antes de montar el ConPTY.
