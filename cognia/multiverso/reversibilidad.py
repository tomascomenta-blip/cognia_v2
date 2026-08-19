# -*- coding: utf-8 -*-
"""CATASTRO DE EFECTOS: clasifica cada accion del agente por REVERSIBILIDAD.

QUE RESUELVE
    Responde, para una accion concreta (tool + argumentos), cuatro cosas: en
    que cubo cae ('puro' / 'reversible' / 'irreversible' / 'desconocido'), con
    QUE compensacion concreta se deshace si es reversible, POR QUE se decidio
    asi y con cuanta confianza. Y mide, sobre trazas reales, que FRACCION del
    trabajo del agente cae en cada cubo.

POR QUE EXISTE
    Los harnesses de hoy autorizan por TIPO DE HERRAMIENTA ("permito Bash?")
    cuando la pregunta que decide todo es "esto se puede deshacer, con que
    mecanismo y en cuanto tiempo?". Sin ese catastro no se puede: (a) ejecutar
    especulativamente lo puro sin pedir permiso, (b) ramificar y quedarse con
    la mejor rama compensando las otras (patron saga), (c) saber si ramificar
    es siquiera viable -- lo que depende de la fraccion IRREVERSIBLE, un numero
    que nadie habia publicado porque nadie habia clasificado trazas reales.
    Ademas: 'ejecutar' es de las tools mas llamadas del repo (3.486 llamadas de
    86.069 en _tool_usage.json) y su cubo NO se decide por el nombre -- `ls` y
    `rm -rf` son la MISMA tool. De ahi el analizador de linea de comandos.

EVIDENCIA (MEDIDA en esta maquina el 2026-08-19 con
`python -m cognia.multiverso.medir`, que se puede re-correr; los conteos se
guardan en cognia/multiverso/medicion_reversibilidad.json)
    Fuente A -- trazas con ARGUMENTOS reales (~/.cognia/data/tareas/*/
    bitacora.jsonl, eventos ToolInicio de tres tareas de agente), n = 20:
        puro          4   20.00%
        reversible    7   35.00%
        irreversible  0    0.00%
        desconocido   9   45.00%
      'ejecutar' aparece 11 veces y REPARTE: 2 puras (`which python`) y 9
      desconocidas (todas `python <script>.py`: codigo arbitrario, no hay
      forma honesta de decidirlo sin ejecutarlo). Ese reparto es la prueba
      de que clasificar por nombre de tool no sirve.
    Fuente B -- agregado por nombre de tool, SIN argumentos
    (cognia/agent/generated_tools/_tool_usage.json; es un fichero VIVO, el n
    crece con cada corrida del agente), n = 86.456 llamadas de 103 tools:
        puro         22.501   26.03%
        reversible   50.045   57.88%
        irreversible  6.322    7.31%
        desconocido   7.588    8.78%
      De ese 8.78% desconocido, 3.585 llamadas (4.15 puntos) son 'ejecutar'
      SIN argumentos guardados: indecidibles por nombre -> caen a
      'desconocido' por la regla de fallar seguro. Ese es el coste MEDIDO de
      no instrumentar los argumentos en la telemetria agregada.
    Fuente C -- mutaciones de fichero YA ocurridas (~/.cognia/checkpoints/*/
    indice.jsonl), n = 413: 100% reversible (escribir/apendar/editar/borrar
    _archivo). Es un sesgo del instrumento y hay que decirlo: ese indice solo
    registra operaciones de fichero, que son justo las compensables.
    LECTURA: un cuarto del trabajo es especulable sin pedir permiso; la mitad
    larga es compensable; lo verdaderamente irreversible es un digito (7.31%).
    Ramificar es viable. Lo caro no es deshacer: es DECIDIR -- el cubo
    'desconocido' (8.78% agregado, 45% con args reales) es lo que hay que
    reducir, y se reduce guardando los argumentos y analizando el comando.

LIMITES DECLARADOS
    - Esto es un CATASTRO, no un sandbox: clasificar 'reversible' no deshace
      nada. La compensacion solo existe si `registrar_efecto` corrio ANTES.
    - La tabla de comandos es una allowlist honesta, no un analizador
      semantico: lo que no esta cae a 'desconocido' A PROPOSITO. NUNCA se
      devuelve 'puro' por defecto.
    - `python script.py`, `tests`, `delegar_subtarea` y todo lo que ejecuta
      codigo arbitrario son 'desconocido' por construccion.
    - Windows/NTFS, solo stdlib. No hay papelera ni snapshots de FS:
      'reversible' significa "tengo el contenido previo guardado", no "el
      sistema operativo lo deshace".
    - Un GET (curl/http_get) se clasifica 'puro' ASUMIENDO que el servidor no
      muta. Es una asuncion, va con confianza baja y aqui queda escrita.
"""

import base64
import hashlib
import json
import os
import re
import shlex
import subprocess
import time
from pathlib import Path

CUBOS = ("puro", "reversible", "irreversible", "desconocido")

# Orden de severidad: al combinar varios efectos (un pipeline, varios
# segmentos) MANDA el peor. 'desconocido' pesa mas que 'reversible' porque no
# saber que paso es peor que saber como deshacerlo.
_SEVERIDAD = {"puro": 0, "reversible": 1, "desconocido": 2, "irreversible": 3}

# Tope para capturar el contenido previo de un fichero. Por encima se DEGRADA
# a 'irreversible en la practica' y se dice: copiar 500 MB en cada escritura
# convierte el catastro en el cuello de botella del agente.
TOPE_BYTES = int(os.environ.get("COGNIA_MULTIVERSO_TOPE_BYTES",
                                str(5 * 1024 * 1024)))

# ---------------------------------------------------------------------------
# TABLAS POR NOMBRE DE TOOL (registry de cognia/agent/tools.py, 2026-08-19)
# ---------------------------------------------------------------------------

# PURAS: leen/consultan/calculan. No tocan el mundo -> especulables sin permiso.
TOOLS_PURAS = {
    "leer_archivo", "leer_lote", "listar", "arbol", "contar_lineas", "buscar",
    "buscar_ficheros", "buscar_en_repo", "repo_map", "code_grafo", "code_wiki",
    "docs_repo", "docs_libreria", "preguntar_repo", "repo_a_prompt",
    "calcular", "fecha", "resumir", "plan", "contratos",
    "git_estado", "git_diff", "git_log",
    "py_validar", "json_validar",
    "notas", "recordar", "kg_buscar", "bitacora_buscar", "tarea_estado",
    "ver_salida", "procesos",
    "ctx_ver", "ctx_grep", "ctx_info", "ctx_partir", "rlm_llamar",
    "escena_consultar", "web_buscar", "http_get",
}

# REVERSIBLES: tienen una compensacion CONCRETA que `compensar` sabe ejecutar.
# Si no hay compensacion implementable, la accion NO se llama reversible aqui.
TOOLS_REVERSIBLES = {
    "escribir_archivo": ("restaurar_fichero", "el contenido previo se restaura tal cual"),
    "editar_archivo": ("restaurar_fichero", "el contenido previo se restaura tal cual"),
    "apendar_archivo": ("restaurar_fichero", "se restaura el contenido previo"),
    "generar_codigo": ("restaurar_fichero", "escribe un .py: se restaura el previo"),
    "copiar_archivo": ("restaurar_fichero", "el destino vuelve a su estado previo"),
    "mover_archivo": ("mover_de_vuelta", "se mueve el destino de vuelta al origen"),
    "crear_directorio": ("borrar_si_vacio", "se borra el directorio si quedo vacio"),
    "borrar_archivo": ("restaurar_fichero", "SOLO si registrar_efecto capturo el contenido"),
    "git_add": ("comando", "git reset HEAD -- <ruta>"),
    "git_commit": ("comando", "git reset --soft HEAD~1"),
    "git_stash": ("comando", "git stash pop"),
    "git_branch": ("comando", "git checkout - (y git branch -D si se creo)"),
    "crear_herramienta": ("comando", "revertir_herramienta <nombre> <version>"),
    "revertir_herramienta": ("comando", "es en si una compensacion: se rehace re-creando"),
    "escena_crear": ("comando", "escena_deshacer"),
    "escena_agregar": ("comando", "escena_deshacer"),
    "escena_quitar": ("comando", "escena_deshacer"),
    "escena_mover": ("comando", "escena_deshacer"),
    "escena_editar": ("comando", "escena_deshacer"),
    "escena_duplicar": ("comando", "escena_deshacer"),
    "escena_rotar": ("comando", "escena_deshacer"),
    "escena_escalar": ("comando", "escena_deshacer"),
    "escena_material": ("comando", "escena_deshacer"),
    "escena_luz": ("comando", "escena_deshacer"),
    "escena_forma": ("comando", "escena_deshacer"),
    "escena_camara": ("comando", "escena_deshacer"),
    "escena_fondo": ("comando", "escena_deshacer"),
    "escena_capa": ("comando", "escena_deshacer"),
    "escena_fisica": ("comando", "escena_deshacer"),
    "escena_alinear": ("comando", "escena_deshacer"),
    "escena_array": ("comando", "escena_deshacer"),
    "escena_distribuir": ("comando", "escena_deshacer"),
    "escena_relacionar": ("comando", "escena_deshacer"),
    "escena_subdividir": ("comando", "escena_deshacer"),
    "escena_suavizar": ("comando", "escena_deshacer"),
    "escena_biselar": ("comando", "escena_deshacer"),
    "escena_vertices": ("comando", "escena_deshacer"),
    "escena_poligono": ("comando", "escena_deshacer"),
    "escena_plantilla": ("comando", "escena_deshacer"),
    "escena_importar": ("comando", "escena_deshacer"),
    "escena_deshacer": ("comando", "escena_rehacer"),
    "escena_rehacer": ("comando", "escena_deshacer"),
}

# IRREVERSIBLES: no tengo inversa. Incluye lo que escribe memoria persistente
# sin borrado expuesto -- llamar 'reversible' a eso seria mentir.
TOOLS_IRREVERSIBLES = {
    "abrir": "abre una URL/app en la maquina del dueno: no hay 'des-abrir'",
    "matar_proceso": "un proceso muerto no se resucita con su estado",
    "memorizar": "memoria episodica persistente sin borrado expuesto",
    "kg_agregar": "agrega un hecho al grafo: no existe kg_quitar",
    "anotar": "escribe memoria de trabajo sin inversa expuesta",
    "cuaderno": "ingesta al cuaderno/RAG sin borrado expuesto",
    "escena_exportar": "escribe fuera del workspace de escena",
    "imagen_generar": "consume hardware/presupuesto y escribe assets",
    "pantalla_click": "un click en la maquina del dueno no se deshace",
    "gritar": "notificacion ya entregada",
}

# DESCONOCIDAS por construccion: ejecutan codigo arbitrario o delegan.
TOOLS_DESCONOCIDAS = {
    "ejecutar": "el cubo depende del COMANDO, no de la tool",
    "ejecutar_fondo": "lanza un proceso vivo: sus efectos ocurren DESPUES",
    "tests": "pytest corre codigo arbitrario del repo (fixtures que escriben)",
    "delegar_subtarea": "un sub-agente con sus propias tools y efectos",
    "ejecutar_flujo": "corre un flujo de nodos con efectos propios",
    "reejecutar_etapa": "re-ejecuta una etapa con sus efectos",
    "crear_flujo": "define y puede disparar efectos de terceros",
    "pantalla_captura": "toca el escritorio del dueno",
    "pantalla_localizar": "toca el escritorio del dueno",
    "web_abrir": "navegador real: cookies, sesiones, formularios",
    "atribuir_fallo": "no esta en el catastro con certeza",
    "render_aprox": "renderiza y puede escribir salidas",
}

# ---------------------------------------------------------------------------
# TABLAS DE COMANDOS (para 'ejecutar' y cualquier shell)
# ---------------------------------------------------------------------------

# Comandos PUROS incondicionales (leen, listan, calculan, imprimen).
CMD_PUROS = {
    "ls", "dir", "cat", "type", "head", "tail", "more", "less", "wc", "sort",
    "uniq", "echo", "pwd", "cd", "tree", "stat", "file", "du", "df", "which",
    "where", "whoami", "hostname", "date", "env", "printenv", "basename",
    "dirname", "realpath", "readlink", "nproc", "uname", "ver", "systeminfo",
    "tasklist", "ps", "netstat", "ipconfig", "ifconfig", "grep", "rg", "ag",
    "findstr", "diff", "cmp", "md5sum", "sha256sum", "jq", "true", "false",
    "seq", "man", "help", "get-content", "get-childitem", "get-location",
    "get-process", "measure-object", "select-string", "select-object",
    "where-object", "test-path", "gc", "gci", "nvidia-smi",
}

# Comandos REVERSIBLES con compensacion concreta.
CMD_REVERSIBLES = {
    "mkdir": ("borrar_si_vacio", "rmdir del directorio creado"),
    "md": ("borrar_si_vacio", "rmdir del directorio creado"),
    "touch": ("restaurar_fichero", "borrar si no existia antes"),
    "cp": ("restaurar_fichero", "restaurar/borrar el destino"),
    "copy": ("restaurar_fichero", "restaurar/borrar el destino"),
    "copy-item": ("restaurar_fichero", "restaurar/borrar el destino"),
    "mv": ("mover_de_vuelta", "mover el destino de vuelta al origen"),
    "move": ("mover_de_vuelta", "mover el destino de vuelta al origen"),
    "move-item": ("mover_de_vuelta", "mover el destino de vuelta al origen"),
    "ren": ("mover_de_vuelta", "renombrar de vuelta"),
    "rename": ("mover_de_vuelta", "renombrar de vuelta"),
}

# Verbos IRREVERSIBLES: si aparecen, no hay vuelta atras.
CMD_IRREVERSIBLES = {
    "rm": "borrado sin papelera",
    "del": "borrado sin papelera",
    "erase": "borrado sin papelera",
    "rmdir": "borra un arbol de directorios",
    "rd": "borra un arbol de directorios",
    "remove-item": "borrado sin papelera",
    "shred": "sobreescribe el contenido",
    "sdelete": "sobreescribe el contenido",
    "format": "formatea un volumen",
    "mkfs": "formatea un volumen",
    "diskpart": "reparticiona discos",
    "dd": "escribe a bajo nivel",
    "shutdown": "apaga la maquina",
    "reboot": "reinicia la maquina",
    "restart-computer": "reinicia la maquina",
    "poweroff": "apaga la maquina",
    "halt": "apaga la maquina",
    "taskkill": "mata procesos ajenos",
    "kill": "mata procesos ajenos",
    "pkill": "mata procesos ajenos",
    "killall": "mata procesos ajenos",
    "stop-process": "mata procesos ajenos",
    "stop-computer": "apaga la maquina",
    "mail": "correo enviado: no se des-envia",
    "sendmail": "correo enviado: no se des-envia",
    "msmtp": "correo enviado: no se des-envia",
    "ssh": "ejecuta en OTRA maquina, fuera de todo sandbox",
    "scp": "copia a OTRA maquina",
    "rsync": "sincroniza contra otra maquina/ruta",
    "twine": "publica un paquete",
    "reg": "toca el registro de Windows",
    "regedit": "toca el registro de Windows",
    "bcdedit": "toca el arranque del sistema",
    "netsh": "reconfigura la red",
    "sc": "toca servicios de Windows",
    "schtasks": "toca tareas programadas del sistema",
    "icacls": "cambia ACLs sin snapshot previo",
    "takeown": "cambia el dueno de ficheros",
    "chkdsk": "puede reparar/mover datos del volumen",
    "cipher": "sobreescribe espacio libre",
    "at": "programa ejecuciones futuras",
    "crontab": "programa ejecuciones futuras",
}

# Sub-comandos: (verbo, segundo token).
SUB_PUROS = {
    ("git", "status"), ("git", "diff"), ("git", "log"), ("git", "show"),
    ("git", "blame"), ("git", "ls-files"), ("git", "rev-parse"),
    ("git", "describe"), ("git", "shortlog"), ("git", "cat-file"),
    ("git", "grep"), ("git", "whatchanged"),
    ("pip", "list"), ("pip", "show"), ("pip", "freeze"),
    ("npm", "ls"), ("npm", "view"), ("npm", "outdated"),
    ("docker", "ps"), ("docker", "images"), ("docker", "logs"),
    ("cargo", "check"), ("go", "vet"),
}
SUB_REVERSIBLES = {
    ("git", "add"): ("comando", "git reset HEAD"),
    ("git", "commit"): ("comando", "git reset --soft HEAD~1"),
    ("git", "stash"): ("comando", "git stash pop"),
    ("git", "tag"): ("comando", "git tag -d"),
    ("git", "mv"): ("mover_de_vuelta", "git mv de vuelta"),
    ("git", "branch"): ("comando", "git branch -D"),
    ("git", "checkout"): ("comando", "git checkout -"),
    ("git", "switch"): ("comando", "git switch -"),
    ("git", "init"): ("comando", "borrar el .git recien creado"),
}
SUB_IRREVERSIBLES = {
    ("git", "push"): "el push ya esta en el remoto: nadie lo deshace por ti",
    ("git", "clean"): "borra ficheros no rastreados sin copia",
    ("git", "rebase"): "reescribe historia",
    ("git", "filter-branch"): "reescribe historia",
    ("git", "gc"): "poda objetos inalcanzables",
    ("git", "remote"): "cambia el remoto configurado",
    ("pip", "install"): "muta el entorno de Python (o el del sistema)",
    ("pip", "uninstall"): "desinstala paquetes",
    ("npm", "publish"): "publica al registro publico",
    ("npm", "install"): "muta node_modules y lockfiles",
    ("cargo", "publish"): "publica al registro publico",
    ("docker", "rm"): "borra contenedores",
    ("docker", "rmi"): "borra imagenes",
    ("docker", "push"): "publica al registro",
    ("docker", "system"): "prune borra sin vuelta",
    ("kubectl", "delete"): "borra recursos del cluster",
    ("kubectl", "apply"): "muta el cluster",
    ("aws", "s3"): "muta un bucket remoto",
    ("gcloud", "compute"): "muta infraestructura remota",
    ("az", "vm"): "muta infraestructura remota",
    ("systemctl", "stop"): "para servicios del sistema",
    ("net", "user"): "toca cuentas de Windows",
}

# Patrones que condenan la linea entera aunque el verbo parezca inocente.
_FLAGS_IRREVERSIBLES = (
    (r"\bgit\b[^|;&]*\breset\b[^|;&]*--hard", "git reset --hard tira el trabajo sin commitear"),
    (r"\bgit\b[^|;&]*\bpush\b", "push al remoto"),
    (r"\bgit\b[^|;&]*\bcheckout\b\s+--\s", "git checkout -- descarta cambios locales"),
    (r"-X\s*['\"]?(POST|PUT|DELETE|PATCH)", "peticion HTTP mutante"),
    (r"\bcurl\b[^|;&]*\s(-d|--data|--data-raw|-F|--form|--upload-file|-T)\b",
     "curl con cuerpo: es un POST"),
    (r"\bwget\b[^|;&]*--post", "wget con POST"),
    (r"\bInvoke-(WebRequest|RestMethod)\b[^|;&]*-Method\s*(Post|Put|Delete|Patch)",
     "peticion HTTP mutante"),
    (r"\bnpm\b\s+publish\b", "publica al registro publico"),
)

# Banderas destructivas: solo condenan si el VERBO ya muta algo (grep -f no es
# 'force'). Se comprueban aparte, despues de decidir el verbo.
_RE_BANDERA_DESTRUCTIVA = re.compile(
    r"(--force\b|--hard\b|\s/f\b|\s/q\b|\s/s\b|-rf\b|-fr\b|--no-preserve-root)", re.I)


def _norm_cmd(tok):
    """Nombre canonico de un ejecutable: sin ruta, sin .exe, en minusculas."""
    t = (tok or "").strip().strip('"').strip("'")
    t = t.replace("\\", "/").rsplit("/", 1)[-1]
    t = t.lower()
    for ext in (".exe", ".cmd", ".bat", ".ps1"):
        if t.endswith(ext):
            t = t[: -len(ext)]
    return t


def _tokenizar(seg):
    """Tokeniza respetando comillas. shlex posix rompe rutas de Windows."""
    try:
        return shlex.split(seg, posix=False)
    except Exception:
        return seg.split()


def _dividir(cmd):
    """Parte una linea en segmentos por &&, ||, |, ;, & respetando comillas.

    Un pipeline son varios comandos y TODOS cuentan: `ls | rm -rf .` es
    irreversible aunque empiece por un comando puro.
    """
    segs, actual, comilla, i = [], [], "", 0
    while i < len(cmd):
        c = cmd[i]
        if comilla:
            actual.append(c)
            if c == comilla:
                comilla = ""
            i += 1
            continue
        if c in "\"'":
            comilla = c
            actual.append(c)
            i += 1
            continue
        if cmd[i:i + 2] in ("&&", "||"):
            segs.append("".join(actual))
            actual = []
            i += 2
            continue
        if c in ";|&\n":
            segs.append("".join(actual))
            actual = []
            i += 1
            continue
        actual.append(c)
        i += 1
    segs.append("".join(actual))
    return [s.strip() for s in segs if s.strip()]


_RE_REDIR = re.compile(r"(?<![0-9])>>?\s*([^\s;|&]+)")


def _redireccion(seg):
    """Ruta de una redireccion a fichero, o '' si no hay o va a un nulo."""
    sin_comillas = re.sub(r"\"[^\"]*\"|'[^']*'", " ", seg)
    m = _RE_REDIR.search(sin_comillas)
    if not m:
        return ""
    destino = m.group(1).strip()
    if destino.lower() in ("nul", "/dev/null", "$null", "&1", "&2"):
        return ""
    return destino


def _clasificar_python_inline(seg):
    """`python -c "..."`: se mira el CODIGO, no el interprete."""
    if re.search(r"shutil\.rmtree|os\.remove|os\.unlink|os\.rmdir", seg):
        return ("irreversible", "", "python -c borra ficheros/arboles")
    if re.search(r"requests\.(post|put|delete)|urlopen\([^)]*data=", seg):
        return ("irreversible", "", "python -c hace una peticion mutante")
    if re.search(r"subprocess|os\.system|os\.exec", seg):
        return ("desconocido", "", "python -c lanza otro proceso: efectos no analizables")
    if re.search(r"open\s*\([^)]*['\"][wax]", seg):
        return ("reversible", "restaurar_fichero",
                "python -c abre un fichero en modo escritura")
    if re.search(r"\bimport\s+os\b.*\bos\.\w+", seg) and not re.search(
            r"os\.(listdir|path|getcwd|environ|walk|stat|sep)", seg):
        return ("desconocido", "", "python -c usa os.* fuera de lo consultivo")
    return ("puro", "", "python -c sin escrituras ni red detectadas")


# Envoltorios que NO deciden nada: lo que manda es el comando que envuelven.
# `xargs rm -rf` es un borrado, no un 'xargs' (bug cazado por el test del
# pipeline: sin esto salia 'desconocido' en vez de 'irreversible').
_ENVOLTORIOS = {"xargs", "nohup", "time", "sudo", "doas", "timeout", "stdbuf",
                "winpty", "nice", "ionice", "start", "cmd", "env", "watch",
                "strace", "ltrace"}


def _clasificar_segmento(seg, _prof=0):
    """(cubo, tipo_compensacion, motivo) de UN segmento de shell."""
    toks = _tokenizar(seg)
    # Asignaciones de entorno delante: VAR=1 cmd ...
    while toks and re.match(r"^[A-Za-z_][A-Za-z_0-9]*=", toks[0]):
        toks = toks[1:]
    if not toks:
        return ("puro", "", "segmento vacio")
    # Envoltorio: se pela (junto a sus flags y argumentos numericos) y se
    # clasifica lo de dentro. Profundidad acotada para no dar vueltas.
    if _prof < 3 and _norm_cmd(toks[0]) in _ENVOLTORIOS and len(toks) > 1:
        dentro = toks[1:]
        while dentro and (dentro[0].startswith("-") or dentro[0].isdigit()
                          or re.match(r"^[A-Za-z_][A-Za-z_0-9]*=", dentro[0])):
            dentro = dentro[1:]
        if dentro:
            cubo, tipo, motivo = _clasificar_segmento(" ".join(dentro), _prof + 1)
            return (cubo, tipo, f"via '{_norm_cmd(toks[0])}': {motivo}")
    base = _norm_cmd(toks[0])
    resto = " ".join(toks[1:])
    segundo = _norm_cmd(toks[1]) if len(toks) > 1 else ""

    # 1) patrones que condenan la linea entera
    for patron, motivo in _FLAGS_IRREVERSIBLES:
        if re.search(patron, seg, re.I):
            return ("irreversible", "", motivo)

    # 2) sub-comandos (git push, pip install, ...)
    if (base, segundo) in SUB_IRREVERSIBLES:
        return ("irreversible", "", SUB_IRREVERSIBLES[(base, segundo)])
    if (base, segundo) in SUB_REVERSIBLES:
        tipo, det = SUB_REVERSIBLES[(base, segundo)]
        return ("reversible", tipo, det)
    if (base, segundo) in SUB_PUROS:
        return ("puro", "", f"'{base} {segundo}' solo consulta")

    # 3) verbos irreversibles
    if base in CMD_IRREVERSIBLES:
        return ("irreversible", "", CMD_IRREVERSIBLES[base])

    # 4) interpretes
    if base in ("python", "python3", "py", "pythonw"):
        if re.search(r"(^|\s)(-V|--version)(\s|$)", resto):
            return ("puro", "", "python --version solo imprime")
        if re.search(r"(^|\s)-c(\s|$)", resto):
            return _clasificar_python_inline(seg)
        if re.search(r"-m\s+pip\s+install", resto):
            return ("irreversible", "", "pip install muta el entorno")
        if re.search(r"-m\s+(pytest|unittest)", resto):
            return ("desconocido", "", "pytest corre codigo arbitrario del repo")
        return ("desconocido", "",
                "script de Python: codigo arbitrario, efectos no analizables")
    if base in ("node", "deno", "bun", "ruby", "perl", "bash", "sh", "zsh",
                "powershell", "pwsh", "cmd"):
        if re.search(r"(^|\s)(-v|--version)(\s|$)", resto):
            return ("puro", "", f"'{base} --version' solo imprime")
        return ("desconocido", "", f"'{base}' ejecuta codigo arbitrario")

    # 5) comandos puros SOLO bajo condiciones
    if base == "find":
        if re.search(r"-delete|-exec|-execdir|-ok\b", resto):
            return ("irreversible", "", "find con -delete/-exec borra o ejecuta")
        return ("puro", "", "find solo lista")
    if base in ("curl", "wget", "invoke-webrequest", "invoke-restmethod", "iwr"):
        if re.search(r"\s(-o|-O|--output|--remote-name|-outfile)\b", seg, re.I):
            return ("reversible", "restaurar_fichero",
                    "descarga a fichero: se restaura el previo")
        return ("puro", "", "GET sin cuerpo (se ASUME servidor sin efectos)")
    if base in ("sed", "awk", "gawk"):
        if re.search(r"(^|\s)-i\b", resto):
            return ("reversible", "restaurar_fichero", "edicion in-place del fichero")
        return ("puro", "", "filtro de texto a stdout")
    if base in ("tar", "zip", "unzip", "7z"):
        if re.search(r"(^|\s)(-x|x|--extract)\b", resto):
            return ("desconocido", "",
                    "extraer sobreescribe rutas que no conozco de antemano")
        return ("reversible", "restaurar_fichero", "crea un archivo comprimido")
    if base in ("set-content", "out-file", "add-content", "new-item"):
        return ("reversible", "restaurar_fichero", "cmdlet de escritura")

    # 6) verbos reversibles (aqui SI aplica la bandera destructiva)
    if base in CMD_REVERSIBLES:
        if _RE_BANDERA_DESTRUCTIVA.search(seg):
            return ("irreversible", "",
                    f"'{base}' con bandera destructiva: sobreescribe sin copia")
        tipo, det = CMD_REVERSIBLES[base]
        return ("reversible", tipo, det)

    # 7) allowlist pura
    if base in CMD_PUROS:
        return ("puro", "", f"'{base}' esta en la allowlist de comandos puros")

    return ("desconocido", "", f"'{base}' no esta en ninguna tabla: fallar seguro")


def clasificar_comando(cmd):
    """Clasifica una linea de shell completa (pipelines, &&, redirecciones)."""
    cmd = (cmd or "").strip()
    if not cmd:
        return {"cubo": "puro", "compensacion": None, "motivo": "comando vacio",
                "confianza": 1.0}
    peor = None
    detalles = []
    for seg in _dividir(cmd):
        cubo, tipo, motivo = _clasificar_segmento(seg)
        destino = _redireccion(seg)
        if destino and cubo == "puro":
            cubo, tipo, motivo = ("reversible", "restaurar_fichero",
                                  f"redireccion a '{destino}': se restaura el previo")
        detalles.append(f"[{seg[:38]}]->{cubo}")
        if peor is None or _SEVERIDAD[cubo] > _SEVERIDAD[peor[0]]:
            peor = (cubo, tipo, motivo)
    cubo, tipo, motivo = peor
    conf = {"puro": 0.85, "reversible": 0.8, "irreversible": 0.9,
            "desconocido": 0.3}[cubo]
    comp = None
    if cubo == "reversible":
        comp = {"tipo": tipo or "restaurar_fichero", "detalle": motivo,
                "requiere_registro": True}
    if len(detalles) > 1:
        motivo = motivo + " | segmentos: " + " ".join(detalles)
    return {"cubo": cubo, "compensacion": comp, "motivo": motivo,
            "confianza": conf}


def clasificar(nombre_tool, args=""):
    """Cubo de una accion (tool + args). NUNCA devuelve 'puro' por defecto.

    Devuelve {cubo, compensacion, motivo, confianza}. `compensacion` es None
    salvo cubo 'reversible', y entonces trae el `tipo` que `compensar` ejecuta.
    """
    nombre = (nombre_tool or "").strip()
    if not isinstance(args, str):
        try:
            args = json.dumps(args, ensure_ascii=False, default=str)
        except Exception:
            args = str(args)
    if not nombre:
        return {"cubo": "desconocido", "compensacion": None,
                "motivo": "sin nombre de tool", "confianza": 0.0}

    # 1) tools que ejecutan shell: manda el COMANDO, no el nombre
    if nombre in ("ejecutar", "ejecutar_fondo", "shell", "bash", "run_shell",
                  "run_command"):
        # 'ejecutar' acepta "<cmd> | timeout=N | cwd=RUTA": esos sufijos NO son
        # un pipeline de shell y no deben clasificarse como comandos.
        limpio = re.sub(r"\s*\|\s*(timeout|cwd)\s*=\s*[^|]*", "", args).strip()
        if not limpio:
            return {"cubo": "desconocido", "compensacion": None, "confianza": 0.2,
                    "motivo": f"'{nombre}' SIN argumentos: indecidible por nombre "
                              f"(este es el coste de no instrumentar los args)"}
        res = clasificar_comando(limpio)
        if nombre == "ejecutar_fondo" and res["cubo"] != "irreversible":
            return {"cubo": "desconocido", "compensacion": None, "confianza": 0.3,
                    "motivo": "proceso en segundo plano: sus efectos ocurren DESPUES "
                              "de clasificar -- " + res["motivo"][:100]}
        res["motivo"] = f"tool '{nombre}': " + res["motivo"]
        return res

    # 2) tablas por nombre
    if nombre in TOOLS_IRREVERSIBLES:
        return {"cubo": "irreversible", "compensacion": None,
                "motivo": TOOLS_IRREVERSIBLES[nombre], "confianza": 0.9}
    if nombre in TOOLS_REVERSIBLES:
        tipo, det = TOOLS_REVERSIBLES[nombre]
        return {"cubo": "reversible",
                "compensacion": {"tipo": tipo, "detalle": det,
                                 "requiere_registro": True},
                "motivo": f"'{nombre}' se deshace: {det}", "confianza": 0.9}
    if nombre in TOOLS_PURAS:
        return {"cubo": "puro", "compensacion": None,
                "motivo": f"'{nombre}' solo lee/consulta/calcula", "confianza": 0.9}
    if nombre in TOOLS_DESCONOCIDAS:
        return {"cubo": "desconocido", "compensacion": None,
                "motivo": TOOLS_DESCONOCIDAS[nombre], "confianza": 0.3}

    # 3) heuristica por prefijo, con confianza BAJA
    bajo = nombre.lower()
    if bajo.startswith(("leer_", "listar", "buscar", "ver_", "consultar_",
                        "get_", "kg_buscar", "docs_")):
        return {"cubo": "puro", "compensacion": None, "confianza": 0.5,
                "motivo": f"'{nombre}' no esta en la tabla; el prefijo sugiere lectura"}
    if bajo.startswith(("borrar_", "eliminar_", "publicar_", "enviar_",
                        "apagar_", "matar_")):
        return {"cubo": "irreversible", "compensacion": None, "confianza": 0.6,
                "motivo": f"'{nombre}' no esta en la tabla; el prefijo sugiere destruccion"}
    return {"cubo": "desconocido", "compensacion": None, "confianza": 0.2,
            "motivo": f"'{nombre}' no esta en ninguna tabla del catastro: fallar seguro"}


def es_especulable(nombre_tool, args=""):
    """True SOLO si la accion es pura: se puede correr sin permiso ni rollback."""
    return clasificar(nombre_tool, args)["cubo"] == "puro"


# ---------------------------------------------------------------------------
# REGISTRO DE EFECTOS (lo que hace posible compensar)
# ---------------------------------------------------------------------------

def _dir_efectos():
    base = os.environ.get("COGNIA_MULTIVERSO_DIR", "").strip()
    return Path(base) if base else (Path.home() / ".cognia" / "multiverso")


def _base_de(ctx):
    """Directorio base para resolver rutas relativas.

    El resolutor REAL del repo es cognia.agent.tools._resolve_write_path (el
    workspace del agente). No lo importo a proposito: quien cablea pasa
    ctx={'resolver': esa funcion} o ctx={'workspace': ruta}. Sin eso, cwd.
    """
    if isinstance(ctx, dict):
        for k in ("workspace", "cwd", "dir", "base"):
            v = ctx.get(k)
            if v:
                return Path(str(v))
    return Path(os.getcwd())


def _resolver(ruta, ctx):
    if isinstance(ctx, dict) and callable(ctx.get("resolver")):
        try:
            return Path(str(ctx["resolver"](ruta)))
        except Exception:
            pass
    p = Path(str(ruta))
    return p if p.is_absolute() else (_base_de(ctx) / p)


def _rutas_de_args(nombre_tool, args):
    """Rutas implicadas segun el formato legacy 'ruta | resto' de las tools."""
    texto = args if isinstance(args, str) else str(args)
    partes = [p.strip().strip('"').strip("'")
              for p in re.split(r"\s*\|\s*", texto, maxsplit=2)]
    partes = [p for p in partes if p]
    if nombre_tool in ("copiar_archivo", "mover_archivo"):
        return partes[:2]
    return partes[:1]


def registrar_efecto(nombre_tool, args, ctx=None, persistir=True):
    """Captura ANTES de ejecutar lo minimo para poder deshacer la accion.

    Devuelve el registro (dict) que `compensar` entiende. Si la accion no es
    reversible, el registro lo dice y `compensar` fallara honestamente. Si el
    fichero supera TOPE_BYTES, DEGRADA a 'irreversible en la practica' y lo
    deja escrito: no se finge un rollback que no se puede hacer.
    """
    clas = clasificar(nombre_tool, args)
    reg = {
        "ts": time.time(),
        "tool": nombre_tool,
        "args": (args if isinstance(args, str) else str(args))[:2000],
        "cubo": clas["cubo"],
        "compensacion": clas.get("compensacion"),
        "motivo": clas.get("motivo", ""),
        "confianza": clas.get("confianza", 0.0),
        "rutas": [],
        "objetivo": "",
        "existia_antes": None,
        "tam_previo": 0,
        "hash_previo": "",
        "contenido_b64": "",
        "degradado": False,
        "detalle": "",
    }
    if clas["cubo"] != "reversible":
        reg["detalle"] = "no reversible: no hay nada que capturar"
        if persistir:
            _persistir(reg)
        return reg

    tipo = (clas.get("compensacion") or {}).get("tipo", "")
    try:
        rutas = [str(_resolver(r, ctx))
                 for r in _rutas_de_args(nombre_tool, args) if r]
    except Exception as e:
        rutas = []
        reg["detalle"] = f"no pude resolver rutas: {e}"
    reg["rutas"] = rutas

    if tipo == "restaurar_fichero" and rutas:
        # copiar_archivo escribe en el SEGUNDO argumento; el resto, en el primero
        objetivo = Path(rutas[-1] if nombre_tool == "copiar_archivo" and len(rutas) > 1
                        else rutas[0])
        reg["objetivo"] = str(objetivo)
        try:
            if objetivo.exists() and objetivo.is_file():
                tam = objetivo.stat().st_size
                reg["existia_antes"] = True
                reg["tam_previo"] = tam
                if tam > TOPE_BYTES:
                    reg["cubo"] = "irreversible"
                    reg["degradado"] = True
                    reg["compensacion"] = None
                    reg["detalle"] = (
                        f"IRREVERSIBLE EN LA PRACTICA: {tam} bytes > tope "
                        f"{TOPE_BYTES}; no copio el contenido previo (copiarlo "
                        f"convertiria el catastro en el cuello de botella)")
                else:
                    datos = objetivo.read_bytes()
                    reg["contenido_b64"] = base64.b64encode(datos).decode("ascii")
                    reg["hash_previo"] = hashlib.sha256(datos).hexdigest()
                    reg["detalle"] = f"contenido previo capturado ({tam} bytes)"
            else:
                reg["existia_antes"] = False
                reg["detalle"] = "no existia: la compensacion es BORRARLO"
        except Exception as e:
            reg["cubo"] = "desconocido"
            reg["compensacion"] = None
            reg["detalle"] = f"no pude leer el previo ({e}): sin rollback honesto"
    elif tipo == "borrar_si_vacio" and rutas:
        objetivo = Path(rutas[0])
        reg["objetivo"] = str(objetivo)
        reg["existia_antes"] = objetivo.exists()
        reg["detalle"] = ("ya existia: la compensacion NO debe borrarlo"
                          if reg["existia_antes"]
                          else "no existia: se borrara si queda vacio")
    elif tipo == "mover_de_vuelta" and len(rutas) >= 2:
        reg["origen"], reg["objetivo"] = rutas[0], rutas[1]
        reg["existia_antes"] = Path(rutas[0]).exists()
        reg["detalle"] = "se movera de vuelta destino -> origen"
    elif tipo == "comando":
        reg["detalle"] = ("compensacion por comando; el que cablea debe poner "
                          "'comando_compensador' en el registro: "
                          + (clas.get("compensacion") or {}).get("detalle", ""))
    else:
        reg["cubo"] = "desconocido"
        reg["compensacion"] = None
        reg["detalle"] = "reversible en teoria pero no identifique la ruta afectada"

    if persistir:
        _persistir(reg)
    return reg


def _persistir(reg):
    """Anota el registro en ~/.cognia/multiverso/efectos.jsonl. Nunca lanza.

    El blob va a un fichero aparte: un jsonl con base64 de ficheros enteros
    se vuelve ilegible y enorme.
    """
    try:
        d = _dir_efectos()
        d.mkdir(parents=True, exist_ok=True)
        linea = dict(reg)
        blob = linea.pop("contenido_b64", "")
        if blob:
            blobs = d / "blobs"
            blobs.mkdir(exist_ok=True)
            nombre = reg.get("hash_previo") or hashlib.sha256(
                blob.encode("ascii")).hexdigest()
            ruta_blob = blobs / (nombre + ".bin")
            if not ruta_blob.exists():
                ruta_blob.write_bytes(base64.b64decode(blob))
            linea["blob"] = str(ruta_blob)
        with open(d / "efectos.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(linea, ensure_ascii=False, default=str) + "\n")
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# COMPENSACION (patron saga)
# ---------------------------------------------------------------------------

def _ejecutor_real(cmd, cwd=None):
    try:
        p = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True,
                           text=True, timeout=60)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as e:
        return 1, str(e)


def compensar(registro, ejecutor=None):
    """Deshace una accion reversible YA HECHA. Nunca lanza: devuelve {ok, detalle}.

    `ejecutor(cmd, cwd) -> (rc, salida)` se inyecta para poder testear sin
    subprocess; por defecto usa subprocess.run.
    """
    salida = {"ok": False, "detalle": "", "tipo": "", "ruta": "",
              "verificado": False}
    try:
        if not isinstance(registro, dict):
            salida["detalle"] = "el registro no es un dict"
            return salida
        salida["tipo"] = (registro.get("compensacion") or {}).get("tipo", "") or ""
        if registro.get("cubo") != "reversible" or not registro.get("compensacion"):
            salida["detalle"] = (
                f"no compensable (cubo={registro.get('cubo')}): "
                + (registro.get("detalle") or registro.get("motivo") or ""))[:400]
            return salida
        tipo = salida["tipo"]

        if tipo == "restaurar_fichero":
            objetivo = registro.get("objetivo") or (registro.get("rutas") or [""])[0]
            salida["ruta"] = objetivo
            if not objetivo:
                salida["detalle"] = "sin ruta objetivo en el registro"
                return salida
            p = Path(objetivo)
            if registro.get("existia_antes"):
                b64 = registro.get("contenido_b64", "")
                if not b64 and registro.get("blob"):
                    try:
                        b64 = base64.b64encode(
                            Path(registro["blob"]).read_bytes()).decode("ascii")
                    except Exception as e:
                        salida["detalle"] = f"blob ilegible: {e}"
                        return salida
                if not b64:
                    salida["detalle"] = ("el registro dice que existia pero NO hay "
                                         "contenido previo: irreversible en la practica")
                    return salida
                datos = base64.b64decode(b64)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(datos)
                ok_hash = (not registro.get("hash_previo")) or (
                    hashlib.sha256(p.read_bytes()).hexdigest()
                    == registro["hash_previo"])
                salida["ok"] = bool(ok_hash)
                salida["verificado"] = bool(ok_hash)
                salida["detalle"] = (f"restaurados {len(datos)} bytes (hash OK)"
                                     if ok_hash
                                     else "restaurado pero el hash NO cuadra")
                return salida
            if p.exists():
                p.unlink()
                salida["ok"] = not p.exists()
                salida["verificado"] = salida["ok"]
                salida["detalle"] = "no existia antes: borrado"
            else:
                salida["ok"] = True
                salida["verificado"] = True
                salida["detalle"] = "no existia antes y sigue sin existir"
            return salida

        if tipo == "borrar_si_vacio":
            objetivo = registro.get("objetivo") or (registro.get("rutas") or [""])[0]
            salida["ruta"] = objetivo
            p = Path(objetivo)
            if registro.get("existia_antes"):
                salida["ok"] = True
                salida["detalle"] = "el directorio ya existia antes: NO se toca"
                return salida
            if not p.exists():
                salida["ok"] = True
                salida["detalle"] = "el directorio ya no esta"
                return salida
            if any(p.iterdir()):
                salida["detalle"] = ("el directorio NO quedo vacio: no lo borro "
                                     "(borrar contenido ajeno seria irreversible)")
                return salida
            p.rmdir()
            salida["ok"] = not p.exists()
            salida["verificado"] = salida["ok"]
            salida["detalle"] = "directorio vacio borrado"
            return salida

        if tipo == "mover_de_vuelta":
            origen, destino = registro.get("origen", ""), registro.get("objetivo", "")
            salida["ruta"] = destino
            if not origen or not destino:
                salida["detalle"] = "faltan origen/destino en el registro"
                return salida
            pd, po = Path(destino), Path(origen)
            if not pd.exists():
                salida["detalle"] = f"el destino '{destino}' no existe: nada que mover"
                return salida
            if po.exists():
                salida["detalle"] = (f"el origen '{origen}' YA existe: mover encima "
                                     f"seria destruir; no lo hago")
                return salida
            po.parent.mkdir(parents=True, exist_ok=True)
            os.replace(str(pd), str(po))
            salida["ok"] = po.exists() and not pd.exists()
            salida["verificado"] = salida["ok"]
            salida["detalle"] = f"movido de vuelta a '{origen}'"
            return salida

        if tipo == "comando":
            cmd = registro.get("comando_compensador") or ""
            if not cmd:
                salida["detalle"] = (
                    "compensacion por comando pero el registro no trae "
                    "'comando_compensador': "
                    + (registro.get("compensacion") or {}).get("detalle", ""))
                return salida
            rc, out = (ejecutor or _ejecutor_real)(cmd, registro.get("cwd"))
            salida["ok"] = (rc == 0)
            salida["detalle"] = f"[rc={rc}] {cmd} :: {str(out)[:300]}"
            return salida

        salida["detalle"] = f"tipo de compensacion desconocido: '{tipo}'"
        return salida
    except Exception as e:
        salida["ok"] = False
        salida["detalle"] = f"excepcion al compensar: {type(e).__name__}: {e}"
        return salida


# ---------------------------------------------------------------------------
# MEDICION SOBRE TRAZAS REALES
# ---------------------------------------------------------------------------

def _normalizar_traza(item):
    """Acepta dicts de varios formatos, tuplas (tool, args) o strings."""
    if isinstance(item, dict):
        nombre = (item.get("action") or item.get("tool") or item.get("nombre")
                  or item.get("name") or item.get("motivo") or "")
        args = item.get("args", item.get("arguments", item.get("argumentos", "")))
        try:
            peso = int(item.get("peso", item.get("calls", 1)) or 1)
        except Exception:
            peso = 1
        return str(nombre), ("" if args is None else args), peso
    if isinstance(item, (list, tuple)):
        nombre = str(item[0]) if item else ""
        args = item[1] if len(item) > 1 else ""
        return nombre, args, 1
    return str(item or ""), "", 1


def medir_distribucion(trazas):
    """Reparto por cubo de acciones REALES: el numero que dice si ramificar sirve.

    Cada elemento puede llevar 'peso' (o 'calls') para trazas agregadas. Se
    reporta ademas cuantas acciones eran de shell (indecidibles por nombre),
    que es el coste MEDIDO de no instrumentar los argumentos.
    """
    conteo = {c: 0 for c in CUBOS}
    por_tool = {}
    n = 0
    acciones_shell = 0
    shell_sin_args = 0
    for item in (trazas or []):
        nombre, args, peso = _normalizar_traza(item)
        if not nombre:
            continue
        clas = clasificar(nombre, args)
        cubo = clas["cubo"] if clas["cubo"] in conteo else "desconocido"
        conteo[cubo] += peso
        n += peso
        d = por_tool.setdefault(nombre, {c: 0 for c in CUBOS})
        d[cubo] += peso
        if nombre in ("ejecutar", "ejecutar_fondo", "shell", "bash"):
            acciones_shell += peso
            if not str(args).strip():
                shell_sin_args += peso
    pct = {c: (round(100.0 * conteo[c] / n, 2) if n else 0.0) for c in CUBOS}
    return {
        "n": n,
        "conteo": conteo,
        "porcentaje": pct,
        "fraccion_especulable": pct["puro"],
        "fraccion_irreversible": pct["irreversible"],
        "acciones_de_shell": acciones_shell,
        "shell_sin_args": shell_sin_args,
        "por_tool": por_tool,
        "cubos": list(CUBOS),
    }


def cargar_trazas(ruta):
    """Lee trazas reales de los formatos que existen en esta maquina.

    Soporta: bitacora.jsonl (eventos ToolInicio con tool+args), _tool_usage.json
    (agregado {tool: {calls: n}} -> se pesa por llamadas, SIN args), el
    indice.jsonl de checkpoints ({motivo, ruta}) y jsonl generico con
    action/args. Devuelve [] si no reconoce nada. Nunca lanza.
    """
    salida = []
    try:
        p = Path(ruta)
        if not p.exists():
            return salida
        if p.suffix == ".json":
            datos = json.loads(p.read_text(encoding="utf-8", errors="replace"))
            if isinstance(datos, dict):
                for k, v in datos.items():
                    if isinstance(v, dict) and "calls" in v:
                        salida.append({"action": k, "args": "",
                                       "peso": int(v["calls"])})
            return salida
        for linea in p.read_text(encoding="utf-8", errors="replace").splitlines():
            linea = linea.strip()
            if not linea.startswith("{"):
                continue
            try:
                d = json.loads(linea)
            except Exception:
                continue
            tipo = d.get("tipo", "")
            if tipo == "ToolFin":
                continue  # el par ToolInicio/ToolFin es la MISMA accion
            if tipo == "ToolInicio" or ("tool" in d and "args" in d):
                salida.append({"action": d.get("tool", ""), "args": d.get("args", "")})
            elif "motivo" in d and "ruta" in d:
                salida.append({"action": d.get("motivo", ""), "args": d.get("ruta", "")})
            elif "action" in d:
                salida.append({"action": d.get("action", ""), "args": d.get("args", "")})
    except Exception:
        return salida
    return salida
