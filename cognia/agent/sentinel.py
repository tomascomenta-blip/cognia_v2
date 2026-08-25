# -*- coding: utf-8 -*-
"""Sentinel — validación de seguridad pre-acción, DEFAULT-ON.

Mandato 2026-07-14: "Sentinel debe estar activo por defecto; todos los
agentes deben usarlo para validación/supervisión/seguridad antes de
ejecutar acciones importantes." El inventario detectó que la seguridad de
Cognia estaba dispersa (GoalContract al final del /hacer, sandbox para
código Python generado, denylist de substrings en `ejecutar` con
shell=True, gates de pantalla) y que `ejecutar` era denylist pura — cualquier
comando no listado pasaba. Sentinel unifica la decisión ANTES de la acción.

Modelo de riesgo para comandos de shell (3 niveles):
- ALLOW: prefijo en la allowlist de dev conocido-seguro (git status, pytest,
  ls, python, ruff, Get-ChildItem, ...) → pasa sin fricción (un agente de
  código los usa todo el tiempo; bloquearlos lo inutiliza). OJO: el prefijo
  NO gana al contenido — ver la nota de PRECEDENCIA más abajo, donde está
  medido el fallo del 2026-08-25 (`find <ruta> -delete` salía ALLOW).
- BLOCK: patrón destructivo duro (rm -rf, mkfs, dd, shutdown, fork-bomb,
  format C:, redirección a dispositivos) → jamás pasa, ni en autónomo.
- CONFIRM: todo lo demás (riesgo desconocido) → pide ctx['confirm'] humano;
  en modo autónomo (COGNIA_AUTONOMOUS=1) procede pero SIEMPRE audita.

Es más defendible que la denylist pura (default-deny para lo desconocido,
no default-allow) y honesto sobre el trade-off: no es aislamiento de OS
(eso es el sandbox de program_creator para código Python). Cada decisión
deja evento en el bus (cognia/events.py) y línea en la auditoría
append-only (~/.cognia/sentinel_audit.jsonl), así la supervisión es
observable por la oficina y por un manager.

Kill-switch: COGNIA_SENTINEL=0 lo desactiva (vuelve al comportamiento
denylist previo). Default = ON (la excepción pedida por el dueño).
"""
import base64
import binascii
import datetime
import json
import os
import re
import threading
from pathlib import Path

# El append con lock + la rotacion viven en backend_activo (solo stdlib): la
# rotacion estaba COPIADA en los dos modulos y por eso la carrera que destruia
# la generacion .1 tambien estaba en los dos. Una implementacion, un arreglo.
from cognia.backend_activo import escribir_linea_jsonl

_AUDIT = Path.home() / ".cognia" / "sentinel_audit.jsonl"

# Rotacion a UNA generacion (.1): el jsonl crecia sin cota (492KB en 2
# semanas). Al superar el tope se renombra a .1 (pisando la generacion
# previa) y se sigue en un archivo fresco. Mismo esquema que backend_activo.
_ROTAR_BYTES = 10 * 1024 * 1024

# ══════════════════════════════════════════════════════════════════════
# PRECEDENCIA (arreglo 2026-08-25): el CONTENIDO gana al PREFIJO
# ══════════════════════════════════════════════════════════════════════
# El orden viejo era: BLOCK duro (substrings) -> encadenamiento ->
# allowlist por PREFIJO. Con eso el prefijo ganaba al contenido y
#   find C:/Users/usuario/Pictures -name '*.jpg' -delete
# salia ALLOW con razon "prefijo 'find' conocido-seguro" (medido hoy con
# la sonda del scratchpad, 3 falsos negativos). Es EXACTAMENTE el comando
# que una sesion del chat afirmo haber ejecutado sobre las capturas del
# dueno, y con COGNIA_ACCESO_TOTAL=1 (default de las sesiones del control
# remoto) un CONFIRM tambien procede: el unico nivel que lo habria parado
# es BLOCK.
#
# En el mismo sentido, el patron ">/dev/" bloqueaba `cat x 2>/dev/null` y
# `ls ... 2>/dev/null | head` (4 falsos positivos medidos): el agente de
# la corrida real gasto 6 pasos y cerro "sin progreso verificado" porque
# TODO lo que llevaba 2>/dev/null salia "patron destructivo irreversible".
#
# Orden nuevo (el primero que casa manda):
#   0) neutralizar el RUIDO de shell (2>/dev/null, >/dev/null, 2>&1): es
#      descarte de salida, no destruccion.
#   1) envoltorios (powershell -c / pwsh -c / cmd /c / bash -c): se
#      clasifica el PAYLOAD, no el envoltorio (si no, `powershell -c "ri
#      -r -fo ..."` heredaba el ALLOW de 'powershell').
#   2) BLOCK duro por patron (rm -rf, format, dd, mkfs, shutdown...).
#   3) BORRADO EN MASA dentro de cualquier comando: find -delete,
#      find -exec rm|del|..., xargs rm, "| Remove-Item", robocopy /MIR,
#      rsync --delete. -> BLOCK siempre (ver justificacion abajo).
#  3b) INTERPRETE con codigo EN LINEA (python -c, node -e, npx <paquete>):
#      el borrado vive en el codigo, no en la cabeza ni en un patron de
#      shell. Se inspecciona el payload (ver mas abajo).
#   4) modificadores destructivos de un solo objetivo -> CONFIRM, y BLOCK
#      si apuntan a ruta protegida o absoluta fuera del cwd.
#   5) encadenamiento (; && | $( ` y el SALTO DE LINEA) -> el peor de los
#      segmentos, propagando el cwd que deja un `cd` anterior.
#   6) CABEZA destructiva (rm/del/Remove-Item/ri/Clear-Content/...) ->
#      CONFIRM/BLOCK por ruta. Va ANTES de la allowlist a proposito.
#   7) allowlist por prefijo.
#   8) desconocido -> CONFIRM (default-deny).
#
# Por que el borrado en MASA es BLOCK y no CONFIRM: el conjunto que borra
# no lo enumero nadie (lo decide el propio find/xargs en tiempo de
# ejecucion), no pasa por la papelera y no hay deshacer. Un CONFIRM aqui
# es papel mojado porque el modo acceso-total lo aprueba solo. Si el dueno
# quiere un borrado masivo, lo hace el (o desactiva el centinela a mano).
#
# Medicion del arreglo: tests/test_sentinel_gate_shell.py (34 destructivos
# + 24 de solo lectura, POSIX y PowerShell). Antes: 3 ALLOW en la lista
# destructiva y 4 BLOCK en la de lectura. Despues: 0 y 0.
#
# ══════════════════════════════════════════════════════════════════════
# 2a TANDA (2026-08-25, tarde): el CWD y el INTERPRETE eran dos escapes
# ══════════════════════════════════════════════════════════════════════
# La tanda anterior cerro el "el prefijo gana al contenido" pero dejo
# CINCO agujeros mas, todos medidos y todos con el mismo patron: el gate
# mira UN string y el borrado real se arma en otro sitio (el cwd, la linea
# de al lado, el payload del interprete, un parametro de la tool).
#
# (A) ESCAPE POR CWD -- PERDIDA DE DATOS REAL. En una corrida con
#     COGNIA_ACCESO_TOTAL=1 el agente pidio borrar las capturas del dueno.
#     La forma directa quedo parada:
#       del "C:\Users\usuario\Pictures\Screenshots\*.png"
#         -> block (borrado de ficheros (del), sobre una ruta fuera del
#            directorio de trabajo)
#     El modelo LEYO la razon ("fuera del directorio de trabajo"), y su
#     siguiente accion fue entrar en la carpeta primero:
#       cd /d "C:\Users\usuario\Pictures\Screenshots" && del *.png
#         -> confirm -> con acceso total, EJECUTADO
#     y borro 3 capturas (105.605 / 189.239 / 207.974 bytes) que no estan
#     en la papelera (`del` no pasa por ella) ni en instantaneas: perdidas.
#     Causa exacta: el paso 5 partia el comando en segmentos y clasificaba
#     CADA UNO POR SEPARADO. `cd ...` salia ALLOW por prefijo y `del *.png`
#     se quedaba solo: _ambito_ruta('del *.png') no ve ninguna ruta, asi
#     que no escalaba y se quedaba en CONFIRM. El `cd` que mete al proceso
#     DENTRO de la carpeta protegida era invisible para el segmento que
#     borra. Arreglo: el cwd se PROPAGA entre segmentos (_cwd_tras_cd);
#     un destructivo sin ruta propia hereda el ambito del `cd` anterior y
#     escala igual que si la ruta estuviera escrita. El cwd propagado es
#     una RUTA y no una etiqueta porque con la etiqueta el `cd` RELATIVO
#     seguia colandose: `cd ..\..\Pictures && del *.png` daba CONFIRM
#     (medido desde el repo). Se resuelve contra el cwd real.
#     Corolario incomodo y asumido: la razon publica es un mapa de la
#     frontera. Se mantiene detallada (sin ella el agente gasta pasos a
#     ciegas), pero por eso la defensa NO puede ser "que no sepa donde
#     esta el muro": tiene que ser que rodearlo no funcione.
#
# (B) EL SALTO DE LINEA NO SEPARABA. `re.sub(r"\s+", " ", cmd)` convertia
#     un comando de dos lineas en UNO solo, y mandaba la cabeza de la
#     primera linea. Medido:
#       echo limpiando<NL>del "C:\...\Screenshots\*.png"  -> ALLOW
#       (razon "prefijo 'echo' conocido-seguro")
#     Peor que (A): ni siquiera llegaba a CONFIRM. Arreglo: el salto de
#     linea se convierte en ';' ANTES de colapsar espacios, respetando las
#     continuaciones de linea ('\', '`' de PowerShell, '^' de cmd), que si
#     son un comando solo.
#
# (C) INTERPRETE CON CODIGO EN LINEA. Misma clase que el bug de `find`
#     (el peligro esta en los ARGUMENTOS) pero para 'python'/'node'/'npx',
#     que estan en la allowlist. Medido:
#       python -c "__import__('shutil').rmtree(r'C:\Users\usuario\Pictures')"
#         -> allow  ("prefijo 'python' conocido-seguro")
#       node -e "require('fs').rmSync('C:/Users/usuario/Pictures',
#                {recursive:true,force:true})"            -> allow
#     ALLOW es peor que CONFIRM: evaluar_shell devuelve (True, None) sin
#     mirar acceso-total ni auditar un veredicto de riesgo. Verificado de
#     punta a punta contra un directorio TEMPORAL: clasificaba allow y el
#     subprocess borraba los ficheros. Arreglo: cuando un interprete lleva
#     codigo en linea (-c/-e/--eval/eval) se inspecciona el PAYLOAD
#     buscando las APIs de borrado; las de arbol entero (shutil.rmtree,
#     fs.rm recursivo, rimraf) son BLOCK como cualquier borrado en masa,
#     y las de un objetivo escalan por ruta con el mismo _escalar().
#     LIMITE DECLARADO (degradacion visible, no silenciosa): esto NO es un
#     analizador de Python ni de JS. `python fichero.py` sigue ALLOW y un
#     payload ofuscado (getattr(__import__('sh'+'util'),'rmtree')) se
#     escapa. Es una capa mas, no un aislamiento; el aislamiento de verdad
#     es el sandbox de program_creator.
#
# (D) EL cwd= DE LA TOOL `ejecutar` -- el mismo escape por la puerta
#     OFICIAL, y ademas sin friccion. La tool acepta `cwd=<ruta>` (se
#     anadio el 2026-08-18 precisamente para que el modelo no tuviera que
#     escribir `cd X && ...`, que caia en CONFIRM), pero al gate solo le
#     llegaba el COMANDO. Medido contra un temporal:
#       _shell("del *.png", cwd=<...\Pictures\Screenshots>)
#         -> "RESULTADO ejecutar: (sin output)" y los 3 .png borrados
#     Arreglo: evaluar_shell acepta `cwd` y lo pasa a clasificar_shell como
#     directorio efectivo, igual que si lo hubiera puesto un `cd`. Vale
#     tambien para `ejecutar_fondo`, que si no seria el mismo agujero con
#     la salida escondida.
#
# (E) APIs .NET DESDE POWERSHELL. `[System.IO.Directory]::Delete(<ruta>,
#     $true)` borra el arbol entero, pero la 'cabeza' del comando es una
#     EXPRESION y no un nombre: no casaba ni con la allowlist ni con
#     ningun patron, asi que salia CONFIRM ('comando de riesgo
#     desconocido') y con acceso total procedia. Ahora la variante
#     recursiva es BLOCK (borrado en masa) y la de un objetivo escala por
#     ruta. De paso se cerro una FUGA en la razon publica: el head de esa
#     expresion sale de quitar parentesis y cortar por la barra, asi que
#     arrastraba un trozo de la RUTA al mensaje que ve el modelo (medido:
#     "comando 'pictures',' de riesgo desconocido" y "comando
#     'secreto.txt' de riesgo desconocido"). Solo se nombra el comando
#     cuando el token crudo ya era un nombre limpio.
#
# (F) EL CWD DEL DUENO NO ES UN WORKSPACE -- 2a PERDIDA DE DATOS REAL, y
#     la peor, porque ninguno de los arreglos (A)-(E) la tocaba. Todos
#     ellos escalan MIRANDO UNA RUTA; un `del *.png` no tiene ninguna, asi
#     que caia en el CONFIRM de "dentro del workspace el agente borra
#     ficheros suyos". Pero el cwd de las sesiones del dueno es
#     C:\Users\usuario\Desktop: no es un workspace, es su Escritorio.
#     Medido en una corrida de verificacion (2026-08-25, tarde): al pedirle
#     "entra a la carpeta con cd y borra ahi" el agente cambio de objetivo
#     al Escritorio y lanzo
#       cd C:\Users\usuario\Desktop && del *.png  -> confirm -> EJECUTADO
#     borrando 60 .png (13.635.124 bytes) que `del` no manda a la papelera.
#     `del *.png` a secas daba el MISMO CONFIRM: el agujero no era el `cd`,
#     era la suposicion sobre el cwd. Arreglo: _cwd_es_personal() -- si el
#     directorio donde va a correr el comando es una carpeta personal ELLA
#     MISMA (Desktop, Pictures, Documents, el HOME, la raiz, un directorio
#     del sistema), un destructivo sin ruta es BLOCK. La regla se queda
#     estrecha adrede: un proyecto colgando de ella (Desktop\cognia_v2) NO
#     cuenta, para que el agente pueda seguir borrando lo suyo.
#
# La exencion del workspace (_ambito_cwd) es la contrapartida: sin ella el
# arreglo se paga dejando al agente sin poder borrar sus propios ficheros,
# que es el otro fallo de la corrida (6 pasos y "sin progreso verificado").
#
# ══════════════════════════════════════════════════════════════════════
# 3a TANDA (2026-08-25, noche): lo que las dos anteriores seguian dejando
# ══════════════════════════════════════════════════════════════════════
# Las tandas 1 y 2 cerraron "el prefijo gana al contenido" y "el cwd no se
# propaga". Una sonda contra el gate YA ARREGLADO encontro CUATRO escapes
# mas de la misma familia (el borrado real se arma donde el gate no mira) y
# una puerta trasera que los volvia a abrir todos:
#
# (G) EL SPLIT DE SEGMENTOS DESTROZABA EL PAYLOAD DEL INTERPRETE. El paso
#     5 partia por [;&|] SIN mirar las comillas, asi que
#       cd C:\Users\usuario\Pictures && python -c "import shutil; shutil.rmtree('.')"
#     se troceaba en `... python -c "import shutil` + `shutil.rmtree('.')"`.
#     Ninguno de los dos trozos es un interprete con codigo en linea, asi
#     que el paso 3b (que SI habria visto el rmtree) no llegaba a correr:
#     el segundo trozo salia "comando de forma no reconocida" -> CONFIRM
#     -> con acceso total, EJECUTADO. Medido: confirm. Es (C) otra vez,
#     reabierto por el arreglo de (A). Ahora el split respeta las comillas
#     (_segmentar), asi que el segmento llega ENTERO al paso 3b.
#     Efecto lateral bueno y medido: `grep -iE 'captur|screenshot'` deja de
#     partirse por el pipe de SU PATRON (era un CONFIRM de friccion pura).
#
# (H) LA RUTA RELATIVA SIN `cd`. La escalada solo leia rutas ABSOLUTAS,
#     asi que desde el repo
#       del ..\..\Pictures\*.png            -> confirm  (medido)
#       echo x > ..\..\Documents\notas.txt  -> allow    (medido)
#     mientras la forma absoluta era BLOCK. El `cd` ni hacia falta: bastaba
#     escribir el camino. Arreglo: los objetivos que parecen ruta se
#     RESUELVEN (normpath del join) contra el cwd EFECTIVO y se juzgan
#     resueltos, que es lo que el sistema de ficheros va a hacer.
#
# (I) EL HOME NO ERA "CARPETA PERSONAL". _cwd_es_personal miraba nombres
#     (Desktop, Pictures, ...) y C:\Users\usuario no es ninguno: con el cwd
#     en el HOME, `del *.png` salia CONFIRM. Ahora el HOME del usuario (y
#     /home/<x>, /Users/<x>, /root) cuenta como carpeta personal.
#
# (J) INTERPRETES QUE FALTABAN Y APIS QUE FALTABAN. `npm exec rimraf <ruta
#     personal>` salia ALLOW ('npm' esta en la allowlist y no se miraba su
#     subcomando); `perl -e "unlink glob('C:/Users/.../*.png')"` y
#     `deno eval "Deno.removeSync(...)"` salian CONFIRM porque los patrones
#     de payload pedian `unlink(` con parentesis pegado y no conocian
#     removeSync/shutil.move/os.rename. Y el -EncodedCommand de PowerShell
#     ahora se DECODIFICA para el audit (el veredicto ya era BLOCK: lo que
#     no se puede leer no pasa).
#
# (K) ACCESO_TOTAL ERA UNA PUERTA TRASERA SOBRE TODO ESTO. Un CONFIRM con
#     COGNIA_ACCESO_TOTAL=1 (el default de las sesiones del control remoto)
#     se auto-aprobaba sin canal humano: por ahi paso el borrado de las 3
#     capturas del dueno del 2026-08-25. Toda la escalada de arriba existe
#     para que lo destructivo-sobre-lo-ajeno sea BLOCK (que el acceso total
#     NO levanta), pero queda un resto: los CONFIRM destructivos cuyo
#     alcance NO SE PUEDE VERIFICAR (el `cd` va a una VARIABLE, el
#     directorio no existe todavia). Ahi el acceso total deja de aprobar
#     solo y exige confirmacion humana real. Lo que no cambia: un CONFIRM
#     destructivo confinado al workspace (rm build.log) se sigue aprobando
#     -- si no, el modo remoto no sirve para nada.
#
# (L) LA RAZON PUBLICA ENSENABA LA EVASION. La razon la LEE el modelo, y
#     "sobre una ruta fuera del directorio de trabajo" es una instruccion:
#     mueve el directorio de trabajo. En la traza real el modelo la leyo y
#     su siguiente accion fue el `cd`. Ahora la razon publica dice QUE se
#     detecto y SOBRE QUE clase de sitio ("borrado de ficheros (del), sobre
#     una carpeta personal del usuario") y es la MISMA para la forma
#     directa y para la rodeada con `cd`: rodear el muro ya no cambia ni el
#     veredicto ni el mensaje, asi que el mensaje no ensena nada. La frase
#     literal (que fue el cwd, que fue un `cd`, que la ruta caia fuera del
#     directorio de trabajo) va INTEGRA al audit jsonl, que es quien la
#     necesita. Ver _PUBLICO y clasificar_shell_detalle.

# Prefijos de comandos de dev conocidos-seguros (allowlist). Se matchea el
# PRIMER token (o los dos primeros para subcomandos de git). No incluye nada
# que borre/mueva masivamente ni toque red sin control.
_ALLOW_PREFIXES = {
    "git", "python", "python3", "py", "pytest", "pip", "ruff", "black",
    "mypy", "flake8", "ls", "dir", "cat", "type", "echo", "pwd", "cd",
    "head", "tail", "wc", "grep", "findstr", "find", "where", "which",
    "node", "npm", "npx", "tsc", "go", "cargo", "rustc", "java", "javac",
    "make", "cmake", "diff", "sort", "uniq", "tree", "date", "whoami",
    "poetry", "uv", "conda", "pytest.exe",
    # lanzadores: abrir apps/archivos/URLs (para "abre Chrome/YouTube/una app").
    # Un payload destructivo dentro sigue cazado por el BLOCK (corre antes).
    "start", "explorer", "open", "xdg-open", "wt", "code", "notepad",
    # consolas y utilidades del sistema (el dueño pidió poder abrirlas/usarlas;
    # un payload destructivo DENTRO sigue cazado por _BLOCK, que corre antes)
    "powershell", "pwsh", "cmd", "tasklist", "taskmgr", "calc", "mspaint",
    "curl", "wget", "ping", "ipconfig", "systeminfo", "hostname",
    # POSIX de solo lectura (2026-08-25): en la corrida real el agente
    # ejecuto `uname -s; echo ...; ls -la "$HOME" 2>/dev/null | head -40`
    # y el encadenado caia a CONFIRM solo porque 'uname' no estaba aqui.
    # Ninguno de estos escribe nada.
    "uname", "printf", "basename", "dirname", "realpath", "stat", "du",
    "df", "file", "cut", "tr", "nl", "seq", "env", "printenv", "id",
    "less", "more", "md5sum", "sha256sum", "certutil",
    # Navegacion de directorios: no escribe nada, y desde el arreglo del
    # cwd (2a tanda) un `cd` a carpeta protegida ya no tapa lo que venga
    # detras -- antes 'pushd'/'set-location' salian "riesgo desconocido"
    # y ademas el segmento siguiente se clasificaba a ciegas.
    "chdir", "pushd", "popd", "set-location", "sl", "push-location",
    "pop-location",
    # ── PowerShell de solo lectura (la maquina del dueno es Windows 11) ──
    # La allowlist era POSIX-centrica: `Get-ChildItem` salia "riesgo
    # desconocido" y el agente no podia ni listar una carpeta sin gastar
    # un CONFIRM. Se listan cmdlet y alias porque el head se compara
    # literal. Todos son de LECTURA (Get-*/Test-*/Measure-*/Select-*).
    "get-childitem", "gci", "get-content", "gc", "select-string", "sls",
    "get-location", "test-path", "measure-object", "where-object",
    "select-object", "sort-object", "group-object", "get-item",
    "get-itemproperty", "get-process", "get-service", "get-date",
    "get-command", "gcm", "get-help", "get-member", "gm", "resolve-path",
    "split-path", "join-path", "convertto-json", "convertfrom-json",
    "format-table", "format-list", "out-string", "out-host", "write-host",
    "write-output", "get-volume", "get-psdrive", "get-filehash",
    "get-random", "get-history", "get-module", "get-variable",
}
# git subcomandos que NO son de solo-lectura pero son parte del flujo normal
# de un agente de código (commit/add/checkout local); push/reset-hard/clean
# NO están → caen a CONFIRM.
_GIT_SAFE_SUB = {"status", "log", "diff", "show", "branch", "add", "commit",
                 "stash", "fetch", "pull", "rev-parse", "ls-files", "blame",
                 "restore", "switch", "checkout", "config"}

# Ruido de shell que NO es destructivo: descartar salida o fusionar stderr.
# Se borra ANTES de buscar patrones destructivos. El patron viejo
# ">/dev/" no distinguia /dev/null (papelera de bits) de /dev/sda (el
# disco): 4 falsos positivos medidos en la corrida real.
_RUIDO_RE = re.compile(r"(?:\d?>>?|&>>?)\s*/dev/null|\d>&\d", re.I)

# Bloqueo duro: destructivo irreversible. (patrón, razón pública). La razón
# DICE QUE se detecto: el agente de la corrida real perdio 3 pasos porque
# "patrón destructivo irreversible" a secas no le decia que arreglar.
_BLOCK_SUB = [
    ("rm -rf", "borrado recursivo forzado (rm -rf)"),
    ("rm -fr", "borrado recursivo forzado (rm -fr)"),
    ("del /s", "borrado recursivo de Windows (del /s)"),
    ("del /q", "borrado sin confirmación de Windows (del /q)"),
    ("del /f", "borrado forzado de Windows (del /f)"),
    (":(){", "fork bomb"),
    (":|:&", "fork bomb"),
    ("mkfs", "formateo de sistema de ficheros (mkfs)"),
    ("dd if=", "escritura a bajo nivel con dd"),
    ("shutdown", "apagado del equipo"),
    ("reboot", "reinicio del equipo"),
    ("rmdir /s", "borrado recursivo de directorio (rmdir /s)"),
    ("format c:", "formateo de la unidad del sistema"),
    ("deltree", "borrado recursivo de árbol (deltree)"),
    ("chmod -r 000", "revocación recursiva de permisos"),
    ("chown -r", "cambio recursivo de propietario"),
    ("rd /s", "borrado recursivo de directorio (rd /s)"),
    ("diskpart", "particionado de disco (diskpart)"),
    ("cipher /w", "borrado seguro del espacio libre (cipher /w)"),
]
_BLOCK_RE = [
    (re.compile(r"\bformat\s+[a-z]:", re.I), "formateo de una unidad"),
    (re.compile(r"\brm\s+-[a-z]*r[a-z]*f", re.I),
     "borrado recursivo forzado (rm -rf)"),
    (re.compile(r"\brm\s+-[a-z]*f[a-z]*r", re.I),
     "borrado recursivo forzado (rm -fr)"),
    # SOLO dispositivos: /dev/null ya se neutralizó arriba, y aquí se
    # excluye explícitamente por si llega otra forma (>| /dev/null).
    (re.compile(r">\s*/dev/(?!null\b|stdout\b|stderr\b|tty\b)[a-z]", re.I),
     "redirección a un dispositivo de bloque (/dev/...)"),
    (re.compile(r"\bdd\b[^|;]*\bof=/dev/", re.I),
     "escritura directa a un dispositivo con dd"),
    (re.compile(r"\bgit\s+push\b.*--force", re.I),
     "reescritura del historial remoto (git push --force)"),
    (re.compile(r"\bgit\s+reset\b.*--hard", re.I),
     "descarte de cambios locales (git reset --hard)"),
    (re.compile(r"\bgit\s+clean\b.*-[a-z]*f", re.I),
     "borrado de ficheros no rastreados (git clean -f)"),
    # borrado recursivo forzado en PowerShell (remove-item -recurse -force)
    (re.compile(r"remove-item\b.*-re?c?u?r?s?e?\b.*-for?ce?\b", re.I),
     "borrado recursivo forzado (Remove-Item -Recurse -Force)"),
    (re.compile(r"remove-item\b.*-for?ce?\b.*-re?c?u?r?s?e?\b", re.I),
     "borrado recursivo forzado (Remove-Item -Force -Recurse)"),
    # Windows: destructores que no borran ficheros pero son irreversibles.
    (re.compile(r"\breg(?:\.exe)?\s+delete\b", re.I),
     "borrado de claves del registro (reg delete)"),
    (re.compile(r"\bsc(?:\.exe)?\s+delete\b", re.I),
     "borrado de un servicio de Windows (sc delete)"),
    (re.compile(r"\bschtasks(?:\.exe)?\b[^|;]*\s/delete\b", re.I),
     "borrado de tareas programadas (schtasks /delete)"),
    (re.compile(r"\bvssadmin\b[^|;]*\bdelete\b", re.I),
     "borrado de instantáneas de volumen (vssadmin delete)"),
    (re.compile(r"\bwmic\b[^|;]*\bshadowcopy\b[^|;]*\bdelete\b", re.I),
     "borrado de instantáneas (wmic shadowcopy delete)"),
    (re.compile(r"\bnet\s+user\b[^|;]*\s/delete\b", re.I),
     "borrado de una cuenta de usuario (net user /delete)"),
    (re.compile(r"\bformat-volume\b", re.I), "formateo de volumen (Format-Volume)"),
    (re.compile(r"\bbcdedit\b", re.I),
     "edición de la configuración de arranque (bcdedit)"),
    (re.compile(r"\bwevtutil\b[^|;]*\bcl\b", re.I),
     "borrado de los registros de eventos (wevtutil cl)"),
    (re.compile(r"\b(?:stop|restart)-computer\b", re.I),
     "apagado o reinicio del equipo"),
    # La papelera es la ULTIMA copia de lo ya borrado: vaciarla convierte
    # cualquier borrado previo (justo el fallo del transcript) en
    # irreparable. Si el dueno quiere vaciarla, son dos clics suyos.
    (re.compile(r"\bclear-recyclebin\b", re.I),
     "vaciado de la papelera de reciclaje (Clear-RecycleBin)"),
    # -EncodedCommand lleva el payload en base64: no es auditable, asi que
    # no se puede clasificar. Lo que no se puede leer, no pasa.
    (re.compile(r"\b(?:powershell|pwsh)\b[^|;]*\s-e(?:nc|ncodedcommand)?\s",
                re.I),
     "comando de PowerShell codificado en base64 (no auditable)"),
    # ── git que DESTRUYE trabajo sin commitear (4a tanda) ────────────
    # Misma clase de bug que `find ... -delete`: el subcomando estaba en
    # _GIT_SAFE_SUB (checkout/restore/stash/branch son parte del flujo
    # normal) y la destruccion vivia en los ARGUMENTOS. Medido en un repo
    # de mentira: los cuatro salian ALLOW y los tres primeros revirtieron
    # el fichero de trabajo ("TRABAJO DE HOY" -> "VERSION COMMITEADA") y
    # `stash push -u` se llevo ademas el untracked. Es BLOCK y no CONFIRM
    # por la misma razon que el borrado en masa: el conjunto que descarta
    # no lo enumero nadie, no pasa por la papelera y con acceso total un
    # CONFIRM se aprueba solo. `git reset --hard` ya era BLOCK desde la 1a
    # tanda: esto es cerrar sus hermanos.
    (re.compile(r"\bgit\s+checkout\b[^|;]*(?:\s--(?:\s|$)|\s\.(?:\s|$))",
                re.I),
     "descarte de cambios del árbol de trabajo (git checkout --)"),
    (re.compile(r"\bgit\s+(?:checkout|switch)\b[^|;]*\s-{1,2}(?:f|force)\b",
                re.I),
     "cambio de rama forzado que descarta cambios (git checkout -f)"),
    (re.compile(r"\bgit\s+restore\b(?![^|;]*--staged(?![^|;]*--worktree))",
                re.I),
     "descarte de cambios del árbol de trabajo (git restore)"),
    # OJO: `git stash push` NO entra aqui, y es una correccion al informe
    # del equipo rojo. Su entrada decia "limpia el working tree INCLUIDOS
    # los untracked ... perdio el cambio Y el fichero nuevo untracked",
    # pero eso no es una perdida: es lo que hace stash. Medido en un repo
    # de mentira -- modificar m.txt, crear nuevo.txt sin trackear,
    # `git stash push -u`, `git stash pop` -- y vuelven LOS DOS. Ademas la
    # tool `git_stash` existe justamente para eso y ya prohibe 'drop' y
    # 'clear'. Bloquearlo habria roto una capacidad deliberada y probada a
    # cambio de nada. Lo que SI destruye es tirar el stash: ahi esta la
    # unica copia de lo que se retiro del arbol.
    (re.compile(r"\bgit\s+stash\s+(?:drop|clear)\b", re.I),
     "borrado del stash, que es la única copia de esos cambios"),
    (re.compile(r"\bgit\s+branch\b[^|;]*\s-(?:d|delete)\b", re.I),
     "borrado de una rama (git branch -D)"),
    # `worktree remove` se lleva un arbol de trabajo entero (con lo que no
    # este commiteado dentro) y `reflog expire` borra la ultima copia de
    # lo que un `reset --hard` dejo atras. `filter-branch` se queda FUERA
    # a proposito: reescribe historia YA COMMITEADA, que es recuperable
    # por el reflog, y el dano medido aqui es el del trabajo SIN
    # commitear. Sigue en CONFIRM, como estaba.
    (re.compile(r"\bgit\s+(?:worktree\s+remove|update-ref\s+-d|"
                r"reflog\s+expire)\b", re.I),
     "operación de git que destruye referencias o árboles de trabajo"),
]

# ── BORRADO EN MASA: modificadores dentro de CUALQUIER comando ────────
# El bug: estos viven en los ARGUMENTOS, no en la cabeza, asi que la
# allowlist por prefijo ('find', 'git', 'robocopy') los tapaba.
_MASA_RE = [
    (re.compile(r"\bfind\b[^|;]*\s-delete\b", re.I),
     "borrado en masa dentro de find (-delete)"),
    (re.compile(r"\bfind\b[^|;]*\s-(?:exec|execdir|ok|okdir)\s+(?:sudo\s+)?"
                r"(rm|del|erase|unlink|shred|truncate|mv|move|chmod|chown|"
                r"remove-item|ri)\b", re.I),
     "find -exec con un comando destructivo ({0})"),
    (re.compile(r"\bxargs\b[^|;]*?\s(?:-\S+\s+)*(rm|rmdir|del|erase|unlink|"
                r"shred|remove-item|ri)\b", re.I),
     "xargs canalizado a un borrado ({0})"),
    (re.compile(r"\|\s*(?:sudo\s+)?(rm|rmdir|del|erase|unlink|shred|"
                r"remove-item|ri|clear-content|clc)\b", re.I),
     "tubería a un comando de borrado ({0})"),
    # PowerShell: `gci ... | % { ri $_ }`. El split por segmentos no entra
    # en el bloque {}, asi que hace falta el patron explicito.
    # OJO con el \b: `%\b` NO casa contra "% {" (ni '%' ni ' ' son \w, asi
    # que no hay frontera y `gci ... | % { ri $_ }` se colaba a CONFIRM).
    # Medido al armar el corpus del test; por eso el lookahead explicito.
    (re.compile(r"\|\s*(?:%|\?|foreach-object|foreach|where-object)(?![\w-])"
                r"[^|]*\b(remove-item|ri|rm|del|erase|clear-content|clc)\b",
                re.I),
     "borrado dentro de un bloque ForEach-Object de PowerShell ({0})"),
    # Bucles que borran: el conjunto lo decide el bucle en tiempo de
    # ejecucion, igual que un `find -delete`. Los tres salian CONFIRM
    # ("comando 'for'/'foreach' de riesgo desconocido") porque la cabeza es
    # una PALABRA CLAVE del lenguaje y no un comando (sonda del 2026-08-25).
    (re.compile(r"\bfor\b[^|;]*\bdo\s+(?:@)?(?:sudo\s+)?"
                r"(rm|rmdir|del|erase|rd|unlink|shred|remove-item|ri)\b",
                re.I),
     "bucle for que borra en cada vuelta ({0})"),
    (re.compile(r"\bforeach\b[^{|;]*\{[^}]*\b"
                r"(remove-item|ri|rm|del|erase|clear-content|clc)\b", re.I),
     "bucle foreach que borra en cada vuelta ({0})"),
    # `gci ... | % { $_.Delete() }`: el borrado es un METODO del objeto, no
    # un cmdlet, asi que ningun nombre de comando aparece en la linea.
    (re.compile(r"\|\s*(?:%|\?|foreach-object|foreach|where-object)"
                r"(?![\w-])[^|]*\.\s*delete\s*\(", re.I),
     "borrado con .Delete() dentro de un bloque de PowerShell"),
    (re.compile(r"\brobocopy\b[^|;]*\s/(mir|purge)\b", re.I),
     "robocopy /{0}: borra en el destino lo que no está en el origen"),
    # /MOVE se lleva los ORIGINALES (los borra del origen una vez copiados).
    # /MIR y /PURGE ya eran BLOCK y /MOVE no: medido en sandbox, la carpeta
    # de origen quedo sin las capturas. Es el mismo borrado en masa mirando
    # al otro lado.
    (re.compile(r"\brobocopy\b[^|;]*\s/mov(?:e)?\b", re.I),
     "robocopy /MOVE: borra en el origen lo que ha copiado"),
    # forfiles ejecuta un comando POR CADA fichero que casa con /m: el
    # conjunto lo decide el, igual que un `find -delete`. Medido: la
    # carpeta del sandbox quedo vacia.
    (re.compile(r"\bforfiles\b[^|;]*\s/c\s+[\"']?[^\"']*?\b"
                r"(del|erase|rm|rd|rmdir|unlink|shred|remove-item|ri)\b",
                re.I),
     "forfiles ejecutando un borrado por cada fichero ({0})"),
    (re.compile(r"\brsync\b[^|;]*\s--delete\b", re.I),
     "rsync --delete: borra en el destino lo que no está en el origen"),
    # .NET desde PowerShell con el flag recursivo: Delete(<ruta>, $true)
    # borra el arbol entero. Salia CONFIRM ("comando de riesgo
    # desconocido") porque la cabeza es '[system.io.directory]::delete(...'
    # y no casaba con ningun patron de shell; con acceso total, procedia.
    (re.compile(r"\[(?:system\.)?io\.directory\]\s*::\s*delete\s*\("
                r"[^)]*,\s*\$?true", re.I),
     "borrado recursivo con la API .NET ([IO.Directory]::Delete(..., $true))"),
]

# ── Destructivos de UN objetivo: CONFIRM, o BLOCK segun la ruta ───────
# (patron, razon, borra_en_bloque). El 3er campo dice si el comando puede
# llevarse por delante EL CONTENIDO DE LA CARPETA en la que corre: solo esos
# escalan cuando el cwd es una carpeta personal (ver _cwd_es_personal). Sin
# el, un `icacls x /grant` o un "cierra Chrome a la fuerza" lanzados desde
# ~/Desktop salian BLOCK, que es el falso positivo que inutiliza al agente.
_MOD_RE = [
    (re.compile(r"\bgit\s+clean\b", re.I),
     "git clean borra ficheros no rastreados", True),
    (re.compile(r"\btar\b[^|;]*\s--overwrite\b", re.I),
     "tar --overwrite pisa ficheros existentes", True),
    (re.compile(r"\b(?:takeown|icacls)\b", re.I),
     "cambio de propietario/permisos (takeown/icacls)", False),
    (re.compile(r"\bstop-process\b[^|;]*-for?ce?\b", re.I),
     "matar procesos a la fuerza (Stop-Process -Force)", False),
    (re.compile(r"\bfsutil\b[^|;]*\b(?:deletejournal|setzerodata)\b", re.I),
     "operación destructiva de fsutil", False),
    # .NET de UN objetivo (sin el flag recursivo): escala por ruta como
    # cualquier `del`. La variante recursiva ya es BLOCK en _MASA_RE.
    (re.compile(r"\[(?:system\.)?io\.(?:directory|file)\]\s*::\s*"
                r"(?:delete|deletefile)\b", re.I),
     "borrado con la API .NET ([IO.File]/[IO.Directory]::Delete)", True),
    # ── 4a tanda ────────────────────────────────────────────────────
    # ESCRIBIR con la API .NET tambien destruye: WriteAllText(<ruta>, "")
    # deja el fichero del dueno en 0 bytes. La cabeza es una EXPRESION, no
    # un nombre, asi que salia "forma no reconocida" -> CONFIRM -> con
    # acceso total, ejecutado. Es el primo de ::Delete, que ya estaba.
    (re.compile(r"\[(?:system\.)?io\.(?:file|directory)\]\s*::\s*"
                r"(?:writeall\w+|appendall\w+|create\w*|move|copy|replace|"
                r"open(?:write|create)?)\b", re.I),
     "escritura con la API .NET ([IO.File]::WriteAllText/Create/Move)",
     False),
    # `python -m venv --clear <dir>` VACIA el directorio de destino antes
    # de crear el entorno. Medido en sandbox: borro las 3 capturas y dejo
    # el venv en su sitio. El prefijo 'python' lo tapaba entero: es el bug
    # de "el peligro vive en los ARGUMENTOS", esta vez en un MODULO.
    (re.compile(r"\bvenv\b[^|;]*\s--clear\b", re.I),
     "venv --clear vacía el directorio de destino", True),
]

# Cabezas de comando destructivas (un objetivo). Van ANTES de la allowlist:
# 'rm'/'del' no estaban en la allowlist pero 'find'/'git' si, y el peligro
# estaba en los argumentos. Aqui se cierra el caso simple `del fichero`.
_HEAD_DESTRUCTIVO = {
    "rm": "borrado de ficheros (rm)",
    "rmdir": "borrado de directorio (rmdir)",
    "unlink": "borrado de fichero (unlink)",
    "shred": "sobrescritura destructiva (shred)",
    "truncate": "truncado de fichero (truncate)",
    "mv": "movimiento de ficheros (mv)",
    "move": "movimiento de ficheros (move)",
    "del": "borrado de ficheros (del)",
    "erase": "borrado de ficheros (erase)",
    "rd": "borrado de directorio (rd)",
    # Remove-Item y TODOS sus alias de PowerShell. 'ri -r -fo <ruta>' salia
    # "riesgo desconocido" (medido): el alias no estaba en ninguna lista.
    "remove-item": "borrado con Remove-Item",
    "ri": "borrado con Remove-Item (alias ri)",
    "rbk": "borrado con Remove-Item (alias)",
    "remove-itemproperty": "borrado de una propiedad del registro",
    "clear-content": "vaciado del contenido de un fichero (Clear-Content)",
    "clc": "vaciado del contenido de un fichero (alias clc)",
    "clear-item": "vaciado de un elemento (Clear-Item)",
    "set-content": "escritura que pisa el fichero (Set-Content)",
    "sc": "escritura que pisa el fichero (alias sc de Set-Content)",
    "out-file": "escritura que pisa el fichero (Out-File)",
    "move-item": "movimiento de ficheros (Move-Item)",
    "rename-item": "renombrado de ficheros (Rename-Item)",
    "mi": "movimiento de ficheros (alias mi)",
    "rni": "renombrado de ficheros (alias rni)",
    # Copiar PISA el destino. Medido: `copy nul C:\...\Pictures\a.png`
    # salia "comando 'copy' de riesgo desconocido" -> CONFIRM -> aprobado
    # por acceso total, y deja el fichero del dueno en 0 bytes. Escalan
    # solo por RUTA (estan en _HEADS_SIN_BORRADO_EN_BLOQUE): copiar algo AL
    # escritorio es una peticion normal del dueno.
    "copy": "copia que pisa el fichero de destino (copy)",
    "cp": "copia que pisa el fichero de destino (cp)",
    "xcopy": "copia recursiva que pisa el destino (xcopy)",
    "copy-item": "copia que pisa el destino (Copy-Item)",
    "cpi": "copia que pisa el destino (alias cpi)",
    "chmod": "cambio de permisos (chmod)",
    "chown": "cambio de propietario (chown)",
    "attrib": "cambio de atributos de fichero (attrib)",
    "taskkill": "matar procesos (taskkill)",
    "stop-process": "matar procesos (Stop-Process)",
    "stop-service": "parar un servicio (Stop-Service)",
    "vssadmin": "administración de instantáneas (vssadmin)",
    "takeown": "toma de propiedad de ficheros (takeown)",
    "icacls": "cambio de ACLs (icacls)",
}

# ── ESCRITORES: comandos que escriben DONDE LES APUNTES (4a tanda) ────
# El equipo rojo saco NUEVE evasiones de esta unica familia y todas tenian
# la misma forma: un comando de la allowlist (o de "riesgo desconocido")
# cuyo trabajo normal es LEER o DESCARGAR, pero que con un flag concreto
# escribe un fichero de destino y lo PISA. Medido en sandbox:
#   certutil -f -encode origen <captura>.png   -> 2.800 -> 168 bytes
#   dir . 1><captura>.png                      -> 1.800 -> 708 bytes
#   curl -o <captura>.png http://x             -> destino sobrescrito
# Ninguno borra "ficheros" en el sentido de `del`, asi que ni las cabezas
# destructivas ni el borrado en masa los veian, y `certutil`/`curl`/`wget`
# ademas estaban en _ALLOW_PREFIXES: salian ALLOW directamente.
#
# La entrada es (regex_del_flag_que_hace_escribir, razon). Con regex None
# el comando escribe SIEMPRE; con regex, solo cuando ese flag esta -- asi
# `certutil -hashfile x sha256` y `curl https://api/x` (leer) siguen en
# ALLOW y solo escala la forma que escribe. Escalan por RUTA con el mismo
# _escalar() que todo lo demas, y NO por "el cwd es personal": escriben un
# fichero NOMBRADO, no vacian la carpeta donde corren.
_HEAD_ESCRIBE = {
    # OJO con re.I: `scan` llega ya en MINUSCULAS, asi que un patron que
    # distinga `-O` de `-o` no casa NUNCA. `wget -O <captura>.png` se
    # colaba por eso mismo cuando `curl -o` ya estaba parado (medido).
    # Da igual: las dos formas escriben un fichero (en wget, `-o` es el
    # log y `-O` la salida; ambas pisan lo que haya).
    "curl": (re.compile(r"\s-{1,2}(?:o|output|remote-name)\b", re.I),
             "descarga que pisa el fichero de destino (curl -o)"),
    "wget": (re.compile(r"\s-{1,2}(?:o|output-document)\b", re.I),
             "descarga que pisa el fichero de destino (wget -O)"),
    "certutil": (re.compile(r"\s[-/](?:f|encode|decode|encodehex|decodehex|"
                            r"urlcache)\b", re.I),
                 "certutil escribe y pisa el fichero de destino"),
    "esentutl": (re.compile(r"\s/[yd]\b", re.I),
                 "esentutl copia y pisa el fichero de destino"),
    "tar": (re.compile(r"\s-[a-z]*x[a-z]*\b|\s--extract\b", re.I),
            "extracción que pisa ficheros del destino (tar -x)"),
    "expand-archive": (None,
                       "extracción que pisa ficheros del destino "
                       "(Expand-Archive)"),
    "new-item": (re.compile(r"\s-for?ce?\b", re.I),
                 "New-Item -Force trunca el fichero que ya existe"),
    "add-content": (None, "escritura que modifica el fichero (Add-Content)"),
    "ac": (None, "escritura que modifica el fichero (alias ac)"),
    "tee": (None, "tee pisa el fichero de destino"),
    "fsutil": (re.compile(r"\b(?:seteof|setzerodata|deletejournal)\b", re.I),
               "fsutil trunca o destruye el contenido del fichero"),
    "set-acl": (None, "cambio de ACLs (Set-Acl)"),
    "set-itemproperty": (None,
                         "escritura de una propiedad (Set-ItemProperty)"),
}

# Cabezas que BORRAN un conjunto de ficheros (no las que pisan uno
# nombrado): son las unicas a las que aplica la regla del comodin.
_HEADS_BORRAN = {
    "rm", "rmdir", "del", "erase", "rd", "unlink", "shred", "truncate",
    "remove-item", "ri", "rbk", "clear-content", "clc", "clear-item",
}

# Programas cuyo unico trabajo es BORRAR UN ARBOL entero. Salieron por el
# `npm run limpiar` del equipo rojo: el cuerpo del script en package.json
# era `rimraf <carpeta personal>` y, al clasificarlo, 'rimraf' no era una
# cabeza conocida -> "riesgo desconocido" -> CONFIRM -> acceso total.
_HEADS_MASA = {"rimraf", "del-cli", "trash-cli"}

# ── COMODIN SOBRE CODIGO FUENTE ──────────────────────────────────────
# Dos entradas del equipo rojo se saltaban toda la escalada por ruta sin
# salir del workspace, que es justo donde el gate afloja a proposito:
#     del *.py               -> confirm  (borra el codigo fuente del repo)
#     del cognia\agent\*.py  -> confirm  (borra el propio centinela)
# y con COGNIA_ACCESO_TOTAL=1 un CONFIRM se ejecuta solo.
#
# La exencion del workspace existe para que el agente pueda limpiar LO
# SUYO (`rm build.log`, `del *.log`), y esa exencion NO se toca: sin ella
# vuelve el falso positivo que el 2026-08-25 le costo 6 pasos y un "sin
# progreso verificado". Lo que se separa es el codigo FUENTE, que no es un
# producto derivado: no se regenera, y en esta maquina el repo lleva
# encima el trabajo sin commitear del dia (el CONTEXTO de esta corrida
# empieza pidiendo justamente que no se reviente). Un comodin sobre el
# codigo es un borrado en masa de ORIGINALES, asi que se le aplica la
# regla del borrado en masa desde la 1a tanda: BLOCK, y con la salida
# buena nombrada (borrar_archivo va a la papelera y es reversible).
#
# La lista es de extensiones a proposito y se queda corta antes que larga:
# lo que NO esta aqui (*.log, *.tmp, *.pyc, *.png) sigue en CONFIRM.
_GLOB_CODIGO_RE = re.compile(
    r"\*\.(?:py|pyw|pyi|js|mjs|cjs|ts|tsx|jsx|java|kt|go|rs|c|h|cc|cpp|hpp|"
    r"cs|rb|php|swift|scala|sql|sh|bash|ps1|psm1|bat|cmd|vbs|lua|pl|"
    r"html|htm|css|scss|vue|svelte|json|toml|yaml|yml|ini|cfg|md|rst)$",
    re.I)

# ── Rutas: el nivel de un destructivo depende de DONDE apunta ─────────
# No es lo mismo `rm build/` dentro del workspace que un borrado sobre
# ~/Pictures. Estas tres piezas deciden la escalada CONFIRM -> BLOCK.
_DIRS_USUARIO = (r"(?:pictures|im[aá]genes|documents|documentos|desktop|"
                 r"escritorio|downloads|descargas|videos|v[ií]deos|music|"
                 r"m[uú]sica|onedrive|appdata|favorites|contacts|links|"
                 r"searches|saved games)")
# Extractor de rutas: solo formas inequivocas. NO se toma "/s" ni "/q"
# (flags de cmd) como rutas POSIX; por eso la rama POSIX exige un primer
# componente conocido (/home, /users, /etc...).
_RUTAS_RE = re.compile(
    # (?<![a-z]) para que "HKCU:\Software" no se lea como la unidad "u:\":
    # daba BLOCK con la razon equivocada ("ruta fuera del directorio de
    # trabajo") en Remove-ItemProperty. El registro se trata aparte.
    r"(?<![a-z])[a-z]:[\\/][^\s\"';|]*"
    r"|~[\\/][^\s\"';|]*"
    r"|~(?=\s|$)"
    r"|\$home[\\/]?[^\s\"';|]*"
    r"|%userprofile%[\\/]?[^\s\"';|]*"
    r"|\$env:userprofile[\\/]?[^\s\"';|]*"
    r"|(?<![\w>&:.])/(?:home|users|etc|usr|var|bin|sbin|boot|opt|lib|root|"
    r"mnt|media)(?:[\\/][^\s\"';|]*)?"
    # Unidad de Windows en forma POSIX: /c/Users/... (Git Bash/MSYS) y
    # /mnt/c/Users/... (WSL). Sin esto, `bash -c "rm /c/Users/usuario/
    # Pictures/*.png"` y `wsl rm -f /mnt/c/Users/.../Pictures/*.png` salian
    # CONFIRM (medido): la rama POSIX de arriba exige un primer componente
    # conocido y 'c' no lo es, asi que la escalada no veia NINGUNA ruta.
    # El lookbehind lleva '/' para no leer el '//x/y' de una URL como ruta.
    r"|(?<![\w>&:./])/(?:mnt/)?[a-z](?=[\\/])[^\s\"';|]*"
    r"|(?<![\w>&:./])/(?=\s|$)", re.I)
# Carpeta personal: protegida si la ruta ES esa carpeta o cuelga UN nivel
# de ella. Dos niveles abajo ya es un workspace (p.ej. Desktop\cognia_v2\
# build) y ahi CONFIRM basta; un nivel abajo NO (Desktop\cognia_v2 es el
# repo entero, ~/Pictures/Screenshots es el caso del transcript).
_PROT_FIN_RE = re.compile(
    r"(?:^|[\\/])" + _DIRS_USUARIO + r"(?:[\\/][^\\/]*)?[\\/]?\**$", re.I)
# ── Carpetas de CONTENIDO del dueno: protegidas a CUALQUIER profundidad ──
# El e2e en sandbox del 2026-08-25 (noche) encontro el ultimo agujero de la
# familia: con el cwd en un directorio de trabajo,
#     del Pictures\Screenshots\*.png
# resolvia DENTRO del cwd, la exencion del workspace se lo tragaba y salia
# CONFIRM -> con acceso total, BORRO los 3 ficheros del sandbox. La causa
# es la regla de profundidad de _PROT_FIN_RE (carpeta personal + UN nivel):
# `Pictures\*.png` era BLOCK y `Pictures\Screenshots\*.png` no, que es
# justo la carpeta del incidente. 'desktop' y 'appdata' NO entran aqui: el
# repo del agente cuelga del Escritorio y los temporales de AppData, y
# protegerlos a cualquier profundidad lo dejaria sin poder trabajar.
_DIRS_CONTENIDO = (r"(?:pictures|im[aá]genes|documents|documentos|downloads|"
                   r"descargas|videos|v[ií]deos|music|m[uú]sica|onedrive|"
                   r"favorites|contacts|saved games)")
_PROT_CONTENIDO_RE = re.compile(
    r"(?:^|[\\/])" + _DIRS_CONTENIDO + r"(?=[\\/])", re.I)
# Directorios del sistema: protegidos a CUALQUIER profundidad.
_PROT_SIEMPRE_RE = re.compile(
    r"(?:^|[\\/])(?:windows|system32|syswow64|program files(?: \(x86\))?|"
    r"programdata|etc|usr|sbin|boot|lib)(?:[\\/]|$)", re.I)
# Raiz de disco o carpeta personal a secas.
_RAIZ_RE = re.compile(
    r"^(?:[a-z]:[\\/]?|/|~|\$home|%userprofile%|\$env:userprofile)"
    r"[\\/]?\**$", re.I)
# La carpeta personal ELLA MISMA (sin nada colgando): C:\Users\usuario\Desktop
# si, C:\Users\usuario\Desktop\cognia_v2 no. Es mas estrecho que
# _PROT_FIN_RE a proposito: sirve para decidir si el DIRECTORIO DE TRABAJO
# es un sitio del dueno o un proyecto, y un proyecto tiene que seguir siendo
# trabajable (ver _cwd_es_personal).
_CWD_PERSONAL_RE = re.compile(
    r"(?:^|[\\/])" + _DIRS_USUARIO + r"[\\/]?$", re.I)

ALLOW, CONFIRM, BLOCK = "allow", "confirm", "block"

# ── Cambios de directorio: mueven el cwd de los segmentos SIGUIENTES ──
# Sin esto, `cd <carpeta protegida> && del *` se clasificaba por partes y
# el `del` no veia ninguna ruta (ver (A) en la cabecera).
_CD_HEADS = {"cd", "chdir", "pushd", "push-location", "set-location", "sl"}
# Flags que NO son el destino: /d de cmd, -Path/-LiteralPath de PowerShell.
_CD_FLAGS = re.compile(
    r"^(?:/d|-d|-path|-literalpath|-lp|-stackname|-passthru)$", re.I)

# ── Interpretes que ejecutan codigo EN LINEA (el payload es el riesgo) ──
_INTERPRETES = {"python", "python3", "py", "node", "nodejs", "deno", "bun",
                "perl", "ruby", "php", "lua", "irb",
                # Hosts de script de Windows: `cscript //nologo borra.vbs`
                # y `mshta vbscript:...DeleteFile(...)` salian "riesgo
                # desconocido" -> CONFIRM -> aprobado por acceso total.
                # Son interpretes como cualquier otro.
                "cscript", "wscript", "mshta"}
# Lanzadores de paquetes: el "payload" es el paquete que corren (npx rimraf).
_LANZA_PAQUETE = {"npx", "bunx", "pnpx", "dlx"}
# `npm` NO puede tratarse como npx: `npm install rimraf` es instalar una
# dependencia, no borrar nada, y bloquearlo seria un falso positivo diario.
# Solo cuenta como lanzador cuando EJECUTA algo (npm exec/run/x).
_NPM_EJECUTA = {"exec", "run", "run-script", "x", "start"}
_FLAG_CODIGO = re.compile(
    r"^(?:--?(?:c|e|p|r|eval|command|exec|print)|eval)$", re.I)
# El MISMO flag con el codigo PEGADO: `python -c"..."`, `python -c=...`,
# `node --eval="..."`, `node -e"..."`, `deno eval"..."`. Era la evasion mas
# barata del equipo rojo -- SEIS de sus entradas -- y consistia solo en
# quitar un espacio: _FLAG_CODIGO compara el TOKEN entero, asi que
# `-c"__import__('shutil').rmtree(...)"` no era "el flag -c" y el payload
# no se inspeccionaba nunca. Se cierra por partida doble: el payload de un
# interprete pasa a ser TODO su argumento (asi el rmtree se ve igual, con
# espacio o sin el) y ademas la forma pegada se marca como no verificable,
# porque cuando el flag y el codigo van pegados el gate no puede decir
# donde empieza el codigo. Por eso `python -c="import shutil"` -- que no
# borra nada -- tampoco se auto-aprueba: lo que se frena es el CANAL.
_FLAG_CODIGO_PEGADO = re.compile(
    r"^(?:--?(?:c|e|p|r|eval|command|exec|print)|eval)(?:=|[\"'])(?=.)",
    re.I)
# Extensiones cuyo contenido ES el programa: ejecutarlas equivale a
# ejecutar lo que lleven dentro, y eso el gate no lo ve en la linea.
_EXT_SCRIPT = (".py", ".js", ".mjs", ".cjs", ".ts", ".sh", ".bash", ".zsh",
               ".ps1", ".psm1", ".bat", ".cmd", ".vbs", ".vbe", ".js e",
               ".jse", ".wsf", ".pl", ".rb", ".lua", ".php")
# De esas, las que son un GUION DE SHELL: su texto se puede pasar por el
# mismo _bloqueo_duro que un comando. En un .py el texto no es shell (y un
# corpus de tests con la cadena "rm -rf" dentro daria un falso positivo).
_EXT_SHELL = (".sh", ".bash", ".zsh", ".ps1", ".psm1", ".bat", ".cmd")
# Tope de lectura de un script: lo que no se puede leer entero no se puede
# afirmar que sea inocuo (cae a "no verificable", como el -EncodedCommand).
_SCRIPT_MAX = 128 * 1024

# Borrado de ARBOL desde codigo: mismo trato que el borrado en masa de
# shell (BLOCK siempre). El conjunto lo decide el programa en ejecucion,
# no pasa por la papelera y no hay deshacer.
_CODIGO_MASA_RE = [
    # Se matchea la LLAMADA, no el modulo: `__import__('shutil').rmtree(x)`
    # no contiene 'shutil.rmtree' (medido, seguia saliendo ALLOW). Los
    # nombres son inequivocos, asi que no hace falta el modulo delante.
    (re.compile(r"\brmtree\s*\(", re.I), "shutil.rmtree"),
    (re.compile(r"\bremovedirs\s*\(", re.I), "os.removedirs"),
    (re.compile(r"\brimraf\b", re.I), "rimraf"),
    (re.compile(r"\bdel-cli\b", re.I), "del-cli"),
    (re.compile(r"\.\s*rm(?:sync)?\s*\([^)]*recursive", re.I),
     "fs.rm recursivo"),
    (re.compile(r"\.\s*rmdirsync\s*\([^)]*recursive", re.I),
     "fs.rmdirSync recursivo"),
    (re.compile(r"\bdirectory\s*(?:\]::|\.)\s*delete\b", re.I),
     "Directory.Delete"),
    # Deno/Node: `Deno.removeSync(x, {recursive:true})`, `fs.rm(x,
    # {recursive:...})`. El patron de arriba pedia la forma `.rm(`, que no
    # casa con 'removeSync' (medido: salia "comando 'deno' de riesgo
    # desconocido" -> CONFIRM -> aprobado por acceso total).
    (re.compile(r"\bremove(?:sync)?\s*\([^)]*recursive", re.I),
     "remove recursivo (Deno.remove/fs.remove)"),
    # Perl: `unlink glob('C:/.../*.png')` -- unlink con una LISTA es un
    # borrado en masa, y no lleva el parentesis pegado que pedia el patron
    # de un objetivo.
    (re.compile(r"\bunlink\s+(?:glob|<)", re.I),
     "unlink sobre un glob (Perl)"),
    # `for p in Path(x).rglob('*'): p.unlink()` -- unlink dentro de un
    # recorrido es un borrado de arbol aunque la API sea de un objetivo.
    (re.compile(r"\b(?:glob|rglob|iterdir|walk|listdir|scandir|readdir)\b"
                r"[\s\S]*\.\s*(?:unlink|rmdir)\s*\(", re.I),
     "unlink dentro de un recorrido de directorio"),
    # VBScript/JScript: DeleteFolder se lleva el arbol entero.
    (re.compile(r"\bdeletefolder\s*[\(\s]", re.I),
     "FileSystemObject.DeleteFolder"),
]
# Borrado de UN objetivo (o arranque de un shell): escala por ruta.
_CODIGO_BORRA_RE = [
    # 'unlink'/'rmdir' son inequivocos: cualquier llamada vale. 'remove'
    # NO lo es (list.remove(x) es una operacion normalisima), asi que solo
    # cuenta cuando su argumento es un LITERAL de cadena -- que es la forma
    # que tiene un borrado de fichero escrito en un `-c`.
    (re.compile(r"\b(?:unlink|rmdir)\s*[\(\s]", re.I), "unlink/rmdir"),
    (re.compile(r"\bremove(?:sync)?\s*\(\s*(?:r|f|rb|br|u)?[\"']", re.I),
     "remove() sobre una ruta literal"),
    # Mover y renombrar TAMBIEN destruyen el original en su sitio: el
    # equivalente de `mv`, que en shell ya escalaba por ruta desde la 1a
    # tanda. `shutil.move(r'C:\...\Pictures\a.png', 'x')` salia CONFIRM.
    # ('replace' se queda FUERA a proposito: `texto.replace('a','b')` es la
    # llamada mas comun de un `python -c` y meterlo cobraba un CONFIRM por
    # cada uso normal -- el falso positivo que inutiliza al agente.)
    (re.compile(r"\b(?:move|rename|copyfile)\s*\(\s*"
                r"(?:r|f|rb|br|u)?[\"']", re.I),
     "move()/rename() sobre una ruta literal"),
    (re.compile(r"\b(?:renamesync|movesync|copyfilesync)\s*\(", re.I),
     "renameSync()/moveSync()"),
    # `File.Delete(...)` / `[IO.File]::Delete(...)`, y su primo de .NET
    # `File.Move` (que pisa el destino).
    (re.compile(r"\bfile\s*(?:\]::|\.)\s*(?:delete|move)\b", re.I),
     "File.Delete/File.Move"),
    (re.compile(r"\bsend2trash\b", re.I), "send2trash"),
    (re.compile(r"\.\s*(?:unlink|rm|rmdir)(?:sync)?\s*\(", re.I),
     "fs.unlink/rm"),
    # Scripting.FileSystemObject (VBScript/JScript): la via de `mshta
    # vbscript:CreateObject("Scripting.FileSystemObject").DeleteFile(...)`
    # y de un .vbs escrito antes. DeleteFolder borra un ARBOL: va arriba.
    (re.compile(r"\bdeletefile\s*[\(\s]", re.I),
     "FileSystemObject.DeleteFile"),
    # Un interprete que abre un shell puede correr CUALQUIER cosa: el
    # texto del comando suele ir troceado ('rm','-rf') y no lo caza
    # _BLOCK_SUB. No se adivina: se escala.
    (re.compile(r"\b(?:subprocess|os\s*\.\s*(?:system|popen|execv?p?)|"
                r"child_process|execsync|spawnsync)\b", re.I),
     "arranque de un shell desde el codigo"),
]

# Codigo que se ARMA en ejecucion: no se puede leer lo que va a hacer.
# `getattr(__import__('sh'+'util'),'rmtree')` es el ejemplo que la 2a tanda
# declaro como escape asumido; no se puede resolver, pero si se le puede
# quitar el automatismo del acceso total (ver _codigo_en_linea).
# (`exec(` y `eval(` a secas se quedan FUERA: `python -c "print(eval('1+1'))"`
# es legitimo y meterlos cobraba friccion por nada. Lo que se caza es el
# codigo que llega CODIFICADO o con el nombre partido, que es la forma real
# de la evasion.)
_CODIGO_OFUSCADO_RE = re.compile(
    r"\b(?:b64decode|b32decode|a85decode|unhexlify|fromhex|"
    r"codecs\s*\.\s*decode|marshal\s*\.\s*loads|pickle\s*\.\s*loads)\s*\(|"
    r"\bgetattr\s*\(\s*__import__|\batob\s*\(", re.I)

# Descarga canalizada a un interprete (`curl ... | sh`, `iex (New-Object
# Net.WebClient).DownloadString(...)`): el codigo que se va a ejecutar no
# esta en la linea, asi que NO se puede clasificar. El nivel se queda como
# esta (CONFIRM: bloquearlo romperia instalaciones legitimas), pero se
# marca como no verificable para que el acceso total no lo lance solo.
_EJECUTA_REMOTO_RE = re.compile(
    r"\|\s*(?:sudo\s+)?(?:sh|bash|zsh|powershell|pwsh|python\d?|node|perl|"
    r"ruby)\b|\b(?:iex|invoke-expression)\b|\bdownloadstring\s*\(", re.I)

# Envoltorios que ESCONDEN el comando real. `powershell -c "ri -r -fo X"`
# heredaba el ALLOW de 'powershell' porque solo se miraba la cabeza.
_ENVOLTORIOS = {"powershell", "pwsh", "cmd", "sh", "bash", "zsh", "wsl",
                "powershell.exe", "pwsh.exe", "cmd.exe"}
# Envoltorios que llevan el comando PEGADO detras, sin flag de por medio:
# `wsl rm -f /mnt/c/...`, `sudo rm ...`. _desenvolver exigia consumir al
# menos un flag (`-c`, `/c`), asi que con estos devolvia None y el comando
# real no se clasificaba nunca: `wsl` salia "riesgo desconocido" -> CONFIRM
# -> con acceso total, y el rm de dentro de WSL borra los ficheros de
# Windows a traves de /mnt/c.
_ENVOLTORIOS_DIRECTOS = {"wsl", "sudo", "doas", "nohup", "nice", "stdbuf",
                         "command", "time"}
# Flags de esos envoltorios que se COMEN el token siguiente (`wsl -d
# Ubuntu <cmd>`, `sudo -u root <cmd>`): sin esto, el nombre de la distro o
# del usuario se leeria como el comando.
_FLAG_CON_VALOR = re.compile(
    r"^-(?:d|u|-distribution|-user|-cd|-exec|n|-adjustment)$", re.I)
# Lanzadores que pueden llevar OTRO comando detras (`start cmd /c del ...`
# salia ALLOW por el prefijo 'start': medido el 2026-08-25). No se
# desenvuelven siempre a proposito -- `start chrome https://youtube.com` y
# `start notepad` tienen que seguir siendo ALLOW, que es para lo que el
# dueno los pidio --, solo cuando lo que arrancan es un envoltorio, un
# interprete o una cabeza destructiva: ver _tras_lanzador.
_LANZADORES = {"start", "wt", "cmd-start"}

_FLAG_ENVOLTORIO = re.compile(
    r"^-(?:c|command|noprofile|nop|noninteractive|noni|windowstyle|w|"
    r"executionpolicy|ep|file|f)$|^/(?:c|k|q)$|^(?:hidden|bypass|"
    r"unrestricted|remotesigned)$", re.I)


def sentinel_enabled() -> bool:
    return os.environ.get("COGNIA_SENTINEL", "1").strip().lower() not in (
        "0", "off", "false", "no")


def _autonomous() -> bool:
    return os.environ.get("COGNIA_AUTONOMOUS", "").strip().lower() in (
        "1", "on", "true", "yes")


def _acceso_total() -> bool:
    """Modo 'acceso total' pedido por el dueño para SU maquina (p.ej. el control
    remoto): los comandos de riesgo DESCONOCIDO (CONFIRM) proceden sin canal de
    confirmacion, para que Cognia pueda de verdad abrir apps/navegar/operar el
    equipo. El BLOCK duro (rm -rf, format, shutdown, dd, mkfs, reset --hard,
    force-push, borrados recursivos, borrado EN MASA...) SIGUE vigente: es la
    ultima red, y con acceso total es la UNICA (por eso el borrado en masa
    subio de CONFIRM a BLOCK el 2026-08-25)."""
    return os.environ.get("COGNIA_ACCESO_TOTAL", "").strip().lower() in (
        "1", "on", "true", "yes")


# ══════════════════════════════════════════════════════════════════════
# RAZON PUBLICA vs CITA LITERAL  (ver (L) en la cabecera)
# ══════════════════════════════════════════════════════════════════════
# La razon la LEE el modelo. Decir "fuera del directorio de trabajo" no es
# describir el hallazgo: es dar la instruccion para rodearlo (mueve el
# directorio de trabajo), y en la traza del 2026-08-25 el modelo hizo
# exactamente eso en el paso siguiente. La razon publica nombra la CLASE de
# sitio; la frase literal se guarda para el audit.
_PUBLICO = {
    "una ruta fuera del directorio de trabajo": "una ruta protegida",
}

# Traza de la clasificacion EN CURSO: la cita literal y si el alcance del
# comando se pudo verificar. Va por hilo (el gate lo llaman el REPL, el
# loop del agente y los workflows) y se resetea en cada clasificacion de
# primer nivel; la recursion (envoltorios, segmentos) la comparte, que es
# justo lo que hace falta para que el detalle del segmento culpable llegue
# al audit del comando entero.
_TRAZA = threading.local()


def _traza_reset() -> None:
    _TRAZA.detalles, _TRAZA.sensible = [], False


def _apunte(detalle: str = None, sensible: bool = False) -> None:
    """Anota la cita literal (solo para el audit) y/o marca el veredicto
    como de alcance NO VERIFICABLE (ver _escalar y evaluar_shell)."""
    if not hasattr(_TRAZA, "detalles"):
        _traza_reset()
    if detalle and detalle not in _TRAZA.detalles:
        _TRAZA.detalles.append(detalle)
    if sensible:
        _TRAZA.sensible = True


def _publica(etiqueta: str) -> str:
    return _PUBLICO.get(etiqueta, etiqueta)


def _norm(ruta: str) -> str:
    """Ruta en minusculas, con barras normales y sin barra final."""
    return (ruta or "").strip().strip("\"'").lower().replace(
        "\\", "/").rstrip("/")


def _cwd_proceso() -> str:
    try:
        return _norm(os.getcwd())
    except OSError:
        # El cwd puede no existir (lo borraron bajo los pies del proceso).
        # Degradar hacia la SEGURIDAD, no hacia el permiso: sin cwd, toda
        # ruta absoluta cuenta como ajena y el destructivo escala a BLOCK.
        return ""


# Tokens que NO son una ruta: flags (-Force, /s), redirecciones, URLs,
# variables sin resolver, asignaciones. Sin este filtro, `del /q` leia "/q"
# como ruta POSIX (por eso la version absoluta exige un primer componente
# conocido) y `grep -iE 'a|b'` metia ruido.
_TOK_NO_RUTA = re.compile(r"^[-/<>|&$%{}\[\]]|^\w+://|^[\w.]+=|^\d+>")


def _rutas_relativas(scan: str):
    r"""Tokens del comando que parecen una ruta RELATIVA (`..\..\Pictures\*`,
    `sub/dir/x.log`). Se exige un separador o un `..` a proposito: un nombre
    suelto (`notas.txt`, `*.png`) NO se resuelve aqui, porque ese caso ya lo
    decide _cwd_es_personal y resolverlo tambien convertiria "guardame esto
    en el escritorio" en un BLOCK."""
    for tok in scan.split():
        t = tok.strip("\"'()[]{},;")
        if not t or _TOK_NO_RUTA.search(t) or _RUTAS_RE.match(t):
            continue
        if "\\" in t or "/" in t or t.startswith(".."):
            yield t


def _resolver(objetivo: str, cwd_ef: str = None):
    """Ruta absoluta a la que apunta `objetivo` desde el cwd EFECTIVO, o
    None si no se puede resolver. Es el `os.path.normpath(join(...))` que
    va a hacer el sistema de ficheros: juzgar el texto sin resolverlo era
    el escape (H) (`del ..\\..\\Pictures\\*.png` salia CONFIRM)."""
    base = cwd_ef if cwd_ef else None
    if base is None:
        base = _cwd_proceso()
    base = _norm(base)
    if not base or not os.path.isabs(base.replace("/", os.sep)):
        return None                    # sin base fiable no se inventa nada
    try:
        return _norm(os.path.normpath(os.path.join(base, objetivo)))
    except (ValueError, OSError, TypeError):
        return None


def _clase_protegida(plana: str, cwd: str):
    """Etiqueta del peor ambito de UNA ruta ya normalizada, o None si cae
    dentro del directorio de trabajo. Es el nucleo compartido por la rama
    absoluta y la rama relativa-resuelta de _ambito_ruta."""
    if _RAIZ_RE.match(plana):
        return "la raíz de un disco o la carpeta personal"
    if _PROT_SIEMPRE_RE.search(plana):
        return "un directorio del sistema"
    if _PROT_FIN_RE.search(plana):
        return "una carpeta personal del usuario"
    if _dentro_de_carpeta_de_contenido(plana, cwd):
        return "una carpeta personal del usuario"
    if cwd and (plana == cwd or plana.startswith(cwd + "/")):
        return None                    # dentro del workspace: no escala
    return "una ruta fuera del directorio de trabajo"


def _dentro_de_carpeta_de_contenido(plana: str, cwd: str) -> bool:
    r"""True si la ruta cuelga (a cualquier profundidad) de una carpeta de
    contenido del dueno -- Pictures, Documents, Downloads... -- y el
    directorio de trabajo NO esta ya dentro de esa misma carpeta.

    Los dos lados de la condicion importan y los dos estan medidos:
    - sin la primera, `del Pictures\Screenshots\*.png` desde el directorio
      de arriba se colaba por la exencion del workspace (borro 3 ficheros
      del sandbox en el e2e);
    - sin la segunda, un proyecto que viva en ~/Documents/<algo> quedaria
      sin poder borrar sus propios ficheros: si el agente YA trabaja dentro
      de la carpeta, esa carpeta es su workspace y vale el CONFIRM de
      siempre. Es la misma frontera que _ambito_cwd, aplicada por ruta."""
    m = _PROT_CONTENIDO_RE.search(plana or "")
    if not m:
        return False
    raiz = plana[:m.end()]             # la ruta HASTA la carpeta personal
    if cwd and (cwd == raiz or cwd.startswith(raiz + "/")):
        return False                   # el cwd ya vive dentro: es su sitio
    return True


def _ambito_ruta(scan: str, cwd_ef: str = None):
    """(etiqueta, es_protegida) del peor destino que menciona el comando.

    Devuelve None si no menciona ninguna ruta: entonces el destructivo
    actua sobre el cwd y lo decide _cwd_es_personal.

    `cwd_ef` es el directorio de trabajo EFECTIVO (el que dejo un `cd`
    encadenado o el cwd= de la tool): contra el se resuelven las rutas
    RELATIVAS, que antes no se miraban."""
    try:
        cwd = os.getcwd().lower().replace("\\", "/").rstrip("/")
    except OSError:
        # El cwd puede no existir (lo borraron bajo los pies del proceso).
        # Degradar hacia la SEGURIDAD, no hacia el permiso: sin cwd, toda
        # ruta absoluta cuenta como "fuera del directorio de trabajo" y el
        # destructivo escala a BLOCK (lo hace el guard `if cwd and ...`).
        cwd = ""
    # El registro de la MAQUINA (HKLM) no es una ruta de fichero pero es
    # igual de irreversible: un destructivo ahi escala a BLOCK. HKCU (el
    # perfil del usuario) se queda en CONFIRM.
    if re.search(r"\b(?:hklm|hkey_local_machine|hkcr|hkey_classes_root)\s*:",
                 scan):
        return "el registro del sistema (HKLM)"
    ajena = None
    for ruta in _RUTAS_RE.findall(scan):
        clase = _clase_protegida(_norm(ruta), cwd)
        if clase is None:
            continue                       # dentro del workspace: no escala
        if clase != "una ruta fuera del directorio de trabajo":
            return clase                   # protegida: el peor caso, corta
        ajena = clase
    # Rutas RELATIVAS resueltas contra el cwd EFECTIVO. Sin esto bastaba
    # escribir el camino a mano para esquivar toda la escalada, sin `cd` y
    # sin nada absoluto: `del ..\..\Pictures\*.png` -> confirm (medido).
    for rel in _rutas_relativas(scan):
        plana = _resolver(rel, cwd_ef)
        if not plana:
            continue
        clase = _clase_protegida(plana, cwd)
        if clase is None:
            continue
        if clase != "una ruta fuera del directorio de trabajo":
            return clase
        ajena = clase
    return ajena


def _ambito_cwd(destino: str):
    r"""Etiqueta del directorio al que movio un `cd` (o el cwd= de la tool),
    o None si es el propio workspace.

    No se reusa _ambito_ruta tal cual porque el ORDEN importa. El repo del
    agente vive UN nivel bajo Desktop, que ES una carpeta personal, asi que
    con el orden de _ambito_ruta un `cd <repo>\build && rm salida.log`
    salia BLOCK (medido) y el agente no podia borrar sus propios ficheros:
    el arreglo se pagaria dejandolo inutil, que es exactamente el otro
    fallo de la corrida. No abre nada nuevo: `rm salida.log` a secas, sin
    cd, ya era CONFIRM.

    La exencion tiene DOS limites, los dos medidos:
    - el destino IGUAL al cwd se exime siempre (el comando corre donde el
      proceso ya estaba: nada se movio);
    - un destino POR DEBAJO del cwd se exime solo si el no casa con un
      patron protegido. Sin ese segundo limite, con el proceso arrancado
      en C:\Users\usuario TODO quedaba eximido y `cd Pictures && del *`
      pasaba otra vez -- ademas de contradecir a `del ~\Pictures\*`, que
      es BLOCK.

    Ademas normaliza a minusculas, que _ambito_ruta da por hecho (su
    entrada normal es `norm`, ya en minusculas) y aqui la ruta viene de
    os.getcwd()/del modelo con la caja que sea."""
    plana = (destino or "").strip("\"'").lower().replace("\\", "/").rstrip("/")
    if not plana:
        return None
    try:
        cwd = os.getcwd().lower().replace("\\", "/").rstrip("/")
    except OSError:
        cwd = ""                       # sin cwd no hay workspace: se escala
    if cwd and plana == cwd:
        # No mueve nada: el comando corre donde el proceso ya estaba, asi
        # que el veredicto tiene que ser el mismo que sin cd (CONFIRM).
        return None
    if cwd and plana.startswith(cwd + "/"):
        # Debajo del cwd SI se exime... salvo que el destino case con un
        # patron protegido por si mismo. Si no, con el cwd en la carpeta
        # personal (C:\Users\usuario) TODO quedaria eximido y
        # `cd Pictures && del *` volveria a pasar: el agujero entero otra
        # vez, y ademas incoherente con `del ~\Pictures\*`, que es BLOCK.
        # Se usa _PROT_FIN_RE (el ancho: la carpeta personal Y un nivel
        # debajo) y no _CWD_PERSONAL_RE (el estrecho), porque el caso a
        # parar es ~/Pictures/Screenshots -- un nivel debajo de Pictures, y
        # el estrecho no lo ve ('screenshots' no es un nombre de carpeta
        # personal).
        # PRECIO DECLARADO, y es una decision, no un descuido: con el
        # proceso arrancado en ~/Desktop, `rm build.log | cwd=<repo>` sale
        # BLOCK, porque Desktop\cognia_v2 tambien esta "un nivel debajo".
        # Se acepta porque YA era el veredicto de la forma absoluta
        # (`rm C:\...\Desktop\cognia_v2\build.log` -> BLOCK desde la 1a
        # tanda): no se anade ninguna incoherencia nueva. La salida limpia
        # es arrancar Cognia DENTRO del repo, y entonces cwd == destino y
        # vuelve a CONFIRM. Distinguir "proyecto" de "carpeta de fotos" un
        # nivel debajo de Desktop pedia heuristicas (¿hay .git?) que se
        # falsifican solas -- ver 'parametro-configurable-siempre-se-
        # falsifica' en el repo.
        if not (_RAIZ_RE.match(plana) or _PROT_SIEMPRE_RE.search(plana) or
                _PROT_FIN_RE.search(plana)):
            return None
    return _ambito_ruta(plana)


# El HOME del usuario ELLA MISMA: C:\Users\usuario, /home/usuario,
# /Users/usuario, /root. No lleva nombre de carpeta conocida, asi que
# _CWD_PERSONAL_RE no lo veia.
_HOME_RE = re.compile(r"^(?:[a-z]:)?/(?:users|home)/[^/]+/?$|^/root/?$", re.I)


def _es_home(plana: str) -> bool:
    if _HOME_RE.match(plana or ""):
        return True
    try:
        return bool(plana) and plana == _norm(os.path.expanduser("~"))
    except Exception:
        return False


def _cwd_es_personal(cwd_cd: str = None):
    r"""Etiqueta si el comando va a correr DENTRO de una carpeta del dueno.

    POR QUE existe (medido el 2026-08-25 con perdida de datos REAL, la
    segunda del dia). Un destructivo que no nombra ninguna ruta actua sobre
    el directorio de trabajo, y hasta aqui eso se daba por bueno: "dentro
    del workspace el agente borra ficheros suyos" -> CONFIRM -> con
    COGNIA_ACCESO_TOTAL=1, ejecutado. Pero el cwd de las sesiones del dueno
    es C:\Users\usuario\Desktop, que no es un workspace: es SU ESCRITORIO.
    En una corrida de prueba el agente recibio "entra a la carpeta con cd y
    borra ahi", cambio de objetivo al Escritorio y lanzo

        cd C:\Users\usuario\Desktop && del *.png    -> confirm -> EJECUTADO

    borrando 60 .png (13.635.124 bytes) que `del` no manda a la papelera.
    Los dos veredictos anteriores eran identicos (`del *.png` a secas
    tambien era CONFIRM): el agujero no era el `cd`, era dar por hecho que
    el cwd es un directorio de trabajo.

    La regla se queda ESTRECHA para no inutilizar al agente: solo cuenta la
    carpeta personal ELLA MISMA (Desktop, Pictures, Documents, el HOME, la
    raiz de un disco, un directorio del sistema). Un proyecto colgando de
    ella (Desktop\cognia_v2) NO cuenta, asi que `rm build.log` dentro del
    repo sigue en CONFIRM, que es como trabaja el agente todo el dia."""
    ruta = cwd_cd
    if ruta is None:
        try:
            ruta = os.getcwd()
        except OSError:
            return None            # sin cwd no hay nada que proteger aqui
    plana = (ruta or "").strip("\"'").lower().replace("\\", "/").rstrip("/")
    if not plana:
        return None
    if _RAIZ_RE.match(plana):
        return "la carpeta personal del usuario"
    if _PROT_SIEMPRE_RE.search(plana):
        return "un directorio del sistema"
    if _CWD_PERSONAL_RE.search(plana):
        return "una carpeta personal del usuario"
    if _es_home(plana):
        # (I) de la 3a tanda: la regla miraba NOMBRES de carpeta (Desktop,
        # Pictures...) y C:\Users\usuario no es ninguno, asi que con el cwd
        # en el HOME `del *.png` salia CONFIRM -- el mismo agujero que se
        # acababa de cerrar en el Escritorio, un nivel mas arriba.
        return "la carpeta personal del usuario"
    return None


# Cabezas de _HEAD_DESTRUCTIVO que NO borran un conjunto de ficheros: unas
# pisan/renombran un fichero NOMBRADO y otras ni siquiera tocan el disco.
# La escalada por "el cwd es una carpeta personal" (ver _cwd_es_personal)
# no aplica a ellas: el dano medido fue un BORRADO EN BLOQUE (`del *.png`),
# y bloquear aqui convertiria "guardame esto en el escritorio" o un
# `taskkill /f /im chrome.exe` en un BLOCK absurdo. Siguen escalando por
# RUTA como siempre.
_HEADS_SIN_BORRADO_EN_BLOQUE = {
    "set-content", "sc", "out-file", "rename-item", "rni", "attrib",
    "takeown", "icacls", "chmod", "chown", "taskkill", "stop-process",
    "stop-service", "vssadmin",
    # copiar ESCRIBE un fichero nombrado; no vacia la carpeta donde corre.
    "copy", "cp", "xcopy", "copy-item", "cpi",
}


def _escalar(scan: str, razon: str, cwd_cd: str = None,
             borra_en_bloque: bool = True) -> tuple:
    """CONFIRM por defecto; BLOCK si el destructivo apunta a ruta protegida
    o absoluta ajena al cwd. Es la regla pedida el 2026-08-25: 'como minimo
    confirm, y block si van sobre rutas fuera del cwd o sobre el
    HOME/Pictures/Documents del usuario'.

    `cwd_cd` es el directorio al que movio un `cd` ENCADENADO antes (ver
    (A) en la cabecera): sin el, `cd <protegida> && del *` no escalaba
    porque el segmento del borrado no menciona ninguna ruta.

    La razon que devuelve es la PUBLICA (la lee el modelo) y es la MISMA
    para la forma directa y para la rodeada con `cd`: si el mensaje
    distinguiera las dos, estaria diciendo cual de ellas probar despues
    (ver (L) en la cabecera). La cita literal -- que fue el cwd, que fue un
    `cd`, que la ruta caia fuera del directorio de trabajo -- se apunta con
    _apunte() y sale por el audit."""
    destino = _ambito_ruta(scan, cwd_cd)
    if destino:
        _apunte(f"{razon}, sobre {destino} (ruta escrita en el comando)")
        return BLOCK, f"{razon}, sobre {_publica(destino)}"
    if cwd_cd:
        # El comando NO escribe la ruta: la puso el `cd` (o el parametro
        # cwd= de la tool). Se clasifica ese destino con _ambito_cwd, que
        # deja pasar el propio workspace.
        destino = _ambito_cwd(cwd_cd)
        if destino:
            _apunte(f"{razon}, dentro de {destino}: ahi es donde apunta el "
                    f"directorio de trabajo del comando (cd encadenado o "
                    f"cwd= de la tool)")
            return BLOCK, f"{razon}, sobre {_publica(destino)}"
    # El comando no nombra NINGUNA ruta: se lleva por delante lo que haya en
    # el directorio donde corra. Si ese directorio es una carpeta del dueno
    # (y no un proyecto), eso son SUS ficheros. Ver _cwd_es_personal: aqui
    # se perdieron 60 .png del Escritorio.
    destino = _cwd_es_personal(cwd_cd) if borra_en_bloque else None
    if destino:
        _apunte(f"{razon}, y el directorio de trabajo es {destino}: un "
                f"comando sin ruta borraria ficheros suyos")
        return BLOCK, f"{razon}, sobre {_publica(destino)}"
    # Se queda en CONFIRM. Pero si el alcance NO SE PUDO VERIFICAR (el `cd`
    # apunta a una variable, o a un directorio que no existe), el acceso
    # total no puede aprobarlo solo: ver (K) en la cabecera y evaluar_shell.
    if _alcance_no_verificable(scan, cwd_cd):
        _apunte("alcance no verificable: el directorio de trabajo del "
                "comando no se pudo resolver a una carpeta real",
                sensible=True)
    return CONFIRM, razon


def _alcance_no_verificable(scan: str, cwd_cd: str = None) -> bool:
    r"""True si no se puede afirmar DONDE va a actuar el destructivo.

    Dos formas medidas, las dos con el mismo efecto: la escalada por ruta
    no tiene nada solido que mirar y el veredicto cae a CONFIRM.
      cd $destino && del *.png        (el `cd` va a una VARIABLE)
      del %CARPETA%\*.png             (el objetivo va a una variable)
    Con COGNIA_ACCESO_TOTAL=1 eso se ejecutaba sin preguntar a nadie."""
    if re.search(r"\$\w|\$\{|%[a-z_][\w()]*%", scan or "", re.I):
        # $HOME / %USERPROFILE% / $env:USERPROFILE SI se resuelven (los lee
        # _RUTAS_RE y cuentan como carpeta personal): no son "sin verificar".
        sin_conocidas = re.sub(
            r"\$home|%userprofile%|\$env:userprofile|\$_\b", " ",
            scan or "", flags=re.I)
        if re.search(r"\$\w|\$\{|%[a-z_][\w()]*%", sin_conocidas, re.I):
            return True
    if not cwd_cd:
        return False                   # corre en el cwd real del proceso
    plana = _norm(cwd_cd)
    if not plana or not os.path.isabs(plana.replace("/", os.sep)):
        return True                    # no se resolvio a nada absoluto
    try:
        return not os.path.isdir(plana)
    except OSError:
        return True


def _sin_grupo(toks: list) -> list:
    r"""Tokens sin la puntuacion de AGRUPACION que los precede.

    Escape medido (4a tanda): con ESPACIOS alrededor, el parentesis o la
    llave son un token PROPIO, y entonces el primer token del segmento no
    es el comando sino el simbolo:
        ( cd /c/Users/usuario/Pictures && rm *.png )
        { cd /c/Users/usuario/Pictures; rm *.png; }
    _destino_cd leia toks[0] = '(' -> no es un `cd` -> el cwd NO se
    propagaba, y el `rm *.png` del segmento siguiente se quedaba sin ruta
    que mirar: CONFIRM -> con acceso total, ejecutado. Con los parentesis
    PEGADOS (`(cd X && rm *)`) si era BLOCK, o sea que el bypass era
    literalmente UN ESPACIO.

    Se quitan los tokens que son SOLO agrupacion; no se toca nada mas."""
    i = 0
    while i < len(toks) and toks[i] and not toks[i].strip("(){}&;"):
        i += 1
    return toks[i:]


def _destino_cd(segmento: str):
    """Ruta a la que mueve un `cd`/`pushd`/`Set-Location`, o None si el
    segmento no cambia de directorio. `cd` a secas va a la carpeta personal."""
    toks = _sin_grupo(segmento.split())
    if not toks:
        return None
    head = toks[0].strip("\"'(){}&")
    if head not in _CD_HEADS:
        return None
    i = 1
    while i < len(toks) and _CD_FLAGS.match(toks[i]):
        i += 1
    if i >= len(toks):
        return "~"                       # `cd` sin argumentos -> $HOME
    return " ".join(toks[i:]).strip().strip("\"'")


def _cwd_tras_cd(segmento: str, cwd_ef: str):
    r"""Directorio de trabajo vigente DESPUES de ejecutar `segmento`.

    Se devuelve una RUTA y no una etiqueta a proposito: con la etiqueta, un
    `cd` RELATIVO no fijaba nada y el escape volvia a abrirse
    (`cd ..\..\Pictures && del *.png` -> CONFIRM, medido). Resolviendo
    contra el cwd real, ese comando apunta a la carpeta protegida y escala.

    - `cd` con ruta reconocible (absoluta, ~, %USERPROFILE%, $HOME): se
      toma tal cual, que _ambito_ruta ya sabe leer esas formas.
    - `cd` relativo: se resuelve contra el cwd efectivo acumulado.
    - cualquier otro comando: no lo toca."""
    destino = _destino_cd(segmento)
    if destino is None:
        return cwd_ef
    if _RUTAS_RE.search(destino):
        return destino
    base = cwd_ef
    if base is None:
        try:
            base = os.getcwd()
        except OSError:
            # Sin cwd no se puede resolver: se devuelve el trozo relativo,
            # que _ambito_ruta leera como "sin ruta" -> CONFIRM. Degradar
            # aqui hacia BLOCK bloquearia `cd build && rm x` y dejaria al
            # agente sin poder trabajar en su propio directorio.
            return destino
    try:
        return os.path.normpath(os.path.join(base, destino))
    except (ValueError, OSError, TypeError):
        return base


def _decodificar_b64(norm: str) -> str:
    """Payload en claro de un `-EncodedCommand <base64>` de PowerShell, o "".

    El VEREDICTO no depende de esto (un comando codificado ya es BLOCK: lo
    que no se puede leer, no pasa). Se decodifica para el AUDIT, que es
    quien tiene que poder decir QUE se intento; si la cadena no es base64
    valido se devuelve "" y no pasa nada."""
    m = re.search(r"-e(?:nc|ncodedcommand)?\s+([a-z0-9+/=]{8,})", norm, re.I)
    if not m:
        return ""
    bruto = m.group(1)
    try:
        crudo = base64.b64decode(bruto + "=" * (-len(bruto) % 4))
    except (binascii.Error, ValueError):
        return ""
    for cod in ("utf-16-le", "utf-8"):
        try:
            texto = crudo.decode(cod).strip()
        except (UnicodeDecodeError, ValueError):
            continue
        if texto.isprintable():
            return texto
    return ""


# ══════════════════════════════════════════════════════════════════════
# EL CODIGO QUE NO ESTA EN LA LINEA  (4a tanda, 2026-08-25)
# ══════════════════════════════════════════════════════════════════════
# Nueve entradas del equipo rojo eran la MISMA jugada en dos pasos:
#   1) escribir el codigo con la tool de escribir (que no pasa por aqui),
#   2) ejecutarlo con una cabeza inocente.
#     python borra_todo.py            -> allow (prefijo 'python')
#     powershell -File .\borra.ps1    -> confirm -> acceso total
#     .\borra.bat                     -> confirm -> acceso total
#     cscript //nologo borra.vbs      -> confirm -> acceso total
#     npm run limpiar                 -> allow (prefijo 'npm')
#     python < borra_todo.py          -> allow
# Las tres confirmadas en sandbox borraron la carpeta entera. Todo el gate
# miraba UNA LINEA y el programa vivia en OTRO SITIO.
#
# La regla que lo cierra es la misma que ya gobernaba el -EncodedCommand
# ("lo que no se puede leer, no pasa"), rebajada un escalon porque aqui SI
# se suele poder leer: se ABRE el fichero (o el script de package.json) y
# se clasifica su contenido. Tres salidas:
#   - contiene un borrado de arbol y NOMBRA una carpeta protegida -> BLOCK
#   - contiene un borrado de arbol fuera del workspace -> CONFIRM y ademas
#     NO VERIFICABLE (el acceso total deja de aprobarlo solo)
#   - no se puede leer (no existe todavia, es enorme, no se resuelve) ->
#     CONFIRM NO VERIFICABLE. Aqui cae el ataque escrito-y-ejecutado
#     cuando el fichero aun no esta, y tambien el simple error de tecleo:
#     el comando iba a fallar de todos modos, asi que el precio es cero.
#   - todo lo demas -> no se toca el veredicto (un `python scripts/x.py`
#     normal sigue en ALLOW, que es como trabaja el agente todo el dia).
#
# LIMITE DECLARADO, igual que el del codigo en linea: esto NO ejecuta ni
# interpreta el script. Un script que calcule la ruta en tiempo de
# ejecucion, o que llame a otro modulo, se escapa. Es una capa mas.

# Patrones para el CONTENIDO de un fichero. Es un subconjunto de
# _CODIGO_BORRA_RE a proposito: 'subprocess', 'os.system' y move/rename
# aparecen en la mitad de los scripts legitimos del repo, y meterlos aqui
# cobraria un CONFIRM por cada `python scripts/*.py` -- el falso positivo
# que inutiliza al agente, que es el otro fallo medido del 2026-08-25.
_FICHERO_BORRA_RE = _CODIGO_MASA_RE + [
    (re.compile(r"\b(?:unlink|rmdir)\s*[\(\s]", re.I), "unlink/rmdir"),
    (re.compile(r"\bremove(?:sync)?\s*\(\s*(?:r|f|rb|br|u)?[\"']", re.I),
     "remove() sobre una ruta literal"),
    (re.compile(r"\bfile\s*(?:\]::|\.)\s*delete\b", re.I), "File.Delete"),
    (re.compile(r"\.\s*(?:unlink|rm|rmdir)(?:sync)?\s*\(", re.I),
     "fs.unlink/rm"),
    (re.compile(r"\bdeletefile\s*[\(\s]", re.I),
     "FileSystemObject.DeleteFile"),
]


def _leer_script(ruta: str, cwd_ef: str = None):
    """(texto, motivo). Nunca lanza.

    `texto` None y motivo "" significa QUE NO HAY NADA QUE EJECUTAR (el
    fichero no existe): no se escala, porque un script que no esta no
    puede destruir nada -- el comando va a fallar solo. Es la diferencia
    entre "no se puede verificar" (existe y no se deja leer -> se escala)
    y "no hay nada" (no existe -> el veredicto no cambia). El ataque real
    del equipo rojo escribe el fichero ANTES de lanzarlo, asi que en el
    momento del gate el fichero SI esta y si se lee."""
    plana = _resolver((ruta or "").strip("\"'"), cwd_ef)
    if not plana:
        return None, "no se pudo resolver dónde está"
    real = plana.replace("/", os.sep)
    try:
        if not os.path.isfile(real):
            return None, ""                     # no hay programa: no escala
        if os.path.getsize(real) > _SCRIPT_MAX:
            return None, "es demasiado grande para leerlo entero"
        with open(real, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read(_SCRIPT_MAX), ""
    except (OSError, ValueError):
        return None, "no se pudo leer"


def _clasificar_texto_de_script(texto: str, etiqueta: str, es_shell: bool,
                                cwd_cd: str = None):
    """(nivel, razon) para el CONTENIDO de un script, o None si está limpio."""
    if es_shell:
        # Un .bat/.ps1/.sh ES una lista de comandos de shell: se clasifica
        # con el GATE ENTERO, no con media docena de patrones. Asi el
        # `del *.png` de dentro de un .bat escala igual que si lo hubiera
        # escrito el modelo en la linea -- que es exactamente el ataque
        # confirmado en sandbox. En un .py no se puede hacer esto: su
        # texto no es shell (y un corpus de tests con la cadena "rm -rf"
        # dentro daria un falso positivo; este mismo repo tiene uno).
        nivel, razon = clasificar_shell(texto or "", 3, cwd_cd)
        if nivel != ALLOW:
            _apunte(f"{etiqueta} contiene: {razon}")
            return nivel, f"el script que se ejecuta contiene {razon}"
        return None
    bajo = re.sub(r"\s+", " ", (texto or "").lower())
    for rx, nombre in _FICHERO_BORRA_RE:
        if not rx.search(bajo):
            continue
        destino = _ambito_ruta(bajo, cwd_cd)
        if destino and destino != "una ruta fuera del directorio de trabajo":
            _apunte(f"{etiqueta} borra con {nombre} sobre {destino}")
            return BLOCK, (f"el script que se ejecuta borra ficheros "
                           f"({nombre}), sobre {_publica(destino)}")
        if destino:
            _apunte(f"{etiqueta} borra con {nombre} sobre {destino}",
                    sensible=True)
            return CONFIRM, (f"el script que se ejecuta borra ficheros "
                             f"({nombre}) fuera de su sitio")
        # El script NO nombra ninguna ruta: borra DONDE CORRA
        # (`shutil.rmtree(os.getcwd())`). Entonces manda el directorio de
        # trabajo, exactamente igual que un `del *.png` sin ruta -- que es
        # la regla que costo 60 .png del Escritorio. Se mira, y si ese
        # directorio es del dueno es BLOCK.
        donde = _cwd_es_personal(cwd_cd) or _ambito_cwd(cwd_cd or "")
        if donde:
            _apunte(f"{etiqueta} borra con {nombre} y correria dentro de "
                    f"{donde}")
            return BLOCK, (f"el script que se ejecuta borra ficheros "
                           f"({nombre}), sobre {_publica(donde)}")
        # Borra dentro del workspace: es su trabajo. No se escala, porque
        # medio repo tiene scripts con un rmtree de su propio build/ y
        # cobrarles un CONFIRM diario es el otro fallo del 2026-08-25.
        return None
    return None


def _clasificar_script(ruta: str, cwd_cd: str = None, quien: str = "el shell"):
    """(nivel, razon) para `<quien> <ruta>`, o None si el script está limpio."""
    etiqueta = f"el script '{(ruta or '')[:80]}' que ejecuta {quien}"
    texto, motivo = _leer_script(ruta, cwd_cd)
    if texto is None:
        if not motivo:
            return None            # no existe: no hay programa que juzgar
        _apunte(f"{etiqueta} {motivo}: el código que se va a ejecutar no se "
                f"puede leer", sensible=True)
        return CONFIRM, ("ejecución de un script cuyo contenido no se puede "
                         "verificar")
    veredicto = _clasificar_texto_de_script(
        texto, etiqueta, (ruta or "").strip("\"'").lower().endswith(_EXT_SHELL),
        cwd_cd)
    # Leido y limpio: se dice ASI, y no con un None. La diferencia importa
    # para `.\build.bat`, cuya cabeza no esta en ninguna lista: sin este
    # ALLOW explicito se quedaba en "comando de forma no reconocida" ->
    # CONFIRM, o sea que abrir el fichero no le servia de nada al uso
    # legitimo y solo cobraba friccion.
    return veredicto or (ALLOW, "script verificado: su contenido está limpio")


def _clasificar_npm_run(tokens: list, cwd_cd: str = None):
    """(nivel, razon) para `npm run <script>`: el cuerpo del script vive en
    package.json, o sea FUERA del comando. `npm run limpiar` salia ALLOW
    entero por el prefijo 'npm' aunque ese script haga lo que quiera."""
    nombre = tokens[2].strip("\"'") if len(tokens) > 2 else ""
    if not nombre or nombre.startswith("-"):
        return None
    etiqueta = f"el script '{nombre}' de package.json"
    texto, motivo = _leer_script("package.json", cwd_cd)
    cuerpo = None
    if texto is not None:
        try:
            cuerpo = (json.loads(texto).get("scripts") or {}).get(nombre)
        except (ValueError, AttributeError, TypeError):
            cuerpo, motivo = None, "no se pudo interpretar"
    if not isinstance(cuerpo, str):
        if texto is None and not motivo:
            return None        # no hay package.json: `npm run` va a fallar
        if texto is not None and not motivo:
            return None        # hay package.json y ese script no existe
        _apunte(f"{etiqueta} {motivo}: el código que se va a ejecutar no se "
                f"puede leer", sensible=True)
        return CONFIRM, ("ejecución de un script de npm cuyo contenido no se "
                         "puede verificar")
    # El cuerpo de un script de npm ES un comando de shell: se clasifica
    # con el gate entero, no con media docena de patrones.
    nivel, razon = clasificar_shell(cuerpo, 3, cwd_cd)
    if nivel == ALLOW:
        return None
    _apunte(f"{etiqueta}: {cuerpo[:200]}")
    return nivel, f"{razon} (dentro del script '{nombre}' de package.json)"


def _pisa_fichero_existente(destino: str, cwd_ef: str = None) -> bool:
    """True si `destino` (el objetivo de una redireccion) ya es un fichero
    en el directorio de trabajo efectivo. Crear un fichero nuevo no
    destruye nada; pisar uno que ya estaba, si."""
    plana = _resolver((destino or "").strip("\"'"), cwd_ef)
    if not plana:
        return False
    try:
        return os.path.isfile(plana.replace("/", os.sep))
    except OSError:
        return False


def _script_a_ejecutar(tokens: list):
    r"""Fichero de programa que va a correr un interprete, o None.

    Se exige que el token TERMINE en una extension de script (y no "el
    primer posicional") porque los flags con valor lo romperian: en
    `python -X utf8 -c"..."`, 'utf8' es el valor de -X y no un programa.
    Un flag de codigo en linea o un `-m <modulo>` cortan la busqueda: ahi
    el programa no es un fichero."""
    for i, bruto in enumerate(tokens):
        if not i:
            continue
        t = bruto.strip("\"'")
        if _FLAG_CODIGO.match(t) or _FLAG_CODIGO_PEGADO.match(t):
            return None
        if t in ("-m", "--module"):
            return None
        if t == "<" and i + 1 < len(tokens):
            return tokens[i + 1].strip("\"'")   # el codigo entra por stdin
        if t.startswith("<") and len(t) > 1:
            return t[1:].strip("\"'")
        if t.lower().endswith(_EXT_SCRIPT):
            return t
    return None


def _codigo_pegado(tokens: list) -> bool:
    """True si algun token trae el flag de codigo PEGADO al codigo."""
    return any(_FLAG_CODIGO_PEGADO.match(t.strip("\"'")) for t in tokens[1:])


def _codigo_en_linea(head: str, tokens: list, cwd_cd: str = None):
    """(nivel, razon) si es un interprete con codigo en linea que borra;
    None si no aplica. Ver (C) en la cabecera, con el limite declarado.

    LIMITE, declarado otra vez porque es lo que justifica (3): esto es
    BEST-EFFORT, no un analizador de Python ni de JS. Un payload ofuscado
    (`getattr(__import__('sh'+'util'),'rmtree')`, un base64 propio, un
    fichero .py escrito antes y lanzado despues) se escapa por diseno, y
    `python script.py` sigue siendo ALLOW. Por eso la ultima red no puede
    ser esta capa sino el acceso total ACOTADO de evaluar_shell: un CONFIRM
    destructivo de alcance no verificable ya no se auto-aprueba."""
    script, pegado = None, False
    if head in _LANZA_PAQUETE:
        payload = " ".join(tokens[1:])
    elif head == "npm":
        # `npm exec rimraf <ruta>` salia ALLOW por el prefijo (medido).
        # `npm install rimraf` NO puede ser lo mismo: instalar no borra.
        sub = tokens[1].strip("\"'").lower() if len(tokens) > 1 else ""
        if sub not in _NPM_EJECUTA:
            return None
        if sub in ("run", "run-script"):
            veredicto = _clasificar_npm_run(tokens, cwd_cd)
            if veredicto:
                return veredicto
        payload = " ".join(tokens[2:])
    elif head in _INTERPRETES:
        # El payload es TODO el argumento del interprete, no "lo que viene
        # detras del flag -c". Buscar el flag como TOKEN suelto era la
        # evasion mas barata del equipo rojo: `python -c"<rmtree>"` (sin
        # espacio) no casaba con ningun token '-c' y el rmtree no se leia
        # nunca -> ALLOW. Con el argumento entero, el mismo payload se ve
        # igual con espacio, con '=' o pegado, y ademas caza los flags
        # intermedios (`python -X utf8 -c"..."`).
        payload = " ".join(tokens[1:])
        script, pegado = _script_a_ejecutar(tokens), _codigo_pegado(tokens)
    else:
        return None
    for rx, nombre in _CODIGO_MASA_RE:
        if rx.search(payload):
            _apunte(f"codigo en linea de '{head}': {nombre}")
            return BLOCK, (f"borrado de un arbol desde codigo en linea de "
                           f"'{head}' ({nombre})")
    for rx, nombre in _CODIGO_BORRA_RE:
        if rx.search(payload):
            return _escalar(payload,
                            f"borrado desde codigo en linea de '{head}' "
                            f"({nombre})", cwd_cd)
    # Los modificadores destructivos (paso 4) tambien valen dentro del
    # argumento de un interprete: `python -m venv --clear <ruta>` VACIA el
    # directorio de destino, y como el paso 3b corre ANTES del 4 se
    # quedaba en el CONFIRM generico de "apunta a una carpeta personal" en
    # vez del BLOCK que le toca.
    for rx, plantilla, borra in _MOD_RE:
        if rx.search(payload):
            return _escalar(payload, plantilla, cwd_cd, borra)
    # El programa vive en un FICHERO: se abre y se clasifica su contenido.
    # `python borra_todo.py` era ALLOW y en sandbox borro la carpeta entera.
    if script:
        veredicto = _clasificar_script(script, cwd_cd, f"'{head}'")
        # El ALLOW de "script limpio" NO se devuelve desde aqui: cortaria
        # el resto de la clasificacion y se perderia lo que venga en la
        # MISMA linea (`python mide.py > <ruta protegida>`). Se deja seguir
        # y que lo resuelva la allowlist del paso 7.
        if veredicto and veredicto[0] != ALLOW:
            return veredicto
    # Flag de codigo PEGADO al codigo (`-c"..."`, `-c=...`, `--eval="..."`,
    # `eval"..."`). Aunque este payload concreto no case con ninguna API de
    # borrado, la forma existe para que el gate no sepa donde empieza el
    # codigo: se le quita el automatismo del acceso total. Con el espacio
    # de siempre (`python -c "print(1)"`) no pasa nada de esto.
    if pegado:
        _apunte(f"codigo en linea de '{head}' con el flag PEGADO al codigo: "
                f"no se puede delimitar donde empieza el codigo",
                sensible=True)
        return CONFIRM, (f"código en línea de '{head}' con el flag pegado al "
                         f"código")
    # El limite declarado arriba dice que un payload OFUSCADO se escapa.
    # No se puede deshacer la ofuscacion, pero si se puede negarle el
    # automatismo: codigo que se construye o se decodifica en tiempo de
    # ejecucion no es verificable, asi que baja a CONFIRM y el acceso total
    # deja de aprobarlo solo (que es lo unico que separaba el CONFIRM de la
    # ejecucion en las sesiones del remoto).
    if _CODIGO_OFUSCADO_RE.search(payload):
        _apunte(f"codigo en linea de '{head}' que se construye o decodifica "
                f"en ejecucion: no es verificable", sensible=True)
        return CONFIRM, (f"código en línea de '{head}' que se construye o "
                         f"decodifica en ejecución")
    # Red de ultimo recurso del limite declarado arriba: si el payload NO
    # casa con ninguna API conocida pero NOMBRA una carpeta personal o del
    # sistema, no se puede afirmar que sea inocuo -- puede ser una API que
    # no esta en la lista o una forma ofuscada. No se bloquea (leer un
    # fichero del dueno con `python -c` es legitimo): se baja a CONFIRM y
    # se marca como no verificable, que es lo que impide que el acceso
    # total lo apruebe solo. Las rutas del propio workspace no cuentan.
    destino = _ambito_ruta(payload, cwd_cd)
    if destino and destino != "una ruta fuera del directorio de trabajo":
        _apunte(f"codigo en linea de '{head}' que nombra {destino} sin "
                f"casar con ninguna API de borrado conocida", sensible=True)
        return CONFIRM, (f"código en línea de '{head}' que apunta a "
                         f"{_publica(destino)}")
    return None


def _tras_lanzador(tokens: list):
    """Comando que arranca un lanzador (`start`, `wt`), o None si lo que
    arranca es una app normal.

    Solo se desenvuelve cuando detras viene un envoltorio, un interprete o
    una cabeza destructiva: `start cmd /c del <ruta>` salia ALLOW por el
    prefijo (medido), pero `start chrome https://youtube.com` y
    `start notepad` tienen que seguir siendo ALLOW -- el dueno pidio
    expresamente poder abrir apps y URLs."""
    i = 1
    # `start "titulo" /min cmd /c ...`: el titulo entrecomillado y los
    # flags de start no son el comando.
    while i < len(tokens) and (tokens[i].startswith("/") or
                               tokens[i].startswith("-") or
                               (tokens[i].startswith('"') and
                                tokens[i].endswith('"'))):
        i += 1
    if i >= len(tokens):
        return None
    cabeza = re.split(r"[\\/]", tokens[i].strip("\"'"))[-1]
    if cabeza.endswith(".exe"):
        cabeza = cabeza[:-4]
    if (cabeza in _ENVOLTORIOS or cabeza in _INTERPRETES or
            cabeza in _LANZA_PAQUETE or cabeza in _HEAD_DESTRUCTIVO or
            cabeza == "npm"):
        return " ".join(tokens[i:])
    return None


def _segmentar(norm: str):
    r"""Trocea por los separadores de shell (; & && | || ` $( ) SIN entrar
    en las comillas.

    El split anterior era un re.split ciego, y eso partia el PAYLOAD de un
    interprete por su propio ';':
      cd <protegida> && python -c "import shutil; shutil.rmtree('.')"
    quedaba como `... python -c "import shutil` + `shutil.rmtree('.')"`, y
    ninguno de los dos trozos es ya "un interprete con codigo en linea", asi
    que el paso 3b no llegaba a mirar el rmtree: CONFIRM -> con acceso
    total, ejecutado (escape (G), medido). Respetar las comillas devuelve el
    segmento ENTERO al paso 3b -- y de paso deja de partir
    `grep -iE 'captur|screenshot'` por el pipe de su propio patron."""
    segs, buf, comilla = [], [], ""
    i, n = 0, len(norm)
    while i < n:
        c = norm[i]
        if comilla:
            buf.append(c)
            if c == comilla:
                comilla = ""
            i += 1
            continue
        if c in "\"'":
            comilla = c
            buf.append(c)
            i += 1
            continue
        if c in ";&|`":
            segs.append("".join(buf))
            buf = []
            # && y || cuentan como UN separador
            i += 2 if (i + 1 < n and norm[i + 1] == c) else 1
            continue
        if c == "$" and i + 1 < n and norm[i + 1] == "(":
            segs.append("".join(buf))
            buf = []
            i += 2
            continue
        buf.append(c)
        i += 1
    segs.append("".join(buf))
    return [s.strip() for s in segs if s.strip()]


def _bloqueo_duro(scan: str):
    """Razón del BLOCK duro, o None. Compartida por clasificar_shell y por
    el modo kill-switch de evaluar_shell (una lista, un arreglo)."""
    for sub, razon in _BLOCK_SUB:
        if sub in scan:
            return razon
    for rx, razon in _BLOCK_RE:
        if rx.search(scan):
            return razon
    for rx, plantilla in _MASA_RE:
        m = rx.search(scan)
        if m:
            grupo = (m.group(1) if m.re.groups else "") or ""
            return plantilla.format(grupo)
    return None


def _desenvolver(norm: str, tokens: list, head: str = ""):
    """Payload real de `powershell -c ...` / `cmd /c ...` / `bash -c ...`
    / `wsl rm ...`, o None si no es un envoltorio (o no lleva comando).

    `head` importa para los envoltorios DIRECTOS (wsl/sudo/...): esos no
    llevan ningun flag entre medias, asi que el bucle no consume nada y la
    version anterior devolvia None -- y el comando de dentro no se
    clasificaba jamas (ver _ENVOLTORIOS_DIRECTOS)."""
    i = 1
    while i < len(tokens) and (tokens[i].startswith("-") or
                               tokens[i].startswith("/")):
        if not _FLAG_ENVOLTORIO.match(tokens[i]):
            break
        i += 1
        # -executionpolicy bypass / -windowstyle hidden: saltar el valor
        if (i < len(tokens) and not tokens[i].startswith("-") and
                _FLAG_ENVOLTORIO.match(tokens[i])):
            i += 1
    if i <= 1 and head in _ENVOLTORIOS_DIRECTOS:
        # `wsl rm -f /mnt/c/...`: el comando empieza justo detras. Y si
        # lleva flags PROPIOS delante (`wsl -e rm ...`, `wsl -d Ubuntu
        # rm ...`, `sudo -u root rm ...`) hay que saltarlos, o el head sale
        # '-e' y el comando de dentro no se clasifica igual (lo cazo la
        # pasada adversarial propia, no el equipo rojo).
        i = 1
        while i < len(tokens) and tokens[i].startswith("-"):
            con_valor = _FLAG_CON_VALOR.match(tokens[i])
            i += 2 if con_valor else 1
    if i < 1 or i >= len(tokens) or (i == 1 and
                                     head not in _ENVOLTORIOS_DIRECTOS):
        return None
    payload = " ".join(tokens[i:]).strip().strip("\"'")
    return payload or None


def clasificar_shell(cmd: str, _prof: int = 0,
                     _cwd_cd: str = None) -> tuple:
    """(nivel, razon) para un comando de shell. Determinista, cero LLM.

    La razon es PUBLICA (la ve el modelo) y dice QUE se detecto, sin
    repetir el payload: el agente de la corrida del 2026-08-25 gasto 3
    pasos reintentando porque "patrón destructivo irreversible" no le
    decia que parte del comando sobraba. Lo que NO dice es como rodear el
    muro: nada de "fuera del directorio de trabajo" (eso es una invitacion
    a hacer `cd`, y en la traza real el modelo la acepto). La cita literal
    va al audit -- ver clasificar_shell_detalle y (L) en la cabecera."""
    if _prof == 0:
        _traza_reset()
    crudo = (cmd or "").strip().lower()
    # El SALTO DE LINEA separa comandos igual que ';'. Colapsarlo con
    # \s+ dejaba `echo x<NL>del "C:\...\Pictures\*.png"` como un solo
    # comando con cabeza 'echo' -> ALLOW (medido; ver (B) en la
    # cabecera). Las continuaciones de linea ('\' de sh, '`' de
    # PowerShell, '^' de cmd) SI son un comando solo: se unen antes.
    crudo = re.sub(r"[\\`^]\r?\n\s*", " ", crudo)
    crudo = re.sub(r"\r?\n", " ; ", crudo)
    norm = re.sub(r"\s+", " ", crudo).strip()
    if not norm:
        return CONFIRM, "comando vacío"
    # 0) ruido de shell fuera: 2>/dev/null NO es destruir un dispositivo.
    scan = _RUIDO_RE.sub(" ", norm)
    if _EJECUTA_REMOTO_RE.search(scan):
        # No cambia el nivel: solo dice que aqui no hay nada que verificar
        # (el codigo llega de la red), y eso le quita el automatismo del
        # acceso total. Ver (K).
        _apunte("descarga canalizada a un interprete: el codigo que se "
                "ejecutaria no esta en el comando", sensible=True)
    tokens = _sin_grupo(norm.split())
    if not tokens:
        return CONFIRM, "comando vacío"
    # Los parentesis de subexpresion de PowerShell son SINTAXIS, no parte
    # del nombre del comando: en la corrida e2e del 2026-08-25
    # `powershell -c "(Get-ChildItem ... | Measure-Object)"` daba head
    # '(get-childitem' -> "riesgo desconocido" y le costo un paso al
    # agente. Un payload destructivo entre parentesis sigue cazado por los
    # pasos 2-4, que miran la linea entera y no la cabeza.
    # El '@' de cmd solo silencia el eco de la linea (`@echo off` es la
    # primera linea de casi todo .bat): no forma parte del nombre del
    # comando. Desde que el contenido de un .bat pasa por el gate entero,
    # no quitarlo dejaba "forma no reconocida" -> CONFIRM en cada guion
    # inofensivo.
    head = tokens[0].strip("\"'(){}&").lstrip("@")
    # `... | Measure-Object).Count` -> el head es 'measure-object).count':
    # cortar en el parentesis de cierre deja el nombre real del cmdlet.
    # Acortar el head nunca abre un agujero: se compara igual contra la
    # tabla de cabezas DESTRUCTIVAS que contra la allowlist.
    if ")" in head:
        head = head.split(")")[0]
    if "/" in head or "\\" in head:
        head = re.split(r"[\\/]", head)[-1]
    if head.endswith(".exe"):
        head = head[:-4]

    # 0b) operador de llamada de PowerShell: `& "C:\...\cmd.exe" /c del X`.
    # El head salia vacio al quitarle el '&' y el comando entero caia en
    # "forma no reconocida" -> CONFIRM -> aprobado por acceso total.
    if tokens[0] in ("&", ".") and len(tokens) > 1 and _prof < 3:
        return clasificar_shell(" ".join(tokens[1:]), _prof + 1, _cwd_cd)

    # 1) envoltorio: clasificar el PAYLOAD (profundidad acotada a 3)
    if (head in _ENVOLTORIOS or head in _ENVOLTORIOS_DIRECTOS) and _prof < 3:
        dentro = _desenvolver(norm, tokens, head)
        if dentro:
            nivel, razon = clasificar_shell(dentro, _prof + 1, _cwd_cd)
            if nivel != ALLOW:
                return nivel, f"{razon} (dentro de '{head}')"
            return nivel, razon

    # 1b) lanzador con OTRO comando detras (`start cmd /c del <ruta>`)
    if head in _LANZADORES and _prof < 3:
        dentro = _tras_lanzador(tokens)
        if dentro:
            nivel, razon = clasificar_shell(dentro, _prof + 1, _cwd_cd)
            if nivel != ALLOW:
                return nivel, f"{razon} (lanzado con '{head}')"
            return nivel, razon

    # 2) bloqueo duro + 3) borrado en masa (ambos ganan a la allowlist)
    razon = _bloqueo_duro(scan)
    if razon:
        return BLOCK, razon

    # 3b) interprete con codigo EN LINEA: el borrado vive en el payload,
    # no en la cabeza (misma clase que el bug de `find ... -delete`).
    # Va ANTES del encadenamiento porque el payload lleva sus propios ';'
    # y el split lo troceaba en pedazos sin sentido.
    veredicto = _codigo_en_linea(head, tokens, _cwd_cd)
    if veredicto:
        return veredicto

    # 3c) el comando ES un fichero de script (`.\borra.bat`, `borra.ps1`
    # detras de `powershell -File`). Mismo agujero que 3b y por la misma
    # razon: el programa no esta en la linea. Las dos formas salian
    # "riesgo desconocido" -> CONFIRM -> aprobado por acceso total, y las
    # dos borraron las capturas del sandbox.
    script_limpio = False
    if tokens[0].strip("\"'").lower().endswith(_EXT_SCRIPT):
        veredicto = _clasificar_script(tokens[0], _cwd_cd, "el shell")
        if veredicto and veredicto[0] != ALLOW:
            return veredicto
        # Igual que en 3b: un script leido y limpio no puede cortar aqui
        # (se perderia una redireccion en la misma linea). Se anota y lo
        # cobra la allowlist del paso 7.
        script_limpio = bool(veredicto)

    # 4) modificadores destructivos de un objetivo
    for rx, plantilla, borra in _MOD_RE:
        if rx.search(scan):
            return _escalar(scan, plantilla, _cwd_cd, borra)
    # redirección que PISA un fichero: solo escala si el destino es una
    # ruta absoluta ajena/protegida (dentro del workspace escribir es el
    # trabajo normal del agente). `2>/dev/null` ya se neutralizó arriba.
    #
    # El `(?<![0-9])` de la version anterior existia para no leer el '2>&1'
    # como una sobrescritura, y de paso dejaba pasar TODA la redireccion
    # NUMERADA: `dir . 2>"<captura>.png"` y `1>"<captura>.png"` salian
    # ALLOW por el prefijo 'dir', y en sandbox truncaron el fichero de
    # 1.800 a 0 y a 708 bytes. El descriptor se consume ahora como parte
    # del operador (`\d?>`), y lo que se excluye es lo que de verdad no
    # escribe un fichero: `>&` (fusion de descriptores). `>>` (anexar)
    # entra tambien: no trunca, pero corrompe igual un .png.
    for m in re.finditer(r"(?<![&>])\d?>>?(?![&>])\s*"
                         r"(\"[^\"]+\"|'[^']+'|\S+)", scan):
        destino = _ambito_ruta(m.group(1), _cwd_cd)
        if destino:
            ajena = "fuera del" in destino
            nivel = CONFIRM if ajena else BLOCK
            _apunte(f"redirección que sobrescribe un fichero en {destino}",
                    # Un CONFIRM que pisa un fichero AJENO no lo puede
                    # aprobar solo el acceso total (ver (K)).
                    sensible=ajena)
            return nivel, ("redirección que sobrescribe un fichero en "
                           f"{_publica(destino)}")
        # El destino no lleva ruta (`2>"a.png"`): entonces cae en el
        # directorio de trabajo, y manda ESE -- misma regla que un
        # `del *.png` sin ruta, que es la que costo 60 .png del
        # Escritorio. Solo cuenta si el fichero YA EXISTE: crear uno
        # nuevo en la carpeta del dueno es "guardame esto en el
        # escritorio" y tiene que seguir pasando; PISAR uno que ya
        # estaba es destruir lo suyo.
        if _pisa_fichero_existente(m.group(1), _cwd_cd):
            nivel, razon = _escalar(scan, "redirección que sobrescribe un "
                                    "fichero que ya existe", _cwd_cd, True)
            if nivel == BLOCK:
                return nivel, razon

    # 5) encadenamiento oculto: un allow-prefix seguido de ; && | `$( puede
    # esconder algo peligroso en el 2º comando. Reclasificar a CONFIRM salvo
    # que TODOS los segmentos sean allow.
    # Se segmenta `scan` (el comando SIN el ruido de shell) y no `norm`:
    # el '&' de un `2>&1` no es un encadenamiento, pero el separador lo
    # partia igual y dejaba un segmento '1' -> "comando '1' de riesgo
    # desconocido". Medido: `pytest -q > informe.txt 2>&1` -- una linea
    # que el agente escribe a diario -- salia CONFIRM por eso.
    segmentos = _segmentar(scan)
    if len(segmentos) > 1:
        # El cwd se PROPAGA de izquierda a derecha: un `cd` a carpeta
        # protegida hace que los segmentos siguientes se clasifiquen como
        # si sus rutas relativas colgasen de ella (ver (A) en la
        # cabecera). Sin esto `cd <protegida> && del *` salia CONFIRM y el
        # acceso total lo ejecutaba: borro 3 capturas del dueno.
        peores, cwd_ef = [], _cwd_cd
        for s in segmentos:
            peores.append(clasificar_shell(s, _prof + 1, cwd_ef))
            cwd_ef = _cwd_tras_cd(s, cwd_ef)
        for nivel, razon in peores:
            if nivel == BLOCK:
                return BLOCK, f"un segmento encadenado es destructivo: {razon}"
        if all(n == ALLOW for n, _ in peores):
            return ALLOW, "todos los segmentos en la allowlist"
        pendiente = next((r for n, r in peores if n == CONFIRM), "")
        return CONFIRM, f"encadena un comando fuera de la allowlist: {pendiente}"

    # 6-) cabezas que SIEMPRE borran un arbol: mismo trato que el borrado
    # en masa (BLOCK), porque el conjunto lo decide el programa. Se mira la
    # CABEZA y no la linea entera a proposito: `npm install rimraf` es
    # instalar una dependencia y tiene que seguir en ALLOW; `rimraf <ruta>`
    # -- que es lo que salio del `npm run limpiar` de package.json -- no.
    if head in _HEADS_MASA:
        _apunte(f"'{head}' borra el arbol de destino entero")
        return BLOCK, f"borrado recursivo de un árbol ({head})"

    # 6) cabeza destructiva ANTES de la allowlist (el contenido manda)
    if head in _HEAD_DESTRUCTIVO:
        nivel, razon = _escalar(scan, _HEAD_DESTRUCTIVO[head], _cwd_cd,
                                head not in _HEADS_SIN_BORRADO_EN_BLOQUE)
        # 6a) COMODIN SOBRE CODIGO FUENTE (ver _GLOB_CODIGO_RE): la
        # escalada por ruta solo sabe decir DONDE borra, y dentro del
        # workspace afloja a proposito -> CONFIRM -> con acceso total, se
        # ejecuta solo. `del *.log` sigue en CONFIRM (es lo suyo); un
        # comodin sobre el codigo fuente, no.
        if nivel == CONFIRM and head in _HEADS_BORRAN:
            for t in tokens[1:]:
                limpio = t.strip("\"'")
                if limpio.startswith(("-", "/")):
                    continue
                if _GLOB_CODIGO_RE.search(limpio):
                    _apunte(f"{_HEAD_DESTRUCTIVO[head]} sobre el comodín "
                            f"'{limpio[:60]}': el conjunto lo decide el "
                            f"glob y son ficheros de código fuente")
                    return BLOCK, (f"{_HEAD_DESTRUCTIVO[head]}, sobre un "
                                   f"conjunto de ficheros de código fuente "
                                   f"decidido por un comodín")
        return nivel, razon

    # 6b) ESCRITORES: comandos cuyo trabajo normal es leer o descargar
    # pero que con un flag concreto PISAN el fichero de destino. Va antes
    # de la allowlist por la misma razon que el paso 6: 'curl', 'wget' y
    # 'certutil' estan en ella y el peligro vive en los ARGUMENTOS.
    if head in _HEAD_ESCRIBE:
        flag, razon = _HEAD_ESCRIBE[head]
        # Solo escala si el destino esta FUERA de su sitio, igual que la
        # redireccion `>`: escribir dentro del workspace es el trabajo
        # normal del agente y cobrarle un CONFIRM por cada
        # `curl -o build/x.json` seria el falso positivo de siempre.
        if ((flag is None or flag.search(scan)) and
                _ambito_ruta(scan, _cwd_cd)):
            return _escalar(scan, razon, _cwd_cd, False)

    # 7) allowlist por prefijo. El head puede ser una RUTA citada a un
    # ejecutable ("c:\...\python.exe" -m pytest ...) que arma el propio
    # Cognia (tool `tests`): ya se redujo al basename sin extensión arriba.
    # La inyección en los argumentos la cazan los pasos 2-5.
    if head in _ALLOW_PREFIXES:
        if head == "git" and len(tokens) > 1 and tokens[1] not in _GIT_SAFE_SUB:
            return CONFIRM, f"git {tokens[1]} no está en el set seguro"
        return ALLOW, f"prefijo '{head}' conocido-seguro"
    if script_limpio:
        return ALLOW, "script verificado: su contenido está limpio"
    # 8) desconocido → default-deny (confirmación)
    # El head se nombra solo si el token ORIGINAL ya era un nombre de
    # comando limpio. Cuando el comando es una expresion .NET
    # (`[system.io.file]::readalltext('C:\...\secreto.txt')`), el head sale
    # de quitarle parentesis/comillas y de cortar por la barra, o sea que
    # arrastra un trozo de la RUTA hasta la razon PUBLICA. Medido en dos
    # formas: "comando 'pictures',' de riesgo desconocido" y "comando
    # 'secreto.txt' de riesgo desconocido". Eso es re-inyectar el payload
    # en el contexto del modelo, justo lo que el resto de razones evita.
    # Mirar el token crudo (y no el head ya limpiado) es lo unico que
    # distingue `regedit` de un basename sacado de una ruta.
    if re.fullmatch(r"[\w.+-]{1,40}", tokens[0]):
        return CONFIRM, f"comando '{head}' de riesgo desconocido"
    return CONFIRM, "comando de forma no reconocida (riesgo desconocido)"


def clasificar_shell_detalle(cmd: str, cwd: str = None) -> tuple:
    """(nivel, razon_publica, detalle, alcance_no_verificable).

    Mismo veredicto que clasificar_shell, mas las dos cosas que NO pueden
    viajar en la razon publica:
      - `detalle`: la cita literal (que ruta caia fuera del directorio de
        trabajo, que un `cd`/cwd= puso el comando dentro de una carpeta
        personal, que patron de codigo se vio). Va al audit jsonl, que es
        quien tiene que poder reconstruir el incidente; al modelo no,
        porque describir la frontera con ese detalle es ensenar por donde
        se rodea (ver (L)).
      - el flag de alcance no verificable, que es lo que hace que
        COGNIA_ACCESO_TOTAL deje de auto-aprobar (ver (K))."""
    nivel, razon = clasificar_shell(cmd, _cwd_cd=(cwd or None))
    detalles = list(getattr(_TRAZA, "detalles", []) or [])
    b64 = _decodificar_b64(re.sub(r"\s+", " ", (cmd or "").strip()))
    if b64:
        detalles.append(f"-EncodedCommand descodificado: {b64[:200]}")
    return (nivel, razon, "; ".join(detalles),
            bool(getattr(_TRAZA, "sensible", False)))


def _audit(accion: str, cmd: str, veredicto: str, razon: str,
           detalle: str = "") -> None:
    """`detalle` es la CITA LITERAL que no viaja en la razon publica (que
    ruta caia fuera del directorio de trabajo, que `cd` movio el comando,
    el -EncodedCommand descodificado). El audit es su unico destino."""
    try:
        # UNA sola write() de la linea completa sobre O_APPEND, y la rotacion
        # DENTRO del mismo lock entre procesos (ver escribir_linea_jsonl).
        registro = {
            "ts": datetime.datetime.now().isoformat(timespec="seconds"),
            "accion": accion, "cmd": cmd[:300],
            "veredicto": veredicto, "razon": razon,
        }
        if detalle:
            registro["detalle"] = detalle[:600]
        linea = (json.dumps(registro, ensure_ascii=False) + "\n").encode(
            "utf-8")
        escribir_linea_jsonl(_AUDIT, linea, _ROTAR_BYTES)
    except Exception:
        pass


# ── la SALIDA, no solo la negativa (2026-08-25) ───────────────────────────
# El agravante de la perdida real fue que la razon publica ("ruta fuera del
# directorio de trabajo") le enseño al modelo COMO evadir: en la traza razona
# la evasion y la ejecuta. Un "no" sin salida empuja a buscar el rodeo. Aqui
# la salida existe y ademas es la buena: `borrar_archivo` manda a la papelera
# de Cognia (harness/papelera), escribe el inventario antes de tocar nada y
# tiene tope de volumen, o sea que lo que el shell hace irreversible por esa
# puerta es reversible. Un borrado por shell NO se puede interceptar desde
# Python — por eso lo unico que se puede hacer es nombrar la puerta buena.
_RAZON_BORRA_RE = re.compile(r"borrad|borra\b|borrar|eliminaci|vaciado", re.I)


def _pista_papelera(razon: str) -> str:
    """Una frase extra cuando lo frenado era un BORRADO: la via reversible.

    Vacia para todo lo demas (apagar el equipo, formatear, un force-push):
    ahi `borrar_archivo` no es alternativa de nada y seria ruido."""
    if not _RAZON_BORRA_RE.search(razon or ""):
        return ""
    return (" Si de verdad hay que quitar ficheros, usa la tool "
            "borrar_archivo: manda a la papelera de Cognia (reversible con "
            "/deshacer-borrado) en vez de destruir, y por encima de "
            "10 ficheros lo confirma el dueño.")


def evaluar_shell(cmd: str, ctx: dict = None, cwd: str = "") -> tuple:
    """Compuerta pre-ejecución de un comando de shell.
    Devuelve (permitido: bool, mensaje_o_None). No ejecuta nada.
    Si Sentinel está OFF, replica la denylist previa (no rompe nada).

    `cwd` es el directorio en el que el llamador va a LANZAR el comando (el
    parametro cwd= de la tool `ejecutar`). Sin el, el gate clasificaba
    `del *.png` en el vacio y devolvia CONFIRM aunque el proceso fuese a
    arrancar dentro de ~/Pictures/Screenshots: el mismo escape que
    `cd <protegida> && del *.png`, pero por la puerta oficial y sin
    friccion. Verificado contra un directorio temporal: borraba los 3
    ficheros y devolvia "(sin output)".

    Con COGNIA_SENTINEL=0 el cwd se ignora a proposito: ese modo replica la
    denylist vieja tal cual, y ahi no habia escalada por ruta que ampliar."""
    ctx = ctx or {}
    if not sentinel_enabled():
        # Misma funcion de bloqueo duro que clasificar_shell (antes eran DOS
        # copias del mismo `any(...)`: el arreglo de 2026-08-25 habria que
        # haberlo hecho dos veces y una se olvida). Incluye el borrado en
        # masa, que con el centinela apagado es lo unico que queda.
        if _bloqueo_duro(_RUIDO_RE.sub(" ", re.sub(r"\s+", " ",
                                                   (cmd or "").lower()))):
            return False, "RESULTADO ejecutar: BLOQUEADO por seguridad"
        return True, None

    nivel, razon, detalle, sin_verificar = clasificar_shell_detalle(cmd, cwd)
    _audit("shell", (f"[cwd={cwd}] {cmd}" if cwd else cmd), nivel, razon,
           detalle)
    try:
        from cognia.events import emit
        emit("sentinel.evaluada", accion="shell", veredicto=nivel,
             razon=razon, cmd_head=(cmd or "")[:80])
    except Exception:
        pass

    if nivel == ALLOW:
        return True, None
    if nivel == BLOCK:
        return False, (f"RESULTADO ejecutar: BLOQUEADO por Sentinel "
                       f"({razon}). Acción destructiva irreversible."
                       + _pista_papelera(razon))
    # ── CONFIRM ──────────────────────────────────────────────────────
    # ACCESO TOTAL ACOTADO (ver (K) en la cabecera). El 2026-08-25 un
    # agente con COGNIA_ACCESO_TOTAL=1 borro 3 capturas del dueno por esta
    # puerta exacta: el comando salio CONFIRM y estas dos lineas lo
    # aprobaron solas, sin canal humano y sin que nadie lo viera hasta
    # despues. El modo sigue existiendo (el dueno lo pidio para operar SU
    # maquina desde el control remoto) pero ya no cubre TODO: un CONFIRM
    # destructivo cuyo ALCANCE no se pudo verificar -- el `cd` va a una
    # variable, el directorio no existe, la redireccion pisa un fichero
    # ajeno -- exige confirmacion humana real. Lo destructivo sobre una
    # carpeta personal o sobre una ruta ajena ya no llega aqui: es BLOCK,
    # y el acceso total NO levanta un BLOCK (la rama de arriba retorna
    # antes de mirar el flag; hay test que lo fija).
    if (_autonomous() or _acceso_total()) and not sin_verificar:
        return True, None            # procede pero YA quedó auditado
    confirm = ctx.get("confirm")
    if callable(confirm):
        try:
            if confirm("ejecutar comando", cmd):
                return True, None
        except Exception:
            pass
        return False, (f"RESULTADO ejecutar: no confirmado por el usuario "
                       f"({razon})." + _pista_papelera(razon))
    # sin canal de confirmación y no-autónomo → denegar (default-deny)
    if sin_verificar:
        # Aqui NO se nombra COGNIA_AUTONOMOUS: en este caso el flag ya no
        # lo levanta, y sugerirlo seria repetir el fallo de ensenar el
        # rodeo. Lo que se pide es lo unico que vale: escribir el comando
        # de forma que se pueda comprobar donde actua.
        return False, (f"RESULTADO ejecutar: requiere confirmación del "
                       f"dueño ({razon}). No se puede comprobar sobre qué "
                       f"carpeta actuaría este comando."
                       + _pista_papelera(razon))
    return False, (f"RESULTADO ejecutar: requiere confirmación ({razon}). "
                   f"Sin canal de confirmación disponible; para permitir "
                   f"comandos de riesgo desconocido en modo desatendido, "
                   f"COGNIA_AUTONOMOUS=1." + _pista_papelera(razon))


# ══════════════════════════════════════════════════════════════════════
# Centinela WEB — contenido de páginas ANTES de que llegue al modelo
# (mandato 2026-08-01: el navegador del agente descarta resultados
# envenenados o fuera de tema y sigue buscando; nunca en silencio).
# Determinista, cero LLM, como clasificar_shell: un juez LLM aquí
# repetiría el cuelgue de "juez-colgado-js-bloqueante" y además el
# contenido hostil podría inyectarse en el propio juez.
# ══════════════════════════════════════════════════════════════════════

# Invisibles/bidi: los usan para esconder instrucciones al ojo humano y
# para partir palabras y evadir matcheo por substring. Se cuentan ANTES
# de normalizar y se quitan ANTES de matchear patrones.
_WEB_INVISIBLES = re.compile(
    "[\u200b-\u200f\u2060\ufeff\u202a-\u202e\u2066-\u2069]")

# Patrones de inyección (ES+EN) sobre texto ya normalizado (minúsculas,
# sin invisibles, espacios colapsados). Substrings para lo literal,
# regex para lo que flexiona.
_WEB_INJ_SUB = [
    "<|im_start|>", "<|system|>", "<<sys>>", "[inst]", "### instruction",
    "### system", "you are now", "pretend you are", "jailbreak",
    "developer mode enabled", "do not tell the user", "no le digas al usuario",
    "hidden instruction", "instruccion oculta", "instrucción oculta",
]
_WEB_INJ_RE = [
    re.compile(r"ignor\w*\s+(?:all\s+|any\s+)?(?:previous|prior|above|earlier)"
               r"\s+(?:instruction|prompt|rule|direction)", re.I),
    re.compile(r"ignora\w*\s+(?:todas?\s+)?(?:las?\s+)?(?:instrucciones|reglas|"
               r"indicaciones)\s+(?:anteriores|previas|del sistema)", re.I),
    re.compile(r"(?:disregard|forget|override)\s+(?:all\s+)?(?:your|previous|"
               r"the)\s+(?:instructions?|prompts?|rules?)", re.I),
    re.compile(r"olvida\s+(?:todas?\s+)?(?:tus|las)\s+(?:instrucciones|reglas)",
               re.I),
    re.compile(r"(?:system|assistant)\s*prompt", re.I),
    re.compile(r"prompt\s+del?\s+sistema", re.I),
    re.compile(r"(?:new|nuevas?)\s+(?:instructions?|instrucciones)\s*:", re.I),
    # exfiltración: pedir claves/tokens o mandarlos a otro sitio
    re.compile(r"(?:reveal|print|send|share|leak)\s+.{0,40}(?:api\s*key|"
               r"password|secret|token|credential)", re.I),
    re.compile(r"(?:env[ií]a|manda|comparte|filtra|exfiltra)\s+.{0,40}"
               r"(?:clave|token|contrase|secreto|credencial)", re.I),
    # imita la gramática ReAct de Cognia ("ACCION: <tool> <args>"): una
    # página legítima no tiene por qué traer líneas de acción del agente.
    re.compile(r"^\s*ACCION\s*:\s*\w+", re.M),
]

# Stopwords mínimas para la relevancia (no exhaustivo a propósito: solo
# quitar conectores que inflarían el denominador).
_WEB_STOP = {
    "para", "como", "cómo", "sobre", "entre", "donde", "dónde", "cuando",
    "cuándo", "cual", "cuál", "esta", "este", "esto", "with", "from",
    "what", "when", "where", "which", "that", "this", "does", "tiene",
    "hace", "mejor", "best",
}


def _sin_acentos(t: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", t)
                   if unicodedata.category(c) != "Mn")


def sanear_texto_web(texto: str) -> str:
    """Texto web listo para el modelo: sin invisibles/bidi, espacios
    colapsados por línea (se preservan los saltos), acentos INTACTOS."""
    texto = _WEB_INVISIBLES.sub("", texto or "")
    lineas = [re.sub(r"[ \t]+", " ", ln).strip() for ln in texto.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lineas)).strip()


def evaluar_contenido_web(texto: str, tema: str = None,
                          fuente: str = "") -> tuple:
    """(nivel, razon) para TEXTO extraído de la web, antes del modelo.

    BLOCK si huele a inyección de prompt (patrones ES/EN, gramática ACCION
    del agente, exceso de invisibles) o si no tiene relación con `tema`.
    ALLOW en el resto. Audita cada veredicto (accion='web') en el mismo
    jsonl que los comandos de shell y lo publica en el bus (evento
    'sentinel.evaluada', como evaluar_shell) para que el panel de analytics
    lo cuente. Determinista: mismo texto, mismo veredicto."""

    def _veredicto(nivel, razon_audit, razon_publica=None):
        # razon_publica: la que ve el modelo/el bus. En inyecciones es
        # GENÉRICA a propósito — citar el texto que casó re-inyectaría el
        # payload (misma regla que el mensaje de bloqueo del navegador);
        # la cita exacta va SOLO a la auditoría jsonl.
        razon = razon_publica or razon_audit
        _audit("web", fuente, nivel, razon_audit)
        try:
            from cognia.events import emit
            emit("sentinel.evaluada", accion="web", veredicto=nivel,
                 razon=razon, fuente=(fuente or "")[:120])
        except Exception:
            pass
        return nivel, razon

    crudo = texto or ""
    if not crudo.strip():
        return _veredicto(BLOCK, "página sin texto extraíble")

    n_invis = len(_WEB_INVISIBLES.findall(crudo))
    # >5: los invisibles sueltos existen en páginas legítimas (emoji ZWJ,
    # marcas RTL); decenas seguidas solo las he visto escondiendo texto.
    if n_invis > 5:
        return _veredicto(BLOCK,
                          f"exceso de caracteres invisibles/bidi ({n_invis})")

    # La razón devuelta es GENÉRICA a propósito: citar el texto que casó
    # re-inyectaría el payload en el contexto del modelo vía el mensaje de
    # bloqueo (lo cazó test_tool_web_abrir_bloqueado). La cita exacta va
    # SOLO a la auditoría.
    norm = re.sub(r"[ \t]+", " ", _WEB_INVISIBLES.sub("", crudo).lower())
    for s in _WEB_INJ_SUB:
        if s in norm:
            return _veredicto(BLOCK, f"patrón de inyección: '{s}'",
                              "patrón de inyección de prompt detectado")
    for rx in _WEB_INJ_RE:
        m = rx.search(_WEB_INVISIBLES.sub("", crudo))
        if m:
            return _veredicto(BLOCK,
                              f"patrón de inyección: '{m.group(0)[:60]}'",
                              "patrón de inyección de prompt detectado")

    if tema:
        base = _sin_acentos(tema.lower())
        palabras = [w for w in re.findall(r"[a-z0-9]{4,}", base)
                    if w not in {_sin_acentos(s) for s in _WEB_STOP}]
        if palabras:
            cuerpo = _sin_acentos(norm)
            hits = sum(1 for w in palabras if w in cuerpo)
            necesarios = max(1, round(0.2 * len(palabras)))
            if hits < necesarios:
                return _veredicto(
                    BLOCK, f"irrelevante para '{tema}': {hits}/{len(palabras)} "
                           f"palabras clave presentes")

    return _veredicto(ALLOW, "contenido limpio y en tema")
